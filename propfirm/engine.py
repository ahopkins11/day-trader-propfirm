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


def fday_at(day, hhmm, what="time"):
    """A clock time on futures trading day `day` (6 PM the evening before to 5 PM):
    times from 18:00 belong to the evening before."""
    t = clock.parse_hhmm(hhmm, what)
    d = day - datetime.timedelta(days=1) if t.hour >= 18 else day
    return datetime.datetime.combine(d, t)


def entry_window(day, sess, cfg, params=None, fday=False):
    """(first entry, last entry, flat time). With fday the window may run overnight
    (e.g. 20:00-01:00) and is capped at the 5 PM daily close instead of 4 PM."""
    o, c = sess
    params = params or {}
    b_txt = params.get("entry_from") or cfg["no_entries_before"]
    a_txt = params.get("entry_to") or cfg["no_entries_after"]
    f_txt = params.get("flat_by") or cfg["flat_by"]
    before = fday_at(day, b_txt, "no_entries_before")
    after = fday_at(day, a_txt, "no_entries_after")
    flat = fday_at(day, f_txt, "flat_by")
    limit = datetime.datetime.combine(day, datetime.time(17, 0)) if fday else c
    if after >= limit:
        after = limit - datetime.timedelta(minutes=30)
    if flat > limit:
        flat = limit - datetime.timedelta(minutes=5)
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
        "breakeven_close": bool(sig.get("breakeven_close")),
        "bar_start": b["t"].strftime("%Y-%m-%d %H:%M") if b else None,
        "bar_close": b["end"].strftime("%Y-%m-%d %H:%M") if b else None,
        "bar_index": b.get("i"),
        "why": sig.get("why", ""),
    }


def futures_day(now, spec=None):
    """The trading day `now` belongs to: from 6 PM it is already the next one."""
    d = now.date() + datetime.timedelta(days=1) if now.time() >= datetime.time(18, 0) else now.date()
    for _ in range(7):
        if clock.trading_day(d)[0]:
            return d
        d += datetime.timedelta(days=1)
    return d


def evaluate_day(strategy, params, bars, now, spec, cfg, not_before=None, day=None):
    """The strategy's verdict at `now` (naive ET) for now's session.
    not_before: ignore entries on bars closing at or before this time (the
    previous trade's exit, for strategies that trade more than once a day).
    day: the trading day to evaluate (default: the one `now` belongs to)."""
    fday = bool(getattr(strategy, "FUTURES_DAY", False))
    day = day or (futures_day(now) if fday else now.date())
    step = bar_minutes(strategy, cfg)
    res = {"symbol": spec["symbol"], "strategy": strategy.NAME, "date": day.isoformat(),
           "now": now.strftime("%Y-%m-%d %H:%M"), "status": "", "reason": "", "levels": {}, "plan": None}
    sess = clock.session(day, spec)
    if not sess:
        ok, why = clock.trading_day(day)
        res.update(status="closed", reason="no regular session today (%s)" % why)
        return res
    o, c = sess
    before, after, flat = entry_window(day, sess, cfg, params, fday=fday)
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
    ctx = {"open": o, "close": c, "now": now, "bar_minutes": step, "spec": spec, "day": day,
           "can_enter": can_enter, "all_bars": closed, "not_before": not_before,
           "entry_from": before, "entry_to": after, "flat_by": flat}
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
    on_close = plan.get("breakeven_close")
    moved = False
    last = None
    best = plan["entry"]          # the furthest price in the trade's favor so far (max favorable excursion)
    best_at = None

    def out(how, price, at):
        o = _out(how, price, at, plan, risk)
        o["mfe_r"] = round(abs(best - plan["entry"]) / risk, 2) if risk else 0.0
        o["mfe_at"] = best_at.strftime("%H:%M") if best_at else None
        return o

    for b in bars_after:
        if b["t"] >= flat_dt:
            return out("flat", b["o"], b["t"])
        hit_stop = b["l"] <= stop if long_ else b["h"] >= stop
        hit_tgt = b["h"] >= plan["target"] if long_ else b["l"] <= plan["target"]
        end = b.get("end", b["t"])
        fav = min(b["h"], plan["target"]) if long_ else max(b["l"], plan["target"])
        if (fav > best) if long_ else (fav < best):
            best, best_at = fav, b["t"]
        if hit_stop:      # reported at the close of the candle that hit it
            return out("breakeven" if moved else "stop", stop, end)
        if hit_tgt:
            return out("target", plan["target"], end)
        if be is not None and not moved:
            px_up, px_dn = (b["c"], b["c"]) if on_close else (b["h"], b["l"])
            if px_up >= be if long_ else px_dn <= be:
                stop, moved = plan["entry"], True
        last = b
    if last is None:
        return out("flat", plan["entry"], None)
    return out("flat", last["c"], last["end"])


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
    on_close = plan.get("breakeven_close")
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
            if be is not None and not moved:
                c = price * rc
                up, dn = (c, c) if on_close else (h, l)
                if (up >= be) if long_ else (dn <= be):
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
    fday = bool(getattr(strategy, "FUTURES_DAY", False))
    rows = []
    for day, _ in data.past_sessions(bars, before_day, spec, n=n, bar_minutes=step):
        sess = clock.session(day, spec)
        _, after, flat = entry_window(day, sess, cfg, params, fday=fday)
        if fday:      # every 5-minute bar from the window to the flat time, overnight included
            day_session = [dict(b, end=b["t"] + FIVE) for b in bars
                           if fday_at(day, "18:00") <= b["t"] <= flat]
            when = max(after, flat)
        else:
            day_session = data.session_bars(bars, day, spec, bar_minutes=step)
            when = sess[1]
        results, not_before = [], None
        while not day_done(results, rule):
            res = evaluate_day(strategy, params, bars, when, spec, cfg, not_before=not_before, day=day)
            if res["status"] != "triggered":
                break
            plan = res["plan"]
            trig_end = datetime.datetime.strptime(plan["bar_close"], "%Y-%m-%d %H:%M")
            w = walk(plan, [b for b in day_session if b["t"] >= trig_end], flat)
            row = {"date": day.isoformat(), "side": plan["side"], "entry": plan["entry"],
                   "stop": plan["stop"], "target": plan["target"], "entry_at": plan["bar_close"][11:]}
            row.update(outcome=w["outcome"], exit=w["exit"], exit_at=w["at"], r=w["r"],
                       mfe_r=w["mfe_r"], mfe_at=w["mfe_at"])
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


def excursion(trades):
    """How far trades went in their favor before they ended, by outcome."""
    def summ(rows):
        m = sorted(r["mfe_r"] for r in rows)
        n = len(m)
        if not n:
            return None
        pct = lambda x: round(100.0 * sum(1 for v in m if v >= x) / n)  # noqa: E731
        return {"n": n, "avg": round(sum(m) / n, 2), "median": m[n // 2] if n % 2 else round((m[n // 2 - 1] + m[n // 2]) / 2, 2),
                "ge_0_5": pct(0.5), "ge_1": pct(1.0), "ge_1_5": pct(1.5), "ge_2": pct(2.0), "ge_3": pct(3.0)}
    out = {"all": summ(trades)}
    for k in ("target", "stop", "breakeven", "flat"):
        s = summ([r for r in trades if r["outcome"] == k])
        if s:
            out[k] = s
    return out
