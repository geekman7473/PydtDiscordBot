"""
Weekly status report logic for the PYDT Discord bot.

This module is intentionally framework-agnostic (no ``azure.functions`` import)
so it can be unit-tested and previewed locally with nothing but ``requests``.

It builds a once-a-week summary for a PYDT game using the public (anonymous)
PYDT API:

  * the fastest turn of the week (to reward a player)
  * the weekly play rate in "turns per day" where a "turn" is one full round
    (every player gets to take their turn)
  * the overall progression rate since the game started, and a projected ETA
    for when the game will finish

In PYDT a ``round`` is the in-game Civ turn number (it advances once every
player has moved), which is exactly the user-facing notion of a "turn" here.
"""

from __future__ import annotations

import io
import logging
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

PYDT_API_BASE = "https://api.playyourdamnturn.com"
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
HTTP_TIMEOUT = 15

# Default Civilization VI game-end turn by game speed. Because a PYDT "round"
# equals the in-game Civ turn number, these double as our ETA target rounds.
DEFAULT_GAME_SPEED_TARGET_ROUNDS = {
    "GAMESPEED_ONLINE": 250,
    "GAMESPEED_QUICK": 330,
    "GAMESPEED_STANDARD": 500,
    "GAMESPEED_EPIC": 750,
    "GAMESPEED_MARATHON": 1500,
}
DEFAULT_TARGET_ROUNDS = 500


