import json
import string
from datetime import datetime
from pathlib import Path
from queue import Queue
from secrets import choice
from threading import Thread
from time import sleep, time
from traceback import print_exc, format_exc

from dateutil.parser import parse as parse_datetime
from requests import Session, post
from requests.exceptions import Timeout

from utils import db_connect

ENDPOINT = "https://discordapp.com/api/v6"


class LoginError(Exception):
    pass


def user_login(email, password, proxies=None):
    data = {
        "email": email,
        "password": password
    }
    headers = {
        'Content-Type': 'application/json'
    }
    r = post(f'{ENDPOINT}/auth/login', json=data, headers=headers, proxies=proxies)
    if r.ok:
        return r.json()
    else:
        raise LoginError(f"Login as user '{email}' failed")


def get_messages_before(s, db, channel_id, msg_id):
    while True:
        try:
            resp = s.get(f"{ENDPOINT}/channels/{channel_id}/messages", params={"before": msg_id}, timeout=10)
        except Timeout:
            db.logs.insert_one({"type": "timeout_msg", "msg_id": msg_id, "timestamp": time()})
            pass
        except Exception as e:
            db.logs.insert_one({"type": "exception_msg", "msg_id": msg_id, "exception": repr(e), "traceback": format_exc(), "timestamp": time()})
            resp = None
            break
        else:
            break
    if not resp or not resp.ok:
        db.logs.insert_one({"type": "fail_msg", "msg_id": msg_id, "data": repr(resp.content) if resp else "<EMPTY>", "status_code": resp.status_code,
                            "timestamp": time()})
        return None, None
    messages = resp.json()
    if messages:
        return messages, min(messages, key=lambda x: parse_datetime(x["timestamp"]))["id"]
    else:
        return [], None


def get_random_string(length):
    chars = string.ascii_letters
    return "".join(choice(chars) for _ in range(length))


def prepare_user(user_obj):
    return {k: v for k, v in user_obj.items() if k in ["id", "username", "email", "avatar", "discriminator"]}


def prepare_message(message_obj):
    ret = {k: v for k, v in message_obj.items() if k in ["id", "content", "type", "channel_id", "pinned", "attachments", "embeds"]}
    ret["timestamp"] = parse_datetime(message_obj["timestamp"])
    ret["author"] = prepare_user(message_obj["author"])
    edited_timestamp = message_obj.get("edited_timestamp", None)
    if edited_timestamp:
        ret["edited_timestamp"] = parse_datetime(edited_timestamp)
    return ret


def create_session(config):
    s = Session()
    s.headers.update({"Authorization": config['token']['s']})
    s.proxies.update(config.get("proxies"))
    return s


class AttachmentFetcher(Thread):
    def __init__(self, db, queue, config):
        super().__init__(daemon=True)
        self.db, self.tasks, self.config = db, queue, config
        self.session = create_session(config)
        self.session.headers.pop("Authorization")  # Won't work with the Authorization header present
        self.root = Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()

    def run(self):
        while True:
            attachment = self.tasks.get()
            find_result = self.db.attachments.find_one({"id": attachment["id"]})
            if find_result and "local_filename" in find_result and (self.root / find_result["local_filename"]).exists():
                print(f"Existed {find_result['id']}")
                continue
            print(attachment)
            try:
                if 'url' in attachment and 'filename' in attachment:
                    local_filename = get_random_string(20) + Path(attachment["filename"]).suffix
                    with open(self.root / local_filename, "wb") as f:
                        f.write(self.session.get(attachment["url"], timeout=10).content)
                    attachment["local_filename"] = local_filename
                    self.db.attachments.insert_one(attachment)
                else:
                    print("UNRECOGNIZED", attachment)
                    self.db.logs.insert_one({"type": "unknown_type", "data": attachment, "timestamp": time()})
            except Exception as e:
                print(e)
                print_exc()
                self.db.logs.insert_one({"type": "attachment_fail", "exception": repr(e), "traceback": format_exc(), "timestamp": time()})
                self.tasks.put(attachment)
            else:
                self.tasks.task_done()


def get_channel_info(s, channel_id):
    chan = s.get(f"{ENDPOINT}/channels/{channel_id}").json()
    chan["timestamp"] = datetime.utcnow()
    return chan


def get_server_info(s, server_id):
    server = s.get(f"{ENDPOINT}/guilds/{server_id}").json()
    server["timestamp"] = datetime.utcnow()
    return server


class ChannelFetcher(Thread):
    def __init__(self, db, queue, msg_id, config, channel_id):
        super().__init__()
        self.db, self.queue, self.msg_id, self.config, self.channel_id = db, queue, msg_id, config, channel_id
        self.session = create_session(config)

    def run(self):
        print(f"Started fetching {self.channel_id}")
        msg_id = self.msg_id
        while True:
            msg_list, new_msg_id = get_messages_before(self.session, self.db, self.channel_id, msg_id)
            if not new_msg_id:  # get_messages_before(...) still returns a new msg_id if there's only one message left in the chat history.
                break
            visited = True
            for msg in msg_list:
                if self.db.messages.find_one({"id": msg["id"]}):
                    continue
                else:
                    visited = False
                if not self.db.users.find_one({"id": msg["author"]["id"], "discriminator": msg["author"]["discriminator"]}):
                    self.db.users.find_one_and_delete({"id": msg["author"]["id"], "imported": True})
                    self.db.users.insert(msg["author"])
                self.db.messages.insert_one(prepare_message(msg))
                if msg["attachments"]:
                    print(f"\033[0;37m{msg['content']}\033[00m", f"\033[0;36m{msg['author']['username']}\033[00m", parse_datetime(msg["timestamp"]),
                          msg["attachments"])
                    for item in msg["attachments"]:
                        self.queue.put(item)
            if visited:
                print("All visited.")
                break
            msg_id = new_msg_id
            sleep(2)


if __name__ == "__main__":
    config = json.load(open("discord.json"))
    db = db_connect(config)
    if "token" in config and time() - config["token"]["timestamp"] < config["prefs"]["token_lifetime"]:
        token = config["token"]["s"]
    else:
        token = user_login(**config["user"], proxies=config.get("proxies", None))["token"]
        config["token"] = {"s": token, "timestamp": time()}
        json.dump(config, open("discord.json", "w"), indent=2, ensure_ascii=False)
    s = create_session(config)
    channel_fetchers = []
    task_queue = Queue()
    for channel_id in config['target']['channel_ids']:
        chan = get_channel_info(s, channel_id)
        db.channels.insert_one(chan)
        if not db.servers.find_one({"id": chan["guild_id"]}):
            db.servers.insert_one(get_server_info(s, chan["guild_id"]))
        fetcher = ChannelFetcher(db, task_queue, chan["last_message_id"], config, channel_id=channel_id)
        fetcher.start()
        channel_fetchers.append(fetcher)
    attachment_fetchers = []
    for _ in range(config["prefs"].get("fetch_threads", 3)):
        fetcher = AttachmentFetcher(db, task_queue, config)
        fetcher.start()
        attachment_fetchers.append(fetcher)
    try:
        for t in channel_fetchers:
            t.join()
    except Exception as e:
        print(e)
        print_exc()
    finally:
        task_queue.join()
        print("Exiting now.")
