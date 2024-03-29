import os
import logging
import hmac
import dotenv
from requests import post
from flask import Flask, request, render_template
from slack import WebClient
from slackeventsapi import SlackEventAdapter
from newsbot import NewsBot
from datetime import datetime

# Initialize a Flask app to host the events adapter
app = Flask(__name__)
# Create an events adapter and register it to an endpoint in the slack app for event injestion.
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
dotenv.load_dotenv(dotenv_path)
slack_events_adapter = SlackEventAdapter(os.environ.get("SLACK_EVENTS_TOKEN"), "/slack/events", app)

command_helptext = """
```
Usage: /popular_news num_days hashtags
A command to search for the most popular news articles posted in the current channel.
Popularity is evaluated by overall number of interactions (reactions, replies, etc.)

Arguments:
num_days    optional    number of days back to search for most popular news links (default: 7)
hashtags    optional    comma-separated list of hashtags to search with no spaces (i.e. #breach,#ransomware)
```
"""

def add_news(team, channel, message_id, timestamp, mention_user, url, desc):
    """Craft the NewsBot, create the message, and send the message to the channel
    """
    # Create a new CoinBot
    news_bot = NewsBot(channel)

    # Get the add news message payload
    message = news_bot.create_addnews_message(message_id, team, timestamp,
                                              mention_user, url, desc)

    if message['text']:
        slack_bot_token = NewsBot.get_oauth_token(team)
        if slack_bot_token:
            # Initialize a Web API client
            slack_web_client = WebClient(token=slack_bot_token)

            # Post a scooped message in Slack if its a duplicate
            slack_web_client.chat_postMessage(**message)
    else:
        return

def post_error_message(team, channel):
    """Send error message in the channel
    """
    text = "Your message should have a URL and a caption (e.g. `@NewsBot http://www.example.com this " + \
           "is an example url \#example`)."

    message = {
        "channel": channel,
        "text": text
    }

    slack_bot_token = NewsBot.get_oauth_token(team)
    if slack_bot_token != "":
        # Initialize a Web API client
        slack_web_client = WebClient(token=slack_bot_token)

        # Post the onboarding message in Slack
        slack_web_client.chat_postMessage(**message)

def get_popular_news(command_body):
    search_start = 7
    text = ""
    channel = ""
    team = ""
    args = []
    tags = []
    tags_after_space = False
    search_start_set = False
    tags_set = False
    return_message = ""

    if command_body:
        if "channel_id" in command_body:
            channel = command_body.get("channel_id", "")
        if "text" in command_body:
            text = command_body.get("text", "")
        if "team_id" in command_body:
            team = command_body.get("team_id", "")
    if not channel or channel == "" or not team or team == "":
        return "Something went wrong with the Slack API. Please try again later."

    if text != "":
        args = text.split(" ")
        if len(args) >= 1:
            for arg in args:
                if arg.isdigit() and not search_start_set:
                    if int(arg) > 0:
                        search_start = int(arg)
                    else:
                        return "Please submit a positive number of days. " + command_helptext
                    search_start_set = True
                elif arg == "help":
                    return command_helptext
                elif "#" in arg and not tags_set:
                    arg_tags = arg.split(",")
                    for tag in arg_tags:
                        if "#" in tag and len(tag.split("#")[1]) > 0:
                            tags.append(tag)
                    tags_set = True
        if len(args) > 2 or \
            (not search_start_set and len(args) > 1):
            hash_count = 0
            for arg in args:
                if "#" in arg:
                    hash_count += 1
            if hash_count > 1:
                 tags_after_space = True

    if tags_set and tags_after_space:
        return_message = return_message + "It also seems like you added extra tags after a " + \
                                          "space in the command arguments, but these tags will " + \
                                          "not be processed. Use the `/popular_news help` command " + \
                                          "for more info. "
    if not tags_set and len(args) > 0 and not search_start_set:
        return_message = return_message + "It seems you may have provided hashtags but they are not " + \
                                          "formatted properly. I will return the most popular " + \
                                          "articles from the past week by default. Use the `" + \
                                          "/popular_news help` command for more info. "

    # Create a new NewsBot
    news_bot = NewsBot(channel)

    slack_bot_token = NewsBot.get_oauth_token(team)
    if slack_bot_token != "":
        # Initialize a Web API client
        slack_web_client = WebClient(token=slack_bot_token)

        # Get the onboarding message payload
        msgs = news_bot.get_messages_list(search_start, tags)
        if len(msgs) == 0:
            return "No messages were found within the time range and the specified tags."

        msgs_reaction_dict = {}
        for msg in msgs:
            reactions_response = slack_web_client.reactions_get(channel=channel,
                                                                timestamp=msg[1],
                                                                full=True)
            reactions_response = reactions_response.data
            if "ok" in reactions_response and \
                reactions_response["ok"] == True and \
                "type" in reactions_response and \
                reactions_response["type"] == "message" and \
                "message" in reactions_response:
                msgs_reaction_dict[msg] = reactions_response

        message, url = news_bot.select_popular_news(msgs_reaction_dict,
                                                    search_start, tags)

        return return_message + message
    else:
        return

