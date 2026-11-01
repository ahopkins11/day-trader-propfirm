"""Prop firm account rules (Topstep-style) and the account state they need.

The firm's limits come from the "account" block of trader/config.json and your
own tighter limits from "personal". The numbers shipped in config.example.json
are EXAMPLES: copy the real ones for your plan from your Topstep dashboard,
because firms change them.

trader/account.json keeps what the rules need between trades:
  balance          your account balance now
  eod_high         the highest end-of-day balance so far (drives the trailing limit)
  date             the trading day realized_today and trades_today belong to
  realized_today   today's realized P&L in dollars (negative = loss)
  trades_today     entries taken today
"""
import datetime
import os

from . import clock, config, contracts

STATE = "account.json"


def order_key(o):
    """One string that changes if anything about the order changes."""
    return "%s|%s|%s|%s|%s|%s|%s" % (o["date"], o["symbol"], o["side"], o["contracts"], o["entry"], o["stop"], o["target"])


def state_path(base=None):
    return os.path.join(config.trader_dir(base), STATE)


def load_state(cfg, today, base=None):
    st = config.read_json(state_path(base))
    acct = cfg["account"]
    if not st:
        st = {"balance": float(acct["starting_balance"]), "eod_high": float(acct["starting_balance"]),
              "date": today.isoformat(), "realized_today": 0.0, "trades_today": 0, "log": []}
    if st.get("date") != today.isoformat():
        st.update(date=today.isoformat(), realized_today=0.0, trades_today=0, results_today=[])
    return st


def save_state(st, base=None):
    config.write_json(state_path(base), st)


def floor(cfg, st):
    """The balance that ends the account: the max loss limit trailing the high.
    With trail_stops_at_start it stops rising once it reaches the starting balance."""
    acct = cfg["account"]
    hi = float(st["eod_high"])
    f = hi - float(acct["max_loss_limit"])
    if acct.get("trail_stops_at_start", True):
        f = min(f, float(acct["starting_balance"]))
    return round(f, 2)


def record_trade(st, pnl, cfg, result=None):
    st["balance"] = round(float(st["balance"]) + pnl, 2)
    st["realized_today"] = round(float(st["realized_today"]) + pnl, 2)
    st["trades_today"] = int(st.get("trades_today") or 0) + 1
    if result is None:
        result = "win" if pnl > 0 else "loss" if pnl < 0 else "be"
    st.setdefault("results_today", []).append(result)
    if cfg["account"].get("trailing") == "intraday":
        st["eod_high"] = max(float(st["eod_high"]), st["balance"])
    st.setdefault("log", []).append({"date": st["date"], "pnl": pnl, "balance": st["balance"]})
    return st


def end_of_day(st, balance=None):
    if balance is not None:
        st["balance"] = float(balance)
    st["eod_high"] = max(float(st["eod_high"]), float(st["balance"]))
    return st


def full_equivalent(contracts_n, spec, cfg):
    if spec.get("is_micro"):
        return contracts_n / float(cfg["account"].get("micros_per_contract") or 10)
    return float(contracts_n)


def room(cfg, st):
    """Dollars you can still lose today before each limit, after the buffer."""
    acct, me = cfg["account"], cfg["personal"]
    buf = float(me.get("buffer_usd") or 0)
    lost = max(0.0, -float(st["realized_today"]))
    out = {"trailing": round(float(st["balance"]) - floor(cfg, st) - buf, 2),
           "personal_daily": round(float(me["max_daily_loss_usd"]) - lost, 2)}
    if acct.get("daily_loss_limit"):
        out["firm_daily"] = round(float(acct["daily_loss_limit"]) - lost - buf, 2)
    return out


