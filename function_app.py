import azure.functions as func
from azure.data.tables import TableServiceClient, TableClient
from datetime import datetime, timezone, timedelta
import json
import logging
import os
import pathlib
import random
import requests

import weekly_status as weekly

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
        "reminderThresholdHours": 2,
        "reminderIntervalHours": 2
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

# Reminder messages organized by intensity level
# LOW: Polite reminders for the first few hours
# MEDIUM: Snarky but friendly reminders
# HIGH: Full snark for extended delays

LOW_INTENSITY_REMINDERS = [
    "Oh hey, your turn exists. Just thought you should know.",
    "Your turn is ready. No pressure, but also... your turn is ready.",
    "Ping! That's the sound of your turn waiting. Patiently. For now.",
    "Just a casual reminder that the End Turn button misses you.",
    "Your turn is still here. It's not going anywhere. Neither is the game, apparently.",
    "Hey, remember Civ? Civ remembers you. Specifically, it remembers you owe it a turn.",
    "Fun fact: You have a turn pending. Less fun fact: Still pending.",
    "Your civilization is holding a 'Where's Our Leader?' meeting. Thought you'd want to know.",
    "Not to be dramatic, but your turn has been sitting there. Just... sitting.",
    "Quick update: Turn still pending. This has been your turn status report.",
    "Your scouts report that it's your turn. They seem unsure what you're doing about it.",
    "The game would like to inform you that your turn is ready. It asked nicely.",
    "Breaking: Local turn remains untaken. Developing story.",
    "Your citizens have started a casual inquiry into your whereabouts. Nothing serious. Yet.",
    "Just popping in to say your turn is here. I'll see myself out.",
    "Turn's up! No rush. Well, maybe a little rush. A micro-rush.",
    "Your turn called. It didn't leave a message, but I think we both know what it wants.",
    "Knock knock. Who's there? Your turn. Your turn who? Your turn to play.",
    "I'm not saying your turn is lonely, but it did ask me to check on you.",
    "Plot twist: You have a turn. The plot continues when you take it.",
    "Your turn is like a fine wine. It's been sitting there. Waiting. Aging.",
    "Hey! Your turn wanted me to tell you it's ready. I'm just the messenger.",
    "Turns out (pun intended) it's your turn. I'll let you process that.",
    "Your turn has been patiently waiting. I, however, am slightly less patient.",
    "Just a little nudge. Consider this a turn-based poke.",
    "Your move, literally. The game is waiting. Calmly. So calmly.",
    "I don't want to alarm you, but there's a turn. And it's yours.",
    "Your turn is pending. Think of this as a gentle, digital elbow nudge.",
    "Hey there! The 'End Turn' button says hi. It's been a while since you visited.",
    "Civilization update: Still waiting for their favorite leader to return.",
    "Your turn awaits. No judgment here. Okay, maybe a little judgment.",
    "The game misses you. The other players... also miss you. Coincidence?",
    "Current status: Turn = Yours. Action required = Whenever you're ready. Ish.",
    "This is your regularly scheduled turn reminder. We now return you to your day.",
    "Your settlers are asking if they should just pick a spot themselves.",
    "I come bearing news: It's your turn. I also come bearing mild impatience.",
    "Your turn has been marked 'unread' for a while now. Just saying.",
    "Pssst. Hey. You. Yeah, you. Turn's ready.",
    "Your turn is giving me 'unread email from three days ago' energy.",
    "The game is open. Your turn is ready. This is not a drill. (But it's also not urgent. Yet.)",
    "Your turn is ready. Your snacks can wait. Probably. Maybe grab the snacks first, then the turn.",
    "Gentle reminder that civilizations require, at minimum, the occasional click.",
    "Your turn is here, sitting quietly like a cat waiting to be fed. The cat is your turn.",
    "Hey, your empire's GPS says you've gone offline. Mind checking in?",
    "Your turn would like to schedule a brief meeting. Estimated duration: one click.",
    "No alarms, no urgency, just a friendly note that your turn exists and would love to be played.",
    "Your turn is doing that thing where it waits politely but checks the clock a lot.",
    "Just a heads up: the turn fairy visited and left you a turn. It's still here.",
    "Your advisors have prepared a lovely presentation titled 'It Is Your Turn.' One slide.",
    "The game would like to gently remind you that it remembers your face. In a friendly way.",
    "Your turn is like a houseplant. Low maintenance, but it does need a little attention.",
    "Soft ping incoming: turn's ready, no stress, take your time, but also the turn is ready.",
    "Your civilization sends its regards and a small note that reads 'pls turn.'",
    "Hey, just checking in. The turn's fine. You're fine. Everything's fine. Turn's ready though.",
    "Your turn put on its nice shoes and everything. It's ready when you are.",
    "Friendly neighborhood reminder bot here. Your turn says hi and also 'please.'",
    "Your turn is patiently doing breathing exercises while it waits. So zen. So ready.",
    "A small bird told me it's your turn. The bird was correct. The bird is always correct.",
    "Your turn has been upgraded to 'gently waiting.' Click to upgrade it to 'completed.'",
    "Hey! Just floating by to mention the turn. The turn that is yours. The one right there.",
    "Your empire's to-do list has exactly one item, and it has your name on it.",
    "Turn status: ready. Vibe status: relaxed. Reminder status: this one.",
    "Your turn is here and it brought good vibes and mild anticipation.",
    "Just a tiny tap on the shoulder. Turn's ready whenever the mood strikes.",
    "Your settlers waved at the screen. They think you can see them. Take the turn, ease their minds.",
    "Your turn is sitting in the lobby flipping through a magazine. It'll be here.",
    "Casual update from your civ: still standing, still loyal, still waiting for one click.",
    "Your turn would like to be played, but it understands you're a busy and important person.",
    "Reminder delivered with a smile: it's your turn, and that's genuinely fine.",
    "Your turn is ready and has chosen to remain optimistic about your return.",
]

