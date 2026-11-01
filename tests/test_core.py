"""Contracts, clock, data, strategy loading and the ORB rule on a known day."""
import datetime
import json
import os
import shutil
import tempfile
import unittest

from _load import ES, FIX, ROOT
from propfirm import clock, config, contracts, data, engine

DT = datetime.datetime


class Contracts(unittest.TestCase):
    def test_es_and_micro_math(self):
        es, mes = contracts.spec("es"), contracts.spec("MES=F")
        self.assertEqual(es["point_value"], 50.0)
        self.assertEqual(mes["point_value"], 5.0)
        self.assertEqual(contracts.ticks_between(6012.25, 6005.00, es), 29)
        self.assertEqual(contracts.dollars(29, es), 362.5)
        self.assertEqual(contracts.dollars(29, mes, 5), 181.25)
        self.assertEqual(es["micro"], "MES")
        self.assertTrue(mes["is_micro"])

    def test_every_contract_point_value(self):
        want = {"ES": 50, "MES": 5, "NQ": 20, "MNQ": 2, "YM": 5, "MYM": 0.5, "RTY": 50, "M2K": 5,
                "CL": 1000, "MCL": 100, "GC": 100, "MGC": 10}
        for sym, pv in want.items():
            self.assertAlmostEqual(contracts.spec(sym)["point_value"], pv, msg=sym)

    def test_stop_rounds_away_from_entry(self):
        es = contracts.spec("ES")
        self.assertEqual(contracts.stop_tick(6005.10, 6012.25, es), 6005.00)   # long: down
        self.assertEqual(contracts.stop_tick(6019.60, 6012.25, es), 6019.75)   # short: up
        self.assertEqual(contracts.round_tick(6019.60, es), 6019.50)
        self.assertEqual(contracts.fmt_price(6012.5, es), "6012.50")
        self.assertEqual(contracts.fmt_price(42000, contracts.spec("YM")), "42000")

    def test_unknown_symbol(self):
        with self.assertRaises(contracts.ContractError):
            contracts.spec("TSLA")


class Clock(unittest.TestCase):
    def test_dst_both_sides(self):
        self.assertEqual(clock.to_eastern(DT(2026, 10, 19, 13, 30)), DT(2026, 10, 19, 9, 30))
        self.assertEqual(clock.to_eastern(DT(2026, 11, 2, 14, 30)), DT(2026, 11, 2, 9, 30))

    def test_sessions(self):
        es, cl = contracts.spec("ES"), contracts.spec("CL")
        self.assertEqual(clock.session(datetime.date(2026, 10, 19), es), (DT(2026, 10, 19, 9, 30), DT(2026, 10, 19, 16, 0)))
        self.assertIsNone(clock.session(datetime.date(2026, 11, 26), es))          # Thanksgiving
        self.assertEqual(clock.session(datetime.date(2026, 11, 27), es)[1], DT(2026, 11, 27, 13, 0))
        self.assertEqual(clock.session(datetime.date(2026, 10, 19), cl)[0], DT(2026, 10, 19, 9, 0))
        self.assertIsNone(clock.session(datetime.date(2026, 10, 18), es))          # Sunday

    def test_parse_now(self):
        self.assertEqual(clock.parse_now("2026-10-19 10:15"), DT(2026, 10, 19, 10, 15))
        self.assertEqual(clock.parse_now("2026-10-19T14:15:00Z"), DT(2026, 10, 19, 10, 15))
        with self.assertRaises(clock.ClockError):
            clock.parse_now("tomorrow")


