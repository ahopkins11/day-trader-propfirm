"""New York time, without the machine's time zone, and the regular trading hours
calendar. Adapted from upstream day-trader-skill (MIT).

CME equity-index futures trade nearly 24 hours, but the strategies here work the
regular session (9:30 a.m. to 4:00 p.m. ET), so the NYSE holiday and early-close
lists below are used to know when that session exists. CME holiday hours can
differ slightly from the NYSE's: check your platform on a holiday week.
"""
import datetime
import re

NYSE_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
EARLY_CLOSE = {  # the regular session ends 1:00 p.m. ET
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
CALENDAR_YEARS = (2026, 2027)
EARLY = datetime.time(13, 0)
EPOCH = datetime.datetime(1970, 1, 1)


class ClockError(Exception):
    pass


def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """-4 in daylight time, -5 otherwise (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    """naive UTC -> naive New York time."""
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def eastern_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


def ts_to_eastern(ts):
    return to_eastern(EPOCH + datetime.timedelta(seconds=int(ts)))


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def parse_now(text):
    """--now text -> naive New York time. No offset means New York time.
    Empty means the real clock."""
    if not text:
        return to_eastern(utc_now())
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise ClockError('--now wants a time like "2026-10-19 10:15" (New York) or ...Z (UTC)')
    if dt.tzinfo is None:
        return dt
    return to_eastern((dt - dt.utcoffset()).replace(tzinfo=None))


def parse_hhmm(text, what="time"):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ClockError("%s wants a New York time like 10:15, got %r" % (what, text))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def trading_day(d):
    if d.weekday() >= 5:
        return False, "weekend"
    name = NYSE_HOLIDAYS.get(d.isoformat())
    if name:
        return False, "holiday: " + name
    return True, ""


def session(d, spec):
    """(open_dt, close_dt) of the contract's regular session on day d, naive ET,
    or None when there is none."""
    ok, _ = trading_day(d)
    if not ok:
        return None
    o = parse_hhmm(spec["rth"][0])
    c = parse_hhmm(spec["rth"][1])
    if d.isoformat() in EARLY_CLOSE and c > EARLY:
        c = EARLY
    return datetime.datetime.combine(d, o), datetime.datetime.combine(d, c)


def ampm(t):
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def hm(t):
    return t.strftime("%H:%M")
