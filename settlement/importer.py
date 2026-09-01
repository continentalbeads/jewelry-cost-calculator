"""Shopify order-export CSV import: column mapping, parsing, idempotent staging."""
import csv
import hashlib
import io
import json

from db import audit
from matching import load_alias_index, load_catalog_index, match_line
from util import parse_cents, parse_date, parse_int

# Fields the user can map a CSV column onto. (field, label, required)
MAP_FIELDS = [
    ("order_ref", "Order number / name", True),
    ("order_date", "Order date", True),
    ("title", "Line item title", True),
    ("sku", "Line item SKU", False),
    ("quantity", "Line item quantity", False),
    ("unit_price", "Line item unit price", False),
    ("line_total", "Line item total (overrides qty x price)", False),
    ("discount", "Line item discount (subtracted)", False),
    ("channel", "Sales channel / source", False),
    ("line_id", "Line item ID (best idempotency key)", False),
    ("financial_status", "Financial status (refund warnings)", False),
]

# Auto-guesses keyed on lowercased CSV header names (Shopify export defaults first).
HEADER_GUESSES = {
    "order_ref": ["name", "order name", "order", "order id", "order number"],
    "order_date": ["created at", "paid at", "processed at", "date", "order date"],
    "title": ["lineitem name", "line item name", "product title", "title"],
    "sku": ["lineitem sku", "line item sku", "sku", "variant sku"],
    "quantity": ["lineitem quantity", "line item quantity", "quantity", "qty"],
    "unit_price": ["lineitem price", "line item price", "price"],
    "line_total": ["lineitem total", "line item total"],
    "discount": ["lineitem discount", "line item discount", "discount amount"],
    "channel": ["source", "source name", "sales channel", "channel"],
    "line_id": ["lineitem id", "line item id"],
    "financial_status": ["financial status"],
}

# Substring -> channel name (must line up with fee_schedule channels).
# Shopify's Source column is inconsistent: POS orders can export as "pos",
# "Point of Sale", "iphone"/"android", or the POS channel's app ID "580111".
CHANNEL_MAP = [
    ("ebay", "eBay"),
    ("etsy", "Etsy"),
    ("faire", "Faire"),
    ("point of sale", "Showroom POS"),
    ("quick_sale", "Showroom POS"),
    ("quick sale", "Showroom POS"),
    ("pos", "Showroom POS"),
    ("580111", "Showroom POS"),
    ("iphone", "Showroom POS"),
    ("android", "Showroom POS"),
    ("web", "Shopify Online"),
    ("online store", "Shopify Online"),
    ("online", "Shopify Online"),
    ("shopify", "Shopify Online"),
    ("draft", "Shopify Online"),
]


def resolve_channel(raw):
    s = (raw or "").strip().lower()
    if not s:
        return "Shopify Online"
    for needle, channel in CHANNEL_MAP:
        if needle in s:
            return channel
    return raw.strip()  # unknown source: keep it visible; no fees will auto-apply


def read_headers(file_bytes):
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        return [h.strip() for h in row]
    return []


def guess_mapping(headers):
    lower = {h.strip().lower(): h for h in headers}
    mapping = {}
    for field, candidates in HEADER_GUESSES.items():
        for cand in candidates:
            if cand in lower:
                mapping[field] = lower[cand]
                break
    return mapping


