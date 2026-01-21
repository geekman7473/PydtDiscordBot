import azure.functions as func
from azure.data.tables import TableServiceClient, TableClient
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import pathlib
import random
import requests

app = func.FunctionApp()

# Load configuration
CONFIG_PATH = pathlib.Path(__file__).parent / "config.json"
try:
    with open(CONFIG_PATH) as f:
        CONFIG = json.load(f)
except Exception as e:
    logging.warning(f"Could not load config.json, using defaults: {e}")
    CONFIG = {
        "blackout": {"enabled": True, "startHour": 0, "endHour": 7, "gmtOffset": -5},
        "reminderThresholdHours": 2
    }


def is_blackout_period() -> bool:
    """Check if current time is within the blackout period (no reminders)."""
    blackout = CONFIG.get("blackout", {})
    if not blackout.get("enabled", False):
        return False
    
    gmt_offset = blackout.get("gmtOffset", -5)
    start_hour = blackout.get("startHour", 0)
    end_hour = blackout.get("endHour", 7)
    
    # Get current time in the configured timezone
    utc_now = datetime.now(timezone.utc)
    local_time = utc_now + timedelta(hours=gmt_offset)
    current_hour = local_time.hour
    
    # Check if current hour is within blackout period
    if start_hour <= end_hour:
        # Simple case: e.g., 0-7 (midnight to 7am)
        return start_hour <= current_hour < end_hour
    else:
        # Wraps around midnight: e.g., 22-6 (10pm to 6am)
        return current_hour >= start_hour or current_hour < end_hour

# Snarky reminders for people taking too long on their turn
SNARKY_REMINDERS = [
    "Hey, remember that Civ game you're in? It remembers you. It's been waiting. Patiently. Unlike me.",
    "Just checking if you're still alive, because your turn certainly isn't progressing.",
    "Fun fact: entire civilizations have risen and fallen in the time you've been 'thinking' about your turn.",
    "I'm not saying you're slow, but I've seen glaciers move faster. Take your turn.",
    "Your opponents have started a betting pool on whether you'll ever finish your turn. The odds aren't great.",
    "Legend has it, if you wait long enough, the turn will play itself. Spoiler: it won't. Take your turn.",
    "I've sent this reminder before. I'll send it again. I have nothing but time. You, apparently, have nothing but excuses.",
    "The other players wanted me to tell you to hurry up. I wanted to tell you that too, but more sarcastically.",
    "Your Civ is starting to think you've abandoned them. Don't make me send a wellness check.",
    "Breaking news: Local player discovers 'taking your turn' is actually an option. More at 11.",
    "Did you know your turn has been pending longer than some people's entire relationships? Take. Your. Turn.",
    "I'm starting to think you're not playing hard to get, you're just not playing at all.",
    "The game isn't going to play itself. Well, technically it could if you enabled AI, but that's not the point.",
    "Tick tock. That's not a clock, that's the sound of everyone's patience running out.",
    "Your turn has been waiting so long it's started collecting dust. Digital dust. That's how long.",
]

# Admonishments for users who change their Steam name
ADMONISHMENTS = [
    "Whoever you are, change your Steam name back. We're not playing guess who here.",
    "Someone changed their Steam name and now I look like an idiot. Thanks for that.",
    "I don't know who you are, but I will find you, and I will ping you. Change your name back.",
    "Congratulations on your new identity. Now change it back so I can do my job.",
    "This is why we can't have nice things. Change your Steam name back.",
    "I'm a simple bot with simple needs. Please don't make my life harder than it needs to be.",
    "Your new Steam name is very cool. I'm sure it was worth confusing everyone. Change it back.",
    "I'm not mad, I'm just disappointed. And also mad. Change your name back.",
    "Did you think I wouldn't notice? I notice everything. Except your new name, apparently.",
    "Plot twist: someone changed their Steam name. Change it back or face mild inconvenience.",
]

# Required fields that PYDT must send
REQUIRED_FIELDS = ["gameName", "userName", "round"]


