"""Runs a strategy on a day's bars, turns its signal into a tick-exact plan, and
walks or replays what happens after the entry. Strategy-agnostic: anything in
strategies/ that follows the template works here.

Optional things a strategy file can declare (ORB declares none of them):
  BAR_MINUTES = 5          force the candle size, whatever the config says
  DAILY_STOP = {...}       allow several trades a day, stopping after
                           {"losses": 1, "breakevens": 2, "wins": 2}
  params "entry_from" / "entry_to"   its own entry window (HH:MM ET)
  signal "breakeven"       a price that, once touched, moves the stop to the entry
"""
import datetime
import random

from . import clock, contracts, data

FIVE = datetime.timedelta(minutes=5)


class EngineError(Exception):
    pass


def entry_window(day, sess, cfg, params=None):
    o, c = sess
    params = params or {}
    b_txt = params.get("entry_from") or cfg["no_entries_before"]
    a_txt = params.get("entry_to") or cfg["no_entries_after"]
    before = datetime.datetime.combine(day, clock.parse_hhmm(b_txt, "no_entries_before"))
    after = datetime.datetime.combine(day, clock.parse_hhmm(a_txt, "no_entries_after"))
    flat = datetime.datetime.combine(day, clock.parse_hhmm(cfg["flat_by"], "flat_by"))
    if after >= c:
        after = c - datetime.timedelta(minutes=30)
    if flat > c:
        flat = c - datetime.timedelta(minutes=5)
    return before, after, flat


def bar_minutes(strategy, cfg):
    return int(getattr(strategy, "BAR_MINUTES", None) or cfg.get("bar_minutes") or 5)


def finalize(sig, spec, cfg):
    """Round to the tick and price the trade for one contract."""
    side = sig["side"]
    entry = contracts.round_tick(sig["entry"], spec)
    stop = contracts.stop_tick(sig["stop"], entry, spec)
    target = contracts.round_tick(sig["target"], spec)
    if side == "long" and not (stop < entry < target):
        raise EngineError("long signal needs stop < entry < target, got %s / %s / %s" % (stop, entry, target))
    if side == "short" and not (target < entry < stop):
        raise EngineError("short signal needs target < entry < stop, got %s / %s / %s" % (target, entry, stop))
    rt = contracts.ticks_between(entry, stop, spec)
    wt = contracts.ticks_between(entry, target, spec)
    fees = float(cfg.get("fees_per_contract_round_trip") or 0)
    b = sig.get("bar") or {}
    be = sig.get("breakeven")
    return {
        "side": side, "entry": entry, "stop": stop, "target": target,
        "risk_ticks": rt, "reward_ticks": wt,
        "risk_points": rt * float(spec["tick"]), "reward_points": wt * float(spec["tick"]),
        "risk_usd_per_contract": round(contracts.dollars(rt, spec) + fees, 2),
        "reward_usd_per_contract": round(contracts.dollars(wt, spec) - fees, 2),
        "reward_risk": round(wt / float(rt), 2) if rt else None,
        "breakeven": contracts.round_tick(be, spec) if be is not None else None,
        "bar_start": b["t"].strftime("%Y-%m-%d %H:%M") if b else None,
        "bar_close": b["end"].strftime("%Y-%m-%d %H:%M") if b else None,
        "bar_index": b.get("i"),
        "why": sig.get("why", ""),
    }