# ---------------------------------------------------------------------------
# PYDT API access
# ---------------------------------------------------------------------------
def fetch_pydt_game(game_id: str) -> dict:
    """Fetch a game object from the PYDT API."""
    resp = requests.get(f"{PYDT_API_BASE}/game/{game_id}", timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_pydt_turns(game_id: str, start_turn: int, end_turn: int) -> list:
    """Fetch the list of per-turn records for a turn range (inclusive)."""
    start_turn = max(1, int(start_turn))
    end_turn = max(start_turn, int(end_turn))
    resp = requests.get(
        f"{PYDT_API_BASE}/game/{game_id}/turns/{start_turn}/{end_turn}",
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_pydt_turns_full(game_id: str, end_turn: int, chunk: int = 500) -> list:
    """
    Fetch every per-turn record from turn 1 through ``end_turn``.

    The PYDT turns endpoint is range-based, so a long game is fetched in
    chunks to keep individual requests modest. Failed chunks are skipped
    (best effort) so a single hiccup doesn't sink the whole report.
    """
    end_turn = max(1, int(end_turn))
    all_turns: list = []
    start = 1
    while start <= end_turn:
        stop = min(end_turn, start + chunk - 1)
        try:
            all_turns.extend(fetch_pydt_turns(game_id, start, stop))
        except Exception as exc:  # pragma: no cover - network best effort
            logging.warning(
                f"Could not fetch turns {start}-{stop} for game {game_id}: {exc}"
            )
        start = stop + 1
    return all_turns


def fetch_pydt_user_name(steam_id: str) -> str:
    """Look up a player's PYDT display name (best effort)."""
    try:
        resp = requests.get(f"{PYDT_API_BASE}/user/{steam_id}", timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("displayName") or ""
    except Exception as exc:  # pragma: no cover - network best effort
        logging.warning(f"Could not fetch PYDT display name for {steam_id}: {exc}")
        return ""


def discover_game_ids_for_steam_ids(steam_ids, min_shared: int = 2, limit: int = 12) -> list:
    """
    Discover the group's active game(s) from a set of Steam IDs.

    Returns game IDs shared by at least ``min_shared`` of the given players
    (so a single player's unrelated solo games are ignored). Falls back to any
    discovered games if none are shared.
    """
    tally: Counter = Counter()
    for steam_id in list(steam_ids)[:limit]:
        try:
            resp = requests.get(f"{PYDT_API_BASE}/user/{steam_id}", timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            for gid in resp.json().get("activeGameIds", []) or []:
                if gid:
                    tally[gid] += 1
        except Exception as exc:  # pragma: no cover - network best effort
            logging.warning(f"Game discovery failed for {steam_id}: {exc}")

    shared = [gid for gid, count in tally.most_common() if count >= min_shared]
    if shared:
        return shared
    return [gid for gid, _ in tally.most_common()]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _parse_date(value) -> "datetime | None":
    """Parse a PYDT ISO-8601 timestamp into a timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_duration(seconds: float) -> str:
    """Render a turn duration like '16 minutes' or '2h 5m'."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        if secs:
            return f"{minutes} min {secs} sec"
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if minutes:
        return f"{hours}h {minutes}m"
    return f"{hours} hour{'s' if hours != 1 else ''}"


def humanize_days(days: float) -> str:
    """Render a span of days like '12 days', 'about 5 months', 'about 2.3 years'."""
    days = float(days)
    if days < 1:
        return "less than a day"
    if days < 45:
        whole = int(round(days))
        return f"{whole} day{'s' if whole != 1 else ''}"
    if days < 365:
        months = int(round(days / 30.44))
        return f"about {months} month{'s' if months != 1 else ''}"
    years = days / 365.25
    return f"about {years:.1f} years"


def format_long_date(dt: datetime, weekday: bool = True) -> str:
    """Render a date in Pacific time, e.g. 'Friday, June 12, 2026'."""
    local = dt.astimezone(PACIFIC_TZ)
    prefix = f"{local:%A}, " if weekday else ""
    return f"{prefix}{local:%B} {local.day}, {local.year}"


# ---------------------------------------------------------------------------
# Stat computation
# ---------------------------------------------------------------------------
def compute_weekly_pace(game: dict, now: datetime, days: int = 7) -> dict:
    """
    Compute the fastest turn and the play rate over the trailing ``days`` window.

    A "turn" in the play-rate sense is a full round (everyone moves once), so
    ``turns_per_day`` = rounds completed in the window / days.
    """
    game_id = game.get("gameId")
    slots = int(game.get("slots") or 0) or 8

    # Current global turn index: gameTurnRangeKey tracks the next/current turn;
    # turnsPlayed + turnsSkipped is a reliable fallback.
    current_turn = int(
        game.get("gameTurnRangeKey")
        or (int(game.get("turnsPlayed") or 0) + int(game.get("turnsSkipped") or 0))
        or 1
    )

    # Look back far enough to comfortably cover the window even at a brisk pace.
    lookback = max(slots * (days + 14), 40)
    start_turn = max(1, current_turn - lookback)

    try:
        turns = fetch_pydt_turns(game_id, start_turn, current_turn)
    except Exception as exc:
        logging.warning(f"Could not fetch turns for game {game_id}: {exc}")
        turns = []

    cutoff = now - timedelta(days=days)
    window = []
    for turn in turns:
        end = _parse_date(turn.get("endDate"))
        if end and end >= cutoff:
            window.append((turn, end))

    fastest = None
    turns_taken = 0
    rounds_seen = []
    for turn, end in window:
        round_no = int(turn.get("round") or 0)
        rounds_seen.append(round_no)
        if turn.get("skipped"):
            continue
        turns_taken += 1
        start = _parse_date(turn.get("startDate"))
        if not start:
            continue
        duration = (end - start).total_seconds()
        if duration < 0:
            continue
        if fastest is None or duration < fastest["seconds"]:
            fastest = {
                "steamId": turn.get("playerSteamId", ""),
                "seconds": duration,
                "round": round_no,
            }

    rounds_completed = (max(rounds_seen) - min(rounds_seen)) if rounds_seen else 0

    return {
        "fastest": fastest,
        "rounds_completed": rounds_completed,
        "turns_per_day": rounds_completed / days if days else 0.0,
        "turns_taken": turns_taken,
        "window_count": len(window),
        "days": days,
    }


def compute_eta(
    game: dict,
    now: datetime,
    target_rounds_map: "dict | None" = None,
    default_target: int = DEFAULT_TARGET_ROUNDS,
) -> dict:
    """Compute the overall progression rate and a projected finish date."""
    target_rounds_map = target_rounds_map or DEFAULT_GAME_SPEED_TARGET_ROUNDS
    created = _parse_date(game.get("createdAt"))
    current_round = int(game.get("round") or 0)
    speed = game.get("gameSpeed", "")
    target = int(target_rounds_map.get(speed, default_target) or default_target)

    age_days = (now - created).total_seconds() / 86400 if created else None
    overall_rate = current_round / age_days if age_days and age_days > 0 else None
    remaining = max(0, target - current_round)
    eta_days = remaining / overall_rate if overall_rate and overall_rate > 0 else None
    eta_date = now + timedelta(days=eta_days) if eta_days is not None else None

    return {
        "created": created,
        "age_days": age_days,
        "current_round": current_round,
        "target_round": target,
        "game_speed": speed,
        "overall_rate": overall_rate,  # rounds (turns) per day
        "remaining_rounds": remaining,
        "eta_days": eta_days,
        "eta_date": eta_date,
        "completed": bool(game.get("completed")),
    }


# ---------------------------------------------------------------------------
# Weekly velocity (full-history chart data)
# ---------------------------------------------------------------------------
def _week_start(dt: datetime) -> datetime:
    """Return the Pacific-local Monday (00:00) of the week containing ``dt``."""
    local = dt.astimezone(PACIFIC_TZ)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def compute_weekly_velocity(game: dict, now: datetime) -> dict:
    """
    Build a one-point-per-calendar-week velocity series over the game's full
    history: how many rounds (turns) were completed during each week.

    Weeks are anchored to Pacific-local Mondays so they line up with the
    Friday report cadence. Weeks with no play are included as zeros so the
    chart shows a continuous timeline. Velocity for a week is the number of
    new rounds reached that week (cumulative max round diffed week over week),
    which makes the per-week values sum to the total rounds played.
    """
    game_id = game.get("gameId")
    current_turn = int(
        game.get("gameTurnRangeKey")
        or (int(game.get("turnsPlayed") or 0) + int(game.get("turnsSkipped") or 0))
        or 1
    )

    turns = fetch_pydt_turns_full(game_id, current_turn)

    # Highest round reached within each week bucket.
    week_max_round: dict[datetime, int] = {}
    min_round = None
    for turn in turns:
        end = _parse_date(turn.get("endDate"))
        round_no = int(turn.get("round") or 0)
        if end is None or round_no <= 0:
            continue
        if min_round is None or round_no < min_round:
            min_round = round_no
        wk = _week_start(end)
        if wk not in week_max_round or round_no > week_max_round[wk]:
            week_max_round[wk] = round_no

    if not week_max_round:
        return {"points": [], "total_rounds": 0, "weeks": 0}

    first_week = min(week_max_round)
    last_week = _week_start(now)
    if last_week < first_week:
        last_week = first_week

    # Walk every calendar week from the first played week to "now", filling
    # gaps. Velocity = (cumulative max round this week) - (previous week's).
    points = []
    baseline = (min_round - 1) if min_round is not None else 0
    running_max = baseline
    week = first_week
    while week <= last_week:
        prev_max = running_max
        if week in week_max_round:
            running_max = max(running_max, week_max_round[week])
        points.append((week, running_max - prev_max))
        week += timedelta(days=7)

    total_rounds = (running_max - baseline) if min_round is not None else 0
    return {
        "points": points,  # list of (week_start_datetime, rounds_completed)
        "total_rounds": total_rounds,
        "weeks": len(points),
    }


def render_velocity_png(velocity: dict, display_name: str) -> "bytes | None":
    """
    Render the weekly velocity series to a PNG (bytes) using matplotlib.

    Returns ``None`` if there's nothing to plot or matplotlib is unavailable.
    """
    points = (velocity or {}).get("points") or []
    if not points:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend (no display on the server)
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        logging.warning(f"matplotlib unavailable; skipping velocity chart: {exc}")
        return None

    weeks = [wk for wk, _ in points]
    values = [val for _, val in points]

    fig, ax = plt.subplots(figsize=(7.0, 3.6), dpi=110)
    discord_blurple = "#5865F2"
    ax.fill_between(weeks, values, color=discord_blurple, alpha=0.18)
    ax.plot(weeks, values, color=discord_blurple, linewidth=2, marker="o", markersize=4)

    ax.set_title(f"Weekly Velocity — {display_name}", fontsize=12, fontweight="bold")
    ax.set_ylabel("turns / week")
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", linestyle="--", alpha=0.4)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=45, ha="right")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------
# Congratulation lines for the fastest turn of the week. Each is a format
# template with ``{label}`` (player), ``{duration}`` (e.g. "16 minutes") and
# ``{round}`` (the in-game round number) placeholders. One is chosen at random.
FASTEST_TURN_CONGRATS = [
    "{label} blitzed their turn in just **{duration}** (round {round}). Take a bow! 🎖️",
    "Speed demon alert! {label} wrapped up round {round} in a blink — **{duration}**. ⚡",
    "{label} clocked the fastest turn this week: **{duration}** on round {round}. Lightning fast! 🏎️",
    "Give it up for {label}, who smashed out round {round} in **{duration}**. 🏆",
    "{label} didn't keep anyone waiting — round {round} done in **{duration}**. 👏",
    "Record pace! {label} finished round {round} in **{duration}**. The rest of us are taking notes. 📝",
    "{label} treated their turn like a speedrun: round {round} in **{duration}**. 🕹️",
    "Hats off to {label} — **{duration}** to clear round {round}. Efficiency incarnate. 🎩",
    "{label} blinked and round {round} was over. Official time: **{duration}**. 😮",
    "The fastest hands in the empire belong to {label}: round {round} in **{duration}**. 🤠",
    "{label} took their turn so fast the barbarians didn't even notice. **{duration}** on round {round}. 🏹",
    "Zoom! {label} powered through round {round} in **{duration}**. 💨",
    "{label} set the weekly benchmark — round {round} in a tidy **{duration}**. 📏",
    "No dawdling here: {label} knocked out round {round} in **{duration}**. 🥇",
    "{label} wins this week's golden stopwatch with **{duration}** on round {round}. ⏱️",
    "{label} made it look easy: round {round} finished in **{duration}**. Smooth. 🧈",
    "Fastest turn of the week goes to {label} — **{duration}** flat on round {round}. 🚀",
    "{label} came, saw, and ended their turn in **{duration}** (round {round}). 🏛️",
    "{label} didn't break a sweat — round {round} done in **{duration}**. 💪",
    "Blink and you'll miss it: {label} finished round {round} in **{duration}**. 👀",
    "{label} is playing on fast-forward — round {round} in **{duration}**. ⏩",
    "All hail {label}, who razed round {round} in just **{duration}**. 👑",
    "{label} finished round {round} in **{duration}** — faster than my will to live on a Monday. ☕",
    "Scientists are baffled: {label} bent spacetime to clear round {round} in **{duration}**. 🔬",
    "{label} ended their turn in **{duration}**. The loading screen took longer than that. Round {round}. ⌛",
    "BREAKING: {label} completes round {round} in **{duration}**, immediately starts trash-talking. 📰",
    "{label} did round {round} in **{duration}** while you were still reading the previous message. 🫵",
    "Gandhi requested {label}'s nukes be classified as a war crime after that **{duration}** turn (round {round}). ☢️",
    "{label} cleared round {round} in **{duration}**. Sun Tzu is taking notes from beyond the grave. 📜",
    "{label} finished round {round} so fast (**{duration}**) the AI conceded out of respect. 🤖",
    "Witnesses say {label} didn't even sit down — round {round} obliterated in **{duration}**. 🪑",
    "{label} speedran round {round} in **{duration}**. Mods are asking for a frame-by-frame review. 🎥",
]


def pick_fastest_turn_congrats(label: str, duration: str, round_no, rng=random) -> str:
    """Return a randomly chosen congratulation line for the fastest turn."""
    template = rng.choice(FASTEST_TURN_CONGRATS)
    return template.format(label=label, duration=duration, round=round_no)


def resolve_player_label(steam_id: str, user_mapping: dict, name_lookup=fetch_pydt_user_name) -> str:
    """Build a Discord-friendly player label, preferring an @mention."""
    discord_id = (user_mapping or {}).get(steam_id, "")
    name = name_lookup(steam_id) if name_lookup else ""
    if discord_id:
        return f"<@{discord_id}>" + (f" ({name})" if name else "")
    if name:
        return f"**{name}**"
    return f"**{steam_id}**"


def build_weekly_status_message(
    game: dict,
    pace: dict,
    eta: dict,
    user_mapping: dict,
    now: datetime,
    name_lookup=fetch_pydt_user_name,
) -> str:
    """Render the full weekly status message for a single game."""
    display_name = game.get("displayName") or "the game"
    lines = [
        "@everyone",
        f"📊 **Weekly Civ Report — {display_name}**",
        "",
        "🏆 **Fastest Turn of the Week**",
    ]

    fastest = pace.get("fastest")
    if fastest and fastest.get("steamId"):
        label = resolve_player_label(fastest["steamId"], user_mapping, name_lookup)
        lines.append(
            pick_fastest_turn_congrats(
                label, format_duration(fastest["seconds"]), fastest["round"]
            )
        )
    else:
        lines.append("Nobody finished a turn this week. The barbarians are getting bored. 🏹")

    rounds_completed = pace.get("rounds_completed", 0)
    turns_taken = pace.get("turns_taken", 0)
    turns_per_day = pace.get("turns_per_day", 0.0)
    lines += [
        "",
        "⏱️ **This Week's Pace**",
        (
            f"We finished **{rounds_completed} round{'s' if rounds_completed != 1 else ''}** "
            f"({turns_taken} player-turn{'s' if turns_taken != 1 else ''}) in the last 7 days — "
            f"an average of **{turns_per_day:.2f} turns/day**."
        ),
        "",
        "📈 **Stats**",
    ]

    if eta.get("overall_rate"):
        lines.append(f"• Age: **{humanize_days(eta['age_days'])}**")
        lines.append(f"• Overall pace: **{eta['overall_rate']:.2f} turns/day**")
        if eta.get("completed"):
            lines.append("• Status: **Completed!** 🎉")
        elif eta.get("eta_date") is not None:
            lines.append(
                f"• ETA: **{format_long_date(eta['eta_date'], weekday=False)}** "
                f"({humanize_days(eta['eta_days'])} to go)"
            )
    else:
        lines.append("Not enough data yet to estimate progress. Check back next week!")

    return "\n".join(lines)


def build_status_for_game(
    game_id: str,
    now: datetime,
    user_mapping: dict,
    config: "dict | None" = None,
    name_lookup=fetch_pydt_user_name,
) -> dict:
    """Fetch data and build the weekly status report for one game."""
    config = config or {}
    ws_cfg = config.get("weeklyStatus", {})
    target_map = ws_cfg.get("gameSpeedTargetRounds") or DEFAULT_GAME_SPEED_TARGET_ROUNDS
    default_target = ws_cfg.get("defaultTargetRounds", DEFAULT_TARGET_ROUNDS)

    game = fetch_pydt_game(game_id)
    if not game.get("gameId"):
        game["gameId"] = game_id

    pace = compute_weekly_pace(game, now)
    eta = compute_eta(game, now, target_map, default_target)
    message = build_weekly_status_message(game, pace, eta, user_mapping, now, name_lookup)

    display_name = game.get("displayName", game_id)

    chart_enabled = ws_cfg.get("velocityChart", {}).get("enabled", True)
    chart_png = None
    velocity = {"points": [], "total_rounds": 0, "weeks": 0}
    if chart_enabled:
        try:
            velocity = compute_weekly_velocity(game, now)
            chart_png = render_velocity_png(velocity, display_name)
        except Exception as exc:  # pragma: no cover - chart is best effort
            logging.warning(f"Could not build velocity chart for {game_id}: {exc}")

    return {
        "gameId": game_id,
        "displayName": display_name,
        "message": message,
        "pace": pace,
        "eta": eta,
        "velocity": velocity,
        "chartPng": chart_png,  # PNG bytes for a Discord attachment, or None
    }

