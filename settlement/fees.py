"""Fee computation from the fee schedule, as of a given order date."""
from util import apply_bps


def applicable_fees(conn, channel, order_date):
    """Deductible fee_schedule rows in effect for this channel on this date."""
    if not channel:
        return []
    return conn.execute(
        """SELECT * FROM fee_schedule
           WHERE channel = ? AND deductible = 1
             AND effective_from <= ?
             AND (effective_to IS NULL OR effective_to >= ?)
           ORDER BY id""",
        (channel, order_date or "9999-12-31", order_date or "0000-01-01"),
    ).fetchall()


def compute_fees(conn, channel, order_date, gross_cents):
    """[{fee_schedule_id, fee_name, amount_cents}] per the schedule.
    Fixed fees flip sign for refund (negative-gross) lines so the fee reverses."""
    out = []
    for row in applicable_fees(conn, channel, order_date):
        amount = apply_bps(gross_cents, row["percent_bps"])
        if row["fixed_cents"]:
            amount += row["fixed_cents"] if gross_cents >= 0 else -row["fixed_cents"]
        out.append({
            "fee_schedule_id": row["id"],
            "fee_name": f"{row['channel']}: {row['fee_name']}",
            "amount_cents": amount,
        })
    return out


def channel_list(conn):
    """Known channels: everything in the fee schedule plus anything seen on lines."""
    rows = conn.execute(
        """SELECT DISTINCT channel FROM fee_schedule
           UNION SELECT DISTINCT channel FROM import_lines WHERE channel IS NOT NULL
           ORDER BY 1"""
    ).fetchall()
    return [r["channel"] for r in rows if r["channel"]]
