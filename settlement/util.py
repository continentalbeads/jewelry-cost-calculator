"""Money and date helpers. All money is integer cents; percentages are basis points."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def parse_cents(value):
    """Parse a user/CSV money string into integer cents. Raises ValueError on garbage."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    s = str(value).strip().replace("$", "").replace(",", "")
    if not s:
        return 0
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not a money amount: {value!r}")
    if negative:
        d = -d
    return int(d.scaleb(2).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_int(value, default=1):
    s = str(value or "").strip()
    if not s:
        return default
    try:
        return int(Decimal(s).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return default


def round_half_up_div(n, d):
    """Integer division rounding half away from zero (money-safe, sign-correct)."""
    sign = -1 if n < 0 else 1
    n = abs(n)
    return sign * ((n + d // 2) // d)


def apply_bps(cents, bps):
    """cents x (bps/10000), rounded half away from zero."""
    return round_half_up_div(cents * bps, 10000)


def fmt_money(cents):
    if cents is None:
        return ""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def fmt_bps(bps):
    if bps is None:
        return ""
    pct = Decimal(bps) / 100
    s = f"{pct.normalize():f}"
    return f"{s}%"


_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M %z",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m/%d/%y",
]


def parse_date(value):
    """Parse a CSV date string to YYYY-MM-DD, or None."""
    s = str(value or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s).date().isoformat()
    except ValueError:
        return None


def today():
    return datetime.now().date().isoformat()
