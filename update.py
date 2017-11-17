import json
from pathlib import Path

from pymongo import MongoClient
from requests import Session

s = Session()

config = json.load(open("discord.json"))
s.proxies.update(config.get("proxies"))
if all(key in config["db"] for key in ("username", "password")):
    c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
else:
    c = MongoClient(config["db"]["host"], config["db"]["port"])
db = c[config["db"]["db_name"]]
mapping = {}
root = Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()

for msg in db.messages.find():
    if not db.users.find_one({"id": msg["author"]["id"]}):
        user = msg["author"]
        user["imported"] = True
        db.users.insert_one(user)
        print(user)