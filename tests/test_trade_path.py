"""Time Machine, sizing, prop firm rules, tickets and the ProjectX payload,
and the whole pipeline end to end in a scratch folder."""
import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from _load import ES, ROOT, tool
from propfirm import config, contracts, data, engine, rules

DT = datetime.datetime
size = tool("prop-budget", "size")
ticket = tool("prop-broker", "ticket")
projectx = tool("prop-broker", "projectx")


def cfg():
    c = json.loads(json.dumps(config.DEFAULTS))
    return c


def state(**kw):
    st = {"balance": 50000.0, "eod_high": 50000.0, "date": "2026-10-19", "realized_today": 0.0, "trades_today": 0}
    st.update(kw)
    return st


PLAN = {"symbol": "ES", "side": "long", "entry": 6012.25, "stop": 6005.0, "target": 6019.5, "risk_ticks": 29,
        "reward_ticks": 29, "risk_usd_per_contract": 362.5, "reward_usd_per_contract": 362.5, "reward_risk": 1.0,
        "date": "2026-10-19", "flat_by": "15:55", "strategy": "orb", "bar_index": 4}


class TimeMachine(unittest.TestCase):
    def test_monte_carlo_is_repeatable_and_sums_to_100(self):
        bars = data.load_offline(ES, "ES")
        past = data.past_sessions(bars, datetime.date(2026, 10, 19), contracts.spec("ES"))
        pools = engine.slot_pools(past)
        a = engine.simulate(PLAN, 5, 77, pools, sims=2000, seed=19)
        b = engine.simulate(PLAN, 5, 77, pools, sims=2000, seed=19)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["target_pct"] + a["stop_pct"] + a["flat_pct"], 100.0, places=1)

    def test_wide_stop_stays_open(self):
        bars = data.load_offline(ES, "ES")
        pools = engine.slot_pools(data.past_sessions(bars, datetime.date(2026, 10, 19), contracts.spec("ES")))
        wide = dict(PLAN, stop=5000.0, target=7000.0, risk_ticks=4049, reward_ticks=3951)
        self.assertEqual(engine.simulate(wide, 5, 77, pools, sims=200, seed=1)["flat_pct"], 100.0)

    def test_both_touched_counts_as_stop(self):
        bar = {"t": DT(2026, 10, 19, 10, 0), "end": DT(2026, 10, 19, 10, 5), "o": 6012, "h": 6020, "l": 6004, "c": 6010}
        self.assertEqual(engine.walk(PLAN, [bar], DT(2026, 10, 19, 15, 55))["outcome"], "stop")

    def test_history_runs_the_strategy_on_past_days(self):
        bars = data.load_offline(ES, "ES")
        strat, params = config.load_strategy(config.DEFAULTS)
        h = engine.history(strat, params, bars, contracts.spec("ES"), cfg(), datetime.date(2026, 10, 19))
        self.assertEqual(h["sessions"], 59)
        self.assertEqual(h["fired"], h["target"] + h["stop"] + h["flat"])
        self.assertTrue(all(t["date"] < "2026-10-19" for t in h["trades"]))
        for t in h["trades"]:
            self.assertTrue(t["exit_at"] is None or t["exit_at"] >= t["entry_at"], t)


class Sizing(unittest.TestCase):
    def test_falls_back_to_micros(self):
        o = size.size(PLAN, cfg(), state())
        self.assertEqual((o["symbol"], o["contracts"], o["loss_at_stop_usd"]), ("MES", 5, 181.25))
        self.assertIn("MES", o["note"])

    def test_full_size_when_it_fits_and_caps(self):
        c = cfg()
        c["personal"].update(max_loss_per_trade_usd=2000, max_daily_loss_usd=5000, max_contracts=2)
        c["account"]["daily_loss_limit"] = 5000
        o = size.size(PLAN, c, state(eod_high=50000))
        self.assertEqual((o["symbol"], o["contracts"]), ("ES", 2))
        self.assertEqual(o["limited_by"], "max contracts")

    def test_daily_room_shrinks_size(self):
        o = size.size(PLAN, cfg(), state(realized_today=-300.0))
        self.assertEqual((o["symbol"], o["contracts"]), ("MES", 2))   # $100 left of $400 -> 2 x $36.25

    def test_nothing_left(self):
        o = size.size(PLAN, cfg(), state(realized_today=-400.0))
        self.assertEqual(o["contracts"], 0)