def get_storage_connection_string() -> str:
    """Get the Azure Storage connection string."""
    connection_string = os.environ.get("AzureWebJobsStorage")
    if not connection_string or connection_string == "UseDevelopmentStorage=true":
        # For local development, use Azurite
        connection_string = "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;"
    return connection_string


def get_table_client(table_name: str = "activegames") -> TableClient:
    """Get or create an Azure Table Storage client."""
    connection_string = get_storage_connection_string()
    table_service = TableServiceClient.from_connection_string(connection_string)
    
    # Create table if it doesn't exist
    try:
        table_service.create_table_if_not_exists(table_name)
    except Exception as e:
        logging.warning(f"Could not create table {table_name} (may already exist): {e}")
    
    return table_service.get_table_client(table_name)


def get_turn_history_client() -> TableClient:
    """Get the table client for turn history."""
    return get_table_client("turnhistory")


def sanitize_key(value: str) -> str:
    """Sanitize a string to be used as a PartitionKey or RowKey in Azure Table Storage."""
    # Azure Table Storage disallows: / \ # ? and control characters
    # Replace problematic characters with underscores
    import re
    sanitized = re.sub(r'[/\\#?\x00-\x1f\x7f-\x9f]', '_', value)
    return sanitized[:1024]  # Max key length is 1KB


def record_turn_completion(game_id: str, game_name: str, previous_player: str, previous_round: str, turn_started_at: str):
    """
    Record the completed turn duration in turn history.
    Called when a new webhook indicates someone else's turn has started.
    """
    try:
        now = datetime.now(timezone.utc)
        
        # Calculate duration in seconds
        if turn_started_at:
            try:
                start_time = datetime.fromisoformat(turn_started_at.replace('Z', '+00:00'))
                duration_seconds = int((now - start_time).total_seconds())
            except (ValueError, TypeError) as e:
                logging.warning(f"Could not parse turn start time: {e}")
                duration_seconds = -1  # Unknown duration
        else:
            duration_seconds = -1  # Unknown duration
        
        history_client = get_turn_history_client()
        
        # PartitionKey: game identifier, RowKey: round_player for uniqueness
        game_key = sanitize_key(game_id if game_id else game_name)
        row_key = sanitize_key(f"{previous_round}_{previous_player}")
        
        entity = {
            "PartitionKey": game_key,
            "RowKey": row_key,
            "gameName": game_name,
            "gameId": game_id or "",
            "steamUsername": previous_player,
            "roundNumber": str(previous_round),
            "turnStartedAt": turn_started_at or "",
            "turnCompletedAt": now.isoformat(),
            "durationSeconds": duration_seconds
        }
        
        history_client.upsert_entity(entity)
        
        if duration_seconds >= 0:
            hours = duration_seconds // 3600
            minutes = (duration_seconds % 3600) // 60
            logging.info(f"Recorded turn completion for {previous_player} in '{game_name}' (Round {previous_round}): {hours}h {minutes}m")
        else:
            logging.info(f"Recorded turn completion for {previous_player} in '{game_name}' (Round {previous_round}): duration unknown")
            
    except Exception as e:
        logging.error(f"Failed to record turn completion: {e}")


