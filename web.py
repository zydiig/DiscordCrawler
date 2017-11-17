import json
import os
from pathlib import Path

import tornado.ioloop
import tornado.web
from markdown import markdown
from pymongo import MongoClient, ASCENDING, DESCENDING


def srcdir_path(rel_path):
    return os.path.join(os.path.dirname(__file__), rel_path)


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.set_status(status_code)
        self.render(srcdir_path("templates/error.html"), code=status_code)


class ChannelHandler(BaseHandler):
    def initialize(self, db):
        self.db = db

    def get(self, channel_id):
        channel_info = self.db.channels.find_one({"id": channel_id}, sort=[("timestamp", DESCENDING)])
        if not channel_info:
            raise tornado.web.HTTPError(404)
        server_name = self.db.servers.find_one({"id": channel_info["guild_id"]})["name"]
        after = self.get_argument("after", default=None)
        before = self.get_argument("before", default=None)
        limit = self.get_argument("limit", default=100)
        first_page = False
        if after:
            dt_limit = self.db.messages.find_one({"id": after, "channel_id": channel_id})["timestamp"]
            messages = self.db.messages.find({"timestamp": {"$gt": dt_limit}, "channel_id": channel_id}, limit=limit, sort=[("timestamp", ASCENDING)])
        elif before:
            dt_limit = self.db.messages.find_one({"id": before, "channel_id": channel_id})["timestamp"]
            messages = self.db.messages.find({"timestamp": {"$lt": dt_limit}, "channel_id": channel_id}, limit=limit,
                                             sort=[("timestamp", DESCENDING)])
            messages = reversed(list(messages))
        else:
            messages = self.db.messages.find({"channel_id": channel_id}, limit=limit, sort=[("timestamp", ASCENDING)])
            first_page = True
        messages = list(messages)
        message_count = self.db.messages.find({"channel_id": channel_id}).count()
        last_message = list(self.db.messages.find({"channel_id": channel_id}, limit=message_count % limit + 1, sort=[("timestamp", DESCENDING)]))[-1]
        last_page = self.db.messages.find_one({"channel_id": channel_id, "timestamp": {"$gt": messages[-1]["timestamp"]}}) is None
        if not first_page:
            first_page = self.db.messages.find_one({"channel_id": channel_id, "timestamp": {"$lt": messages[0]["timestamp"]}}) is None
        for message in messages:
            for item in message.get("attachments", []):
                item["local_filename"] = self.db.attachments.find_one({"id": item["id"]})["local_filename"]

        self.render(srcdir_path("templates/channel.html"), msgs=list(messages), last_id=last_message["id"],
                    format_datetime=lambda x: x.strftime("%Y-%m-%d %H:%M:%S"), channel_id=channel_id, first_page=first_page, last_page=last_page,
                    channel_info=channel_info, markdown=markdown, message_count=message_count, server_name=server_name)


class MainHandler(BaseHandler):
    def initialize(self, db):
        self.db = db

    def get(self):
        channels = []
        for idx in self.db.channels.distinct("id"):
            channel = self.db.channels.find_one({"id": idx}, sort=[("timestamp", DESCENDING)])
            channel["server_name"] = self.db.servers.find_one({"id": channel["guild_id"]})["name"]
            channels.append(channel)
        self.render(srcdir_path("templates/index.html"), channels=channels)


class AttachmentHandler(BaseHandler):
    def initialize(self, db):
        self.db = db

    def get(self, idx):
        self.render(srcdir_path("templates/attachment.html"), data=self.db.attachments.find_one({"id": idx}))


class MessageHandler(BaseHandler):
    def initialize(self, db):
        self.db = db

    def get(self, idx):
        msg = self.db.messages.find_one({"id": idx})
        attachments = []
        for x in msg["attachments"]:
            attachments.append(self.db.attachments.find_one({"id": x["id"]}))
        self.render(srcdir_path("templates/message.html"), data=self.db.messages.find_one({"id": idx}), attachments=attachments)


def make_app(db, static_path):
    return tornado.web.Application([
        (r"/", MainHandler, dict(db=db)),
        (r"/channel/(.+)", ChannelHandler, dict(db=db)),
        (r"/attachment/(.+)", AttachmentHandler, dict(db=db)),
        (r"/message/(.+)", MessageHandler, dict(db=db)),
        (r"/res/(.+)", tornado.web.StaticFileHandler, {"path": static_path}),
        (r"/static/(.+)", tornado.web.StaticFileHandler, {"path": srcdir_path("static")})
    ])


if __name__ == "__main__":
    config = json.load(open("discord.json"))
    if all(key in config["db"] for key in ("username", "password")):
        c = MongoClient(config["db"]["host"], config["db"]["port"], username=config["db"]["username"], password=config["db"]["password"])
    else:
        c = MongoClient(config["db"]["host"], config["db"]["port"])
    db = c[config["db"]["db_name"]]
    app = make_app(db, str(Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()))
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
