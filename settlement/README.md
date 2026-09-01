# CBS Consignment Settlement

Local, single-user tool for Continental Bead Suppliers' monthly consignment
settlements: import the Shopify order export, match lines to consignors (SKU
prefixes and fuzzy title matching for showroom quick-sales), deduct per-channel
fees as of each order's date, split 60/40, review and edit every number, commit
to an append-only ledger, then print statements and run the Zelle payout
worksheet with carry-forward balances.

See `DESIGN.md` for the schema, the matching approach, and the list of
assumptions to verify (fee rates are seeded as unverified placeholders).

## Run it

```bash
cd settlement
pip install flask
python app.py
```

Open <http://127.0.0.1:5111>.

First-time setup, in order:

1. **Consignors** — add your four consignors with their SKU/title prefixes,
   split %, Zelle contact, W-9 status.
2. **Fees** — correct every seeded rate and tick *verified* (a banner nags
   until you do).
3. **Import** — upload the Shopify order CSV, confirm the column mapping
   (remembered afterwards).
4. **Review Queue** — confirm fuzzy matches, assign or dismiss unmatched lines
   (saving aliases as you go so next month matches itself).
5. **Runs** — create a draft run, edit anything in the review table, commit.
6. **Payouts** — pay via Zelle, mark paid. Print statements from the run page.

## Data & backups

- Everything lives in `settlement/data/cbs.sqlite` (created on first start,
  not in git). That file is the source of truth — copy it anywhere to back up
  or migrate.
- The app automatically snapshots the DB to `settlement/data/backups/` before
  every committed run.
- The ledger is append-only (enforced by DB triggers); every manual edit is in
  the Audit page with old/new values and timestamps.