def check(order, cfg, st, now):
    """-> {"verdict": "PASS"|"BLOCK", "reasons": [...], "warnings": [...], ...}"""
    acct, me = cfg["account"], cfg["personal"]
    reasons, warns = [], []
    spec = contracts.spec(order["symbol"])
    n = int(order.get("contracts") or 0)
    if n < 1:
        reasons.append("size: 0 contracts (the stop is too far for your max loss, or no budget left)")
    if order.get("stop") is None:
        reasons.append("stop: every order needs a stop")
    loss = float(order.get("loss_at_stop_usd") or 0)

    fe = full_equivalent(n, spec, cfg)
    if fe > float(acct["max_contracts"]):
        reasons.append("contracts: %d %s = %.1f full-size, over the plan's max of %s"
                       % (n, spec["symbol"], fe, acct["max_contracts"]))
    if fe > float(me.get("max_contracts") or acct["max_contracts"]):
        reasons.append("contracts: %.1f full-size, over your own max of %s" % (fe, me["max_contracts"]))

    if loss > float(me["max_loss_per_trade_usd"]):
        reasons.append("max loss: $%.2f at the stop, over your $%.2f per trade" % (loss, me["max_loss_per_trade_usd"]))
    rm = room(cfg, st)
    if loss > rm["personal_daily"]:
        reasons.append("daily: $%.2f at the stop, only $%.2f left of your daily loss" % (loss, max(rm["personal_daily"], 0)))
    if "firm_daily" in rm and loss > rm["firm_daily"]:
        reasons.append("firm daily loss limit: $%.2f at the stop, only $%.2f left (after your $%s buffer)"
                       % (loss, max(rm["firm_daily"], 0), me.get("buffer_usd", 0)))
    if loss > rm["trailing"]:
        reasons.append("trailing max loss: the account ends at $%.2f; the stop would leave $%.2f above it (buffer $%s)"
                       % (floor(cfg, st), float(st["balance"]) - loss - floor(cfg, st), me.get("buffer_usd", 0)))

    rule = me.get("daily_stop")
    res = st.get("results_today") or []
    if rule and (res.count("loss") >= rule.get("losses", 99) or res.count("be") >= rule.get("breakevens", 99)
                 or res.count("win") >= rule.get("wins", 99)):
        reasons.append("daily stop: today is %s; your rule stops after %s loss(es), %s breakeven(s) or %s win(s)"
                       % (", ".join(res), rule.get("losses", "-"), rule.get("breakevens", "-"), rule.get("wins", "-")))
    if int(st["trades_today"]) >= int(me["max_trades_per_day"]):
        reasons.append("trades: %d taken today, your max is %s" % (st["trades_today"], me["max_trades_per_day"]))
    rr = order.get("reward_risk")
    if rr is not None and rr < float(me["min_reward_risk"]):
        reasons.append("reward/risk %.2f under your minimum %.2f" % (rr, me["min_reward_risk"]))

    day = now.date()
    sess = clock.session(day, spec)
    if not sess:
        reasons.append("time: no regular session today")
    else:
        before = datetime.datetime.combine(day, clock.parse_hhmm(cfg["no_entries_before"]))
        after = datetime.datetime.combine(day, clock.parse_hhmm(cfg["no_entries_after"]))
        if now < before or now > after:
            reasons.append("time: %s ET is outside your entry window %s-%s"
                           % (clock.hm(now), cfg["no_entries_before"], cfg["no_entries_after"]))
    if order.get("date") and order["date"] != day.isoformat():
        reasons.append("stale: this order is from %s" % order["date"])

    mins = int(cfg.get("news_blackout_minutes") or 0)
    for ev in cfg.get("news_events") or []:
        try:
            at = datetime.datetime.strptime(ev["at"], "%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            warns.append("news_events: could not read %r (want {\"at\": \"2026-11-04 14:00\", \"label\": ...})" % ev)
            continue
        if abs((now - at).total_seconds()) <= mins * 60:
            reasons.append("news: %s at %s, inside your %d-minute blackout" % (ev.get("label", "event"), ev["at"][11:], mins))

    if acct.get("stage") == "live":
        warns.append("Live Funded: Topstep does not allow API trading on live accounts. Enter this one by hand.")
    gain = float(st["balance"]) - float(acct["starting_balance"])
    if acct.get("profit_target") and gain >= float(acct["profit_target"]):
        warns.append("profit target reached ($%.2f up): check your plan's other requirements before trading more" % gain)
    if spec["symbol"] in ("CL", "MCL", "GC", "MGC"):
        warns.append("%s: check your plan allows it and its own trading hours" % spec["symbol"])

    return {"verdict": "BLOCK" if reasons else "PASS", "reasons": reasons, "warnings": warns,
            "loss_at_stop_usd": loss, "room": rm, "floor": floor(cfg, st), "balance": st["balance"]}
