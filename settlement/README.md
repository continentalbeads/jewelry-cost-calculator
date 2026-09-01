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

0. **Create your login** — the first launch shows a one-time setup screen:
   confirm your email and pick a password (8+ characters). After that the whole
   app sits behind a sign-in page. Forgot the password? Delete the row in the
   `users` table (`sqlite3 data/cbs.sqlite "DELETE FROM users"`) and setup
   runs again; ledger data is untouched.
1. **Consignors** — Kevin Long (prefix *Kiowa*), Sue Smith (*Beads Amore*),
   Esther Morse (*Esther*), and Pauline Mariano (*Pauline*) are pre-seeded at
   the default 40% split on a fresh database. Fill in each one's Zelle
   contact and W-9 status (payouts are blocked without a W-9 unless you
   override), plus any business names or extra aliases.
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
