import getpass
import json
import os
import sys
import tkinter as tk
from collections import UserDict

from db_logger_gui import MainApp, ScreenRes, check_singleton
from make_db_entry import DBSessionLogger


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
    keys_non_null = [
        "database_name",
        "database_relpath",
        "networkdrive_hostname",
        "daq_relpath",
    ]

    for k in keys_non_null:
        if not config.get(k):
            raise ValueError(
                "Config is NOT valid: entry `{}` is not present or Null.".format(k)
            )

    return True


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

    # config
    # The setting config will look for settings from environment variable first.
    # If not exist, it will read from `$HOME/nexuslims/gui/config.json` as fallback.

    config = _Config()

    try:
        config_fn = os.path.join(
            os.path.expanduser("~"), "nexuslims", "gui", "config.json")
        config.update(json.loads(open(config_fn).read()))
    except:
        pass

    try:
        validate_config(config)
    except Exception as e:
        root = tk.Tk()
        root.title("Error")
        root.withdraw()
        tk.messagebox.showerror(parent=root, title="Error", message=str(e))
        sys.exit(0)

    # user
    login = getpass.getuser()

    # logger window
    dbdl = DBSessionLogger(config=config, user=login, verbosity=2)
    sres = ScreenRes(dbdl)

    # main app
    root = MainApp(dbdl, screen_res=sres)
    root.protocol("WM_DELETE_WINDOW", root.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()
