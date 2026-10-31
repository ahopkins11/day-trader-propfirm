"""Bars in, bars out. Every tool reads bars through here, so a new data source
only has to be added once.

A bar is a dict: {"t": start time (naive New York), "o", "h", "l", "c", "v"}.

Sources
  yahoo     Yahoo Finance's free chart endpoint (ES=F, NQ=F ...). Continuous
            front-month contract, can be delayed. Fine for research and replays,
            check live entries against your platform's chart.
  offline   a file or folder you saved: Yahoo chart JSON, ProjectX bars JSON
            (prop-broker/projectx.py bars ... --out), or CSV with columns
            time,open,high,low,close,volume.
"""
import csv
import re
import datetime
import io
import json
import os
import time
import urllib.error
import urllib.request

from . import clock

UA = "Mozilla/5.0 (compatible; day-trader-propfirm/1.0)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")


class DataError(Exception):
    pass


# ---------------------------------------------------------------- parsing

def _f(x):
    return None if x is None else float(x)


def _bar(t_et, o, h, l, c, v):
    if None in (o, h, l, c):
        return None
    return {"t": t_et, "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": int(v or 0)}


def _parse_time(text):
    """Unix seconds, ISO with offset (UTC or other) or naive ISO (New York)."""
    if isinstance(text, (int, float)) or str(text).strip().isdigit():
        return clock.ts_to_eastern(int(float(text)))
    t = str(text).strip().replace("Z", "+00:00")
    t = re.sub(r"(\.\d{1,6})\d*", r"\1", t)          # .0000000 -> .000000 (Python 3.8 wants 6 digits at most)
    t = re.sub(r"\.(\d{1,5})(?=[+-]|$)", lambda m: "." + m.group(1).ljust(6, "0"), t)
    dt = datetime.datetime.fromisoformat(t)
    if dt.tzinfo is None:
        return dt
    return clock.to_eastern((dt - dt.utcoffset()).replace(tzinfo=None))


def parse_yahoo(doc):
    res = ((doc.get("chart") or {}).get("result") or [None])[0]
    if not res:
        err = (doc.get("chart") or {}).get("error") or {}
        raise DataError("Yahoo sent no chart (%s)" % (err.get("description") or "empty answer"))
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        def col(k):
            v = q.get(k) or []
            return v[i] if i < len(v) else None
        b = _bar(clock.ts_to_eastern(ts), col("open"), col("high"), col("low"), col("close"), col("volume"))
        if b:
            out.append(b)
    return out


def parse_projectx(doc):
    out = []
    for r in doc.get("bars") or []:
        b = _bar(_parse_time(r["t"]), r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v"))
        if b:
            out.append(b)
    return out


def parse_csv(text):
    out = []
    rows = csv.DictReader(io.StringIO(text))
    for r in rows:
        r = {k.strip().lower(): v for k, v in r.items() if k}
        b = _bar(_parse_time(r.get("time") or r.get("timestamp") or r.get("datetime")),
                 _f(r.get("open")), _f(r.get("high")), _f(r.get("low")), _f(r.get("close")),
                 _f(r.get("volume")) or 0)
        if b:
            out.append(b)
    return out


def parse_any(text):
    s = text.lstrip()
    if s.startswith("{"):
        doc = json.loads(s)
        if "chart" in doc:
            return parse_yahoo(doc)
        if "bars" in doc:
            return parse_projectx(doc)
        raise DataError("JSON is neither a Yahoo chart nor ProjectX bars")
    return parse_csv(text)


def clean(bars):
    """Sorted, one bar per start time (the last one wins)."""
    by = {}
    for b in bars:
        by[b["t"]] = b
    return [by[k] for k in sorted(by)]


# ---------------------------------------------------------------- loading

def offline_path(path, symbol):
    if os.path.isdir(path):
        for ext in (".json", ".csv"):
            for name in (symbol, symbol.lower(), symbol + "=F"):
                p = os.path.join(path, name + ext)
                if os.path.exists(p):
                    return p
        raise DataError("no %s.json or %s.csv in %s" % (symbol, symbol, path))
    return path


def load_offline(path, symbol):
    p = offline_path(path, symbol)
    with open(p, encoding="utf-8") as fh:
        return clean(parse_any(fh.read()))


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def load_yahoo(spec, days=60, interval_min=5, sleep=time.sleep):
    rng = "%dd" % min(int(days), 60)       # Yahoo keeps 60 days of 5-minute bars
    path = "/v8/finance/chart/%s?range=%s&interval=%dm&includePrePost=true" % (spec["yahoo"], rng, interval_min)
    last = "no answer"
    for attempt in (0, 1):
        for host in YAHOO_HOSTS:
            try:
                return clean(parse_yahoo(json.loads(http_get(host + path))))
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = str(getattr(e, "reason", e))
        if attempt == 0:
            sleep(3)
    raise DataError("Yahoo answered %s for %s. Try again, or pass --offline with saved bars." % (last, spec["yahoo"]))


def load(spec, offline=None, days=60, interval_min=5):
    if offline:
        return load_offline(offline, spec["symbol"])
    return load_yahoo(spec, days=days, interval_min=interval_min)


# ---------------------------------------------------------------- sessions

def session_bars(bars, day, spec, now=None, bar_minutes=5):
    """The regular-session bars of `day`, on the bar grid, that have closed by
    `now` (naive ET; None = all of them). Each gets "i", its slot from the open."""
    s = clock.session(day, spec)
    if not s:
        return []
    o, c = s
    step = datetime.timedelta(minutes=bar_minutes)
    out = []
    for b in bars:
        if b["t"].date() != day or not (o <= b["t"] < c):
            continue
        off = (b["t"] - o).total_seconds()
        if off % (bar_minutes * 60):
            continue
        if now is not None and b["t"] + step > now:
            continue
        nb = dict(b)
        nb["i"] = int(off // (bar_minutes * 60))
        nb["end"] = b["t"] + step
        out.append(nb)
    return out


def days_in(bars):
    return sorted({b["t"].date() for b in bars})


def past_sessions(bars, before_day, spec, n=59, bar_minutes=5, min_bars=10):
    """Up to n full regular sessions before `before_day`, oldest first, as
    {day: [bars]}. Days with too few bars (data gaps) are skipped."""
    out = []
    for d in days_in(bars):
        if d >= before_day:
            continue
        sb = session_bars(bars, d, spec, bar_minutes=bar_minutes)
        if len(sb) >= min_bars:
            out.append((d, sb))
    return out[-n:]
