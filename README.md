DiscordCrawler
=============
Crawls chat history for all the pics.

Also logs all messages.

Dependencies
---------
* MongoDB
* Python 3 (at least 3.6)
* Python packages
  * requests
  * pymongo
  * python-dateutil

Configuration
-------------
~~~
{
  "user": {
    "email": "",
    "password": ""
  },
  "proxies": {
    "http": "http://127.0.0.1:10000",
    "https": "http://127.0.0.1:10000"
  },
  "prefs": {
    "token_lifetime": 3600,
    "fetch_threads": 2,
    "save_dest":"discord"
  },
  "target": {
    "channel_id": "<YOUR CHANNEL ID HERE>"
  },
  "db": {
    "host": "localhost",
    "port": 27017,
    "db_name": "ddlc"
  }
}
~~~
Copy and save it as `discord.json`. The script expects the config file placed in the current working directory (`$PWD`).