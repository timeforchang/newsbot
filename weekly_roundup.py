import os
import requests
import dotenv
from slack import WebClient
from slack.errors import SlackApiError
from mysql.connector import connect
from newsbot import NewsBot


dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
dotenv.load_dotenv(dotenv_path)

unauthed_error_types = [
    "as_user_not_supported",
    "channel_not_found",
    "ekm_access_denied",
    "is_archived",
    "messages_tab_disabled",
    "not_in_channel",
    "restricted_action",
    "restricted_action_non_threadable_channel",
    "restricted_action_read_only_channel",
    "restricted_action_thread_locked",
    "restricted_action_thread_only_channel",
    "team_access_not_granted",
    "access_denied",
    "account_inactive",
    "enterprise_is_restricted",
    "invalid_auth",
    "missing_scope",
    "not_allowed_token_type",
    "not_authed",
    "no_permission",
    "org_login_required",
    "accesslimited"
]

def get_summary(url):
    smmry_api = "https://api.smmry.com/"
    smmry_params = {
        'SM_API_KEY': os.environ.get("SMMRY_API_KEY"),
        'SM_LENGTH': 5,
        'SM_URL': url
    }

    smmry_response = requests.get(smmry_api, params=smmry_params)
    if smmry_response.status_code == 200:
        title = None
        summary = None
        smmry_json = smmry_response.json()
        if "sm_api_content" in smmry_json:
            summary = smmry_json.get("sm_api_content", "")
        if "sm_api_title" in smmry_json:
            title= smmry_json.get("sm_api_title", "")
        return title, summary
    return None, None

def craft_message(slack_web_client, channel, msgs):
    msgs_reaction_dict = {}
    for msg in msgs:
        try:
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
        except:
            print("* Could not find message " + str(msg) + "in channel " + str(channel))
            continue

    news_bot = NewsBot(channel)
    not_needed, url = news_bot.select_popular_news(msgs_reaction_dict, 7, [])

    weeklyroundup = [{
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": ":rotating_light: Weekly NewsBot Roundup :rotating_light:",
            "emoji": True
        }
    },
    {
        "type": "divider"
    }]

    title, summary = get_summary(url)
    if title and summary:
        weeklyroundup_summary = [{
            "type": "section",
            "text": {
            "type": "mrkdwn",
                "text": "*" + title + "*"
            }
        },
        {
            "type": "section",
            "text": {
            "type": "mrkdwn",
                "text": summary + "\n\n" + "Read more <" + url + "|here>",
                "unfurl_links": false
            }
        }]
    elif title and not summary:
        weeklyroundup_summary = [{
            "type": "section",
            "text": {
            "type": "mrkdwn",
                "text": "*" + title + "*\nRead more <" + url + "|here>",
                "unfurl_links": false
            }
        }]
    else:
       weeklyroundup_summary = [{
            "type": "section",
            "text": {
            "type": "mrkdwn",
                "text": summary + "\n\n" + "Read more <" + url + "|here>",
                "unfurl_links": false
            }
        }]

    weeklyroundup.extend(weeklyroundup_summary)

    other_urls = []
    for msg in msgs:
        if msg[3] != url:
            other_urls.append("• <" + msg[3] + "|" + msg[4] + ">")

    if len(other_urls) > 0:
        weeklyroundup_otherurls = [{
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
            "type": "mrkdwn",
                "text": "*Some other articles from the past week you may have missed:*\n" + \
                        "\n".join(other_urls),
                "unfurl_links": false
            }
        }]
        weeklyroundup.extend(weeklyroundup_otherurls)

    message = {
        "channel": channel,
        "blocks": weeklyroundup
    }

    return message

def send_weekly_roundup():
    teams_and_channels = []
    conn = connect(
        user=os.environ.get("NEWSBOT_MYSQL_USER"),
        password=os.environ.get("NEWSBOT_MYSQL_PASSWORD"),
        host=os.environ.get("NEWSBOT_MYSQL_HOST"),
        database=os.environ.get("NEWSBOT_MYSQL_DB"),
    )
    cursor = conn.cursor()
    cursor.callproc("get_channels", )
    for result in cursor.stored_results():
        teams_and_channels = [(row[0], row[1]) for row in result.fetchall()]
    print(teams_and_channels)
    cursor.close()
    conn.close()

    for team_and_channel in teams_and_channels:
        team = team_and_channel[0]
        channel = team_and_channel[1]
        news_bot = NewsBot(channel)
        msgs = news_bot.get_messages_list(7, [])

        if len(msgs) == 0:
            continue
        else:
            try:
                slack_bot_token = NewsBot.get_oauth_token(team)
                if slack_bot_token != "":
                    # Initialize a Web API client
                    slack_web_client = WebClient(token=slack_bot_token)
                    to_post = craft_message(slack_web_client, channel, msgs)
                    slack_web_client.chat_postMessage(**to_post)
                else:
                    print(" * Following team did not install app: " + team)
                    continue
            except SlackApiError as e:
                response = e.response
                if response.get("error", "") in unauthed_error_types:
                    print(" * No longer authorized to request info for channel " + channel + ", deleting channel and URLs")
                    news_bot.delete_newsbot()
                else:
                    print(" * Something went wrong with the Slack API: " + str(response))
                continue

if __name__ == "__main__":
    send_weekly_roundup()