MEDIUM_INTENSITY_REMINDERS = [
    "Hey, remember that Civ game you're in? It remembers you. It's been waiting. Patiently. Unlike me.",
    "Just checking if you're still alive, because your turn certainly isn't progressing.",
    "I'm not saying you're slow, but I've seen glaciers move faster. Take your turn.",
    "Your opponents have started a betting pool on whether you'll ever finish your turn. The odds aren't great.",
    "Legend has it, if you wait long enough, the turn will play itself. Spoiler: it won't. Take your turn.",
    "The other players wanted me to tell you to hurry up. I wanted to tell you that too, but more sarcastically.",
    "Your Civ is starting to think you've abandoned them. Don't make me send a wellness check.",
    "Breaking news: Local player discovers 'taking your turn' is actually an option. More at 11.",
    "I'm starting to think you're not playing hard to get, you're just not playing at all.",
    "The game isn't going to play itself. Well, technically it could if you enabled AI, but that's not the point.",
    "Tick tock. That's not a clock, that's the sound of everyone's patience running out.",
    "Your turn has been waiting so long it's started collecting dust. Digital dust. That's how long.",
    "Your citizens are starting to ask if maybe they should just elect a new leader.",
    "Even the barbarians are wondering what's taking so long.",
    "Just one more turn? How about just ONE turn? Please?",
    "Your trade routes have expired. Your alliances have crumbled. Your turn remains unplayed.",
    "You know the 'One More Turn' button? It requires you to finish THIS turn first.",
    "Roses are red, violets are blue, your turn's been pending, what else is new?",
    "If procrastination were a tech, you'd have it fully boosted by now.",
    "Your civ has so many unemployed citizens because even THEY'RE waiting for your turn.",
    "At this point, your inaction counts as a policy decision.",
    "Your turn has entered the chat. Your turn has left the chat. Your turn is still pending.",
    "Your amenities are dropping because your citizens are bored of waiting.",
    "Sir, this is a Wendy's. Also, take your turn.",
    "Your turn has been pending so long it's developed object permanence. It knows you're avoiding it.",
    "I'd say a watched pot never boils, but your turn isn't even being watched, and it's still not happening.",
    "Your citizens started a group chat. The group chat is mostly about you. It's not flattering.",
    "Breaking: Local leader spotted doing literally anything except their turn. Sources are concerned.",
    "Your turn is collecting frequent flyer miles in the 'pending' lounge. It's about to hit Gold status.",
    "I've started to think you and the End Turn button are in a long-distance relationship. A very long distance.",
    "Your empire's morale is held together with duct tape and the faint hope you'll come back.",
    "At this point your turn has more patience than I do, and I'm a literal program.",
    "Your scouts found something incredible over the horizon. Also they found that you still haven't moved.",
    "The AI players just asked me if you're okay. They're not even being passive-aggressive. That's worse.",
    "Your turn called in a favor. The favor was me. I'm the favor. Take your turn.",
    "Your civ's national pastime is now 'waiting.' They've gotten really good at it. Concerningly good.",
    "You've ghosted your own civilization. That's a bold strategy. Let's see if it pays off. (It won't.)",
    "Your wonders are half-built and your citizens are fully done with your shenanigans.",
    "I ran the numbers and your procrastination is now statistically significant. Peer-reviewed, even.",
    "Your turn has more pending time than my last software update, and that thing took forever.",
    "Your generals drew up battle plans. Then they drew up retirement plans. They're using the retirement plans.",
    "You know what's wild? You could've taken your turn in the time it took to read this. But here we are.",
    "Your empire would like to file a missing-leader report. I told them to wait. Like you're making them wait.",
    "The barbarians left a sticky note on your city: 'Came to raid, you weren't even playing, very anticlimactic.'",
    "Your turn is so overdue the library is charging it late fees. The library is me. Pay up. With a turn.",
    "Your citizens have invented three new religions while waiting. All of them are about taking turns.",
    "I'm not mad, I'm just disappointed. And also a little mad. Mostly about the turn.",
    "Your turn has been pending longer than my will to keep being polite about it.",
    "Your diplomats negotiated a peace treaty with everyone. The terms? You take your turn. Sign here.",
    "At this rate the 'one more turn' addiction skipped you entirely. You're doing 'zero more turns.' Impressive, honestly.",
    "Your city is throwing a parade. The theme is 'Please Come Back.' Attendance is mandatory but you're not there.",
    "Your turn just asked me if this is normal. I lied and said yes. Don't make a liar out of me.",
    "You've spent more time not taking your turn than most people spend choosing a Netflix show. And that's saying something.",
    "Your empire's economy is fine, actually. Your turn-taking economy, however, is in a full recession.",
    "I've seen sloths with better turnaround time. Literal sloths. Take your turn.",
]