def evaluate_day(strategy, params, bars, now, spec, cfg, not_before=None):
    """The strategy's verdict at `now` (naive ET) for now's session.
    not_before: ignore entries on bars closing at or before this time (the
    previous trade's exit, for strategies that trade more than once a day)."""
    day = now.date()
    step = bar_minutes(strategy, cfg)
    res = {"symbol": spec["symbol"], "strategy": strategy.NAME, "date": day.isoformat(),
           "now": now.strftime("%Y-%m-%d %H:%M"), "status": "", "reason": "", "levels": {}, "plan": None}
    sess = clock.session(day, spec)
    if not sess:
        ok, why = clock.trading_day(day)
        res.update(status="closed", reason="no regular session today (%s)" % why)
        return res
    o, c = sess
    before, after, flat = entry_window(day, sess, cfg, params)
    res.update(session="%s-%s" % (clock.hm(o), clock.hm(c)), no_entries_before=clock.hm(before),
               no_entries_after=clock.hm(after), flat_by=clock.hm(flat))
    if now < o and not getattr(strategy, "PRE_OPEN_OK", False):
        res.update(status="pre-open", reason="the regular session opens at %s ET" % clock.ampm(o))
        return res
    day_bars = data.session_bars(bars, day, spec, now=now, bar_minutes=step)
    res["bars_closed"] = len(day_bars)
    if day_bars:
        res["last"] = {"bar_start": clock.hm(day_bars[-1]["t"]), "close": day_bars[-1]["c"]}

    def can_enter(b):
        if not_before is not None and b["end"] <= not_before:
            return False
        return before <= b["end"] <= after

    closed = [b for b in bars if b["t"] + FIVE <= now]   # every closed 5-minute bar, all hours
    ctx = {"open": o, "close": c, "now": now, "bar_minutes": step, "spec": spec,
           "can_enter": can_enter, "all_bars": closed, "not_before": not_before}
    out = strategy.evaluate(day_bars, params, ctx) or {}
    res["status"] = out.get("status") or "waiting"
    res["reason"] = out.get("reason") or ""
    res["levels"] = out.get("levels") or {}
    sig = out.get("signal")
    if sig:
        res["status"] = "triggered"
        res["plan"] = finalize(sig, spec, cfg)
        res["plan"]["bar_minutes"] = step
    elif res["status"] == "waiting" and now >= after:
        res["status"] = "expired"
        res["reason"] = "no signal by %s, the last time for a new entry (%s)" % (clock.ampm(after), res["reason"])
    elif not day_bars and res["status"] != "forming" and now >= o and not getattr(strategy, "PRE_OPEN_OK", False):
        res.update(status="no-data", reason="no bars yet for %s (the data may be delayed)" % day.isoformat())
    return res


# ---------------------------------------------------------------- after the entry

def walk(plan, bars_after, flat_dt):
    """What really happened: the first of stop, target or the flat time.
    A bar that touches both counts as the stop (the honest worst case). With a
    breakeven price, the stop moves to the entry from the bar after it is touched."""
    long_ = plan["side"] == "long"
    risk = abs(plan["entry"] - plan["stop"])
    stop = plan["stop"]
    be = plan.get("breakeven")
    moved = False
    last = None
    for b in bars_after:
        if b["t"] >= flat_dt:
            return _out("flat", b["o"], b["t"], plan, risk)
        hit_stop = b["l"] <= stop if long_ else b["h"] >= stop
        hit_tgt = b["h"] >= plan["target"] if long_ else b["l"] <= plan["target"]
        end = b.get("end", b["t"])
        if hit_stop:      # reported at the close of the candle that hit it
            return _out("breakeven" if moved else "stop", stop, end, plan, risk)
        if hit_tgt:
            return _out("target", plan["target"], end, plan, risk)
        if be is not None and not moved and (b["h"] >= be if long_ else b["l"] <= be):
            stop, moved = plan["entry"], True
        last = b
    if last is None:
        return _out("flat", plan["entry"], None, plan, risk)
    return _out("flat", last["c"], last["end"], plan, risk)


def _out(how, price, at, plan, risk):
    sign = 1 if plan["side"] == "long" else -1
    r = (sign * (price - plan["entry"]) / risk) if risk else 0.0
    return {"outcome": how, "exit": price, "at": at.strftime("%H:%M") if at else None, "r": round(r, 3),
            "_at": at}


def slot_pools(sessions, bar_minutes=5):
    """{slot: [(o, h, l, c) as ratios to the previous bar's close]} from past sessions."""
    pools = {}
    for _, bars in sessions:
        by = {b["i"]: b for b in bars}
        for i, b in by.items():
            p = by.get(i - 1)
            if not p or not p["c"]:
                continue
            pc = p["c"]
            pools.setdefault(i, []).append((b["o"] / pc, b["h"] / pc, b["l"] / pc, b["c"] / pc))
    return pools