class Rules(unittest.TestCase):
    def test_trailing_floor(self):
        c = cfg()
        self.assertEqual(rules.floor(c, state()), 48000)
        self.assertEqual(rules.floor(c, state(eod_high=51000)), 49000)
        self.assertEqual(rules.floor(c, state(eod_high=53000)), 50000)     # stops at the starting balance
        c["account"]["trail_stops_at_start"] = False
        self.assertEqual(rules.floor(c, state(eod_high=53000)), 51000)

    def test_eod_and_intraday_trailing(self):
        c = cfg()
        st = rules.record_trade(state(), 500.0, c)
        self.assertEqual((st["eod_high"], st["trades_today"]), (50000.0, 1))
        self.assertEqual(rules.end_of_day(st)["eod_high"], 50500.0)
        c["account"]["trailing"] = "intraday"
        self.assertEqual(rules.record_trade(state(), 500.0, c)["eod_high"], 50500.0)

    def order(self, **kw):
        o = size.size(PLAN, cfg(), state())
        o.update(kw)
        return o

    def test_pass(self):
        r = rules.check(self.order(), cfg(), state(), DT(2026, 10, 19, 9, 56))
        self.assertEqual(r["verdict"], "PASS", r["reasons"])

    def test_blocks(self):
        now = DT(2026, 10, 19, 9, 56)
        c = cfg()
        cases = [
            (self.order(contracts=60), state(), now, "contracts"),
            (self.order(loss_at_stop_usd=250.0), state(), now, "max loss"),
            (self.order(), state(trades_today=3), now, "trades"),
            (self.order(), state(), DT(2026, 10, 19, 15, 30), "time"),
            (self.order(), state(balance=48150.0), now, "trailing"),
            (self.order(reward_risk=0.5), state(), now, "reward/risk"),
            (self.order(date="2026-10-16"), state(), now, "stale"),
            (self.order(stop=None), state(), now, "stop"),
        ]
        for o, st, at, word in cases:
            r = rules.check(o, c, st, at)
            self.assertEqual(r["verdict"], "BLOCK", word)
            self.assertTrue(any(x.startswith(word) for x in r["reasons"]), (word, r["reasons"]))

    def test_firm_daily_limit(self):
        c = cfg()
        c["personal"]["max_daily_loss_usd"] = 5000
        r = rules.check(self.order(), c, state(realized_today=-750.0), DT(2026, 10, 19, 9, 56))
        self.assertTrue(any(x.startswith("firm daily") for x in r["reasons"]), r["reasons"])

    def test_news_blackout(self):
        c = cfg()
        c["news_events"] = [{"at": "2026-10-19 10:00", "label": "EXAMPLE report"}]
        r = rules.check(self.order(), c, state(), DT(2026, 10, 19, 9, 56))
        self.assertTrue(any(x.startswith("news") for x in r["reasons"]))
        r = rules.check(self.order(), c, state(), DT(2026, 10, 19, 10, 6))
        self.assertEqual(r["verdict"], "PASS")

    def test_live_stage_warns(self):
        c = cfg()
        c["account"]["stage"] = "live"
        r = rules.check(self.order(), c, state(), DT(2026, 10, 19, 9, 56))
        self.assertTrue(any("Live Funded" in w for w in r["warnings"]))


class Broker(unittest.TestCase):
    def test_payload_shape(self):
        o = size.size(PLAN, cfg(), state())
        b = projectx.order_payload(o, "123", "CON.F.US.MES.Z26")
        self.assertEqual((b["accountId"], b["type"], b["side"], b["size"]), (123, 2, 0, 5))
        self.assertEqual(b["stopLossBracket"], {"ticks": 29, "type": 4})
        self.assertEqual(b["takeProfitBracket"], {"ticks": 29, "type": 1})
        s = projectx.order_payload(o, 1, "X", signed_ticks=True)
        self.assertEqual(s["stopLossBracket"]["ticks"], -29)
        short = dict(o, side="short")
        self.assertEqual(projectx.order_payload(short, 1, "X")["side"], 1)

    def test_ask_yes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(projectx.ask_yes("t", reader=lambda _: " YES "))
            self.assertFalse(projectx.ask_yes("t", reader=lambda _: "y"))


def run(tool_path, *args, cwd):
    return subprocess.run([sys.executable, os.path.join(ROOT, tool_path)] + list(args), cwd=cwd,
                          capture_output=True, text=True, env=dict(os.environ, PROJECTX_USERNAME="", PROJECTX_API_KEY=""))


class EndToEnd(unittest.TestCase):
    def test_pipeline(self):
        tmp = tempfile.mkdtemp()
        try:
            now = ["--now", "2026-10-19 09:56"]
            r = run("prop-entry/entry.py", "check", "ES", "--offline", ES, "--write", *now, cwd=tmp)
            self.assertIn("TRIGGERED", r.stdout, r.stderr)
            self.assertEqual(run("prop-exit/exit.py", "plan", "--write", cwd=tmp).returncode, 0)
            r = run("prop-timemachine/timemachine.py", "run", "--sims", "500", "--seed", "19", "--offline", ES, "--write", cwd=tmp)
            self.assertIn("fired", r.stdout, r.stderr)
            r = run("prop-budget/size.py", "--write", *now, cwd=tmp)
            self.assertIn("BUY 5 MES", r.stdout, r.stderr)
            r = run("prop-risk/check.py", *now, "check", cwd=tmp)
            self.assertIn("PASS", r.stdout, r.stderr)
            r = run("prop-broker/projectx.py", *now, "place", "--index", "1", "--account-id", "1", "--contract-id", "X", cwd=tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("no yes", r.stderr)
            r = run("prop-broker/ticket.py", *now, "confirm", "--index", "1", "--reply", "ok sure", cwd=tmp)
            self.assertIn("NOT approved", r.stdout)
            run("prop-broker/ticket.py", *now, "confirm", "--index", "1", "--reply", "yes", cwd=tmp)
            r = run("prop-broker/projectx.py", "--now", "2026-10-19 09:58", "place", "--index", "1",
                    "--account-id", "1", "--contract-id", "CON.F.US.MES.Z26", cwd=tmp)
            self.assertIn("DRY RUN", r.stdout, r.stderr)
            self.assertIn('"size": 5', r.stdout)
            r = run("prop-broker/projectx.py", "--now", "2026-10-19 10:30", "place", "--index", "1",
                    "--account-id", "1", "--contract-id", "X", cwd=tmp)
            self.assertIn("no yes", r.stderr)                                  # the yes expired
            r = run("prop-broker/projectx.py", "--now", "2026-10-19 09:58", "place", "--index", "1",
                    "--account-id", "1", "--contract-id", "X", "--send", cwd=tmp)
            self.assertIn("PROJECTX_USERNAME", r.stderr)                       # no credentials, nothing sent
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
