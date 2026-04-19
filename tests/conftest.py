"""
conftest.py — Lädt decision_engine.py direkt per importlib,
ohne das HA-abhängige __init__.py der Integration zu durchlaufen.
"""
import sys
import types
import importlib.util
import os

# --- Minimale Stubs damit const.py und power_controller.py importierbar sind ---
class _Platform:
    SENSOR = "sensor"
    NUMBER = "number"
    SELECT = "select"
    SWITCH = "switch"

def _mod(name: str, **attrs) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules.setdefault(name, m)
    return m

_mod("homeassistant")
_mod("homeassistant.const", Platform=_Platform)


def _load_module(rel_path: str, module_name: str):
    """Lädt eine einzelne .py-Datei als Modul, unabhängig vom Package."""
    root = os.path.join(os.path.dirname(__file__), "..")
    path = os.path.normpath(os.path.join(root, rel_path))
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Reihenfolge: Abhängigkeiten zuerst
_base = "custom_components.battery_smartflow_ai"
_load_module(f"custom_components/battery_smartflow_ai/power_controller.py",
             f"{_base}.power_controller")
_load_module(f"custom_components/battery_smartflow_ai/const.py",
             f"{_base}.const")
_load_module(f"custom_components/battery_smartflow_ai/decision_engine.py",
             f"{_base}.decision_engine")
