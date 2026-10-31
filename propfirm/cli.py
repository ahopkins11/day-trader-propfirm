"""Small helpers the command-line tools share."""
import argparse
import os
import sys

from . import clock, config, contracts, data, engine, rules


def parser(desc):
    p = argparse.ArgumentParser(description=desc)
    return p


def common(p, symbols=False, symbol=False):
    if symbols:
        p.add_argument("--symbols", help="comma list, e.g. MES,MNQ (default: config symbols)")
    if symbol:
        p.add_argument("symbol", help="contract root, e.g. ES, MES, NQ, MNQ")
    p.add_argument("--now", help='New York time to evaluate at, e.g. "2026-10-19 10:30" (default: now)')
    p.add_argument("--offline", help="a saved bars file or folder instead of Yahoo")
    p.add_argument("--config", help="config path (default trader/config.json)")
    p.add_argument("--strategy", help="strategy name, overrides the config")
    p.add_argument("--write", action="store_true", help="save the result in trader/")
    return p


def setup(a):
    cfg = config.load(a.config)
    strat, params = config.load_strategy(cfg, name=getattr(a, "strategy", None))
    now = clock.parse_now(getattr(a, "now", None))
    return cfg, strat, params, now


def fail(msg, code=2):
    sys.stderr.write("error: %s\n" % msg)
    sys.exit(code)


def run(main):
    try:
        return main()
    except (clock.ClockError, config.ConfigError, contracts.ContractError, data.DataError,
            engine.EngineError, ValueError) as e:
        fail(str(e))


def out_path(name):
    return os.path.join(config.trader_dir(), name)


def money(x):
    return ("-$%.2f" % -x) if x < 0 else ("$%.2f" % x)
