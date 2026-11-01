"""
=============================================================================
  STRATEGY: NYAM sweep + iFVG (AJ's Setup #1)          strategies/nyam.py
=============================================================================

  A mechanical version of Primary Setup #1 from the NYAM playbook:

    Bias -> sweep of liquidity (pre-market allowed) into a 15m/1H FVG
         -> 5m displacement candle that CLOSES through the last opposite 5m FVG (iFVG)
         -> entry at that close
         -> stop 2 ticks beyond the sweep's extreme
         -> target the nearest untaken 1H-or-higher draw on liquidity (min 1.5R)
         -> stop to breakeven once price touches the nearest 5m FVG in the trade's direction
    Daily stop: 1 loss, or 2 breakevens, or 2 wins.

  What the code CANNOT do, and the playbook says matters most: judge clean vs
  choppy price action, the quality of a PD array or a DOL, order blocks,
  rejection blocks, OTE, the 10:00 4H-open setups and the continuation model.
  A backtest of this file tests the rule skeleton, not your discretion.

  Definitions (all New York time, futures daily candle = 6:00 PM to 5:00 PM)
    PDH / PDL        previous day's daily candle high / low
    previous NYAM    previous day 9:30-11:00 high / low
    Asia             8:00 PM-midnight high / low (the evening before)
    London           2:00-5:00 AM high / low
    4H highs/lows    today's completed 4H candles (4H opens 6 PM, 10 PM, 2 AM, 6 AM, 10 AM, 2 PM);
                     as TARGETS also the 4H candles of the past lookback_days
    prev NY lunch    yesterday 12:00-1:00 high / low       (targets only)
    prev NY PM       yesterday 1:30-4:00 high / low        (targets only)
    1H swing         a 1H high (low) above (below) the 1H candles either side
    valid target     a DOL until a 1H candle closes beyond it (target_valid_until)
    FVG              three candles where candle 3's low is above candle 1's high
                     (bullish) or candle 3's high is below candle 1's low (bearish)
    bias "auto"      long if yesterday closed above the day before's midpoint,
                     short if below it. For live trading set
                     "bias": "long" / "short" / "none" each morning in
                     trader/config.json under strategy_params.
=============================================================================
"""
import bisect
import datetime

from propfirm import clock

NAME = "nyam"
DESCRIPTION = "NYAM: liquidity sweep into a 15m/1H FVG, 5m iFVG with displacement, target the nearest HTF DOL"
BAR_MINUTES = 5                                   # execution candles (the data is 5-minute)
DAILY_STOP = {"losses": 1, "breakevens": 2, "wins": 2}
PRE_OPEN_OK = True                                # show the pre-market sweep status before 9:30

PARAMS = {
    "bias": "auto",              # "auto", "long", "short" or "none"
    "entry_from": "09:30",       # entries only between these times
    "entry_to": "11:00",
    "flat_by": None,             # e.g. "12:00" to close any open trade by noon (None = the config's flat_by)
    "sweep_from": "05:00",       # a sweep counts from this time (pre-market allowed)
    "displacement_x": 1.3,       # inversion candle body >= 1.3 x the average of the last bodies
    "body_lookback": 10,
    "stop_buffer_ticks": 2,
    "min_rr": 1.5,               # skip a setup whose nearest DOL is under 1.5R away
    "max_target_r": None,        # e.g. 2.0: never aim further than 2R, even if the DOL is further
    "target_valid_until": "1h_close",  # a DOL stays a target until a 1H candle CLOSES beyond it
                                       # "4h_close": until a 4H close beyond it
                                       # "touch": until price trades through it at all
    "fvg_leg_bars": 12,          # the inverted FVG formed within 12 x 5m bars before the sweep
    "max_bars_after_sweep": 24,  # the iFVG must come within 2 hours of the sweep
    "pd_touch_minutes": 30,      # the move into the sweep touched the PD array within this window
    "pd_timeframes": [15, 60],   # PD array = an FVG on these timeframes (minutes)
    "lookback_days": 3,          # how far back to look for PD arrays and 1H swings
    "breakeven": True,
    "breakeven_mode": "touch",   # "touch": nearest 5m FVG ahead is touched
                                 # "close": a candle CLOSES beyond that FVG
                                 # "second": the SECOND 5m FVG ahead is touched
                                 # "1r": price reaches 1R in profit
}