def simulate(plan, start_slot, end_slot, pools, sims=10000, seed=None):
    """Monte Carlo: the rest of the session `sims` times, each bar drawn from the
    same time of day on a past session, scaled to the price. Returns counts."""
    rnd = random.Random(seed)
    long_ = plan["side"] == "long"
    tgt, entry = plan["target"], plan["entry"]
    be = plan.get("breakeven")
    risk = abs(entry - plan["stop"])
    slots = [s for s in range(start_slot, end_slot) if pools.get(s)]
    if not slots:
        raise EngineError("no past bars for the rest of this session: load more history")
    counts = {"target": 0, "stop": 0, "breakeven": 0, "flat": 0}
    flat_r = []
    for _ in range(sims):
        price = entry
        stop, moved = plan["stop"], False
        done = None
        for s in slots:
            ro, rh, rl, rc = rnd.choice(pools[s])
            h, l = price * rh, price * rl
            if (l <= stop) if long_ else (h >= stop):
                done = "breakeven" if moved else "stop"
                break
            if (h >= tgt) if long_ else (l <= tgt):
                done = "target"
                break
            if be is not None and not moved and ((h >= be) if long_ else (l <= be)):
                stop, moved = entry, True
            price = price * rc
        if done:
            counts[done] += 1
        else:
            counts["flat"] += 1
            flat_r.append(((price - entry) if long_ else (entry - price)) / risk if risk else 0.0)
    rr = plan["reward_ticks"] / float(plan["risk_ticks"]) if plan["risk_ticks"] else 0.0
    exp_r = (counts["target"] * rr - counts["stop"] + sum(flat_r)) / float(sims)
    out = {"sims": sims, "seed": seed, "bars_simulated": len(slots),
           "target_pct": round(100.0 * counts["target"] / sims, 1),
           "stop_pct": round(100.0 * counts["stop"] / sims, 1),
           "flat_pct": round(100.0 * counts["flat"] / sims, 1),
           "expected_r": round(exp_r, 3)}
    if be is not None:
        out["breakeven_pct"] = round(100.0 * counts["breakeven"] / sims, 1)
    return out


def day_done(results, rule):
    """True once the day's results hit the daily stop rule."""
    if not rule:
        return len(results) >= 1
    return (results.count("loss") >= rule.get("losses", 99) or results.count("be") >= rule.get("breakevens", 99)
            or results.count("win") >= rule.get("wins", 99))


def result_kind(outcome, r):
    if outcome == "target" or (outcome == "flat" and r > 0.05):
        return "win"
    if outcome == "breakeven" or (outcome == "flat" and abs(r) <= 0.05):
        return "be"
    return "loss"


def history(strategy, params, bars, spec, cfg, before_day, n=59):
    """Run the same strategy on each past session and walk every signal. A
    strategy with DAILY_STOP may trade again after each exit until the rule stops it."""
    step = bar_minutes(strategy, cfg)
    rule = getattr(strategy, "DAILY_STOP", None)
    rows = []
    for day, _ in data.past_sessions(bars, before_day, spec, n=n, bar_minutes=step):
        sess = clock.session(day, spec)
        _, _, flat = entry_window(day, sess, cfg, params)
        day_session = data.session_bars(bars, day, spec, bar_minutes=step)
        results, not_before = [], None
        while not day_done(results, rule):
            res = evaluate_day(strategy, params, bars, sess[1], spec, cfg, not_before=not_before)
            if res["status"] != "triggered":
                break
            plan = res["plan"]
            trig_end = datetime.datetime.strptime(plan["bar_close"], "%Y-%m-%d %H:%M")
            w = walk(plan, [b for b in day_session if b["t"] >= trig_end], flat)
            row = {"date": day.isoformat(), "side": plan["side"], "entry": plan["entry"],
                   "stop": plan["stop"], "target": plan["target"], "entry_at": plan["bar_close"][11:]}
            row.update(outcome=w["outcome"], exit=w["exit"], exit_at=w["at"], r=w["r"])
            rows.append(row)
            results.append(result_kind(w["outcome"], w["r"]))
            if w["_at"] is None or w["outcome"] == "flat":
                break
            not_before = w["_at"]
    sessions = len(data.past_sessions(bars, before_day, spec, n=n, bar_minutes=step))
    tally = {k: sum(1 for r in rows if r["outcome"] == k) for k in ("target", "stop", "breakeven", "flat")}
    total_r = round(sum(r["r"] for r in rows), 2)
    out = {"sessions": sessions, "fired": len(rows), "total_r": total_r,
           "avg_r": round(total_r / len(rows), 3) if rows else None, "trades": rows}
    out.update(tally)
    return out