class Data(unittest.TestCase):
    def test_real_yahoo_chart_format_parses(self):
        p = os.path.join(FIX, "real-yahoo", "TSLA-2026-10-19-5m.json")
        bars = data.load_offline(p, "TSLA")
        self.assertEqual(len(bars), 17)                       # a snapshot taken mid-morning
        self.assertEqual(bars[0]["t"], DT(2026, 10, 19, 9, 30))
        self.assertEqual(bars[-1]["t"], DT(2026, 10, 19, 10, 49, 45))   # Yahoo's live tick, off the grid
        sb = data.session_bars(bars, datetime.date(2026, 10, 19), contracts.spec("ES"))
        self.assertEqual(len(sb), 16)                         # the live tick is not a bar
        self.assertEqual(round(max(b["h"] for b in sb[:3]), 2), 362.18)  # upstream README's TSLA range high

    def test_session_filter_drops_overnight_and_open_bars(self):
        bars = data.load_offline(ES, "ES")
        self.assertTrue(any(b["t"].time() < datetime.time(9, 30) for b in bars))   # overnight is in the file
        sb = data.session_bars(bars, datetime.date(2026, 10, 16), contracts.spec("ES"))
        self.assertEqual(len(sb), 78)
        self.assertEqual(sb[0]["i"], 0)
        self.assertEqual(sb[-1]["t"].time(), datetime.time(15, 55))
        part = data.session_bars(bars, datetime.date(2026, 10, 16), contracts.spec("ES"), now=DT(2026, 10, 16, 9, 47))
        self.assertEqual(len(part), 3)                                              # 9:45 bar not closed yet

    def test_csv_and_projectx_formats(self):
        csv_text = "time,open,high,low,close,volume\n2026-10-19 09:30,1,2,0.5,1.5,10\n"
        self.assertEqual(data.parse_any(csv_text)[0]["t"], DT(2026, 10, 19, 9, 30))
        px = {"bars": [{"t": "2026-10-19T13:30:00+00:00", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 3}]}
        self.assertEqual(data.parse_any(json.dumps(px))[0]["t"], DT(2026, 10, 19, 9, 30))
        for stamp in ("2026-10-19T13:30:00.0000000+00:00", "2026-10-19T13:30:00.5+00:00", "2026-10-19T13:30:00Z"):
            self.assertEqual(data._parse_time(stamp).replace(microsecond=0), DT(2026, 10, 19, 9, 30), stamp)

    def test_past_sessions(self):
        bars = data.load_offline(ES, "ES")
        past = data.past_sessions(bars, datetime.date(2026, 10, 19), contracts.spec("ES"))
        self.assertEqual(len(past), 59)
        self.assertLess(past[-1][0], datetime.date(2026, 10, 19))


class StrategyLoading(unittest.TestCase):
    def test_default_is_orb(self):
        mod, params = config.load_strategy(config.DEFAULTS)
        self.assertEqual(mod.NAME, "orb")
        self.assertEqual(params["range_minutes"], 15)
        self.assertTrue(mod.__file_path__.endswith(os.path.join("strategies", "orb.py")))

    def test_config_overrides_params(self):
        cfg = dict(config.DEFAULTS, strategy_params={"range_minutes": 30, "direction": "both"})
        _, params = config.load_strategy(cfg)
        self.assertEqual((params["range_minutes"], params["direction"]), (30, "both"))

    def test_template_loads_and_project_strategy_wins(self):
        mod, _ = config.load_strategy(dict(config.DEFAULTS, strategy="template"))
        self.assertEqual(mod.NAME, "template")
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "trader", "strategies"))
            shutil.copy(os.path.join(ROOT, "strategies", "template.py"),
                        os.path.join(tmp, "trader", "strategies", "mine.py"))
            mod, _ = config.load_strategy(dict(config.DEFAULTS, strategy="mine"), base=tmp)
            self.assertTrue(mod.__file_path__.startswith(tmp))
        finally:
            shutil.rmtree(tmp)

    def test_missing_strategy(self):
        with self.assertRaises(config.ConfigError):
            config.load_strategy(dict(config.DEFAULTS, strategy="nope"))

    def test_example_config_matches_defaults(self):
        with open(os.path.join(ROOT, "config.example.json")) as fh:
            ex = json.load(fh)
        for k in config.DEFAULTS:
            self.assertIn(k, ex, k)
        for k in config.DEFAULTS["account"]:
            self.assertIn(k, ex["account"], k)
        for k in config.DEFAULTS["personal"]:
            self.assertIn(k, ex["personal"], k)


