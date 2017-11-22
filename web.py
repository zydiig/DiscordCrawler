import json
import os
from pathlib import Path

import tornado.ioloop
import tornado.web
from markdown import markdown
from pymongo import ASCENDING, DESCENDING

from utils import db_connect


def srcdir_path(rel_path):
    return os.path.join(os.path.dirname(__file__), rel_path)


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.set_status(status_code)
        self.render(srcdir_path("templates/error.html"), code=status_code)

    def initialize(self, db):
        self.db = db


class ChannelHandler(BaseHandler):
    def get(self, channel_id):
        channel_info = self.db.channels.find_one({"id": channel_id}, sort=[("timestamp", DESCENDING)])
        if not channel_info:
            raise tornado.web.HTTPError(404)
        server_name = self.db.servers.find_one({"id": channel_info["guild_id"]})["name"]
        after = self.get_argument("after", default=None)
        before = self.get_argument("before", default=None)
        limit = self.get_argument("limit", default=100)

        def get_message(query, nullable=False, **kwargs):
            query.update({"channel_id": channel_id})
            ret = self.db.messages.find_one(query, **kwargs)
            if not ret and not nullable:
                print(query)
                raise tornado.web.HTTPError(404)
            else:
                return ret

        def get_messages(query, **kwargs):
            query.update({"channel_id": channel_id})
            return self.db.messages.find(query, **kwargs)

        if after:
            dt_limit = get_message({"id": after})["timestamp"]
            messages = list(get_messages({"timestamp": {"$gt": dt_limit}}, limit=limit, sort=[("timestamp", ASCENDING)]))
        elif before:
            dt_limit = get_message({"id": before})["timestamp"]
            messages = list(reversed(list(get_messages({"timestamp": {"$lt": dt_limit}}, limit=limit, sort=[("timestamp", DESCENDING)]))))
        else:
            messages = list(get_messages({}, limit=limit, sort=[("timestamp", ASCENDING)]))
        message_count = get_messages({}).count()
        last_page_lower_bound = list(get_messages({}, limit=message_count % limit + 1, sort=[("timestamp", DESCENDING)]))[-1]
        is_last_page = get_message({"timestamp": {"$gt": messages[-1]["timestamp"]}}, nullable=True) is None
        is_first_page = get_message({"timestamp": {"$lt": messages[0]["timestamp"]}}, nullable=True) is None
        for message in messages:
            for item in message.get("attachments", []):
                item["local_filename"] = self.db.attachments.find_one({"id": item["id"]})["local_filename"]

        self.render(srcdir_path("templates/channel.html"), msgs=messages, last_id=last_page_lower_bound["id"],
                    format_datetime=lambda x: x.strftime("%Y-%m-%d %H:%M:%S"), channel_id=channel_id, is_first_page=is_first_page,
                    is_last_page=is_last_page,
                    channel_info=channel_info, markdown=markdown, message_count=message_count, server_name=server_name)


class MainHandler(BaseHandler):
    def get(self):
        channels = []
        for idx in self.db.channels.distinct("id"):
            channel = self.db.channels.find_one({"id": idx}, sort=[("timestamp", DESCENDING)])
            channel["server_name"] = self.db.servers.find_one({"id": channel["guild_id"]})["name"]
            channels.append(channel)
        self.render(srcdir_path("templates/index.html"), channels=channels)


class AttachmentHandler(BaseHandler):
    def get(self, idx):
        self.render(srcdir_path("templates/attachment.html"), data=self.db.attachments.find_one({"id": idx}))


class MessageHandler(BaseHandler):
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
    db = db_connect(config)
    app = make_app(db, str(Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()))
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