HIGH_INTENSITY_REMINDERS = [
    "Fun fact: entire civilizations have risen and fallen in the time you've been 'thinking' about your turn.",
    "I've sent this reminder before. I'll send it again. I have nothing but time. You, apparently, have nothing but excuses.",
    "Did you know your turn has been pending longer than some people's entire relationships? Take. Your. Turn.",
    "Gandhi has mass-produced nukes in less time than you've spent on this turn.",
    "I've seen people research the entire tech tree faster than you're taking this turn.",
    "At this rate, you'll achieve a Time Victory before you achieve 'clicking End Turn.'",
    "Your scouts have returned, aged, retired, and their grandchildren are now scouts. Still waiting.",
    "Plot twist: the real Domination Victory was the turns we waited for along the way.",
    "If turns were a wonder, yours would be the Great Wait of China.",
    "Somewhere, a Great General has earned enough points to spawn. You haven't earned enough points to click 'Next Turn.'",
    "I'm not saying you're slow, but your Civ just entered a Dark Age from lack of activity.",
    "The World Congress has convened specifically to discuss why you haven't taken your turn.",
    "Your spies have gathered intel, written reports, and retired. The intel? You still haven't moved.",
    "A settler could have founded a city, grown it to size 20, and built every wonder by now.",
    "Your opponents have researched Future Tech twelve times waiting for you.",
    "Rome wasn't built in a day, but it fell faster than you're taking this turn.",
    "The Hundred Years' War was shorter than this wait. Take your turn.",
    "Napoleon conquered Europe in less time than you've been staring at this save file.",
    "The Great Pyramid took 20 years to build. Your turn is approaching that milestone.",
    "Historians will debate what you were doing during this turn for centuries.",
    "Your turn has been pending so long, it qualifies as a UNESCO World Heritage Site.",
    "The Manhattan Project had fewer delays than your turn.",
    "I've started writing fan fiction about what your next move might be. Chapter 47 is getting interesting.",
    "The Bronze Age Collapse happened faster than this turn is progressing.",
    "If this were a real civilization, there would have been three coups by now.",
    "Alexander the Great wept, for there were no more worlds to conquer. You weep because you can't click a button.",
    "This delay is longer than the list of Henry VIII's wives. And almost as tragic.",
    "Your turn has been pending longer than the Byzantine Empire lasted. Okay, not quite. But close.",
    "I'm starting to think 'Play Your Damn Turn' was too subtle a hint.",
    "Your neighbors have forward-settled you, built wonders in your face, and converted your cities. Still waiting.",
    "The Library of Alexandria burned down. Your turn remains unplayed. One of these is a greater loss to humanity.",
    "Charlemagne united Europe. You can't unite your mouse with the End Turn button.",
    "The fall of Constantinople was faster than this. The Ottomans are judging you.",
    "Your civ is in anarchy. Not because of government change, but because nobody's at the wheel.",
    "At this pace, heat death of the universe might be a legitimate victory condition.",
    "The Founding Fathers wrote the Constitution faster than you're taking this turn. And they had to use quills.",
    "Lewis and Clark crossed the entire continent and back. You can't cross the distance to your keyboard.",
    "The transcontinental railroad was completed faster than this turn. They had to lay track through mountains.",
    "Paul Revere rode through the night to warn the colonists. I'm riding through the internet to warn you: TAKE YOUR TURN.",
    "The Louisiana Purchase doubled America's size in less time than you've been 'thinking.'",
    "We put a man on the moon in 1969 with less computing power than your phone. You can click End Turn.",
    "The Declaration of Independence was drafted, debated, and signed faster than this. John Hancock is not impressed.",
    "The Civil War lasted four years. Your turn is giving it competition.",
    "The Boston Tea Party took one night. Your turn has taken longer than brewing actual tea. In Boston Harbor.",
    "The Gold Rush moved thousands across a continent. You can't move your mouse across a desk.",
    "Prohibition lasted 13 years. This wait feels longer. And I could use a drink.",
    "D-Day was planned and executed faster than this turn. Eisenhower would be disappointed.",
    "The Cuban Missile Crisis was resolved in 13 days. We're approaching that milestone.",
    "The Hoover Dam was built during the Great Depression faster than you're playing this turn.",
    "The entire Interstate Highway System took 35 years. Your turn might beat that record.",
    "Watergate unraveled faster than your strategy appears to be forming.",
    "The Berlin Airlift delivered 2.3 million tons of supplies. You can't deliver one save file.",
    "Woodstock was three days of peace, love, and music. This has been three days of waiting for your turn.",
    "The government declassified Area 51 faster than you're taking this turn. What are YOU hiding?",
    "The March on Washington brought 250,000 people together in less time than your turn has taken.",
    "Wikipedia has been written, edited, and argued about faster than you're taking this turn.",
    "The Mars rovers Spirit and Opportunity were built, launched, and landed faster than this. Opportunity lasted 15 years. Your turn might too.",
    "SpaceX learned to land rockets on drone ships faster than you're landing this turn.",
    "The entire iPhone was designed and released faster than you're making this move. Steve Jobs is rolling in his grave.",
    "Netflix went from mailing DVDs to streaming to making movies faster than you're finishing this turn.",
    "Pluto was demoted from planet status, mourned, and memed faster than this turn is being played.",
    "The James Webb Space Telescope was delayed 14 years. Your turn is starting to feel relatable.",
    "Pokemon Go was released, went viral, and people stopped playing it faster than you're taking this turn.",
    "Tesla went from 'that might work' to mass production faster than you're clicking End Turn.",
    "The entire Bitcoin rollercoaster has happened multiple times waiting for your turn. We could've been rich. Or broke. Probably broke.",
    "Continental drift is making measurable progress. Your turn is not. The tectonic plates are embarrassed for you.",
    "The Library of Congress could catalog every book ever written before you click that button.",
    "Stonehenge was erected by people without wheels faster than you're moving your mouse with a literal wheel on it.",
    "The dinosaurs went extinct over millions of years. Your turn is testing whether that's actually the fast option.",
    "Voyager 1 left the solar system waiting for your turn. It's now in interstellar space. Your turn is still in your living room.",
    "The Suez Canal got unblocked faster than this turn. And that involved an actual stuck cargo ship.",
    "Mount Everest grew several millimeters taller during this turn. You contributed nothing to that, or anything else.",
    "The Roman Empire collapsed, was studied by historians for 1500 years, and got a dozen documentaries before you moved a unit.",
    "Halley's Comet is due back before you finish this turn. It comes every 76 years. I'm not optimistic.",
    "The pyramids were sealed shut for 4000 years and still got opened faster than your save file.",
    "Genghis Khan conquered most of the known world with horses and vibes faster than you're conquering this menu.",
    "The Black Death wiped out half of Europe in less time than your turn. Grim, but accurate, and you're still not done.",
    "The Sahara was a green oasis once. It dried into the world's largest desert waiting for you to click End Turn.",
    "The Renaissance happened. The Enlightenment happened. An entire enlightenment, and you remain un-enlightened about your turn.",
    "The Wright brothers invented flight, and aviation advanced to supersonic jets, while you taxied on the runway of this turn.",
    "The Cold War thawed faster than your strategic decision-making. Even the Berlin Wall gave up before you did.",
    "Pangaea broke apart into seven continents in the time you've spent contemplating where to move one settler.",
    "The entire human genome was sequenced faster than you're sequencing your next three moves.",
    "Light from distant stars has traveled millions of years to reach us, only to find you still haven't taken your turn.",
    "The Great Barrier Reef formed over thousands of years and is dying faster than this turn is progressing. Both are tragedies.",
    "Beethoven went deaf and still composed nine symphonies before you composed a single coherent strategy.",
    "The Ottoman Empire rose, ruled for 600 years, and fell. Your turn outlasted all of it.",
    "Antarctica was a tropical forest once. It froze into a mile-thick ice sheet waiting for your move.",
    "The printing press, the internet, and AI were all invented to spread information faster, and yet here I am, still waiting on you.",
    "Magellan's crew circumnavigated the globe and most of them died doing it, faster than you're circling this decision.",
    "The Mariana Trench is the deepest point on Earth. Your turn's pending time is approaching it.",
    "Egypt built the Aswan Dam, relocated entire temples stone by stone, and you can't relocate your cursor.",
    "The plot of every soap opera ever combined has fewer unresolved cliffhangers than this turn.",
    "Glaciers carved entire valleys during the last ice age faster than you're carving out time for this turn.",
    "The fall of the Soviet Union, the rise of the internet, and the entire smartphone era all happened. Your turn predates all of it now.",
    "A redwood tree grew from a seed to 300 feet tall, lived 2000 years, and was made into a coffee table before you ended your turn.",
    "Even the heat death of the universe sent its RSVP. It's running late, but it'll still beat your turn.",
]


