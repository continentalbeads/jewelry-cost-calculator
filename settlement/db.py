"""SQLite connection, schema init, seed data, backups, audit helper."""
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "cbs.sqlite")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    conn = connect()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    migrate(conn)
    seed_fee_schedule(conn)
    seed_consignors(conn)
    seed_tag_aliases(conn)
    conn.commit()
    conn.close()


def migrate(conn):
    """In-place upgrades for databases created by earlier versions."""
    # 2026-09: ledger.channel records the sales channel on SALE/REFUND entries
    ledger_cols = [r["name"] for r in conn.execute("PRAGMA table_info(ledger)")]
    if "channel" not in ledger_cols:
        conn.execute("ALTER TABLE ledger ADD COLUMN channel TEXT")
    # 2026-09: aliases.kind gains 'tag' (product-tag matching); unique now
    # includes kind so the same text can exist as both alias and tag
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='aliases'"
    ).fetchone()
    if row and "'tag'" not in row["sql"]:
        conn.executescript("""
            CREATE TABLE aliases_migrated (
              id           INTEGER PRIMARY KEY,
              consignor_id INTEGER NOT NULL REFERENCES consignors(id) ON DELETE CASCADE,
              text         TEXT NOT NULL,
              kind         TEXT NOT NULL DEFAULT 'prefix'
                           CHECK (kind IN ('prefix','alias','tag')),
              created_at   TEXT NOT NULL DEFAULT (datetime('now')),
              UNIQUE (consignor_id, text, kind)
            );
            INSERT INTO aliases_migrated SELECT * FROM aliases;
            DROP TABLE aliases;
            ALTER TABLE aliases_migrated RENAME TO aliases;
        """)


# Website product tags per consignor. Kiowa items are tagged with the payee's
# name; the others are tagged with their prefix. Runs idempotently on every
# start so existing databases pick up additions.
SEED_TAGS = [
    ("Kevin Long", "Kevin Long"),
    ("Sue Smith", "Beads Amore"),
    ("Esther Morse", "Esther"),
    ("Pauline Mariano", "Pauline"),
]


def seed_tag_aliases(conn):
    for name, tag in SEED_TAGS:
        row = conn.execute("SELECT id FROM consignors WHERE name=?", (name,)).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO aliases (consignor_id, text, kind) VALUES (?,?,'tag')",
                (row["id"], tag))


# CBS's consignors as of 2026-09: payee name + their SKU/tag prefix.
# Seeded only into a brand-new database; edit freely in the UI afterwards
# (add Zelle contacts, W-9 status, business names, extra aliases).
SEED_CONSIGNORS = [
    ("Kevin Long", "Kiowa"),
    ("Sue Smith", "Beads Amore"),
    ("Esther Morse", "Esther"),
    ("Pauline Mariano", "Pauline"),
]


def seed_consignors(conn):
    if conn.execute("SELECT COUNT(*) AS c FROM consignors").fetchone()["c"]:
        return
    for name, prefix in SEED_CONSIGNORS:
        cur = conn.execute(
            "INSERT INTO consignors (name, split_bps, active) VALUES (?, 4000, 1)",
            (name,),
        )
        conn.execute(
            "INSERT INTO aliases (consignor_id, text, kind) VALUES (?, ?, 'prefix')",
            (cur.lastrowid, prefix),
        )


# Seeded rates are PLACEHOLDERS (verified=0). The UI shows a banner until every
# row is confirmed or replaced by the real numbers.
SEED_FEES = [
    # (channel, fee_name, percent_bps, fixed_cents, deductible)
    ("Shopify Online", "Shopify Payments (online)", 290, 30, 1),
    ("Showroom POS", "Shopify Payments (card present)", 260, 10, 1),
    ("eBay", "Final value fee", 1360, 30, 1),
    ("eBay", "Promoted Listings (optional ads - NOT deductible)", 200, 0, 0),
    ("Etsy", "Transaction fee", 650, 0, 1),
    ("Etsy", "Payment processing", 300, 25, 1),
    ("Etsy", "Offsite Ads (attributed orders only - add per line)", 1500, 0, 0),
    ("Faire", "Commission", 1500, 0, 1),
]


def seed_fee_schedule(conn):
    if conn.execute("SELECT COUNT(*) AS c FROM fee_schedule").fetchone()["c"]:
        return
    for channel, name, bps, fixed, deductible in SEED_FEES:
        conn.execute(
            """INSERT INTO fee_schedule
               (channel, fee_name, percent_bps, fixed_cents, effective_from,
                effective_to, deductible, verified)
               VALUES (?,?,?,?, '2000-01-01', NULL, ?, 0)""",
            (channel, name, bps, fixed, deductible),
        )


def backup_db(conn, tag):
    """Copy the live DB to the backups folder using the SQLite backup API."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_path = os.path.join(BACKUP_DIR, f"cbs-{tag}-{stamp}.sqlite")
    dest = sqlite3.connect(dest_path)
    with dest:
        conn.backup(dest)
    dest.close()
    return dest_path


def audit(conn, table, record_id, field, old, new, context=""):
    conn.execute(
        """INSERT INTO audit_log (table_name, record_id, field, old_value, new_value, context)
           VALUES (?,?,?,?,?,?)""",
        (table, record_id, field,
         None if old is None else str(old),
         None if new is None else str(new),
         context),
    )


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
