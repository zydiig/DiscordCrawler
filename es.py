import json

from elasticsearch import Elasticsearch
from pymongo import MongoClient
from requests import Session

s = Session()

config = json.load(open("discord.json"))
s.proxies.update(config.get("proxies"))
if all(key in config["db"] for key in ("username", "password")):
    c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
else:
    c = MongoClient(config["db"]["host"], config["db"]["port"])
attachments = c[config["db"]["db_name"]].attachments
messages = c[config["db"]["db_name"]].messages

es = Elasticsearch()
docs = []
for msg in messages.find():
    doc = {"content": msg["content"], "n_attachments": len(msg["attachments"]), "id": msg["id"], "author": msg["author"]["username"]}
    docs.append(doc)
print(len(docs))
for doc in docs:
    hit = es.search("messages", "message", {"query": {"match": {"id": doc["id"]}}})["hits"]["total"]
    if hit == 0:
        es.index(index="messages", doc_type="message", body=doc)