def get_reminder_by_intensity(hours_waiting: float) -> str:
    """Select a reminder message based on how long the turn has been waiting."""
    intensity_config = CONFIG.get("reminderIntensity", {})
    low_max = intensity_config.get("lowMaxHours", 3)
    medium_max = intensity_config.get("mediumMaxHours", 8)
    
    if hours_waiting <= low_max:
        return random.choice(LOW_INTENSITY_REMINDERS)
    elif hours_waiting <= medium_max:
        return random.choice(MEDIUM_INTENSITY_REMINDERS)
    else:
        return random.choice(HIGH_INTENSITY_REMINDERS)

# Required fields that PYDT must send
REQUIRED_FIELDS = ["gameName", "userName", "round"]


def get_storage_connection_string() -> str:
    """Get the Azure Storage connection string."""
    return os.environ.get("AzureWebJobsStorage", "")


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


def update_turn_tracking(game_name: str, game_id: str, steam_username: str, steam_id: str, discord_user_id: str, round_num: str):
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
            "steamId": steam_id or "",
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
                "steamId": req.form.get("steamId"),
                "round": req.form.get("round"),
                "civName": req.form.get("civName"),
                "leaderName": req.form.get("leaderName"),
                "gameId": req.form.get("gameId"),
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
        steam_id = data.get("steamId", "")  # Steam64 ID from PYDT webhook
        round_num = data.get("round", "?")
        civ_name = data.get("civName", "Unknown Civ")
        leader_name = data.get("leaderName", "Unknown Leader")
        game_id = data.get("gameId", "")  # PYDT may send this

        logging.info(f"Turn notification: {steam_username} (Steam64: {steam_id}) in {game_name} (Round {round_num})")

        # Load user mapping from environment variable (steam64Id -> discordId)
        user_mapping_json = os.environ.get("USER_MAPPING", "{}")
        try:
            user_mapping = json.loads(user_mapping_json)
        except json.JSONDecodeError:
            logging.error("Failed to parse USER_MAPPING JSON")
            user_mapping = {}

        # Look up Discord user ID by Steam64 ID
        discord_user_id = user_mapping.get(steam_id, "") if steam_id else ""

        # Track this turn in storage for reminders
        update_turn_tracking(game_name, game_id, steam_username, steam_id, discord_user_id, round_num)

        # Format the message
        if discord_user_id:
            message = f"<@{discord_user_id}> - Your turn in \"{game_name}\" (Round {round_num}) as {leader_name} of {civ_name}"
        else:
            # Fallback to PYDT username when Discord ID mapping is missing
            logging.warning(f"No Discord ID configured for Steam64 ID: {steam_id} ({steam_username})")
            message = (
                f"**{steam_username}** - Your turn in \"{game_name}\" (Round {round_num}) as {leader_name} of {civ_name}\n\n"
                f"⚠️ *No Discord mapping configured for this player.*"
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
        
        # Load user mapping for fallback lookups (steam64Id -> discordId)
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
                steam_id = entity.get("steamId", "")
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
                    reminder_interval = CONFIG.get("reminderIntervalHours", 2)
                    if hours_since_last_reminder < reminder_interval:
                        logging.info(f"Skipping reminder for {game_name} - only {hours_since_last_reminder:.1f} hours since last reminder (interval: {reminder_interval}h)")
                        continue

                # Pick a reminder based on intensity level
                snark = get_reminder_by_intensity(hours_waiting)

                # Format the reminder message
                if discord_user_id:
                    message = f"⏰ <@{discord_user_id}> - Reminder #{reminder_count + 1}: Your turn in \"{game_name}\" (Round {round_num}) has been waiting for {hours_waiting:.1f} hours.\n\n{snark}"
                else:
                    # Try to look up the Discord ID again by Steam64 ID in case mapping was updated
                    discord_user_id = user_mapping.get(steam_id, "") if steam_id else ""
                    if discord_user_id:
                        message = f"⏰ <@{discord_user_id}> - Reminder #{reminder_count + 1}: Your turn in \"{game_name}\" (Round {round_num}) has been waiting for {hours_waiting:.1f} hours.\n\n{snark}"
                    else:
                        # Fallback to PYDT username when Discord ID mapping is missing
                        message = f"⏰ **{steam_username}** - Reminder #{reminder_count + 1}: Your turn in \"{game_name}\" (Round {round_num}) has been waiting for {hours_waiting:.1f} hours.\n\n{snark}\n\n⚠️ *No Discord mapping configured for this player.*"
                
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


def _load_user_mapping() -> dict:
    """Load the Steam64 ID -> Discord ID mapping from the environment."""
    raw = os.environ.get("USER_MAPPING", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logging.error("Failed to parse USER_MAPPING JSON")
        return {}


def get_tracked_game_ids() -> list:
    """
    Determine which PYDT game IDs to include in the weekly status report.

    Priority:
      1. Explicit game IDs in config (weeklyStatus.gameIds).
      2. Game IDs recorded in the active games table.
      3. Auto-discovery from the mapped players' active games (fallback).
    """
    ids = []
    seen = set()

    def add(game_id):
        if game_id and game_id not in seen:
            seen.add(game_id)
            ids.append(game_id)

    ws_cfg = CONFIG.get("weeklyStatus", {})

    for game_id in ws_cfg.get("gameIds", []) or []:
        add(game_id)

    try:
        table_client = get_table_client()
        for entity in table_client.list_entities():
            add(entity.get("gameId"))
    except Exception as exc:
        logging.warning(f"Could not read tracked games from table: {exc}")

    if not ids and ws_cfg.get("autoDiscoverGames", True):
        user_mapping = _load_user_mapping()
        if user_mapping:
            for game_id in weekly.discover_game_ids_for_steam_ids(list(user_mapping.keys())):
                add(game_id)

    return ids


def generate_weekly_status_messages(now=None, explicit_game_ids=None) -> list:
    """Build the weekly status report(s). Does not post anything to Discord."""
    now = now or datetime.now(timezone.utc)
    user_mapping = _load_user_mapping()
    game_ids = explicit_game_ids if explicit_game_ids else get_tracked_game_ids()

    reports = []
    for game_id in game_ids:
        try:
            reports.append(weekly.build_status_for_game(game_id, now, user_mapping, CONFIG))
        except Exception as exc:
            logging.error(f"Failed to build weekly status for game {game_id}: {exc}")
    return reports


@app.timer_trigger(schedule="0 0 22,23 * * 5", arg_name="timer", run_on_startup=False)
def weekly_status_timer(timer: func.TimerRequest) -> None:
    """
    Post a weekly status report every Friday at 3:00 PM Pacific time.

    The schedule fires at 22:00 and 23:00 UTC on Fridays. Exactly one of those
    is 15:00 Pacific depending on daylight saving time, so we compute the actual
    Pacific time and only proceed for the 3 PM slot.
    """
    ws_cfg = CONFIG.get("weeklyStatus", {})
    if not ws_cfg.get("enabled", True):
        logging.info("Weekly status is disabled in config; skipping.")
        return

    now_utc = datetime.now(timezone.utc)
    now_pacific = now_utc.astimezone(weekly.PACIFIC_TZ)
    target_hour = int(ws_cfg.get("postHourPacific", 15))
    target_weekday = int(ws_cfg.get("postWeekday", 4))  # Mon=0 ... Fri=4 ... Sun=6

    if now_pacific.weekday() != target_weekday or now_pacific.hour != target_hour:
        logging.info(
            f"Weekly status: not the scheduled slot (Pacific now "
            f"{now_pacific:%A %H:%M}); skipping."
        )
        return

    discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not discord_webhook_url:
        logging.error("DISCORD_WEBHOOK_URL not configured - cannot post weekly status")
        return

    reports = generate_weekly_status_messages(now_utc)
    if not reports:
        logging.warning("Weekly status: no games found to report on.")
        return

    posted = 0
    for report in reports:
        try:
            response = requests.post(
                discord_webhook_url,
                json={
                    "content": report["message"],
                    "allowed_mentions": {"parse": ["everyone", "users", "roles"]},
                },
                timeout=10,
            )
            if response.status_code == 204:
                posted += 1
                logging.info(f"Posted weekly status for '{report['displayName']}'")
            else:
                logging.error(
                    f"Failed to post weekly status for '{report['displayName']}': "
                    f"{response.status_code} - {response.text}"
                )
        except requests.RequestException as exc:
            logging.error(f"Error posting weekly status for '{report['displayName']}': {exc}")

    logging.info(f"Weekly status job complete. Posted {posted} report(s).")


@app.route("weekly-status-preview", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def weekly_status_preview(req: func.HttpRequest) -> func.HttpResponse:
    """
    Return the weekly status message(s) as plain text WITHOUT posting to Discord.

    Optional query parameter: ?gameId=<id> to preview a specific game.
    Useful for verifying the report before relying on the Friday auto-post.
    """
    try:
        game_id = req.params.get("gameId")
        explicit = [game_id] if game_id else None
        reports = generate_weekly_status_messages(explicit_game_ids=explicit)

        if not reports:
            return func.HttpResponse(
                "No games found to report on. Set weeklyStatus.gameIds in config.json "
                "or make sure games are being tracked.",
                status_code=200,
                mimetype="text/plain; charset=utf-8",
            )

        body = "\n\n========================================\n\n".join(
            report["message"] for report in reports
        )
        return func.HttpResponse(body, status_code=200, mimetype="text/plain; charset=utf-8")
    except Exception as exc:
        logging.error(f"Failed to generate weekly status preview: {exc}")
        return func.HttpResponse(
            json.dumps({"error": str(exc)}),
            status_code=500,
            mimetype="application/json",
        )
