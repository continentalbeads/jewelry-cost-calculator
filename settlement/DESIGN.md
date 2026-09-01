# CBS Consignment Settlement — Design

Read this first. It documents the schema and the matching approach, and flags every
assumption I made so you can correct them before (or after) your first real run.
Nothing here is hard to change — the SQLite file is the source of truth and the UI
is a thin layer over it.

## Stack

- Python 3 + Flask + SQLite. One dependency (`pip install flask`), runs locally,
  single user, no auth, no hosting.
- All money is **integer cents**. Percentages are **basis points** (4000 = 40%).
  No floats anywhere in money math.
- DB file: `settlement/data/cbs.sqlite`. Automatic backup copy to
  `settlement/data/backups/` before every committed run.

## Core model: the append-only ledger

`ledger` is the source of truth. One row per financial event per consignor.
A consignor's balance is `SUM(amount_cents)` over their rows. Everything else
(statements, payout worksheet, 1099) is a view over it.

| type | sign of `amount_cents` | meaning |
|---|---|---|
| `SALE` | + | consignor's share of net proceeds for one sold line |
| `REFUND` | − | consignor's share of a refunded line (hits the month it comes back) |
| `ADJUSTMENT` | either | manual correction, **note required** |
| `CHARGE` | − | money you bill the consignor (e.g. recurring display-case rent) |
| `PAYOUT` | − | money you sent them (date + method recorded) |

- The ledger is enforced append-only with SQLite triggers: `UPDATE` and `DELETE`
  on `ledger` abort. Corrections are new `ADJUSTMENT` rows.
- Negative balances are allowed and simply carry forward; the payout worksheet
  floors amount-due at zero. No clawbacks.
- Every sale/refund row stores gross, itemized fee detail (JSON), net, consignor
  share, your share, the source order/line reference, and a `manually_edited` flag.

## Tables

- `consignors` — name, business name, split (bps, default 4000 = 40% to them),
  Zelle contact, W-9 on file, active flag, optional recurring monthly charge
  (amount / start / end / note).
- `aliases` — many per consignor. `kind='prefix'` rows are used for **SKU
  prefix** matching *and* title matching; `kind='alias'` rows are title-only
  (for typo variants you save from the review queue).
- `fee_schedule` — channel, fee name, percent (bps), fixed cents, effective-from,
  effective-to (nullable), deductible flag, **verified flag**. Multiple rows per
  channel stack. Rate changes mid-month = end-date the old row, add a new row
  with the new effective-from; each order line uses the rows in effect on **its
  order date**.
- `imports` / `import_lines` — raw CSV staging. Each line gets a deterministic
  `line_key` (Shopify line-item ID if your export has one, else a hash of
  order + sku + title + qty + amount + date, with an occurrence counter for
  identical duplicates within one order). Re-importing the same CSV skips
  existing keys — **idempotent, no double counting**.
- `runs` / `run_lines` / `run_line_fees` — a settlement run is a *draft*
  workspace: every matched, unsettled line is copied in with its
  schedule-computed fees, and everything is editable there (gross, each fee,
  split, exclude, ad-hoc fees, manual lines). Only **commit** writes to the
  ledger. Original values are stored on first edit and every change is written
  to `audit_log` (old value, new value, timestamp).
- `audit_log` — every edit anywhere (run lines, fees, consignors, fee schedule).
- `inventory_items` — stub table for the future aging report (days listed,
  6-month / 12-month markdown flags). No import yet; the hook exists.

## Matching approach (import → review queue)

For each imported line, in order:

1. **SKU prefix** — SKU, lowercased, starts with a known consignor prefix
   (separator-tolerant: `kiowa-1234`, `KIOWA1234`, `kiowa_1234` all match
   prefix `Kiowa`). → **confident** bucket.
1b. **Product tag** — the line's SKU (or exact title) is found in the imported
   Shopify *product* catalog and that product's Tags include a consignor's
   tag alias (Kiowa items online carry the tag `Kevin Long`). Shopify's order
   export doesn't include product tags, so this needs the product export
   uploaded on the Import page; uploads replace the stored catalog and re-run
   matching on pending lines. → **confident**.
2. **Title contains** — the line title, lowercased and whitespace-normalized,
   contains a prefix or alias as a token/substring. → **confident**.
3. **Fuzzy title** — each word token of the title is compared to every
   prefix/alias with `difflib.SequenceMatcher`; best ratio ≥ 0.72 →
   **fuzzy** bucket, shown with the score and the raw typed text for you to
   confirm or reject. (Catches `Kiwoa lampwork bead`, `kiowa's`, `KIOWA-`.)
4. Otherwise → **unmatched** bucket.

Review-queue rules:

- Nothing settles until every fuzzy line is confirmed/rejected and every
  unmatched line is either assigned to a consignor or explicitly dismissed as
  not-consignment. Run creation is blocked while the queue has pending lines.
  A bulk "dismiss all remaining unmatched" button exists (explicit, never
  silent) because most showroom lines are your own retail merchandise.
- When you manually assign a line, the form offers to save the text as a new
  alias so it matches automatically next time, then you can hit "re-run
  matching" to sweep the rest of the queue with the new alias.
- Confident matches are also listed (collapsed) so you can catch a wrong
  auto-match; nothing is hidden.

## Channels and fees

- Channel is guessed per line from the mapped source column
  (`ebay→eBay`, `etsy→Etsy`, `faire→Faire`, `pos/point of sale→Showroom POS`,
  `web/online→Shopify Online`) and is overridable per line in the review queue.
- Fee per line = sum over applicable schedule rows (channel matches, deductible,
  order date within effective window) of `round_half_up(gross × bps/10000) +
  fixed`. Fixed fees flip sign on refund lines so the fee reverses too.
- Gross = line quantity × unit price (minus line discount if you map one).
  **Shipping never enters**: the import reads line items only, so order-level
  shipping is excluded from the split base and never deducted as a fee.

## Assumptions to correct (flagged in the UI too)

1. **Every seeded fee rate is a placeholder and marked UNVERIFIED** — a red
   banner stays up until you've confirmed or replaced each row. Seeds:
   Shopify Payments online 2.9% + 30¢; Shopify Payments card-present
   (Showroom POS) 2.6% + 10¢; eBay final value 13.6% + 30¢; Etsy transaction
   6.5%; Etsy processing 3% + 25¢; Faire commission 15%.
2. **Etsy Offsite Ads (15%) is seeded as NOT auto-applied** (deductible=no),
   because it only hits attributed orders — auto-deducting it from every Etsy
   sale would overcharge consignors. Add it per-line as an ad-hoc fee on
   attributed orders, or flip the row to deductible if virtually all your Etsy
   volume is attributed. eBay Promoted Listings is seeded non-deductible per
   your rules.
3. **Refund rows**: a CSV line with negative quantity/price/total imports as a
   refund. Shopify's order export often reports refunds only order-level
   (`Refunded Amount`), not per line — lines whose financial status contains
   "refunded" are tagged with a warning in the review queue, and you can add a
   manual REFUND line in any run for partial/otherwise-invisible refunds.
4. **Rounding**: half-up (away from zero), applied per fee and once to the
   consignor share; your share is `net − their share`, so the split always sums
   exactly.
5. **Recurring charges** post on commit, once per consignor per period month
   (deduped by `recurring:YYYY-MM`), dated the 1st of the period.
6. **Prior balance on a statement** = the consignor's entire ledger before this
   run's entries (sales, refunds, charges, adjustments, payouts), so deficits
   and unpaid remainders carry forward automatically.
