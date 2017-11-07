import json
from os import stat
from pathlib import Path

from pymongo import MongoClient
from requests import Session
from traceback import print_exc

s=Session()

config = json.load(open("discord.json"))
s.proxies.update(config.get("proxies"))
if all(x in config["db"] for x in ("username", "password")):
    c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
else:
    c = MongoClient(config["db"]["host"], config["db"]["port"])
attachments = c[config["db"]["db_name"]].attachments
messages = c[config["db"]["db_name"]].messages
mapping = {}
root = Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()


def check_attachment(x):
    path = root / x["local_filename"]
    if not path.exists():
        print("!!!MISSING FILE!!!")
        return False
    local_size = stat(path).st_size
    remote_size = x["size"]
    if local_size != remote_size:
        print(x["id"], local_size, remote_size, x["local_filename"], x['proxy_url'],x['url'])
        return False
    return True


for x in attachments.find():
    if not check_attachment(x):
        try:
            data = s.get(x["url"], timeout=10).content
            if len(data) == x["size"]:
                with open(root / x["local_filename"], "wb") as f:
                    f.write(data)
                print(f"FIXED {x['filename']} {x['id']}")
            else:
                print(f"ERRORED {x['filename']} {x['id']}")
        except Exception as e:
            print(e)
            print_exc()
            continue

exit(0)
print("===========")
print("Inconsistent size")

for x in messages.find({"attachments": {"$ne": []}}):
    for a in x["attachments"]:
        check_attachment(attachments.find_one({"id": a["id"]}))