H = datetime.timedelta(hours=1)
M5 = datetime.timedelta(minutes=5)
ANCHOR = datetime.datetime(2000, 1, 1, 18, 0)    # futures day starts 6 PM ET; 15m/1H/4H all line up


# ---------------------------------------------------------------- building blocks

def at(day, hhmm):
    return datetime.datetime.combine(day, clock.parse_hhmm(hhmm))


def prev_trading_day(d):
    d = d - datetime.timedelta(days=1)
    for _ in range(10):
        if clock.trading_day(d)[0]:
            return d
        d -= datetime.timedelta(days=1)
    return d


def day_window(d):
    """The futures daily candle for trading day d: 6 PM the evening before to 5 PM."""
    return at(d - datetime.timedelta(days=1), "18:00"), at(d, "17:00")


def between(bars, a, b):
    return [x for x in bars if a <= x["t"] < b]


def resample(bars, minutes):
    period = datetime.timedelta(minutes=minutes)
    out, cur, key = [], None, None
    for b in bars:
        k = (b["t"] - ANCHOR) // period
        if k != key:
            if cur:
                out.append(cur)
            start = ANCHOR + k * period
            cur = {"t": start, "end": start + period, "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "n": 1}
            key = k
        else:
            cur["h"] = max(cur["h"], b["h"])
            cur["l"] = min(cur["l"], b["l"])
            cur["c"] = b["c"]
            cur["n"] += 1
    if cur:
        out.append(cur)
    return out


def fvgs(series):
    """[{side, bottom, top, formed}] in the order they formed."""
    out = []
    for i in range(2, len(series)):
        c1, c3 = series[i - 2], series[i]
        if c3["l"] > c1["h"]:
            out.append({"side": "bull", "bottom": c1["h"], "top": c3["l"], "formed": c3["end"], "t": c3["t"]})
        elif c3["h"] < c1["l"]:
            out.append({"side": "bear", "bottom": c3["h"], "top": c1["l"], "formed": c3["end"], "t": c3["t"]})
    return out


def swings(series, kind):
    """1H fractal highs/lows: (price, formed_at)."""
    out = []
    for i in range(1, len(series) - 1):
        a, b, c = series[i - 1], series[i], series[i + 1]
        if kind == "high" and b["h"] > a["h"] and b["h"] > c["h"]:
            out.append((b["h"], c["end"]))
        if kind == "low" and b["l"] < a["l"] and b["l"] < c["l"]:
            out.append((b["l"], c["end"]))
    return out


def hi(bars):
    return max(b["h"] for b in bars) if bars else None


def lo(bars):
    return min(b["l"] for b in bars) if bars else None


def levels(all5, day, now):
    """Liquidity levels and the auto bias for `day`. Each level: (name, price, formed_at)."""
    p = prev_trading_day(day)
    pp = prev_trading_day(p)
    pbars = between(all5, *day_window(p))
    ppbars = between(all5, *day_window(pp))
    if not pbars or not ppbars:
        return None
    highs, lows = [], []
    pw_end = day_window(p)[1]
    highs.append(("PDH", hi(pbars), pw_end))
    lows.append(("PDL", lo(pbars), pw_end))
    ny = between(all5, at(p, "09:30"), at(p, "11:00"))
    if ny:
        highs.append(("prev NYAM high", hi(ny), at(p, "11:00")))
        lows.append(("prev NYAM low", lo(ny), at(p, "11:00")))
    asia = between(all5, at(day - datetime.timedelta(days=1), "20:00"), at(day, "00:00"))
    if asia:
        highs.append(("Asia high", hi(asia), at(day, "00:00")))
        lows.append(("Asia low", lo(asia), at(day, "00:00")))
    ldn = between(all5, at(day, "02:00"), at(day, "05:00"))
    if ldn:
        highs.append(("London high", hi(ldn), at(day, "05:00")))
        lows.append(("London low", lo(ldn), at(day, "05:00")))
    for c4 in resample(between(all5, *day_window(day)), 240):
        if c4["end"] <= now:
            highs.append(("4H high %s" % c4["t"].strftime("%H:%M"), c4["h"], c4["end"]))
            lows.append(("4H low %s" % c4["t"].strftime("%H:%M"), c4["l"], c4["end"]))
    close = pbars[-1]["c"]
    mid = (hi(ppbars) + lo(ppbars)) / 2.0
    bias = "long" if close > mid else "short" if close < mid else "none"
    return {"highs": highs, "lows": lows, "bias": bias, "prev_close": close,
            "prev_prev_high": hi(ppbars), "prev_prev_low": lo(ppbars), "prev_prev_mid": mid}


# ---------------------------------------------------------------- the setup

def evaluate(bars, p, ctx):
    """See strategies/orb.py for what bars, p and ctx hold. This strategy works
    from ctx["all_bars"] (every closed 5-minute bar, overnight included)."""
    if ctx["bar_minutes"] != 5:
        raise ValueError("nyam runs on 5-minute candles")
    now, spec = ctx["now"], ctx["spec"]
    day = ctx["open"].date()
    tick = float(spec["tick"])
    start = at(day - datetime.timedelta(days=p["lookback_days"] + 4), "18:00")
    all5 = [dict(b, end=b["t"] + M5) for b in ctx["all_bars"] if b["t"] >= start]
    lv = levels(all5, day, now)
    if lv is None:
        return {"status": "waiting", "signal": None, "levels": {}, "reason": "not enough history for yesterday's levels"}
    bias = lv["bias"] if p["bias"] == "auto" else p["bias"]
    info = {"bias": bias, "bias_source": p["bias"]}
    if bias not in ("long", "short"):
        return {"status": "waiting", "signal": None, "levels": info,
                "reason": "no bias today (yesterday closed %.2f, exactly the day before's midpoint)"
                          % lv["prev_close"] if p["bias"] == "auto" else "bias set to none"}
    long_ = bias == "long"
    liq = lv["lows"] if long_ else lv["highs"]              # what gets swept
    dols = lv["highs"] if long_ else lv["lows"]             # where it delivers

    recent = between(all5, at(day - datetime.timedelta(days=p["lookback_days"]), "18:00"), now + M5)
    htf = []
    for tf in p["pd_timeframes"]:
        series = [c for c in resample(recent, tf) if c["end"] <= now]
        htf += [dict(f, tf=tf) for f in fvgs(series) if f["side"] == ("bull" if long_ else "bear")]
    hourly = [c for c in resample(recent, 60) if c["end"] <= now]
    today_start = day_window(day)[0]
    side_key, word = ("h", "high") if long_ else ("l", "low")
    dols = dols + [("4H %s %s" % (word, c["t"].strftime("%m-%d %H:%M")), c[side_key], c["end"])
                   for c in resample(recent, 240) if c["end"] <= now and c["t"] < today_start]
    pday = prev_trading_day(day)
    for label, a_, b_ in (("prev NY lunch", "12:00", "13:00"), ("prev NY PM", "13:30", "16:00")):
        seg = between(all5, at(pday, a_), at(pday, b_))
        if seg:
            dols.append(("%s %s" % (label, word), hi(seg) if long_ else lo(seg), at(pday, b_)))
    dols = dols + [("1H swing %s" % (f.strftime("%m-%d %H:%M")), price, f)
                   for price, f in swings(hourly, "high" if long_ else "low")]
    m5 = [b for b in all5 if b["t"] >= at(day - datetime.timedelta(days=1), "18:00") and b["end"] <= now]
    m5_fvgs = fvgs([b for b in recent if b["end"] <= now])     # 5m FVGs over the lookback (for breakeven)
    opp = [f for f in m5_fvgs if f["side"] == ("bear" if long_ else "bull")]

    scan = [b for b in m5 if b["t"] >= at(day, p["sweep_from"]) and b["t"] < at(day, p["entry_to"])]
    taken = set()
    state = "waiting for a sweep of %s" % ("sell-side liquidity" if long_ else "buy-side liquidity")

    times = [x["t"] for x in all5]

    mode = p.get("target_valid_until") or "1h_close"
    if mode not in ("1h_close", "4h_close", "touch"):
        raise ValueError("target_valid_until is 1h_close, 4h_close or touch")
    closes_tf = [c for c in resample(recent, 60 if mode == "1h_close" else 240)] if mode != "touch" else []

    def untouched_since(price, formed, upto, above):
        """Is this DOL still a target? (not inversed: no 1H/4H close beyond it, or untouched)"""
        if mode == "touch":
            for x in all5[bisect.bisect_left(times, formed):bisect.bisect_left(times, upto)]:
                if (x["h"] >= price) if above else (x["l"] <= price):
                    return False
            return True
        for c in closes_tf:
            if c["t"] >= formed and c["end"] <= upto and ((c["c"] > price) if above else (c["c"] < price)):
                return False
        return True

    for f in htf:                                   # when (if ever) a close broke through it
        f["broken_at"] = None
        for x in all5[bisect.bisect_left(times, f["formed"]):]:
            if formed_close_breaks(x, f, long_):
                f["broken_at"] = x["t"]
                break

    def pd_array(b):
        """An HTF FVG that the sweep candle, or any candle in the move into it
        (pd_touch_minutes), traded into while the FVG was still intact."""
        lead = all5[bisect.bisect_left(times, b["t"] - datetime.timedelta(minutes=p["pd_touch_minutes"])):
                    bisect.bisect_right(times, b["t"])]
        for f in reversed(htf):
            for x in reversed(lead):
                if f["formed"] > x["t"] or (f["broken_at"] is not None and f["broken_at"] < x["t"]):
                    continue
                if x["l"] <= f["top"] and x["h"] >= f["bottom"]:
                    return f
        return None

    for j, b in enumerate(scan):
        for name, price, formed in liq:
            if name in taken or formed > b["t"]:
                continue
            if (b["l"] < price) if long_ else (b["h"] > price):
                taken.add(name)
                f = pd_array(b)
                if not f:
                    state = "%s taken at %s but not into a 15m/1H FVG" % (name, clock.hm(b["t"]))
                    continue
                sig, why = look_for_ifvg(j, b, name, f, scan, m5, opp, dols, p, ctx, tick, long_,
                                         untouched_since)
                if sig:
                    sig["levels"] = dict(info, swept=name, pd_array="%dm FVG %.2f-%.2f" % (f["tf"], f["bottom"], f["top"]))
                    return {"status": "triggered", "signal": sig, "levels": sig.pop("levels"),
                            "reason": "%s swept at %s into a %dm FVG, iFVG at %s" % (
                                name, clock.hm(b["t"]), f["tf"], clock.hm(sig["bar"]["t"]))}
                state = why
    return {"status": "waiting", "signal": None, "levels": info, "reason": "bias %s; %s" % (bias, state)}


def formed_close_breaks(x, f, long_):
    """A close through the far side of an HTF FVG invalidates it as support/resistance."""
    return x["c"] < f["bottom"] if long_ else x["c"] > f["top"]


def look_for_ifvg(j, sweep, name, f_htf, scan, m5, opp, dols, p, ctx, tick, long_, untouched_since):
    ext = sweep["l"] if long_ else sweep["h"]
    leg_start = sweep["t"] - M5 * p["fvg_leg_bars"]
    note = ""
    for k in range(j + 1, min(len(scan), j + 1 + p["max_bars_after_sweep"])):
        bk = scan[k]
        cands = [f for f in opp if leg_start <= f["t"] and f["formed"] <= bk["t"]]
        if not cands:
            ext = min(ext, bk["l"]) if long_ else max(ext, bk["h"])
            continue
        f = cands[-1]
        through = bk["c"] > f["top"] if long_ else bk["c"] < f["bottom"]
        if not through:
            ext = min(ext, bk["l"]) if long_ else max(ext, bk["h"])
            continue
        # a close through the FVG: it counts only with displacement, inside the entry
        # window; a weak close (or one before 9:30) doesn't end the setup, keep watching
        prior = [x for x in m5 if x["t"] < bk["t"]][-p["body_lookback"]:]
        avg = sum(abs(x["c"] - x["o"]) for x in prior) / float(len(prior)) if prior else 0.0
        body = bk["c"] - bk["o"] if long_ else bk["o"] - bk["c"]
        ext = min(ext, bk["l"]) if long_ else max(ext, bk["h"])
        if body <= 0 or body < p["displacement_x"] * avg:
            note = "; closed through without displacement at %s" % clock.hm(bk["t"])
            continue
        if not ctx["can_enter"](bk) or bk["t"] < at(bk["t"].date(), p["entry_from"]):
            note = "; displacement through it at %s, outside the entry window" % clock.hm(bk["t"])
            continue
        entry = bk["c"]
        stop = ext - p["stop_buffer_ticks"] * tick if long_ else ext + p["stop_buffer_ticks"] * tick
        targets = [(price, dn) for dn, price, formed in dols
                   if formed <= bk["t"] and ((price > entry) if long_ else (price < entry))
                   and untouched_since(price, formed, bk["end"], long_)]
        if not targets:
            return None, "iFVG at %s but no untaken draw on liquidity %s" % (clock.hm(bk["t"]), "above" if long_ else "below")
        target, tname = (min(targets) if long_ else max(targets))
        rr = abs(target - entry) / abs(entry - stop)
        if rr < p["min_rr"]:
            return None, "iFVG at %s but %s is only %.2fR away (min %.1f)" % (clock.hm(bk["t"]), tname, rr, p["min_rr"])
        if p.get("max_target_r") and rr > p["max_target_r"]:
            capped = p["max_target_r"] * abs(entry - stop)
            target = entry + capped if long_ else entry - capped
            tname = "%s (capped at %.1fR)" % (tname, p["max_target_r"])
        be, be_close = None, False
        mode = p.get("breakeven_mode") or "touch"
        if mode not in ("touch", "close", "second", "1r"):
            raise ValueError("breakeven_mode is touch, close, second or 1r")
        if p.get("breakeven") and mode == "1r":
            be = entry + abs(entry - stop) if long_ else entry - abs(entry - stop)
        elif p.get("breakeven"):
            ahead = [g for g in opp if g["formed"] <= bk["t"]
                     and ((g["bottom"] > entry) if long_ else (g["top"] < entry))
                     and not any(((x["c"] > g["top"]) if long_ else (x["c"] < g["bottom"]))
                                 for x in m5 if g["formed"] <= x["t"] <= bk["t"])]
            ahead.sort(key=lambda g: g["bottom"] if long_ else -g["top"])     # nearest first
            pick = 1 if mode == "second" else 0
            if len(ahead) > pick:
                g = ahead[pick]
                if mode == "close":
                    be, be_close = (g["top"] if long_ else g["bottom"]), True     # close beyond its far edge
                else:
                    be = g["bottom"] if long_ else g["top"]                       # touch its near edge
        if be is not None and ((be >= target) if long_ else (be <= target)):
            be = None
        bar = dict(bk, i=int((bk["t"] - ctx["open"]).total_seconds() // 300))
        return {"side": "long" if long_ else "short", "entry": entry, "stop": stop, "target": target,
                "breakeven": be, "breakeven_close": be_close, "bar": bar,
                "why": "%s swept into %dm FVG, 5m iFVG %.2f-%.2f, target %s" % (
                    name, f_htf["tf"], f["bottom"], f["top"], tname)}, ""
    return None, "%s swept at %s into a %dm FVG; no displacement iFVG yet%s" % (
        name, clock.hm(sweep["t"]), f_htf["tf"], note)
