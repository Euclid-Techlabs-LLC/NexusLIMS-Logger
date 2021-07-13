"""utility functions"""
__all__ = ["check_singleton", "show_error_msg_box", "get_logger"]

import logging
import sys
import tkinter as tk
import tkinter.messagebox

from tendo import singleton


def check_singleton():
    """make sure only ONE instance of the program running."""

    if sys.platform == 'win32':
        if hasattr(sys, '_MEIPASS'):
            # we're in a pyinstaller environment, so use psutil to check for exe
            import psutil
            db_logger_exe_count = 0
            for proc in psutil.process_iter():
                try:
                    pinfo = proc.as_dict(attrs=['pid', 'name', 'username'])
                    if pinfo['name'] == 'NexusLIMS Session Logger.exe':
                        db_logger_exe_count += 1
                except psutil.NoSuchProcess:
                    pass
                else:
                    pass
            # When running the pyinstaller .exe, two processes are spawned, so
            # if we see more than that, we know there's already an instance
            # running
            if db_logger_exe_count > 2:
                raise OSError('Only one instance of NexusLIMS Session Logger '
                              'allowed')
        else:
            # we're not running as an .exe, so use tendo
            return tendo_singleton()
    else:
        return tendo_singleton()


def tendo_singleton():
    try:
        me = singleton.SingleInstance()
    except singleton.SingleInstanceException:
        raise OSError('Only one instance of db_logger_gui allowed')
    return me


def show_error_msg_box(msg):
    """show a tkinter error box."""
    root = tk.Tk()
    root.title("Error")
    root.withdraw()
    tkinter.messagebox.showerror(parent=root, title="Error", message=msg)
    return root


def get_logger(name, verbose=logging.INFO, stream=None):
    """get a logger from logging module, direct output to stdout,
    verbose level set by ``verbose``.

    If additional stream is provided, direct output (DEBUG) to that
    stream too."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s')
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(verbose)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    if stream:
        st = logging.StreamHandler(stream)
        st.setLevel(logging.DEBUG)
        st.setFormatter(formatter)
        logger.addHandler(st)
    return logger
