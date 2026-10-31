"""trader/config.json, its defaults, the trader/ folder, and the strategy loader."""
import copy
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "strategy": "orb",
    "strategy_params": {},
    "symbols": ["MES", "MNQ"],
    "bar_minutes": 5,
    "no_entries_before": "09:45",
    "no_entries_after": "15:00",
    "flat_by": "15:55",
    "account": {
        "firm": "Topstep",
        "plan": "50K Trading Combine (EXAMPLE numbers: copy yours from the Topstep dashboard)",
        "stage": "combine",
        "starting_balance": 50000,
        "max_loss_limit": 2000,
        "trailing": "eod",
        "trail_stops_at_start": True,
        "daily_loss_limit": 1000,
        "profit_target": 3000,
        "max_contracts": 5,
        "micros_per_contract": 10,
    },
    "personal": {
        "max_loss_per_trade_usd": 200,
        "max_daily_loss_usd": 400,
        "max_trades_per_day": 3,
        "min_reward_risk": 1.0,
        "buffer_usd": 100,
        "max_contracts": 2,
    },
    "fees_per_contract_round_trip": 0.0,
    "news_events": [],
    "news_blackout_minutes": 5,
    "broker": "projectx",
}


class ConfigError(Exception):
    pass


def trader_dir(base=None):
    return os.path.join(base or os.getcwd(), "trader")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k.startswith("_"):
            continue  # "_notes" and other comments
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    path = path or os.path.join(trader_dir(), "config.json")
    if not os.path.exists(path):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["_source"] = "defaults (no %s yet: copy config.example.json there)" % path
        return cfg
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as e:
        raise ConfigError("%s is not valid JSON: %s" % (path, e))
    cfg = _merge(DEFAULTS, doc)
    cfg["_source"] = path
    return cfg


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, default=str)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- strategies

def strategy_paths(name, base=None):
    """Your project's trader/strategies/ first, then the repo's strategies/."""
    return [os.path.join(trader_dir(base), "strategies", name + ".py"),
            os.path.join(ROOT, "strategies", name + ".py")]


def load_strategy(cfg, name=None, base=None):
    """-> (module, params). params = the module's PARAMS + config strategy_params."""
    name = name or cfg.get("strategy") or "orb"
    for p in strategy_paths(name, base):
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("strategy_" + name, p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for need in ("NAME", "PARAMS", "evaluate"):
                if not hasattr(mod, need):
                    raise ConfigError("strategy %s (%s) has no %s: start from strategies/template.py" % (name, p, need))
            params = dict(mod.PARAMS)
            params.update(cfg.get("strategy_params") or {})
            mod.__file_path__ = p
            return mod, params
    raise ConfigError("no strategy named %r. Looked in: %s" % (name, ", ".join(strategy_paths(name, base))))
