"""Imports the tools by path (their folders have dashes) and points at fixtures."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
ES = os.path.join(FIX, "ES-synthetic-5m.json")
sys.path.insert(0, ROOT)


def tool(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    if os.path.join(ROOT, folder) not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, folder))
    spec = importlib.util.spec_from_file_location(folder.replace("-", "_") + "_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
