import functools
import getpass
import io
import json
import logging
import os
import pathlib
import sys
import tkinter as tk
from collections import UserDict

import requests

from .db_logger_gui import MainApp, ScreenRes, check_singleton
from .filewatcher import FileWatcher
from .instrument import GCPInstrument
from .make_db_entry import DBSessionLogger


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


def get_logger(name, verbose=logging.INFO, stream=None):
    logger = logging.getLogger(name)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(verbose)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    if stream:
        st = logging.StreamHandler(stream)
        st.setLevel(logging.NOTSET)
        st.setFormatter(formatter)
        logger.addHandler(st)
    logger.setLevel(verbose)
    return logger


def main():
    # check singleton
    try:
        sing = check_singleton()
    except OSError as e:
        root = tk.Tk()
        root.title('Error')
        message = "Only one instance of the NexusLIMS " + \
                  "Session Logger can be run at one time. " + \
                  "Please close the existing window if " + \
                  "you would like to start a new session " \
                  "and run the application again."
        if sys.platform == 'win32':
            message = message.replace('be run ', 'be run\n')
            message = message.replace('like to ', 'like to\n')
        root.withdraw()
        tk.messagebox.showerror(parent=root, title="Error", message=message)
        sys.exit(0)

    verbosity = logging.WARNING
    if len(sys.argv) > 1:
        v = sys.argv[1][1:]
        if v == 's':
            verbosity = logging.CRITICAL
        elif v == 'v':
            verbosity = logging.INFO
        elif v == 'vv':
            verbosity = logging.DEBUG
        elif v == 'vvv':
            verbosity = logging.NOTSET

    log_text = io.StringIO()
    _get_logger = functools.partial(get_logger,
                                    verbose=verbosity,
                                    stream=log_text)

    logger = _get_logger("APP")
    config_fn = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "config.json")
    cred_json = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "creds.json")
    cache_json = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "cache.json")

    # config
    # The setting config will look for settings from environment variable first.
    # If not exist, it will read from `$HOME/nexuslims/gui/config.json` as fallback.

    config = _Config()
    try:
        config.update(json.load(open(config_fn)))
    except:
        logger.warning("file `%s` cannot be found, use ENV variables instead.")

    try:
        validate_config(config)
    except Exception as e:
        root = tk.Tk()
        root.title("Error")
        root.withdraw()
        tk.messagebox.showerror(parent=root, title="Error", message=str(e))
        sys.exit(0)

    # credential
    if not os.path.exists(cred_json):
        msg = "Credential file `%s` cannot be found!" % cred_json
        root = tk.Tk()
        root.title("Error")
        root.withdraw()
        tk.messagebox.showerror(parent=root, title="Error", message=msg)
        sys.exit(0)

    # cache
    if not os.path.exists(cache_json):
        with open(cache_json, 'w') as f:
            f.write(json.dumps({}))

    # user
    login = getpass.getuser()

    # logger window
    dbdl = DBSessionLogger.from_config(config,
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

    # main app
    root = MainApp(dbdl, instr, fw,
                   screen_res=sres,
                   logger=_get_logger("GUI"),
                   log_text=log_text)
    root.protocol("WM_DELETE_WINDOW", root.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
