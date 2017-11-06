import json
from os import stat
from pathlib import Path

from pymongo import MongoClient

config = json.load(open("discord.json"))
if all(x in config["db"] for x in ("username", "password")):
    c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
else:
    c = MongoClient(config["db"]["host"], config["db"]["port"])
attachments = c[config["db"]["db_name"]].attachments
messages = c[config["db"]["db_name"]].messages
mapping = {}
root = Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()


def check_attachment(x):
    path=root / x["local_filename"]
    if not path.exists():
        print("!!!MISSING FILE!!!")
    local_size = stat(path).st_size
    remote_size = x["size"]
    if local_size != remote_size:
        print(x["id"], local_size, remote_size, x["local_filename"], x['proxy_url'])


for x in attachments.find():
    check_attachment(x)

print("===========")
print("Incosistent size")

for x in messages.find():
    for a in x["attachments"]:
        check_attachment(attachments.find_one({"id": a["id"]}))
