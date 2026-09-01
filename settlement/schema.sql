PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consignors (
  id                     INTEGER PRIMARY KEY,
  name                   TEXT NOT NULL,
  business_name          TEXT,
  split_bps              INTEGER NOT NULL DEFAULT 4000,  -- consignor share, basis points
  zelle_contact          TEXT,
  w9_on_file             INTEGER NOT NULL DEFAULT 0,
  active                 INTEGER NOT NULL DEFAULT 1,
  recurring_charge_cents INTEGER,                        -- NULL = no monthly charge
  recurring_charge_start TEXT,                           -- YYYY-MM-DD
  recurring_charge_end   TEXT,
  recurring_charge_note  TEXT,
  created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS aliases (
  id           INTEGER PRIMARY KEY,
  consignor_id INTEGER NOT NULL REFERENCES consignors(id) ON DELETE CASCADE,
  text         TEXT NOT NULL,
  -- 'prefix' matches SKU prefixes AND title text; 'alias' matches title text only
  kind         TEXT NOT NULL DEFAULT 'prefix' CHECK (kind IN ('prefix','alias')),
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (consignor_id, text)
);

CREATE TABLE IF NOT EXISTS fee_schedule (
  id             INTEGER PRIMARY KEY,
  channel        TEXT NOT NULL,
  fee_name       TEXT NOT NULL,
  percent_bps    INTEGER NOT NULL DEFAULT 0,   -- basis points of gross
  fixed_cents    INTEGER NOT NULL DEFAULT 0,   -- per-transaction fixed amount
  effective_from TEXT NOT NULL,                -- YYYY-MM-DD
  effective_to   TEXT,                         -- NULL = still in effect
  deductible     INTEGER NOT NULL DEFAULT 1,   -- 0 = reference only, never auto-applied
  verified       INTEGER NOT NULL DEFAULT 0,   -- seeded rows start unverified
  created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS imports (
  id          INTEGER PRIMARY KEY,
  filename    TEXT,
  file_sha256 TEXT,
  rows_total  INTEGER NOT NULL DEFAULT 0,
  rows_new    INTEGER NOT NULL DEFAULT 0,
  rows_dup    INTEGER NOT NULL DEFAULT 0,
  imported_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS import_lines (
  id             INTEGER PRIMARY KEY,
  import_id      INTEGER NOT NULL REFERENCES imports(id),
  line_key       TEXT NOT NULL UNIQUE,         -- idempotency key
  order_ref      TEXT,
  order_date     TEXT,                          -- YYYY-MM-DD
  channel        TEXT,                          -- resolved channel, overridable
  channel_raw    TEXT,
  sku            TEXT,
  title          TEXT,
  quantity       INTEGER NOT NULL DEFAULT 1,
  gross_cents    INTEGER NOT NULL,              -- line total excl. shipping; negative = refund
  is_refund      INTEGER NOT NULL DEFAULT 0,
  refund_warning INTEGER NOT NULL DEFAULT 0,    -- financial status mentioned a refund
  raw_json       TEXT,
  match_status   TEXT NOT NULL DEFAULT 'unmatched'
                 CHECK (match_status IN ('confident','fuzzy','confirmed','unmatched','dismissed')),
  match_method   TEXT,
  match_score    REAL,
  consignor_id   INTEGER REFERENCES consignors(id),
  settled_run_id INTEGER REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS runs (
  id           INTEGER PRIMARY KEY,
  label        TEXT,
  period       TEXT NOT NULL,                   -- YYYY-MM, used for recurring charges
  status       TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','committed')),
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  committed_at TEXT,
  backup_path  TEXT
);

CREATE TABLE IF NOT EXISTS run_lines (
  id                 INTEGER PRIMARY KEY,
  run_id             INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  import_line_id     INTEGER REFERENCES import_lines(id),
  consignor_id       INTEGER NOT NULL REFERENCES consignors(id),
  entry_type         TEXT NOT NULL DEFAULT 'SALE' CHECK (entry_type IN ('SALE','REFUND')),
  order_ref          TEXT,
  order_date         TEXT,
  channel            TEXT,
  description        TEXT,
  gross_cents        INTEGER NOT NULL,
  split_bps          INTEGER NOT NULL,
  original_gross_cents INTEGER,                 -- set on first manual edit
  original_split_bps   INTEGER,
  excluded           INTEGER NOT NULL DEFAULT 0,
  manual             INTEGER NOT NULL DEFAULT 0, -- added by hand, not from CSV
  edited             INTEGER NOT NULL DEFAULT 0,
  note               TEXT
);

CREATE TABLE IF NOT EXISTS run_line_fees (
  id                    INTEGER PRIMARY KEY,
  run_line_id           INTEGER NOT NULL REFERENCES run_lines(id) ON DELETE CASCADE,
  fee_schedule_id       INTEGER REFERENCES fee_schedule(id),
  fee_name              TEXT NOT NULL,
  amount_cents          INTEGER NOT NULL,
  original_amount_cents INTEGER,                -- set on first manual edit
  source                TEXT NOT NULL DEFAULT 'schedule' CHECK (source IN ('schedule','manual')),
  removed               INTEGER NOT NULL DEFAULT 0,
  edited                INTEGER NOT NULL DEFAULT 0
);

-- The append-only ledger. Balance = SUM(amount_cents) per consignor.
CREATE TABLE IF NOT EXISTS ledger (
  id                    INTEGER PRIMARY KEY,
  consignor_id          INTEGER NOT NULL REFERENCES consignors(id),
  entry_date            TEXT NOT NULL,
  type                  TEXT NOT NULL CHECK (type IN ('SALE','REFUND','ADJUSTMENT','CHARGE','PAYOUT')),
  run_id                INTEGER REFERENCES runs(id),
  source_ref            TEXT,                   -- order/line reference, nullable
  description           TEXT,
  gross_cents           INTEGER NOT NULL DEFAULT 0,
  fee_cents             INTEGER NOT NULL DEFAULT 0,
  fee_detail            TEXT,                   -- JSON [{"name":..,"amount_cents":..}]
  net_cents             INTEGER NOT NULL DEFAULT 0,
  consignor_share_cents INTEGER NOT NULL DEFAULT 0,
  my_share_cents        INTEGER NOT NULL DEFAULT 0,
  amount_cents          INTEGER NOT NULL,       -- signed effect on consignor balance
  payout_method         TEXT,
  note                  TEXT,
  manually_edited       INTEGER NOT NULL DEFAULT 0,
  created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only; add an ADJUSTMENT instead'); END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
BEGIN SELECT RAISE(ABORT, 'ledger is append-only; add an ADJUSTMENT instead'); END;

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY,
  table_name TEXT NOT NULL,
  record_id  INTEGER,
  field      TEXT,
  old_value  TEXT,
  new_value  TEXT,
  context    TEXT,
  changed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Stub for the future aging report (inventory import not built yet).
CREATE TABLE IF NOT EXISTS inventory_items (
  id           INTEGER PRIMARY KEY,
  consignor_id INTEGER REFERENCES consignors(id),
  sku          TEXT,
  description  TEXT,
  listed_date  TEXT,   -- date first listed / offered for sale
  price_cents  INTEGER,
  sold         INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ledger_consignor ON ledger(consignor_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_import_lines_status ON import_lines(match_status, settled_run_id);
CREATE INDEX IF NOT EXISTS idx_run_lines_run ON run_lines(run_id);
