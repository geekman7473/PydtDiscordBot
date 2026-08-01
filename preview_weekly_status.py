"""
Local preview for the weekly status report.

Renders the message(s) that the bot would post on Friday at noon Pacific,
using live data from the public PYDT API. Nothing is posted to Discord.

Usage:
    python preview_weekly_status.py                 # auto-discover game(s) from mappings.json
    python preview_weekly_status.py <gameId> [...]  # preview specific game(s)

Requires only the `requests` and `tzdata` packages (see requirements.txt).
"""

import json
import pathlib
import sys
from datetime import datetime, timezone

import weekly_status as weekly

ROOT = pathlib.Path(__file__).parent


def load_json(name, default):
    path = ROOT / name
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def main(argv):
    config = load_json("config.json", {})
    user_mapping = load_json("mappings.json", {})
    now = datetime.now(timezone.utc)

    game_ids = argv[1:]
    if not game_ids:
        print("No game id passed; discovering from mappings.json players...\n")
        game_ids = weekly.discover_game_ids_for_steam_ids(list(user_mapping.keys()))

    if not game_ids:
        print("Could not find any games to preview.")
        return 1

    for game_id in game_ids:
        report = weekly.build_status_for_game(game_id, now, user_mapping, config)
        print("=" * 60)
        print(f"GAME: {report['displayName']}  ({game_id})")
        print("=" * 60)
        print(report["message"])
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