class OrbKnownDay(unittest.TestCase):
    """tests/make_fixtures.py hand-builds 2026-10-19: range 6000-6010, breakout close 6012.25 at 9:55."""

    @classmethod
    def setUpClass(cls):
        cls.bars = data.load_offline(ES, "ES")
        cls.cfg = config.load(os.path.join(tempfile.mkdtemp(), "none.json"))
        cls.strat, cls.params = config.load_strategy(cls.cfg)
        cls.es = contracts.spec("ES")

    def at(self, hhmm, **over):
        params = dict(self.params, **over)
        return engine.evaluate_day(self.strat, params, self.bars, DT(2026, 10, 19, *map(int, hhmm.split(":"))),
                                   self.es, self.cfg)

    def test_phases(self):
        self.assertEqual(self.at("09:00")["status"], "pre-open")
        self.assertEqual(self.at("09:40")["status"], "forming")
        self.assertEqual(self.at("09:50")["status"], "waiting")
        self.assertEqual(self.at("09:55")["status"], "triggered")

    def test_levels_and_plan(self):
        r = self.at("10:30")
        self.assertEqual(r["levels"]["range_high"], 6010.0)
        self.assertEqual(r["levels"]["range_low"], 6000.0)
        p = r["plan"]
        self.assertEqual((p["side"], p["entry"], p["stop"], p["target"]), ("long", 6012.25, 6005.0, 6019.5))
        self.assertEqual((p["risk_ticks"], p["reward_ticks"], p["risk_usd_per_contract"]), (29, 29, 362.5))
        self.assertEqual(p["bar_close"], "2026-10-19 09:55")

    def test_stop_at_range_and_2r(self):
        p = self.at("10:30", stop="range", target_r=2.0)["plan"]
        self.assertEqual((p["stop"], p["target"]), (6000.0, 6036.75))

    def test_walk_hits_target_at_1020(self):
        p = self.at("10:30")["plan"]
        after = [b for b in data.session_bars(self.bars, datetime.date(2026, 10, 19), self.es)
                 if b["t"] >= DT(2026, 10, 19, 9, 55)]
        w = engine.walk(p, after, DT(2026, 10, 19, 15, 55))
        self.assertEqual((w["outcome"], w["exit"], w["at"], w["r"]), ("target", 6019.5, "10:25", 1.0))

    def test_entry_window_blocks_early_breakout(self):
        cfg = dict(self.cfg, no_entries_before="10:00")
        r = engine.evaluate_day(self.strat, self.params, self.bars, DT(2026, 10, 19, 9, 56), self.es, cfg)
        self.assertEqual(r["status"], "waiting")

    def test_expired_after_cutoff(self):
        cfg = dict(self.cfg, no_entries_after="09:50")
        r = engine.evaluate_day(self.strat, self.params, self.bars, DT(2026, 10, 19, 11, 0), self.es, cfg)
        self.assertEqual(r["status"], "expired")

    def test_holiday(self):
        r = engine.evaluate_day(self.strat, self.params, self.bars, DT(2026, 11, 26, 10, 0), self.es, self.cfg)
        self.assertEqual(r["status"], "closed")


class FifteenMinuteBars(unittest.TestCase):
    """The known day built into 15-minute candles from its 5-minute bars."""

    def test_aggregation(self):
        bars = data.load_offline(ES, "ES")
        sb = data.session_bars(bars, datetime.date(2026, 10, 19), contracts.spec("ES"), bar_minutes=15)
        first = sb[0]
        self.assertEqual((first["t"], first["end"], first["i"]), (DT(2026, 10, 19, 9, 30), DT(2026, 10, 19, 9, 45), 0))
        self.assertEqual((first["o"], first["h"], first["l"], first["c"]), (6003.00, 6010.00, 6000.00, 6004.00))
        self.assertEqual(len(sb), 26)
        part = data.session_bars(bars, datetime.date(2026, 10, 19), contracts.spec("ES"),
                                 now=DT(2026, 10, 19, 9, 55), bar_minutes=15)
        self.assertEqual(len(part), 1)                       # the 9:45 candle is still forming

    def test_orb_on_15_minute_candles(self):
        bars = data.load_offline(ES, "ES")
        cfg = dict(config.DEFAULTS, bar_minutes=15)
        strat, params = config.load_strategy(cfg)
        r = engine.evaluate_day(strat, params, bars, DT(2026, 10, 19, 10, 30), contracts.spec("ES"), cfg)
        p = r["plan"]
        self.assertEqual((p["entry"], p["stop"], p["bar_close"][11:], p["risk_ticks"]), (6014.0, 6005.0, "10:00", 36))
        self.assertEqual(r["levels"]["range_high"], 6010.0)

    def test_history_runs_on_15(self):
        bars = data.load_offline(ES, "ES")
        cfg = dict(config.DEFAULTS, bar_minutes=15)
        strat, params = config.load_strategy(cfg)
        h = engine.history(strat, params, bars, contracts.spec("ES"), cfg, datetime.date(2026, 10, 19))
        self.assertEqual(h["fired"], h["target"] + h["stop"] + h["flat"])


class Shorts(unittest.TestCase):
    def test_short_breakout(self):
        orb = config.load_strategy(config.DEFAULTS)[0]
        t0 = DT(2026, 10, 19, 9, 30)
        bars = []
        for k, (o, h, l, c) in enumerate([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100), (100, 100, 97, 98.5)]):
            bars.append({"t": t0 + datetime.timedelta(minutes=5 * k), "end": t0 + datetime.timedelta(minutes=5 * k + 5),
                         "i": k, "o": o, "h": h, "l": l, "c": c, "v": 10})
        ctx = {"bar_minutes": 5, "can_enter": lambda b: True}
        p = dict(orb.PARAMS, direction="both")
        r = orb.evaluate(bars, p, ctx)
        self.assertEqual((r["signal"]["side"], r["signal"]["entry"], r["signal"]["stop"], r["signal"]["target"]),
                         ("short", 98.5, 100.0, 97.0))
        self.assertIsNone(orb.evaluate(bars, dict(orb.PARAMS, direction="long"), ctx)["signal"])


if __name__ == "__main__":
    unittest.main()
