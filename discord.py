import json
import string
from base64 import b64encode
from datetime import datetime
from pathlib import Path
from queue import Queue
from secrets import choice
from threading import Thread
from time import sleep
from traceback import print_exc, format_exc

from dateutil.parser import parse as parse_datetime
from pymongo import MongoClient
from requests import Session, post
from requests.exceptions import Timeout

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


# def parse_datetime(s):
#     m = match(r"^(\d+)-(\d+)-(\d+)T(\d+):(\d+):(\d+)",s)
#     if not m:
#         print(s)
#     elements = [int(x) for x in m.groups()]
#     return datetime(*elements)


def get_messages_before(s, db, channel_id, msg_id):
    while True:
        try:
            resp = s.get(f"{ENDPOINT}/channels/{channel_id}/messages", params={"before": msg_id}, timeout=10)
        except Timeout:
            db.logs.insert_one({"type": "timeout_msg", "msg_id": msg_id})
            pass
        except Exception as e:
            db.logs.insert_one({"type": "exception_msg", "msg_id": msg_id, "exception": repr(e), "traceback": format_exc()})
            resp = None
            break
        else:
            break
    if not resp or not resp.ok:
        db.logs.insert_one({"type": "fail_msg", "msg_id": msg_id, "data": b64encode(resp.content) if resp else "", "status_code": resp.status_code})
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
    return {k: v for k, v in user_obj.items() if k in ["id", "username", "email", "avatar"]}


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
                    self.db.logs.insert_one({"type": "unknown_type", "data": attachment})
            except Exception as e:
                print(e)
                print_exc()
                self.db.logs.insert_one({"type": "attachment_fail", "exception": repr(e), "traceback": format_exc()})
                self.tasks.put(attachment)
            else:
                self.tasks.task_done()


class ChatFetcher(Thread):
    def __init__(self, db, queue, msg_id, config):
        super().__init__()
        self.db, self.queue, self.msg_id, self.config = db, queue, msg_id, config
        self.session = create_session(config)

    def run(self):
        msg_id = self.msg_id
        while True:
            msg_list, new_msg_id = get_messages_before(self.session, self.db, config['target']['channel_id'], msg_id)
            if not new_msg_id:  # get_messages_before(...) still returns a new msg_id if there's only one message left in the chat history.
                break
            visited = True
            for msg in msg_list:
                if self.db.messages.find_one({"id": msg["id"]}):
                    continue
                else:
                    visited = False
                self.db.messages.insert_one(prepare_message(msg))
                if msg["attachments"]:
                    print(msg["content"], msg["author"]["username"], parse_datetime(msg["timestamp"]), msg["attachments"])
                    for item in msg["attachments"]:
                        self.queue.put(item)
            if visited:
                print("All visited.")
                break
            msg_id = new_msg_id
            sleep(2)


if __name__ == "__main__":
    config = json.load(open("discord.json"))
    if all(x in config["db"] for x in ("username", "password")):
        c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
    else:
        c = MongoClient(config["db"]["host"], config["db"]["port"])
    db = c[config["db"]["db_name"]]
    if "token" in config and datetime.utcnow().timestamp() - config["token"]["timestamp"] < config["prefs"]["token_lifetime"]:
        token = config["token"]["s"]
    else:
        token = user_login(**config["user"], proxies=config.get("proxies", None))["token"]
        config["token"] = {"s": token, "timestamp": datetime.utcnow().timestamp()}
        json.dump(config, open("discord.json", "w"), indent=2, ensure_ascii=False)
    s = create_session(config)
    chan = s.get(f"{ENDPOINT}/channels/{config['target']['channel_id']}").json()
    msg_id = chan["last_message_id"]
    attachment_fetchers = []
    task_queue = Queue()
    for _ in range(config["prefs"].get("fetch_threads", 3)):
        fetcher = AttachmentFetcher(db, task_queue, config)
        fetcher.start()
        attachment_fetchers.append(fetcher)
    chat_fetcher = ChatFetcher(db, task_queue, msg_id, config)
    chat_fetcher.start()
    try:
        chat_fetcher.join()
    except Exception as e:
        print(e)
        print_exc()
    finally:
        task_queue.join()
        print("Exiting now.")
        c.close()
