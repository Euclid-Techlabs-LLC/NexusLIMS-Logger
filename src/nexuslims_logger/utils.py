"""utility functions"""
__all__ = ["check_singleton", "show_error_msg_box",
           "get_logger", "Config", "ScreenRes", "resource_path"]

import logging
import os
import re
import subprocess
import sys
import tkinter as tk
import tkinter.messagebox
from collections import UserDict

from tendo import singleton

LOGGING_FMT = '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'

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

    formatter = logging.Formatter(LOGGING_FMT)
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


class Config(UserDict):
    """subclass `dict`, get keys from environment first."""

    def __getitem__(self, k):
        if k in os.environ:
            return os.getenv(k)
        return super().__getitem__(k)

    def get(self, k):
        if k in os.environ:
            return os.getenv(k)
        return super().get(k)


class ScreenRes:
    def __init__(self, logger=None):
        """
        When an instance of this class is created, the screen is queried for its
        dimensions. This is done once, so as to limit the number of calls to
        external programs.
        """
        default_screen_dims = ('800', '600')
        self.logger = logger or logging.getLogger("SCREEN")
        try:
            if sys.platform == 'win32':
                cmd = 'wmic path Win32_VideoController get ' + \
                      'CurrentHorizontalResolution, CurrentVerticalResolution'
                output = self.run_cmd(cmd).split()[-2::]
                # Tested working in Windows XP and Windows 7/10
                screen_dims = tuple(map(int, output))
                self.logger.debug('Found "raw" Windows resolution '
                                  'of {}'.format(screen_dims))

                # Get the DPI of the screen so we can adjust the resolution
                cmd = r'reg query "HKCU\Control Panel\Desktop\WindowMetrics" ' \
                      r'/v AppliedDPI'
                # pick off last value, which is DPI in hex, and convert to
                # decimal:
                dpi = 96
                dpi = int(self.run_cmd(cmd).split()[-1], 16)
                scale_factor = dpi / 96
                screen_dims = tuple(int(d / scale_factor) for d in screen_dims)
                self.logger.debug("Found DPI of {}; ".format(dpi) +
                                  "Scale factor {}; Scaled ".format(scale_factor) +
                                  "resolution is {}".format(screen_dims))
                temp_file = 'TempWmicBatchFile.bat'
                if os.path.isfile(temp_file):
                    os.remove(temp_file)
                    self.logger.debug("Removed {}".format(temp_file))

            elif sys.platform == 'linux':
                cmd = 'xrandr'
                screen_dims = os.popen(cmd).read()
                result = re.search(r'primary (\d+)x(\d+)', screen_dims)
                screen_dims = result.groups() if result else default_screen_dims
                screen_dims = tuple(map(int, screen_dims))
                self.logger.debug('Found Linux resolution of '
                                  '{}'.format(screen_dims))

            else:
                screen_dims = default_screen_dims
        except Exception as e:
            self.logger.warning("Caught exception when determining "
                                "screen resolution: {}".format(e) + ' ' +
                                "Using default of {}".format(default_screen_dims))
            screen_dims = default_screen_dims
        self.screen_dims = screen_dims
        self.logger.debug("dimension: %s" % str(screen_dims))

    def get_center_geometry_string(self, width, height):
        """
        This method will return a Tkinter geometry string that will place a
        Toplevel window into the middle of the screen given the
        widget's width and height (using a Windows command or `xrandr` as
        needed). If it fails for some reason, a basic resolution of 800x600
        is assumed.

        Parameters
        ----------
        width : int
            The width of the widget desired
        height : int
            The height of the widget desired

        Returns
        -------
        geometry_string : str
            The Tkinter geometry string that will put a window of `width` and
            `height` at the center of the screen given the current resolution
            (of
            the format "WIDTHxHEIGHT+XPOSITION+YPOSITION")
        """
        screen_width, screen_height = (int(x) for x in self.screen_dims)
        geometry_string = "%dx%d%+d%+d" % (width, height,
                                           int(screen_width / 2 - width / 2),
                                           int(screen_height / 2 - height / 2))
        return geometry_string

    def run_cmd(self, cmd):
        """
        Run a command using the subprocess module and return the output. Note
        that because we want to run the eventual logger without a console
        visible, we do not have access to the standard stdin, stdout,
        and stderr, and these need to be redirected ``subprocess`` pipes,
        accordingly.

        Parameters
        ----------
        cmd : str
            The command to run (will be run in a new Windows `cmd` shell).
            ``stderr`` will be redirected for ``stdout`` and included in the
            returned output

        Returns
        -------
        output : str
            The output of ``cmd``
        """
        try:
            # Redirect stderr to stdout, and then stdout and stdin to
            # subprocess.PIP
            p = subprocess.Popen(cmd,
                                 shell=True,
                                 stderr=subprocess.STDOUT,
                                 stdout=subprocess.PIPE,
                                 stdin=subprocess.PIPE)
            p.stdin.close()
            p.wait()
            output = p.stdout.read().decode()
        except subprocess.CalledProcessError as e:
            p = e.output.decode()
            msg = "command %s returned with error (code %d): %s" % (
                e.cmd, e.returncode, p)
            self.logger.exception(msg)
        return output


def resource_path(relative_path):
    try:
        # try to set the base_path to the pyinstaller temp dir (for when we're)
        # running from a compiled .exe built with pyinstaller
        base_path = os.path.join(sys._MEIPASS, 'resources')
    except Exception:
        thisdir = os.path.dirname(os.path.abspath(__file__))
        base_path = os.path.join(thisdir, 'resources')

    pth = os.path.join(base_path, relative_path)

    return pth
