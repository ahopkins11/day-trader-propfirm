"""AJ's NYAM sweep + iFVG strategy on a hand-built week where the answer is known.

Wed 2026-10-21, ES:
  Mon daily candle 5990-6010; Tue closes 6020 above Mon's high -> bias long.
  Tue: 10:00 spike to 6030 (PDH, prev NYAM high, 1H swing high) leaves a bearish
       5m FVG 6025-6027; 13:00-13:45 rally leaves bullish 15m/1H FVGs below 6020.
  Wed: Asia 6019.25-6019.75, London 6016-6019. 9:00-9:15 drop sweeps the Asia
       and London lows into the Tue FVGs and leaves a bearish 5m FVG 6017-6019.
       9:35 displacement candle closes 6020, through 6019 -> iFVG entry.
  Expected: long 6020.00, stop 6014.00 (sweep low 6014.50 - 2 ticks), target
  6030.00 (1.67R), breakeven trigger 6025.00; 9:40 touches it, 9:45 hits 6030.
"""
import datetime
import unittest

from _load import ROOT  # noqa: F401
from propfirm import config, contracts, engine

DT = datetime.datetime
ES = contracts.spec("ES")
WED = datetime.date(2026, 10, 21)


def bar(t, o, h, l, c, v=1000):
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": v}


def flat(t, price, wiggle=0.0):
    return bar(t, price, price + wiggle, price - wiggle, price)


def week():
    special = {}

    def put(day, hhmm, o, h, l, c):
        special[DT.combine(day, datetime.datetime.strptime(hhmm, "%H:%M").time())] = (o, h, l, c)

    mon, tue = datetime.date(2026, 10, 19), datetime.date(2026, 10, 20)
    put(mon, "11:00", 6000, 6010, 6000, 6000)
    put(mon, "13:00", 6000, 6000, 5990, 6000)
    put(tue, "10:00", 6008, 6030, 6008, 6029)
    put(tue, "10:05", 6029, 6029, 6027, 6027.5)
    put(tue, "10:10", 6027.5, 6027.5, 6024, 6024.5)
    put(tue, "10:15", 6024.5, 6025, 6023, 6023.5)
    for m in ("13:00", "13:05", "13:10"):
        put(tue, m, 6011.5, 6012, 6011.5, 6011.5)
    put(tue, "13:15", 6012, 6016, 6012, 6016)
    put(tue, "13:20", 6016, 6017, 6016, 6017)
    put(tue, "13:25", 6017, 6018, 6017, 6018)
    for m in ("13:30", "13:35", "13:40"):
        put(tue, m, 6018, 6018, 6015.5, 6018)
    put(WED, "03:00", 6018, 6018.25, 6016, 6018)
    put(WED, "04:00", 6018, 6019, 6017.75, 6018)
    put(WED, "09:00", 6019.5, 6020, 6019, 6019.25)
    put(WED, "09:05", 6019.25, 6019.25, 6016.5, 6016.75)
    put(WED, "09:10", 6016.75, 6017, 6015.5, 6016)
    put(WED, "09:15", 6016, 6016.25, 6014.5, 6015)
    put(WED, "09:20", 6015, 6015.5, 6014.75, 6015.25)
    put(WED, "09:25", 6015.25, 6015.75, 6015, 6015.5)
    put(WED, "09:30", 6015.5, 6016, 6015.25, 6015.75)
    put(WED, "09:35", 6015.75, 6020.25, 6015.5, 6020)
    put(WED, "09:40", 6020, 6025.5, 6019.75, 6025)
    put(WED, "09:45", 6025, 6030.5, 6024, 6030)

    def base(t):
        if t < DT(2026, 10, 19, 18):
            return 6000, 0
        if t < DT(2026, 10, 20, 10, 0):
            return 6008, 0
        if t < DT(2026, 10, 20, 13, 45):
            return 6011.5, 0
        if t < DT(2026, 10, 20, 18):
            return 6020, 0
        if DT(2026, 10, 21, 2) <= t < DT(2026, 10, 21, 5):
            return 6018, 0.25
        if t >= DT(2026, 10, 21, 9, 50):
            return 6030, 0
        return 6019.5, 0.25

    out, t = [], DT(2026, 10, 18, 18)
    while t < DT(2026, 10, 21, 12):
        if t.hour != 17:                       # the daily 5-6 PM halt
            if t in special:
                out.append(bar(t, *special[t]))
            else:
                price, w = base(t)
                out.append(flat(t, price, w))
        t += datetime.timedelta(minutes=5)
    return out


