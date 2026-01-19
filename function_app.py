import azure.functions as func
import json
import logging
import os
import random
import requests

app = func.FunctionApp()

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


@app.route("pydt-webhook", methods=["POST"])
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

        game_name = data.get("gameName", "Unknown Game")
        steam_username = data.get("userName", "Unknown Player")
        round_num = data.get("round", "?")
        civ_name = data.get("civName", "Unknown Civ")
        leader_name = data.get("leaderName", "Unknown Leader")

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

        # Format the message
        if discord_user_id:
            message = f"<@{discord_user_id}> - Your turn in \"{game_name}\" (Round {round_num})"
        else:
            logging.warning(f"No Discord mapping found for Steam user: {steam_username}")
            admonishment = random.choice(ADMONISHMENTS)
            message = (
                f"@everyone - It's \"{steam_username}\"'s turn in \"{game_name}\" (Round {round_num})\n\n"
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


@app.route("health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Simple health check endpoint."""
    return func.HttpResponse(
        json.dumps({"status": "healthy"}),
        status_code=200,
        mimetype="application/json"
    )