def update_turn_tracking(game_name: str, game_id: str, steam_username: str, discord_user_id: str, round_num: str):
    """
    Update or create a record tracking whose turn it is in a game.
    Also records the previous turn's duration if there was a previous turn.
    """
    try:
        table_client = get_table_client()
        
        # Use game_id if available, otherwise use sanitized game_name
        row_key = sanitize_key(game_id if game_id else game_name)
        
        # Try to get the existing record to close out the previous turn
        try:
            existing = table_client.get_entity("activegames", row_key)
            previous_player = existing.get("steamUsername", "")
            previous_round = existing.get("roundNumber", "")
            previous_turn_started = existing.get("turnStartedAt", "")
            
            # Only record if this is actually a different turn (different player or round)
            if previous_player and (previous_player != steam_username or previous_round != str(round_num)):
                record_turn_completion(
                    game_id=game_id,
                    game_name=game_name,
                    previous_player=previous_player,
                    previous_round=previous_round,
                    turn_started_at=previous_turn_started
                )
        except Exception:
            # No existing record - this is the first time we're seeing this game
            # That's fine, we just can't record the previous turn's duration
            logging.info(f"First webhook received for game '{game_name}' - no previous turn to record")
        
        # Now update with the new turn info
        entity = {
            "PartitionKey": "activegames",
            "RowKey": row_key,
            "gameName": game_name,
            "gameId": game_id or "",
            "steamUsername": steam_username,
            "discordUserId": discord_user_id or "",
            "roundNumber": str(round_num),
            "turnStartedAt": datetime.now(timezone.utc).isoformat(),
            "lastReminderAt": "",
            "reminderCount": 0
        }
        
        table_client.upsert_entity(entity)
        logging.info(f"Updated turn tracking for game '{game_name}': {steam_username}'s turn")
        
    except Exception as e:
        logging.error(f"Failed to update turn tracking: {e}")


def remove_game_tracking(game_id: str, game_name: str):
    """Remove a game from tracking (when game ends or is deleted)."""
    try:
        table_client = get_table_client()
        row_key = sanitize_key(game_id if game_id else game_name)
        
        table_client.delete_entity("activegames", row_key)
        logging.info(f"Removed tracking for game: {game_name}")
        
    except Exception as e:
        logging.warning(f"Could not remove game tracking (may not exist): {e}")


def validate_pydt_payload(data: dict) -> tuple[bool, str]:
    """Validate that the request looks like a legitimate PYDT webhook."""
    if not data:
        return False, "Empty payload"

    # Check required fields are present and non-empty
    for field in REQUIRED_FIELDS:
        value = data.get(field)
        if not value or (isinstance(value, str) and not value.strip()):
            return False, f"Missing or empty required field: {field}"

    # Basic sanity checks
    try:
        round_val = int(data.get("round", 0))
        if round_val < 0 or round_val > 10000:
            return False, "Invalid round number"
    except (ValueError, TypeError):
        return False, "Round must be a number"

    # Check gameName and userName aren't suspiciously long (prevent abuse)
    if len(str(data.get("gameName", ""))) > 200:
        return False, "Game name too long"
    if len(str(data.get("userName", ""))) > 100:
        return False, "Username too long"

    return True, ""