def setup(**params):
    cfg = dict(config.DEFAULTS, strategy="nyam")
    strat, p = config.load_strategy(cfg)
    p.update(params)
    return cfg, strat, p


class NyamKnownDay(unittest.TestCase):
    def test_signal(self):
        cfg, strat, p = setup()
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 9, 41), ES, cfg)
        self.assertEqual(r["status"], "triggered", r["reason"])
        pl = r["plan"]
        self.assertEqual((pl["side"], pl["entry"], pl["stop"], pl["target"], pl["breakeven"]),
                         ("long", 6020.0, 6014.0, 6030.0, 6025.0))
        self.assertEqual((pl["risk_ticks"], pl["reward_ticks"], pl["bar_close"][11:]), (24, 40, "09:40"))
        self.assertEqual(pl["bar_index"], 1)
        self.assertEqual(r["levels"]["bias"], "long")

    def test_waiting_before_the_inversion(self):
        cfg, strat, p = setup()
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 9, 32), ES, cfg)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("waiting for a 5m iFVG", r["reason"])

    def test_pre_market_status(self):
        cfg, strat, p = setup()
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 8, 30), ES, cfg)
        self.assertEqual(r["status"], "waiting")
        self.assertIn("bias long", r["reason"])

    def test_min_rr_skips(self):
        cfg, strat, p = setup(min_rr=2.0)
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 11, 30), ES, cfg)
        self.assertEqual(r["status"], "expired")

    def test_no_bias_no_trade(self):
        cfg, strat, p = setup(bias="none")
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 9, 41), ES, cfg)
        self.assertEqual(r["status"], "waiting")
        cfg, strat, p = setup(bias="short")
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 9, 41), ES, cfg)
        self.assertNotEqual(r["status"], "triggered")

    def test_weak_candle_is_not_displacement(self):
        cfg, strat, p = setup(displacement_x=20.0)
        r = engine.evaluate_day(strat, p, week(), DT(2026, 10, 21, 9, 41), ES, cfg)
        self.assertNotEqual(r["status"], "triggered")

    def test_history_walks_to_target(self):
        cfg, strat, p = setup()
        h = engine.history(strat, p, week(), ES, cfg, datetime.date(2026, 10, 22))
        self.assertEqual(h["fired"], 1)
        t = h["trades"][0]
        self.assertEqual((t["entry_at"], t["outcome"], t["exit"], t["exit_at"]), ("09:40", "target", 6030.0, "09:50"))
        self.assertAlmostEqual(t["r"], 10 / 6.0, places=2)


class Breakeven(unittest.TestCase):
    PLAN = {"side": "long", "entry": 100.0, "stop": 98.0, "target": 106.0, "breakeven": 103.0}

    def b(self, m, h, l):
        t = DT(2026, 10, 21, 10, m)
        return {"t": t, "end": t + datetime.timedelta(minutes=5), "o": 100, "h": h, "l": l, "c": 100}

    def test_moves_to_entry_then_scratches(self):
        w = engine.walk(self.PLAN, [self.b(0, 103.5, 99.5), self.b(5, 101, 99.75)], DT(2026, 10, 21, 15, 55))
        self.assertEqual((w["outcome"], w["r"]), ("breakeven", 0.0))

    def test_stop_before_trigger_is_a_loss(self):
        w = engine.walk(self.PLAN, [self.b(0, 102, 97.5)], DT(2026, 10, 21, 15, 55))
        self.assertEqual(w["outcome"], "stop")

    def test_daily_stop_rule(self):
        rule = {"losses": 1, "breakevens": 2, "wins": 2}
        self.assertTrue(engine.day_done(["loss"], rule))
        self.assertFalse(engine.day_done(["win", "be"], rule))
        self.assertTrue(engine.day_done(["be", "be"], rule))
        self.assertTrue(engine.day_done(["win", "be", "win"], rule))
        self.assertTrue(engine.day_done(["win"], None))          # ORB: one trade a day


if __name__ == "__main__":
    unittest.main()
