import functools
import getpass
import io
import json
import logging
import os
import pathlib
import sys
from collections import UserDict

import requests

from .dbsessionlogger import DBSessionLogger
from .filewatcher import FileWatcher
from .gui import App, ScreenRes
from .instrument import GCPInstrument
from .utils import check_singleton, get_logger, show_error_msg_box


class _Config(UserDict):
    """subclass `dict`, get keys from environment first."""

    def __getitem__(self, k):
        if k in os.environ:
            return os.getenv(k)
        return super().__getitem__(k)

    def get(self, k):
        if k in os.environ:
            return os.getenv(k)
        return super().get(k)


def validate_config(config):
    # `api_url`
    api_url = config.get("api_url")
    res = requests.get(api_url)
    if res.status_code != 200 or res.text != "API for nexuslims-db":
        raise ValueError("api_url `%s` is not responding" % api_url)

    # `filestore_path`
    filestore_path = config.get("filestore_path")
    if not os.path.isdir(filestore_path):
        raise ValueError("filestore_path `%s` does not exist" % filestore_path)

    return True


def help():
    res = (
        "OPTIONS:  (-s|v|vv|h)\n"
        "   -s  silent\n"
        "   -v  verbose\n"
        "   -vv debug\n"
        "   -h  help\n"
    )
    return res


def main():
    # check singleton
    try:
        check_singleton()
    except OSError:
        msg = ("Only one instance of the NexusLIMS Session Logger can be run at one time. "
               "Please close the existing window if you would like to start a new session "
               "and run the application again.")
        show_error_msg_box(msg)
        sys.exit(0)

    # options
    verbosity = logging.WARNING
    if len(sys.argv) > 1:
        v = sys.argv[1][1:]
        if v == 's':
            verbosity = logging.CRITICAL
        elif v == 'v':
            verbosity = logging.INFO
        elif v == 'vv':
            verbosity = logging.DEBUG
        elif v == 'h':
            print(help())
            sys.exit(1)
        else:
            print("wrong option provided!")
            print(help())
            sys.exit(0)

    log_text = io.StringIO()
    _get_logger = functools.partial(get_logger, verbose=verbosity, stream=log_text)

    logger = _get_logger("APP")

    # config, credential, cache
    config_fn = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "config.json")
    config = _Config()
    try:
        config.update(json.load(open(config_fn)))
    except Exception:
        logger.warning("file `%s` cannot be found, use ENV variables instead.")

    try:
        validate_config(config)
    except Exception as e:
        show_error_msg_box(str(e))
        sys.exit(0)

    # credential
    cred_json = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "creds.json")
    if not os.path.exists(cred_json):
        msg = "Credential file `%s` cannot be found!" % cred_json
        show_error_msg_box(msg)
        sys.exit(0)

    # cache
    cache_json = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "cache.json")
    if not os.path.exists(cache_json):
        with open(cache_json, 'w') as f:
            f.write(json.dumps({}))

    # user
    login = getpass.getuser()

    # logger window
    dbsl = DBSessionLogger.from_config(config,
                                       user=login,
                                       logger=_get_logger("DSL"))
    sres = ScreenRes(logger=_get_logger("SCREEN"))
    instr = GCPInstrument.from_config(config,
                                      credential_fn=cred_json,
                                      logger=_get_logger("GCP"))
    fw = FileWatcher.from_config(config,
                                 credential_fn=cred_json,
                                 cache_fn=cache_json,
                                 logger=_get_logger("FW"))

    # app
    app = App(dbsl, instr, fw,
              screen_res=sres,
              logger=_get_logger("GUI"),
              log_text=log_text)
    app.mainloop()


if __name__ == "__main__":
    main()
