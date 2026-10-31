"""Builds tests/fixtures/ES-synthetic-5m.json: SYNTHETIC ES bars in Yahoo's
chart format, made from a seeded random walk. It is not market data. It exists
so the tests run offline and reproduce exactly. Re-run to rebuild:

    python3 tests/make_fixtures.py

The last session (2026-10-19) is hand-built so the ORB answer is known:
  opening range 9:30-9:45: high 6010.00, low 6000.00, mid 6005.00
  9:45 bar closes 6008.00 (inside), 9:50 bar closes 6012.25 (breakout)
  -> long 6012.25, stop 6005.00 (29 ticks), target 6019.50 (1R)
  the 10:20 bar reaches 6020.00: the target is hit first.
"""
import datetime
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from propfirm import clock  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ES-synthetic-5m.json")
LAST = datetime.date(2026, 10, 19)


def rnd_day_bars(rng, day, price):
    """All-hours 5-minute bars 6:00 p.m. the evening before to 5:00 p.m. ET."""
    bars = []
    t = datetime.datetime.combine(day - datetime.timedelta(days=1), datetime.time(18, 0))
    end = datetime.datetime.combine(day, datetime.time(17, 0))
    while t < end:
        rth = datetime.time(9, 30) <= t.time() < datetime.time(16, 0)
        vol = 2.2 if rth else 0.7
        if rth and t.time() < datetime.time(10, 30):
            vol = 3.4
        o = price
        c = o + rng.gauss(0.02, vol)
        h = max(o, c) + abs(rng.gauss(0, vol * 0.6))
        l = min(o, c) - abs(rng.gauss(0, vol * 0.6))
        q = lambda x: round(x * 4) / 4.0  # noqa: E731
        bars.append((t, q(o), q(h), q(l), q(c), int(rng.uniform(4000, 20000) if rth else rng.uniform(200, 2000))))
        price = c
        t += datetime.timedelta(minutes=5)
    return bars, price


def known_day(day):
    bars = []
    t0 = datetime.datetime.combine(day, datetime.time(9, 30))
    fixed = [  # o, h, l, c   one per 5 minutes from 9:30
        (6003.00, 6006.00, 6000.00, 6005.50),
        (6005.50, 6010.00, 6004.00, 6007.25),
        (6007.25, 6008.50, 6002.75, 6004.00),   # range: 6000.00 - 6010.00
        (6004.00, 6009.00, 6003.50, 6008.00),   # 9:45 inside
        (6008.00, 6013.00, 6007.50, 6012.25),   # 9:50 breakout close
        (6012.25, 6015.00, 6009.00, 6014.00),
        (6014.00, 6016.50, 6011.00, 6013.25),
        (6013.25, 6017.75, 6012.00, 6017.00),
        (6017.00, 6018.25, 6013.50, 6015.75),
        (6015.75, 6019.25, 6014.00, 6018.50),
        (6018.50, 6020.00, 6016.00, 6019.75),   # 10:20 reaches 6020.00 >= 6019.50
    ]
    for k, (o, h, l, c) in enumerate(fixed):
        bars.append((t0 + datetime.timedelta(minutes=5 * k), o, h, l, c, 15000))
    t = t0 + datetime.timedelta(minutes=5 * len(fixed))
    price = 6019.75
    while t.time() < datetime.time(16, 0):
        bars.append((t, price, price + 1, price - 1, price, 6000))
        t += datetime.timedelta(minutes=5)
    return bars


def main():
    rng = random.Random(2026)
    price = 5900.0
    rows = []
    d = LAST - datetime.timedelta(days=95)
    while d < LAST:
        ok, _ = clock.trading_day(d)
        if ok:
            b, price = rnd_day_bars(rng, d, price)
            rows += b
        d += datetime.timedelta(days=1)
    rows += known_day(LAST)
    ts = [int((clock.eastern_to_utc(r[0]) - clock.EPOCH).total_seconds()) for r in rows]
    doc = {"chart": {"result": [{
        "meta": {"symbol": "ES=F", "note": "SYNTHETIC test data from tests/make_fixtures.py, not market data"},
        "timestamp": ts,
        "indicators": {"quote": [{"open": [r[1] for r in rows], "high": [r[2] for r in rows],
                                  "low": [r[3] for r in rows], "close": [r[4] for r in rows],
                                  "volume": [r[5] for r in rows]}]}}], "error": None}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    print("wrote %d bars to %s" % (len(rows), OUT))


if __name__ == "__main__":
    main()