@app.route("pydt-webhook", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def pydt_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """
    Receives webhook from PYDT (Play Your Damn Turn) and posts to Discord.

    PYDT sends POST with parameters: gameName, userName, round, civName, leaderName
    """
    logging.info("PYDT webhook received")

    try:
        # Parse request - PYDT can send as form data or JSON
        content_type = req.headers.get("Content-Type", "")

        if "application/json" in content_type:
            data = req.get_json()
        else:
            # Form data
            data = {
                "gameName": req.form.get("gameName"),
                "userName": req.form.get("userName"),
                "round": req.form.get("round"),
                "civName": req.form.get("civName"),
                "leaderName": req.form.get("leaderName"),
            }

        # Validate the payload looks like a real PYDT webhook
        is_valid, error_msg = validate_pydt_payload(data)
        if not is_valid:
            logging.warning(f"Invalid PYDT payload: {error_msg}")
            return func.HttpResponse(
                json.dumps({"error": "Invalid request"}),
                status_code=400,
                mimetype="application/json"
            )

        game_name = data.get("gameName", "Unknown Game")
        steam_username = data.get("userName", "Unknown Player")
        round_num = data.get("round", "?")
        civ_name = data.get("civName", "Unknown Civ")
        leader_name = data.get("leaderName", "Unknown Leader")
        game_id = data.get("gameId", "")  # PYDT may send this

        logging.info(f"Turn notification: {steam_username} in {game_name} (Round {round_num})")

        # Load user mapping from environment variable
        user_mapping_json = os.environ.get("USER_MAPPING", "{}")
        try:
            user_mapping = json.loads(user_mapping_json)
        except json.JSONDecodeError:
            logging.error("Failed to parse USER_MAPPING JSON")
            user_mapping = {}

        # Look up Discord user ID
        discord_user_id = user_mapping.get(steam_username)

        # Track this turn in storage for reminders
        update_turn_tracking(game_name, game_id, steam_username, discord_user_id, round_num)

        # Format the message
        if discord_user_id:
            message = f"<@{discord_user_id}> - Your turn in \"{game_name}\" (Round {round_num}) as {leader_name} of {civ_name}"
        else:
            logging.warning(f"No Discord mapping found for Steam user: {steam_username}")
            admonishment = random.choice(ADMONISHMENTS)
            message = (
                f"@everyone - It's \"{steam_username}\"'s turn in \"{game_name}\" (Round {round_num}) as {leader_name} of {civ_name}\n\n"
                f"{admonishment}"
            )

        # Post to Discord
        discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not discord_webhook_url:
            logging.error("DISCORD_WEBHOOK_URL not configured")
            return func.HttpResponse(
                json.dumps({"error": "Discord webhook not configured"}),
                status_code=500,
                mimetype="application/json"
            )

        discord_payload = {"content": message}
        response = requests.post(discord_webhook_url, json=discord_payload, timeout=10)

        if response.status_code == 204:
            logging.info("Successfully posted to Discord")
            return func.HttpResponse(
                json.dumps({"status": "success", "message": "Posted to Discord"}),
                status_code=200,
                mimetype="application/json"
            )
        else:
            logging.error(f"Discord API error: {response.status_code} - {response.text}")
            return func.HttpResponse(
                json.dumps({"error": "Failed to post to Discord", "details": response.text}),
                status_code=502,
                mimetype="application/json"
            )

    except ValueError as e:
        logging.error(f"Invalid request data: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Invalid request data"}),
            status_code=400,
            mimetype="application/json"
        )
    except requests.RequestException as e:
        logging.error(f"Request to Discord failed: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Failed to reach Discord"}),
            status_code=502,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json"
        )


