import os
import dotenv
from datetime import datetime, timedelta
from mysql.connector import connect


dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
dotenv.load_dotenv(dotenv_path)
# Create the NewsBot Class
class NewsBot:
    # The constructor for the class. It takes the channel name as the a
    # parameter and then sets it as an instance variable
    def __init__(self, channel):
        self.channel = channel

    def _check_url_exists(self, lookup_url, lookup_channelId):
        conn = connect(
            user=os.environ.get("NEWSBOT_MYSQL_USER"),
            password=os.environ.get("NEWSBOT_MYSQL_PASSWORD"),
            host=os.environ.get("NEWSBOT_MYSQL_HOST"),
            database=os.environ.get("NEWSBOT_MYSQL_DB"),
        )
        cursor = conn.cursor()
        cursor.callproc("get_url_info", (lookup_url, lookup_channelId))
        for result in cursor.stored_results():
            urlExists = result.fetchone()
        cursor.close()
        conn.close()
        if urlExists:
            return urlExists
        else:
            return False

    # Attempt to add a news URL item if it has yet to be added to
    def _add_news(self, channel, message_id, timestamp, mention_user,
                  url, desc):
        urlExists = self._check_url_exists(url, channel)
        if urlExists:
            text = "This URL is a duplicate. You have been :spoon: " + \
                   "_*SCOOPED*_ by <@" + \
                   urlExists[1] + \
                   "> on " + \
                   datetime.fromtimestamp(float(urlExists[0]))\
                       .strftime("%Y-%m-%d %H:%M:%S") + \
                   "!"
        else:
            conn = connect(
                user=os.environ.get("NEWSBOT_MYSQL_USER"),
                password=os.environ.get("NEWSBOT_MYSQL_PASSWORD"),
                host=os.environ.get("NEWSBOT_MYSQL_HOST"),
                database=os.environ.get("NEWSBOT_MYSQL_DB"),
            )
            cursor = conn.cursor()
            cursor.callproc("add_news", (message_id, channel, timestamp,
                                         mention_user, url, desc))
            conn.commit()
            text = url + " has been added to the <#" + channel + \
                   "> channel list."
            cursor.close()
            conn.close()

        return text

    # Get the popular news articles since x number of days by tags
    def get_messages_list(self, search_start, tags):
        today = datetime.now()
        day_delta = timedelta(days = search_start)
        start_timestamp = (today - day_delta).timestamp()
        msgs = []
        if len(tags) == 0:
            conn = connect(
                user=os.environ.get("NEWSBOT_MYSQL_USER"),
                password=os.environ.get("NEWSBOT_MYSQL_PASSWORD"),
                host=os.environ.get("NEWSBOT_MYSQL_HOST"),
                database=os.environ.get("NEWSBOT_MYSQL_DB"),
            )
            cursor = conn.cursor()
            cursor.callproc("get_urls_since_by_tag", (self.channel, start_timestamp, '%%'))
            for result in cursor.stored_results():
                msgs = [(row[0], row[1], row[2], row[3], row[4]) for row in result.fetchall()]
            cursor.close()
            conn.close()
        elif len(tags) > 0:
            conn = connect(
                user=os.environ.get("NEWSBOT_MYSQL_USER"),
                password=os.environ.get("NEWSBOT_MYSQL_PASSWORD"),
                host=os.environ.get("NEWSBOT_MYSQL_HOST"),
                database=os.environ.get("NEWSBOT_MYSQL_DB"),
            )
            cursor = conn.cursor()
            for tag in tags:
                cursor.callproc("get_urls_since_by_tag", (self.channel, start_timestamp, '%' + tag + '%'))
                for result in cursor.stored_results():
                    msgs.extend([(row[0], row[1], row[2], row[3], row[4]) for row in result.fetchall()])
            cursor.close()
            conn.close()

        return msgs

    # Select the most popular news item given a list of messages
    def select_popular_news(self, msgs, search_start, tags):
        top_interactions = -1
        top_replies = -1
        top_reactions = -1
        top_interactions_ts = ""
        top_interactions_poster = ""
        top_interactions_url = ""
        interactions_tie = False
        for msg in msgs:
            reactions = 0
            replies = 0
            if msgs[msg]["message"]["client_msg_id"] == msg[0] and \
                "reply_count" in msgs[msg]["message"]:
                replies = msgs[msg]["message"]["reply_count"]
            if "reactions" in msgs[msg]["message"] and \
                len(msgs[msg]["message"]["reactions"]) > 0:
                for reaction in msgs[msg]["message"]["reactions"]:
                    if "count" in reaction:
                        reactions += reaction["count"]
            interactions = reactions + replies
            if interactions > top_interactions:
                top_interactions = interactions
                top_replies = replies
                top_reactions = reactions
                top_interactions_ts = msg[1]
                top_interactions_poster = msg[2]
                top_interactions_url = msg[3]
            elif interactions == top_interactions:
                if replies > top_replies:
                    top_interactions = interactions
                    top_replies = replies
                    top_reactions = reactions
                    top_interactions_ts = msg[1]
                    top_interactions_poster = msg[2]
                    top_interactions_url = msg[3]
                elif replies == top_replies and top_interactions > 0:
                    interactions_tie = True
        response_msg = "The most popular article posted to the <#" + \
                       self.channel + \
                       "> channel in the past " + \
                       str(search_start) + \
                       " days "
        if len(tags) > 0:
            response_msg = response_msg + \
                           "with the tag(s): " + \
                           ", ".join(tags) + \
                           " "
        response_msg = response_msg + \
                       "was posted on " + \
                       datetime.fromtimestamp(float(top_interactions_ts)).strftime("%Y-%m-%d") + \
                       " by <@" + \
                       top_interactions_poster + \
                       ">. You can read the article again here: " + \
                       top_interactions_url
        if interactions_tie:
            response_msg = "There was a tie in popularity. The most recently posted article will be " + \
                           "returned.\n" + response_msg

        return response_msg, top_interactions_url

    # Craft and return the payload for the add_news event
    def create_addnews_message(self, message_id, timestamp,
                               mention_user, url, desc):
        return {
            "channel": self.channel,
            "text": self._add_news(self.channel, message_id, timestamp,
                                   mention_user, url, desc),
        }
