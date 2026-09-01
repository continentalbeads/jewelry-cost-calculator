"""Match imported lines to consignors.

Order of attempts per line:
  1. SKU starts with a known consignor prefix (case-insensitive, separator-tolerant)
     -> confident
  2. Title contains a prefix or alias as a token/substring (case-insensitive,
     whitespace-normalized) -> confident
  3. Fuzzy: best difflib ratio between any title token and any prefix/alias
     >= FUZZY_THRESHOLD -> fuzzy (needs confirmation, score shown)
  4. -> unmatched
"""
import re
from difflib import SequenceMatcher

FUZZY_THRESHOLD = 0.72

_TOKEN_SPLIT = re.compile(r"[\s\-_/,.:;()\[\]'\"#]+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(s):
    return (s or "").strip().lower()


def _squash(s):
    return _NON_ALNUM.sub("", _norm(s))


def _tokens(s):
    return [t for t in _TOKEN_SPLIT.split(_norm(s)) if t]


def load_alias_index(conn):
    """[(alias_text_lower, kind, consignor_id, consignor_name), ...] for active consignors."""
    rows = conn.execute(
        """SELECT a.text, a.kind, a.consignor_id, c.name
           FROM aliases a JOIN consignors c ON c.id = a.consignor_id
           WHERE c.active = 1"""
    ).fetchall()
    return [(_norm(r["text"]), r["kind"], r["consignor_id"], r["name"]) for r in rows if _norm(r["text"])]


def match_line(sku, title, alias_index):
    """Return (status, consignor_id, method, score) for one line."""
    sku_squashed = _squash(sku)
    if sku_squashed:
        for text, kind, cid, _name in alias_index:
            if kind == "prefix" and _squash(text) and sku_squashed.startswith(_squash(text)):
                return ("confident", cid, f"sku prefix '{text}'", 1.0)

    title_norm = _norm(title)
    title_squashed = _squash(title)
    title_tokens = _tokens(title)

    if title_norm:
        for text, _kind, cid, _name in alias_index:
            if text in title_norm or (_squash(text) and _squash(text) in title_squashed):
                return ("confident", cid, f"title contains '{text}'", 1.0)

        best = (0.0, None, None)
        for text, _kind, cid, _name in alias_index:
            for tok in title_tokens:
                ratio = SequenceMatcher(None, text, tok).ratio()
                if ratio > best[0]:
                    best = (ratio, cid, f"fuzzy '{tok}' ~ '{text}'")
        if best[0] >= FUZZY_THRESHOLD and best[1] is not None:
            return ("fuzzy", best[1], best[2], round(best[0], 3))

    return ("unmatched", None, None, None)


def rematch_pending(conn):
    """Re-run matching on lines still fuzzy/unmatched (never touches confirmed,
    dismissed, or settled lines). Returns count of lines that changed."""
    alias_index = load_alias_index(conn)
    lines = conn.execute(
        """SELECT id, sku, title FROM import_lines
           WHERE match_status IN ('fuzzy','unmatched') AND settled_run_id IS NULL"""
    ).fetchall()
    changed = 0
    for line in lines:
        status, cid, method, score = match_line(line["sku"], line["title"], alias_index)
        conn.execute(
            """UPDATE import_lines
               SET match_status=?, consignor_id=?, match_method=?, match_score=?
               WHERE id=?""",
            (status, cid, method, score, line["id"]),
        )
        if status != "unmatched":
            changed += 1
    return changed
