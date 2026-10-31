"""Futures contract specs and the tick math every tool shares.

tick       the smallest price step
tick_value dollars one tick is worth for one contract
point      dollars a full 1.00 move is worth for one contract (tick_value / tick)
rth        the regular session the strategies trade, New York time
micro      the micro contract that is one tenth the size (for sizing down)

These are CME's published contract sizes. Check them against your platform's
contract details if you add a new one.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_UP

EQUITY_RTH = ("09:30", "16:00")

CONTRACTS = {
    "ES":  {"name": "E-mini S&P 500",        "tick": "0.25", "tick_value": "12.50", "rth": EQUITY_RTH, "micro": "MES"},
    "MES": {"name": "Micro E-mini S&P 500",  "tick": "0.25", "tick_value": "1.25",  "rth": EQUITY_RTH, "full": "ES"},
    "NQ":  {"name": "E-mini Nasdaq-100",     "tick": "0.25", "tick_value": "5.00",  "rth": EQUITY_RTH, "micro": "MNQ"},
    "MNQ": {"name": "Micro E-mini Nasdaq-100", "tick": "0.25", "tick_value": "0.50", "rth": EQUITY_RTH, "full": "NQ"},
    "YM":  {"name": "E-mini Dow",            "tick": "1",    "tick_value": "5.00",  "rth": EQUITY_RTH, "micro": "MYM"},
    "MYM": {"name": "Micro E-mini Dow",      "tick": "1",    "tick_value": "0.50",  "rth": EQUITY_RTH, "full": "YM"},
    "RTY": {"name": "E-mini Russell 2000",   "tick": "0.10", "tick_value": "5.00",  "rth": EQUITY_RTH, "micro": "M2K"},
    "M2K": {"name": "Micro E-mini Russell 2000", "tick": "0.10", "tick_value": "0.50", "rth": EQUITY_RTH, "full": "RTY"},
    "CL":  {"name": "Crude Oil",             "tick": "0.01", "tick_value": "10.00", "rth": ("09:00", "14:30"), "micro": "MCL"},
    "MCL": {"name": "Micro Crude Oil",       "tick": "0.01", "tick_value": "1.00",  "rth": ("09:00", "14:30"), "full": "CL"},
    "GC":  {"name": "Gold",                  "tick": "0.10", "tick_value": "10.00", "rth": ("08:20", "13:30"), "micro": "MGC"},
    "MGC": {"name": "Micro Gold",            "tick": "0.10", "tick_value": "1.00",  "rth": ("08:20", "13:30"), "full": "GC"},
}


class ContractError(Exception):
    pass


def spec(symbol):
    """'es', 'ES', 'ES=F' -> the spec dict with Decimal tick math filled in."""
    root = symbol.upper().replace("=F", "").strip()
    if root not in CONTRACTS:
        raise ContractError("%s is not in the contract table (propfirm/contracts.py). Known: %s"
                            % (symbol, ", ".join(sorted(CONTRACTS))))
    s = dict(CONTRACTS[root])
    s["symbol"] = root
    s["yahoo"] = root + "=F"
    s["tick_d"] = Decimal(s["tick"])
    s["tick_value_d"] = Decimal(s["tick_value"])
    s["point_value"] = float(s["tick_value_d"] / s["tick_d"])
    s["is_micro"] = "full" in s
    return s


def _q(price, s, rounding):
    p = Decimal(repr(float(price)))
    return float((p / s["tick_d"]).to_integral_value(rounding=rounding) * s["tick_d"])


def round_tick(price, s):
    return _q(price, s, ROUND_HALF_UP)


def stop_tick(stop, entry, s):
    """A stop rounds away from the entry, so the real risk is never understated."""
    return _q(stop, s, ROUND_FLOOR if stop < entry else ROUND_CEILING)


def ticks_between(a, b, s):
    return int(round(abs(Decimal(repr(float(a))) - Decimal(repr(float(b)))) / s["tick_d"]))


def dollars(ticks, s, contracts=1):
    return float(Decimal(ticks) * s["tick_value_d"] * contracts)


def fmt_price(p, s):
    places = max(0, -s["tick_d"].as_tuple().exponent)
    return ("%." + str(places) + "f") % p
