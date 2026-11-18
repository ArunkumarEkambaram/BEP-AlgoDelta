"""
settings_store.py - keeps the "once a day" settings in settings.json next to the app, so a restart does
not ask for them again: strike count, scan interval, max orders/day and each index's AlgoDelta settings
(webhook URL, JSON template, target / SL / trail, quantity, max points above BEP, exit on opposite).

Deliberately NOT saved: the Upstox token (memory only), Dry run (the app always starts in Dry run),
Pause alerts and Pause algo trade.
"""
import json
import os

import config

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
_AUTO_KEYS = ("webhook_url", "confirmed", "tgt", "sl", "tgt_type", "sl_type", "qty", "exit_on_opposite", "trail",
              "trail_type", "trail_trigger", "trail_point", "trail_gap", "max_above_bep", "templates")


def load() -> str:
    """Applies settings.json to config. Returns a short status text."""
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return "No saved settings yet (defaults in use)."
    except (OSError, ValueError) as ex:
        return f"Could not read settings.json ({ex}); defaults in use."
    if isinstance(data.get("strikes_each_side"), int):
        config.STRIKES_EACH_SIDE = max(0, data["strikes_each_side"])
    if isinstance(data.get("scan_interval"), int) and data["scan_interval"] >= 1:
        config.SCAN_INTERVAL_SECONDS = data["scan_interval"]
    if isinstance(data.get("daily_limit"), int) and data["daily_limit"] >= 1:
        config.AUTO_ORDER_DAILY_LIMIT = data["daily_limit"]
    for name, saved in (data.get("auto_order") or {}).items():
        if name in config.AUTO_ORDER and isinstance(saved, dict):
            config.AUTO_ORDER[name].update({k: v for k, v in saved.items() if k in _AUTO_KEYS})
    return "Saved settings loaded."


def save() -> str:
    data = {
        "strikes_each_side": config.STRIKES_EACH_SIDE,
        "scan_interval": config.SCAN_INTERVAL_SECONDS,
        "daily_limit": config.AUTO_ORDER_DAILY_LIMIT,
        "auto_order": {n: {k: v for k, v in cfg.items() if k in _AUTO_KEYS} for n, cfg in config.AUTO_ORDER.items()},
    }
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, PATH)
        return "Settings saved."
    except OSError as ex:
        return f"Could not save settings ({ex})."
