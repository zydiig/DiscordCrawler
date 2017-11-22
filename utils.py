import json

from pymongo import MongoClient


def db_connect(config=None):
    config = json.load(open("discord.json")) if not config else config
    if all(key in config["db"] for key in ("username", "password")):
        c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
    else:
        c = MongoClient(config["db"]["host"], config["db"]["port"])
    return c[config["db"]["db_name"]]