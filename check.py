import json
from argparse import ArgumentParser
from os import stat
from pathlib import Path
from traceback import print_exc

from requests import Session

from utils import db_connect

s = Session()

config = json.load(open("discord.json"))
s.proxies.update(config.get("proxies", {}))
db = db_connect(config)
attachments = db.attachments
messages = db.messages
mapping = {}
root = Path(config["prefs"].get("save_dest", "discord")).expanduser().resolve()


def check_attachment(x, id=None):
    if not x:
        print(f"{id} wasn't fetched")
        return False
    path = root / x["local_filename"]
    if not path.exists():
        print("!!!MISSING FILE!!!")
        return False
    local_size = stat(path).st_size
    remote_size = x["size"]
    if local_size != remote_size:
        print(x["id"], local_size, remote_size, x["local_filename"], x['proxy_url'], x['url'])
        return False
    return True


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-f", "--fix", help="Actually fix local attachment mismatch", dest="fix", action="store_true", default=False)
    args = parser.parse_args()
    total, total_good, total_bad = 0, 0, 0
    for x in attachments.find():
        if not check_attachment(x, x["id"]):
            total_bad += 1
            if args.fix:
                try:
                    data = s.get(x["url"], timeout=10).content
                    if len(data) == x["size"]:
                        with open(root / x["local_filename"], "wb") as f:
                            f.write(data)
                        print(f"FIXED {x['filename']} {x['id']}")
                    else:
                        print(f"ERROR {x['filename']} {x['id']}")
                except Exception as e:
                    print(e)
                    print_exc()
            else:
                print(f"MISMATCH {x['filename']} {x['id']}")
        else:
            total_good += 1
        total += 1
    print(f"Total {total} Good {total_good} Bad {total_bad}")
    print("==============================================")
    total, total_good, total_bad = 0, 0, 0
    for x in messages.find({"attachments": {"$ne": []}}):
        for a in x["attachments"]:
            total += 1
            if not check_attachment(attachments.find_one({"id": a["id"]}), a["id"]):
                total_bad += 1
            else:
                total_good += 1
    print(f"Total {total} Good {total_good} Bad {total_bad}")