def newsbot_delete_channel(channel_id):
    # Create a new NewsBot
    news_bot = NewsBot(channel_id)

    news_bot.delete_channel()

    print(" * Newsbot deleted news for channel " + channel_id)
    return

def newsbot_uninstall_app(team_id):
    NewsBot.uninstall_app(team_id)

    print(" * Newsbot uninstalled for team " + team_id)
    return

# When a 'message' event is detected by the events adapter, forward that payload
# to this function.
@slack_events_adapter.on("app_mention")
def mention(payload):
    """Parse the message event and handle the mention
    """
    # Check and see if the message was well-formatted
    # If so, add news to the database
    msg_id = ""
    timestamp = ""
    mention_user = ""
    url = ""
    desc = ""
    channel = ""
    team = ""

    event = payload.get("event", {})

    if event:
        msg_id = event.get("client_msg_id", "")
        timestamp = event.get("ts", "")
        mention_user = event.get("user", "")
        channel = event.get("channel", "")
        team = event.get("team", "")
        if "blocks" in event and len(event["blocks"]) > 0:
            for block in event["blocks"]:
                if "type" in block and \
                    block["type"] == "rich_text" and \
                    "elements" in block and \
                    len(block["elements"]) > 0:
                    for element in block["elements"]:
                        if "type" in element and \
                            element["type"] == "rich_text_section" and \
                            "elements" in element and \
                            len(element["elements"]) > 0:
                            for sub_element in element["elements"]:
                                if "type" in sub_element and \
                                    sub_element["type"] == "link" and \
                                    len(sub_element.get("url", "")) > len(url):
                                    url = sub_element.get("url", "")
                                elif "type" in sub_element and \
                                    sub_element["type"] == "text":
                                    desc = desc + sub_element.get("text", "")\
                                               .lstrip().rstrip()
                            break

    if msg_id != "" and \
        timestamp != "" and \
        mention_user != "" and \
        url != "" and \
        desc != "" and \
        channel != "" and \
        team != "":
        # Execute the add_news function and send the results of
        # attempt to add news to the channel
        return add_news(team, channel, msg_id, timestamp, mention_user, url, desc)
    elif team:
        return post_error_message(team, channel)

@slack_events_adapter.on("channel_deleted")
def channel_deleted(payload):
    channel = ""

    event = payload.get("event", {})
    if event:
        channel = event.get("channel", "")

    if channel != "":
        newsbot_delete_channel(channel)
    return

@slack_events_adapter.on("tokens_revoked")
def app_uninstalled(payload):
    team = ""

    event = payload.get("event", {})
    if event:
        team = event.get("team_id", "")

    if team != "":
        newsbot_uninstall_app(team)
    return

@app.route('/slack/slash_commands/popular_news', methods=['POST'])
def command_popular_news():
    # First verify the request from Slack
    slack_signing_secret = os.environ.get("SLACK_EVENTS_TOKEN")
    request_body_str = request.get_data().decode()

    timestamp = request.headers['X-Slack-Request-Timestamp']
    if abs(datetime.now().timestamp() - float(timestamp)) > 60 * 5:
        # The request timestamp is more than five minutes from local time.
        # It could be a replay attack, so let's ignore it.
        return

    sig_basestring = 'v0:' + timestamp + ':' + request_body_str
    calculated_sig = 'v0=' + hmac.new(key=bytes(bytearray(slack_signing_secret,
                                                          encoding='utf-8')),
                                      msg=sig_basestring.encode('utf-8'),
                                      digestmod='sha256').hexdigest()
    slack_signature = request.headers['X-Slack-Signature']

    if hmac.compare_digest(calculated_sig, slack_signature):
        # request is now confirmed to be from Slack!
        request_body_dict = request.form.to_dict()
        response_message = get_popular_news(request_body_dict)
        return(response_message)
    else:
        return

@app.route('/install', methods=['GET'])
def install_app():
    return render_template('install.html')

@app.route('/oauth', methods=['GET'])
def oauth_flow():
    args = request.args
    if "code" in args:
        code = args.get("code", "")
        client_id = os.environ.get("SLACK_CLIENT_ID")
        client_secret =  os.environ.get("SLACK_CLIENT_SECRET")
        url = "https://slack.com/api/oauth.v2.access"
        post_args = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret
        }

        response = post(url, data=post_args)
        if response.json()["ok"]:
            NewsBot.register_oauth_token(response.json())
            return "Successfully installed app to your Slack team!", 200
        else:
            return "Something went wrong with OAuth", 500
    else:
        return "Bad Request", 400

if __name__ == "__main__":
    # Create the logging object
    logger = logging.getLogger()

    # Set the log level to DEBUG. This will increase verbosity of logging messages
    logger.setLevel(logging.DEBUG)

    # Add the StreamHandler as a logging handler
    logger.addHandler(logging.StreamHandler())

    # Run our app on our externally facing IP address on port 3000 instead of
    # running it on localhost, which is traditional for development.
    app.run(host='0.0.0.0', port=3000)