def run_import(conn, file_bytes, filename, mapping):
    """Parse the CSV with the given mapping and stage lines. Idempotent by line_key.
    Returns the imports row id."""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    sha = hashlib.sha256(file_bytes).hexdigest()

    cur = conn.execute(
        "INSERT INTO imports (filename, file_sha256) VALUES (?,?)", (filename, sha)
    )
    import_id = cur.lastrowid

    alias_index = load_alias_index(conn)
    catalog_index = load_catalog_index(conn)
    # Shopify fills order-level columns only on the first line-item row of an
    # order; forward-fill those.
    carry_fields = ["order_ref", "order_date", "channel", "financial_status"]
    carried = {}
    seen_keys = {}  # tuple-key -> occurrence count within this file
    total = new = dup = 0

    def col(row, field):
        header = mapping.get(field)
        return (row.get(header) or "").strip() if header else ""

    for row in reader:
        title = col(row, "title")
        sku = col(row, "sku")
        if not title and not sku:
            continue  # not a line-item row
        total += 1

        values = {f: col(row, f) for f, _label, _req in MAP_FIELDS}
        for f in carry_fields:
            if values[f]:
                carried[f] = values[f]
            else:
                values[f] = carried.get(f, "")

        qty = parse_int(values["quantity"], default=1)
        try:
            if values["line_total"]:
                gross = parse_cents(values["line_total"])
            else:
                gross = parse_cents(values["unit_price"]) * qty
            if values["discount"]:
                gross -= parse_cents(values["discount"])
        except ValueError:
            gross = 0
        order_date = parse_date(values["order_date"])
        is_refund = 1 if gross < 0 or qty < 0 else 0
        refund_warning = 1 if "refund" in values["financial_status"].lower() else 0
        channel = resolve_channel(values["channel"])

        if values["line_id"]:
            line_key = f"li:{values['line_id']}"
        else:
            base = (values["order_ref"], sku, title, str(qty), str(gross), order_date or "")
            n = seen_keys.get(base, 0)
            seen_keys[base] = n + 1
            digest = hashlib.sha1("|".join(base).encode()).hexdigest()
            line_key = f"h:{digest}#{n}"

        status, cid, method, score = match_line(sku, title, alias_index, catalog_index)
        try:
            conn.execute(
                """INSERT INTO import_lines
                   (import_id, line_key, order_ref, order_date, channel, channel_raw,
                    sku, title, quantity, gross_cents, is_refund, refund_warning,
                    raw_json, match_status, match_method, match_score, consignor_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (import_id, line_key, values["order_ref"], order_date, channel,
                 values["channel"], sku, title, qty, gross, is_refund, refund_warning,
                 json.dumps(row), status, method, score, cid),
            )
            new += 1
        except Exception as e:
            if "UNIQUE" in str(e):
                dup += 1  # already imported: skip, never double-count
            else:
                raise

    conn.execute(
        "UPDATE imports SET rows_total=?, rows_new=?, rows_dup=? WHERE id=?",
        (total, new, dup, import_id),
    )
    audit(conn, "imports", import_id, "import", None,
          f"{filename}: {total} rows, {new} new, {dup} duplicates skipped", "csv import")
    return import_id


# ------------------- product catalog import (for tag matching) -------------------

CATALOG_FIELDS = [
    ("title", "Product title", True),
    ("tags", "Tags", True),
    ("sku", "Variant SKU", False),
    ("handle", "Handle", False),
]

CATALOG_GUESSES = {
    "title": ["title", "product title"],
    "tags": ["tags", "product tags"],
    "sku": ["variant sku", "sku"],
    "handle": ["handle"],
}


def guess_catalog_mapping(headers):
    lower = {h.strip().lower(): h for h in headers}
    mapping = {}
    for field, candidates in CATALOG_GUESSES.items():
        for cand in candidates:
            if cand in lower:
                mapping[field] = lower[cand]
                break
    return mapping


def run_catalog_import(conn, file_bytes, filename, mapping):
    """Replace the stored product catalog with this Shopify product export.
    Returns the number of catalog rows stored."""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    def col(row, field):
        header = mapping.get(field)
        return (row.get(header) or "").strip() if header else ""

    conn.execute("DELETE FROM catalog_items")
    # Shopify's product export fills Title/Tags only on the product's first
    # variant row; forward-fill them onto the following variant rows.
    carried = {"title": "", "tags": "", "handle": ""}
    count = 0
    for row in reader:
        values = {f: col(row, f) for f, _label, _req in CATALOG_FIELDS}
        if values["handle"] and values["handle"] != carried["handle"]:
            carried = {"title": "", "tags": "", "handle": values["handle"]}
        for f in ("title", "tags"):
            if values[f]:
                carried[f] = values[f]
            else:
                values[f] = carried[f]
        if not values["sku"] and not values["title"]:
            continue
        conn.execute(
            "INSERT INTO catalog_items (handle, sku, title, tags) VALUES (?,?,?,?)",
            (values["handle"] or None, values["sku"] or None,
             values["title"] or None, values["tags"] or None))
        count += 1
    audit(conn, "catalog_items", None, "import", None,
          f"{filename}: {count} products/variants (previous catalog replaced)",
          "catalog import")
    return count
