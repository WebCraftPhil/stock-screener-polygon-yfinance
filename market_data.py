"""Exchange-session helpers used to label timestamps without guessing data."""
from datetime import datetime, time, date, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def market_session(timestamp: datetime) -> str:
    """Return premarket/regular/after-hours/closed for US Eastern wall time.

    This labels clock intervals only; callers must validate holidays and actual
    provider timestamps before treating a quote as a current market observation.
    """
    local = timestamp.astimezone(NEW_YORK) if timestamp.tzinfo else timestamp.replace(tzinfo=NEW_YORK)
    t = local.time().replace(tzinfo=None)
    if time(4) <= t < time(9, 30):
        return "premarket"
    if time(9, 30) <= t < time(16):
        return "regular"
    if time(16) <= t < time(20):
        return "after-hours"
    return "closed"


def is_nyse_session(timestamp: datetime) -> bool:
    """Use exchange_calendars when installed to reject weekends and holidays."""
    local = timestamp.astimezone(NEW_YORK) if timestamp.tzinfo else timestamp.replace(tzinfo=NEW_YORK)
    try:
        import exchange_calendars as xcals
        cal = xcals.get_calendar("XNYS")
        return bool(cal.is_session(local.date().isoformat()))
    except ImportError:
        day = local.date()
        return day.weekday() < 5 and day not in _us_market_holidays(day.year)


def _us_market_holidays(year: int) -> set[date]:
    def observed(d: date) -> date:
        return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d
    def nth_weekday(month: int, weekday: int, n: int) -> date:
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    def last_weekday(month: int, weekday: int) -> date:
        last = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    easter_month = (h + l - 7 * m + 114) // 31
    easter_day = (h + l - 7 * m + 114) % 31 + 1
    good_friday = date(year, easter_month, easter_day) - timedelta(days=2)
    return {observed(date(year, 1, 1)), nth_weekday(1, 0, 3), nth_weekday(2, 0, 3), good_friday,
            last_weekday(5, 0), observed(date(year, 6, 19)), observed(date(year, 7, 4)),
            nth_weekday(9, 0, 1), nth_weekday(11, 3, 4), observed(date(year, 12, 25))}