@app.route("health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Simple health check endpoint."""
    return func.HttpResponse(
        json.dumps({"status": "healthy"}),
        status_code=200,
        mimetype="application/json"
    )


@app.timer_trigger(schedule="0 */15 * * * *", arg_name="timer", run_on_startup=False)
def send_turn_reminders(timer: func.TimerRequest) -> None:
    """
    Timer trigger that runs every 15 minutes to send snarky reminders
    to players who haven't taken their turn for 2+ hours.
    Respects blackout periods configured in config.json.
    """
    logging.info("Turn reminder timer triggered")
    
    # Check if we're in a blackout period
    if is_blackout_period():
        blackout = CONFIG.get("blackout", {})
        logging.info(f"Skipping reminders - currently in blackout period ({blackout.get('startHour', 0)}:00-{blackout.get('endHour', 7)}:00, GMT{blackout.get('gmtOffset', -5):+d})")
        return
    
    try:
        table_client = get_table_client()
        
        # Get Discord webhook URL
        discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not discord_webhook_url:
            logging.error("DISCORD_WEBHOOK_URL not configured - cannot send reminders")
            return
        
        # Load user mapping for fallback lookups
        user_mapping_json = os.environ.get("USER_MAPPING", "{}")
        try:
            user_mapping = json.loads(user_mapping_json)
        except json.JSONDecodeError:
            user_mapping = {}
        
        # Query all active games
        entities = table_client.list_entities()
        
        now = datetime.now(timezone.utc)
        reminders_sent = 0
        
        for entity in entities:
            try:
                game_name = entity.get("gameName", "Unknown Game")
                steam_username = entity.get("steamUsername", "Unknown Player")
                discord_user_id = entity.get("discordUserId", "")
                round_num = entity.get("roundNumber", "?")
                turn_started_at = entity.get("turnStartedAt", "")
                reminder_count = entity.get("reminderCount", 0)
                
                # Parse when the turn started
                if turn_started_at:
                    turn_start = datetime.fromisoformat(turn_started_at.replace('Z', '+00:00'))
                    hours_waiting = (now - turn_start).total_seconds() / 3600
                else:
                    hours_waiting = 0
                
                # Only send reminder if turn has been pending for at least the threshold
                reminder_threshold = CONFIG.get("reminderThresholdHours", 2)
                if hours_waiting < reminder_threshold:
                    logging.info(f"Skipping reminder for {game_name} - only {hours_waiting:.1f} hours elapsed (threshold: {reminder_threshold}h)")
                    continue

                # Check if enough time has passed since the last reminder
                last_reminder_at = entity.get("lastReminderAt", "")
                if last_reminder_at:
                    last_reminder = datetime.fromisoformat(last_reminder_at.replace('Z', '+00:00'))
                    hours_since_last_reminder = (now - last_reminder).total_seconds() / 3600
                    if hours_since_last_reminder < reminder_threshold:
                        logging.info(f"Skipping reminder for {game_name} - only {hours_since_last_reminder:.1f} hours since last reminder (threshold: {reminder_threshold}h)")
                        continue
                
                # Pick a snarky reminder
                snark = random.choice(SNARKY_REMINDERS)
                
                # Format the reminder message
                if discord_user_id:
                    message = f"⏰ <@{discord_user_id}> - Reminder #{reminder_count + 1}: Your turn in \"{game_name}\" (Round {round_num}) has been waiting for {hours_waiting:.1f} hours.\n\n{snark}"
                else:
                    # Try to look up the Discord ID again in case mapping was updated
                    discord_user_id = user_mapping.get(steam_username, "")
                    if discord_user_id:
                        message = f"⏰ <@{discord_user_id}> - Reminder #{reminder_count + 1}: Your turn in \"{game_name}\" (Round {round_num}) has been waiting for {hours_waiting:.1f} hours.\n\n{snark}"
                    else:
                        message = f"⏰ @everyone - Reminder #{reminder_count + 1}: **{steam_username}**'s turn in \"{game_name}\" (Round {round_num}) has been waiting for {hours_waiting:.1f} hours.\n\n{snark}"
                
                # Send the reminder to Discord
                discord_payload = {"content": message}
                response = requests.post(discord_webhook_url, json=discord_payload, timeout=10)
                
                if response.status_code == 204:
                    logging.info(f"Sent reminder #{reminder_count + 1} for {game_name} to {steam_username}")
                    reminders_sent += 1
                    
                    # Update the reminder tracking
                    entity["lastReminderAt"] = now.isoformat()
                    entity["reminderCount"] = reminder_count + 1
                    table_client.upsert_entity(entity)
                else:
                    logging.error(f"Failed to send reminder for {game_name}: {response.status_code}")
                    
            except Exception as e:
                logging.error(f"Error processing reminder for game: {e}")
                continue
        
        logging.info(f"Turn reminder job complete. Sent {reminders_sent} reminders.")
        
    except Exception as e:
        logging.error(f"Failed to run turn reminders: {e}")


@app.route("active-games", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_active_games(req: func.HttpRequest) -> func.HttpResponse:
    """Debug endpoint to list all active games being tracked."""
    try:
        table_client = get_table_client()
        entities = list(table_client.list_entities())
        
        games = []
        for entity in entities:
            games.append({
                "gameName": entity.get("gameName"),
                "steamUsername": entity.get("steamUsername"),
                "roundNumber": entity.get("roundNumber"),
                "turnStartedAt": entity.get("turnStartedAt"),
                "reminderCount": entity.get("reminderCount", 0)
            })
        
        return func.HttpResponse(
            json.dumps({"activeGames": games, "count": len(games)}),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logging.error(f"Failed to get active games: {e}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
