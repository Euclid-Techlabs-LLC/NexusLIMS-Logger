"""GUI impl"""
__all__ = ["ScreenRes", "App"]

import io
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox
from datetime import datetime, timedelta
from tkinter import ttk
from uuid import uuid4

from timeloop import Timeloop


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


def format_date(dt, with_newline=True):
    """
    Format a datetime object in our preferred format

    Parameters
    ----------
    dt : datetime.datetime

    Returns
    -------
    datestring : str
        A datetime formatted in our preferred format
    """
    datestring = dt.strftime("%a %b %d, %Y" +
                             ("\n" if with_newline else " at ") +
                             "%I:%M:%S %p")
    return datestring


class ScreenRes:
    def __init__(self, logger=None):
        """
        When an instance of this class is created, the screen is queried for its
        dimensions. This is done once, so as to limit the number of calls to
        external programs.

        Can provide a db_logger instance (from MainApp) if output should be
        logged to the LogWindow
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


class App(tk.Tk):
    def __init__(self, db_logger, instrument, filewatcher,
                 screen_res=None, logger=None, log_text=None):
        """
        This class configures and populates the main toplevel window. ``top`` is
        the toplevel containing window.

        Parameters
        ----------
        db_logger : dbsessionlogger.DBSessionLogger
            Instance of the database logger that actually does the
            communication with the database
        instrument : instrument.Instrument
            Instance of Instrument that can generate data.
        filewatcher : filewatcher.FileWatcher
            Instance of FileWatcher that will sync raw data to GCP
        screen_res : ScreenRes
            An instance of the screen resolution class to help determine where
            to place the window in the center of the screen
        logger : logging.Logger
        log_text : io.StringIO
            stream of logs
        """
        super(App, self).__init__()
        self.logger = logger or logging.getLogger("GUI")
        self.logger.info('Creating the session logger instance')

        self.db_logger = db_logger
        self.instrument = instrument
        self.filewatcher = filewatcher
        self.log_text = log_text or io.StringIO()
        self.buttons = []

        self.screen_res = screen_res or ScreenRes()

        self.startup_thread_queue = queue.Queue()
        self.startup_thread_exit_queue = queue.Queue()
        self.startup_thread = None
        self.end_thread_queue = queue.Queue()
        self.end_thread_exit_queue = queue.Queue()
        self.end_thread = None

        self.timeloop = Timeloop()
        self.timeloop.logger = self.logger
        self.timeloop._add_job(self.filewatcher.upload,
                               timedelta(seconds=self.filewatcher.interval))

        self.style = ttk.Style()
        if sys.platform == "win32":
            self.style.theme_use('winnative')
        self.style.configure('.', font=("TkDefaultFont"))

        self.info_font = 'TkDefaultFont 16 bold'
        self.geometry(self.screen_res.get_center_geometry_string(350, 600))
        self.resizable(False, False)
        self.title("NexusLIMS Session Logger")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Set window icon
        self.icon = tk.PhotoImage(master=self, file=resource_path("logo_bare.png"))
        self.wm_iconphoto(True, self.icon)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)  # logo
        self.rowconfigure(1, weight=3)  # info
        self.rowconfigure(2, weight=1)  # button
        self.logger.info('Created the top level window')

        self.create_widgets()
        self.logger.info("Widgets created.")

        self.session_startup()
        self.logger.info("Session started.")

    def draw_logo(self):
        """Top NexusLIMS logo with tooltip."""

        if os.path.isfile(resource_path("logo_text_250x100_version.png")):
            fname = resource_path("logo_text_250x100_version.png")
        else:
            fname = resource_path("logo_text_250x100.png")
        self.logo_img = tk.PhotoImage(file=fname)
        self.logo_label = ttk.Label(self, image=self.logo_img)
        ToolTip(self.logo_label,
                msg='Brought to you by the NIST Office of Data and Informatics '
                    'and the Electron Microscopy Nexus',
                header_msg='NexusLIMS',
                delay=0.25)

        self.logo_label.grid(row=0, column=0, sticky=tk.N, pady=(15, 0))

    def draw_info(self):
        """information section"""

        # Loading information that is hidden after session is established
        self.setup_frame = tk.Frame(self)
        self.loading_Label = ttk.Label(self.setup_frame,
                                       anchor='center',
                                       justify='center',
                                       wraplength="250",
                                       text="Please wait while the session is "
                                            "established...")
        self.loading_pbar = ttk.Progressbar(self.setup_frame,
                                            orient=tk.HORIZONTAL,
                                            length=200,
                                            mode='determinate')
        self.loading_pbar_length = 5.0
        self.loading_status_text = tk.StringVar()
        self.loading_status_text.set('Initiating session logger...')
        self.loading_status_Label = ttk.Label(self.setup_frame,
                                              foreground="#777",
                                              font='TkDefaultFont 10 italic',
                                              anchor='center',
                                              justify='center',
                                              wraplength="250",
                                              textvariable=self.loading_status_text)

        # Actual information that is shown once session is started
        self.running_frame = tk.Frame(self)
        self.running_Label_1 = ttk.Label(self.running_frame,
                                         anchor='center',
                                         justify='center',
                                         wraplength="250",
                                         text="A new session has been started "
                                              "for the",
                                         font=self.info_font)
        self.instr_string = tk.StringVar()
        self.instr_string.set("$INSTRUMENT")
        self.instrument_label = ttk.Label(self.running_frame,
                                          foreground="#12649b",
                                          anchor='center',
                                          justify='center',
                                          wraplength="250",
                                          textvariable=self.instr_string,
                                          font=self.info_font)
        self.running_Label_2 = ttk.Label(self.running_frame,
                                         anchor='center',
                                         justify='center',
                                         wraplength="250",
                                         text="at",
                                         font=self.info_font)
        self.datetime_string = tk.StringVar()
        self.datetime_string.set('$DATETIME')
        self.datetime_label = ttk.Label(self.running_frame,
                                        foreground="#12649b",
                                        anchor='center',
                                        justify='center',
                                        wraplength="250",
                                        textvariable=self.datetime_string,
                                        font=self.info_font)
        self.running_Label_3 = ttk.Label(self.running_frame,
                                         anchor='center',
                                         justify='left',
                                         wraplength="250",
                                         foreground='#a30019',
                                         text="Leave this window open while you "
                                              "work! Click `End session` button "
                                              "below or close the window to end "
                                              "the session.")

        # grid the setup_frame contents
        self.setup_frame.grid(row=1, column=0)
        self.loading_Label.grid(row=0, column=0)
        self.loading_pbar.grid(row=1, column=0, pady=10)
        self.loading_status_Label.grid(row=2, column=0)

    def draw_buttons(self):
        """buttons at the bottom"""

        self.button_frame = tk.Frame(self, padx=15, pady=10, width=300)

        # "End session"
        self.end_icon = tk.PhotoImage(file=resource_path('window-close.png'))
        self.end_button = tk.Button(self.button_frame,
                                    text="End session",
                                    width=250,
                                    padx=5,
                                    pady=5,
                                    state=tk.DISABLED,
                                    compound=tk.LEFT,
                                    command=lambda: self.session_end(),
                                    font=('kDefaultFont', 14, 'bold'),
                                    image=self.end_icon)
        self.buttons.append(self.end_button)

        ToolTip(self.end_button,
                msg="Ending the session will close this window and start the "
                    "record building process (don't click unless you're sure "
                    "you've saved all your data to the network share!)",
                header_msg='Warning!',
                delay=0.05)

        # "Show Debug Log"
        self.log_icon = tk.PhotoImage(file=resource_path('file.png'))
        self.log_button = tk.Button(self.button_frame,
                                    text="Show Debug Log",
                                    command=lambda: LogWindow(parent=self),
                                    width=250,
                                    padx=5,
                                    pady=5,
                                    state=tk.DISABLED,
                                    compound=tk.LEFT,
                                    font=('kDefaultFont', 14, 'bold'),
                                    image=self.log_icon)
        self.buttons.append(self.log_button)
        ToolTip(self.log_button, msg="Show debug log window.", delay=0.05)

        # "Add Session Note"
        self.note_icon = tk.PhotoImage(file=resource_path('note.png'))
        self.note_button = tk.Button(self.button_frame,
                                     text="Add Session Note",
                                     command=lambda: NoteWindow(parent=self),
                                     width=250,
                                     padx=5,
                                     pady=5,
                                     state=tk.DISABLED,
                                     compound=tk.LEFT,
                                     font=('kDefaultFont', 14, 'bold'),
                                     image=self.note_icon)
        self.buttons.append(self.note_button)
        ToolTip(self.note_button, msg="Add a session note.", delay=0.05)

        # "Make data"
        self.copy_icon = tk.PhotoImage(file=resource_path('copy.png'))
        self.makedata_button = tk.Button(self.button_frame,
                                         text="Make Data",
                                         padx=5,
                                         pady=5,
                                         width=250,
                                         state=tk.DISABLED,
                                         compound=tk.LEFT,
                                         command=lambda: self.instrument.generate_data(),
                                         font=('kDefaultFont', 14, 'bold'),
                                         image=self.copy_icon)
        self.buttons.append(self.makedata_button)
        ToolTip(self.makedata_button,
                msg="Pretend self as an instrument, making some data.",
                delay=0.05)

        self.button_frame.grid(row=2, column=0, sticky=tk.S, pady=(0, 15))
        self.end_button.grid(row=0, column=0, sticky=tk.NSEW, pady=2)
        self.log_button.grid(row=1, column=0, sticky=tk.NSEW, pady=2)
        self.note_button.grid(row=2, column=0, sticky=tk.NSEW, pady=2)
        self.makedata_button.grid(row=3, column=0, sticky=tk.NSEW, pady=2)

    def enable_buttons(self):
        """bring state of all buttons on main window to `NORMAL`"""
        for btn in self.buttons:
            btn.configure(state=tk.NORMAL)

    def disable_buttons(self):
        """bring state of all buttons on main window to `DISABLED`"""
        for btn in self.buttons:
            btn.configure(state=tk.DISABLED)

    def create_widgets(self):
        """draw widgets on main frame."""

        self.draw_logo()
        self.draw_info()
        self.draw_buttons()

    def session_startup(self):
        self.startup_thread = threading.Thread(
            target=self.session_startup_worker
        )
        self.startup_thread.start()
        self.loading_pbar_length = 5.0
        self.after(100, self.watch_for_startup_result)

    def session_startup_worker(self):
        # a flag to indicate `self.db_logger` started successfully
        db_logger_start_success = False

        # each of these methods will return True if they succeed, and we only
        # want to continue with each one if the last ones succeeded
        if self.db_logger.db_logger_setup(
                self.startup_thread_queue,
                self.startup_thread_exit_queue):
            # Check to make sure that the last session was ended
            if self.db_logger.last_session_ended(
                    self.startup_thread_queue,
                    self.startup_thread_exit_queue):
                if self.db_logger.process_start(
                        self.startup_thread_queue,
                        self.startup_thread_exit_queue):
                    self.db_logger.db_logger_teardown(
                        self.startup_thread_queue,
                        self.startup_thread_exit_queue)
                    db_logger_start_success = True
            else:
                # we got an inconsistent state from the DB, so ask user
                # what to do about it
                response = HangingSessionDialog(self, self.db_logger).show()
                if response == 'new':
                    # we need to end the existing session that was found
                    # and then create a new one by changing the session_id to
                    # a new UUID4 and running process_start
                    self.loading_pbar_length = 8.0
                    self.db_logger.session_id = self.db_logger.last_session_id
                    self.logger.info('Chose to start a new session; '
                                     'ending the existing session with id '
                                     '{}'.format(self.db_logger.session_id))
                    if self.db_logger.process_end(
                            self.startup_thread_queue,
                            self.startup_thread_exit_queue):
                        self.db_logger.session_id = str(uuid4())
                        self.logger.info('Starting a new session with new id '
                                         '{}'.format(self.db_logger.session_id))
                        if self.db_logger.process_start(
                                self.startup_thread_queue,
                                self.startup_thread_exit_queue):
                            self.db_logger.db_logger_teardown(
                                self.startup_thread_queue,
                                self.startup_thread_exit_queue)
                            db_logger_start_success = True
                elif response == 'continue':
                    # we set the session_id to the one that was previously
                    # found (and set the time accordingly, and only run the
                    # teardown instead of process_start
                    self.loading_pbar_length = 1.0
                    self.running_Label_1.configure(text='Continuing the last session for the')
                    self.running_Label_2.configure(text=' started at ')
                    self.db_logger.session_id = self.db_logger.last_session_id
                    self.logger.info('Chose to continue the existing '
                                     'session; setting the logger\'s '
                                     'session_id to the existing value '
                                     '{}'.format(self.db_logger.session_id))
                    self.db_logger.session_started = True
                    self.db_logger.session_start_time = datetime.strptime(
                        self.db_logger.last_session_ts,
                        "%a, %d %b %Y %H:%M:%S %Z")
                    self.db_logger.db_logger_teardown(
                        self.startup_thread_queue,
                        self.startup_thread_exit_queue)
                    db_logger_start_success = True

        if db_logger_start_success:
            self.filewatcher.bucket_dir = \
                self.db_logger.instr_info.get("filestore_path", self.db_logger.instr_pid)
            self.filewatcher.mtime_since = \
                self.db_logger.session_start_time.timestamp()
            self.timeloop.start()  # start syncing

    def watch_for_startup_result(self):
        """Check if there is something in the queue."""

        try:
            res = self.startup_thread_queue.get(0)
            self.show_error_if_needed(res)
            if not isinstance(res, Exception):
                msg, progress = res
                self.loading_status_text.set(msg)
                self.loading_pbar['value'] = \
                    int(progress / self.loading_pbar_length * 100)
                self.update()
                if res[0] == "TEARDOWN":
                    # time.sleep(0.5)
                    self.instr_string.set(self.db_logger.instr_schema)
                    self.datetime_string.set(
                        format_date(self.db_logger.session_start_time)
                    )
                    self.done_loading()
                else:
                    self.after(100, self.watch_for_startup_result)
        except queue.Empty:
            self.after(100, self.watch_for_startup_result)

    def show_error_if_needed(self, res):
        if isinstance(res, Exception):
            self.loading_pbar['value'] = 50
            st = ttk.Style()
            st.configure("red.Horizontal.TProgressbar",
                         background='#990000')
            self.loading_pbar.configure(style="red.Horizontal.TProgressbar")
            msg = "Error encountered during session setup: \n\n%s" % str(res)
            tkinter.messagebox.showerror(parent=self, title="Error", message=msg)
            lw = LogWindow(parent=self, is_error=True)
            lw.mainloop()

    def done_loading(self):
        # Remove the setup_frame contents
        self.setup_frame.grid_forget()

        # grid the running_frame contents to be shown after session is started
        self.running_frame.grid(row=1, column=0)
        self.running_Label_1.grid(row=0, pady=(20, 0))
        self.instrument_label.grid(row=1, pady=(15, 5))
        self.running_Label_2.grid(row=2, pady=(0, 0))
        self.datetime_label.grid(row=3, pady=(5, 15))
        self.running_Label_3.grid(row=4, pady=(0, 20))

        # activate the "end session" button
        self.enable_buttons()

    def switch_gui_to_end(self):
        # Remove the setup_frame contents
        self.running_frame.grid_forget()

        # grid the setup_frame contents again
        self.setup_frame.grid(row=1, column=0)

        # disable the buttons
        self.disable_buttons()

    def session_end(self):
        # signal the startup thread to exit (if it's still running)
        self.startup_thread_exit_queue.put(True)

        # do this in a separate end_thread (since it could take some time)
        if not self.db_logger.session_started:
            msg = ("No session started\n"
                   "A session was never started, so the logger "
                   "will exit without sending a log to the database.")
            tkinter.messagebox.showinfo(msg, icon='warning')
            self.destroy()
        else:
            self.logger.debug('Starting session_end thread')
            self.end_thread = threading.Thread(target=self.session_end_worker)
            self.end_thread.start()
            msg = ("Please wait while the session end is logged to the database...\n"
                   "(this window will close when completed)")
            self.loading_Label.configure(text=msg)
            self.switch_gui_to_end()
            self.loading_pbar_length = 6.0
            self.loading_pbar['value'] = 0
            self.loading_status_text.set('Ending the session...')
            self.after(100, self.watch_for_end_result)

    def session_end_worker(self):
        if self.db_logger.process_end(self.end_thread_queue,
                                      self.end_thread_exit_queue):

            self.end_thread_queue.put(("stopping sync threads..",
                                       self.db_logger.progress_num))
            try:
                self.timeloop.stop()
            except RuntimeError:
                pass

            self.end_thread_queue.put(("final syncing.. (do not close)",
                                       self.db_logger.progress_num))
            self.filewatcher.upload()
            self.logger.debug("Final sync finished.")

            self.db_logger.db_logger_teardown(self.end_thread_queue,
                                              self.end_thread_exit_queue)

    def watch_for_end_result(self):
        """Check if there is something in the queue."""

        try:
            res = self.end_thread_queue.get(0)
            self.show_error_if_needed(res)
            msg, progress = res
            self.loading_status_text.set(msg)
            self.loading_pbar['value'] = \
                int(progress / self.loading_pbar_length * 100)
            self.update()
            if msg == "TEARDOWN":
                self.after(1000, self.destroy)
                self.close_warning(1)
                self.after(1000, lambda: self.close_warning(0))
            else:
                self.after(100, self.watch_for_end_result)
        except queue.Empty:
            self.after(100, self.watch_for_end_result)

    def close_warning(self, num_to_show):
        msg = "Closing window in %d seconds..." % num_to_show
        self.loading_status_text.set(msg)

    def on_closing(self):
        resp = PauseOrEndDialogue(self, db_logger=self.db_logger).show()
        self.logger.debug('User clicked on window manager close button; '
                          'asking for clarification')
        if resp == 'end':
            self.logger.info('Received end session signal from '
                             'PauseOrEndDialogue')
            self.session_end()
        elif resp == 'pause':
            self.logger.info('Received pause session signal from '
                             'PauseOrEndDialogue')
            self.destroy()
        elif resp == 'cancel':
            self.logger.info('User clicked Cancel in PauseOrEndDialogue')


class PauseOrEndDialogue(tk.Toplevel):
    def __init__(self, parent, db_logger):
        super(PauseOrEndDialogue, self).__init__(parent)
        self.response = tk.StringVar()
        self.parent = parent
        self.screen_res = parent.screen_res
        self.geometry(self.screen_res.get_center_geometry_string(480, 200))
        self.grab_set()
        self.title("Confirm exit")
        self.bell()

        self.end_icon = tk.PhotoImage(file=resource_path('window-close.png'))
        self.pause_icon = tk.PhotoImage(file=resource_path('pause.png'))
        self.cancel_icon = tk.PhotoImage(
            file=resource_path('arrow-alt-circle-left.png')
        )
        self.error_icon = tk.PhotoImage(file=resource_path('error-icon.png'))

        self.top_frame = tk.Frame(self)
        self.button_frame = tk.Frame(self, padx=15, pady=10)
        self.label_frame = tk.Frame(self.top_frame)

        self.top_label = ttk.Label(self.label_frame,
                                   text="Are you sure?",
                                   font=("TkDefaultFont", 12, "bold"),
                                   wraplength=250,
                                   anchor='w',
                                   justify='left')

        if db_logger.session_started:
            msg = "Are you sure you want to exit? If so, please choose " \
                  "whether to end the current session, or pause it so it may " \
                  "be continued by running the Session Logger application " \
                  "again. Click \"Cancel\" to return to the main screen."
        else:
            msg = "Are you sure you want to exit?\nPlease choose an option " \
                  "below."

        self.warn_label = ttk.Label(self.label_frame,
                                    wraplength=250,
                                    anchor='w',
                                    justify='left',
                                    text=msg)

        self.error_icon_label = ttk.Label(self.top_frame,
                                          background=self['background'],
                                          foreground="#000000",
                                          relief="flat",
                                          image=self.error_icon)

        if not db_logger.session_started:
            end_text = "Exit logger"
        else:
            end_text = "End session"

        self.end_button = tk.Button(self.button_frame,
                                    text=end_text,
                                    command=self.click_end,
                                    padx=10, pady=5, width=80,
                                    compound=tk.LEFT,
                                    image=self.end_icon)
        self.pause_button = tk.Button(self.button_frame,
                                      text='Pause session',
                                      command=self.click_pause,
                                      padx=10, pady=5, width=80,
                                      compound=tk.LEFT,
                                      image=self.pause_icon)
        self.cancel_button = tk.Button(self.button_frame,
                                       text='Cancel',
                                       command=self.click_cancel,
                                       padx=10, pady=5, width=80,
                                       compound=tk.LEFT,
                                       image=self.cancel_icon)

        self.top_frame.grid(row=0, column=0)
        self.error_icon_label.grid(column=0, row=0, padx=20, pady=25)
        self.label_frame.grid(column=1, row=0, padx=0, pady=0)
        self.top_label.grid(row=0, column=0, padx=10, pady=0, sticky=tk.SW)
        self.warn_label.grid(row=1, column=0, padx=10, pady=(5, 0))

        self.button_frame.grid(row=1, column=0, ipadx=10, ipady=5)
        self.end_button.grid(row=0, column=0,  padx=10)
        if db_logger.session_started:
            self.pause_button.grid(row=0, column=1, padx=10)
        self.cancel_button.grid(row=0, column=2, padx=10)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.focus_force()
        self.resizable(False, False)
        self.transient(parent)

        if db_logger.session_started:
            ToolTip(self.end_button,
                    msg="Ending the session will close this window and start the "
                        "record building process (don't click unless you're sure "
                        "you've saved all your data to the network share!)",
                    header_msg='Warning!',
                    delay=0.05)
            ToolTip(self.pause_button,
                    msg="Pausing the session will leave the NexusLIMS database in "
                        "an inconsistent state. Please only do this if you plan to "
                        "immediately resume the session before another user uses "
                        "the tool (such as if you need to reboot the computer). To "
                        "resume the session, simply run this application again and "
                        "you will be prompted whether to continue or start a new "
                        "session.",
                    header_msg='Warning!',
                    delay=0.05)

        self.protocol("WM_DELETE_WINDOW", self.click_close)
        self.parent.disable_buttons()

    def show(self):
        self.wm_deiconify()
        self.focus_force()
        self.wait_window()
        return self.response.get()

    def click_end(self):
        self.response.set('end')
        self.destroy()

    def click_pause(self):
        self.response.set('pause')
        self.destroy()

    def click_cancel(self):
        self.response.set('cancel')
        self.destroy()

    def click_close(self):
        self.click_cancel()

    def destroy(self):
        super(PauseOrEndDialogue, self).destroy()
        self.parent.enable_buttons()


class HangingSessionDialog(tk.Toplevel):
    def __init__(self, parent, db_logger):
        super(HangingSessionDialog, self).__init__(parent)
        self.response = tk.StringVar()
        self.parent = parent
        self.screen_res = parent.screen_res
        self.geometry(self.screen_res.get_center_geometry_string(400, 250))
        self.grab_set()
        self.title("Incomplete session warning")
        self.bell()

        if db_logger.last_session_ts is not None:
            last_session_dt = datetime.strptime(db_logger.last_session_ts,
                                                "%a, %d %b %Y %H:%M:%S %Z")
            last_session_timestring = format_date(last_session_dt, with_newline=False)
        else:
            last_session_timestring = 'UNKNOWN'

        self.new_icon = tk.PhotoImage(file=resource_path('file-plus.png'))
        self.continue_icon = tk.PhotoImage(file=resource_path('arrow-alt-circle-right.png'))
        self.error_icon = tk.PhotoImage(file=resource_path('error-icon.png'))

        self.top_frame = tk.Frame(self)
        self.button_frame = tk.Frame(self, padx=15, pady=10)
        self.label_frame = tk.Frame(self.top_frame)

        self.top_label = ttk.Label(self.label_frame,
                                   text="Warning!",
                                   font=("TkDefaultFont", 14, "bold"),
                                   wraplength=250,
                                   anchor='w',
                                   justify='left')
        msg = "An interrupted session was found in the database for this " \
              "instrument (started on {}). ".format(last_session_timestring)

        db_logger.logger.warning(msg)

        msg += "Would you like to continue that existing session, or end it " \
               "and start a new one?"

        self.warn_label = ttk.Label(self.label_frame,
                                    wraplength=250,
                                    anchor='w',
                                    justify='left',
                                    text=msg)

        self.error_icon_label = ttk.Label(self.top_frame,
                                          background=self['background'],
                                          foreground="#000000",
                                          image=self.error_icon)

        self.continue_button = tk.Button(self.button_frame,
                                         text='Continue',
                                         command=self.click_continue,
                                         padx=10,
                                         pady=5,
                                         width=80,
                                         compound=tk.LEFT,
                                         image=self.continue_icon)
        self.new_button = tk.Button(self.button_frame,
                                    text='New session',
                                    command=self.click_new,
                                    padx=10,
                                    pady=5,
                                    width=80,
                                    compound=tk.LEFT,
                                    image=self.new_icon)

        self.top_frame.grid(row=0, column=0)
        self.error_icon_label.grid(column=0, row=0, padx=20, pady=25)
        self.label_frame.grid(column=1, row=0, padx=0, pady=0)
        self.top_label.grid(row=0, column=0, padx=10, pady=0, sticky=tk.SW)
        self.warn_label.grid(row=1, column=0, padx=10, pady=(5, 0))

        self.button_frame.grid(row=1, column=0, sticky=tk.S, ipadx=10, ipady=5)
        self.continue_button.grid(row=0, column=0, sticky=tk.E, padx=15)
        self.new_button.grid(row=0, column=1, sticky=tk.W, padx=15)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.focus_force()
        self.resizable(False, False)
        self.transient(parent)

        self.protocol("WM_DELETE_WINDOW", self.click_close)
        self.parent.disable_buttons()

    def show(self):
        self.wm_deiconify()
        self.focus_force()
        self.wait_window()
        return self.response.get()

    def click_new(self):
        self.response.set('new')
        self.destroy()

    def click_continue(self):
        self.response.set('continue')
        self.destroy()

    def click_close(self):
        msg = "Please choose to either continue the existing session or start a new one."
        tkinter.messagebox.showerror(parent=self, title="Error", message=msg)

    def destroy(self):
        super().destroy()
        self.parent.enable_buttons()


class LogWindow(tk.Toplevel):
    def __init__(self, parent, is_error=False):
        """
        Create and raise a window showing a text field that holds the session
        logger `log_text`

        Parameters
        ----------
        parent : MainApp
            The MainApp (or other widget) this LogWindow is associated with
        is_error : bool
            If True, closing the log window will close the whole application
        """
        super(LogWindow, self).__init__(parent, padx=3, pady=3)
        self.screen_res = parent.screen_res
        self.transient(parent)
        self.grab_set()
        self.geometry(self.screen_res.get_center_geometry_string(450, 350))
        self.title('NexusLIMS Session Logger Log')

        self.text_label = tk.Label(self,
                                   text="Session Debugging Log:",
                                   padx=5,
                                   pady=5)
        self.text = tk.Text(self, width=40, height=10, wrap='none')

        msg = (
            "--------------------------------------------------------\n"
            "If you encounter an error, please send the following log\n"
            "information to nexuslims developers for assistance.     \n"
            "--------------------------------------------------------\n"
        )
        self.text.insert('1.0', msg + '\n' + parent.log_text.getvalue())

        self.s_v = ttk.Scrollbar(self,
                                 orient=tk.VERTICAL,
                                 command=self.text.yview)
        self.s_h = ttk.Scrollbar(self,
                                 orient=tk.HORIZONTAL,
                                 command=self.text.xview)

        self.text['yscrollcommand'] = self.s_v.set
        self.text['xscrollcommand'] = self.s_h.set
        self.text.configure(state='disabled')

        self.button_frame = tk.Frame(self, padx=15, pady=10)

        self.copy_icon = tk.PhotoImage(file=resource_path('copy.png'))
        self.close_icon = tk.PhotoImage(file=resource_path('window-close.png'))

        self.copy_button = tk.Button(self.button_frame,
                                     text='Copy',  # log to clipboard',
                                     command=lambda: self.copy_text_to_clipboard(),
                                     padx=10,
                                     pady=5,
                                     width=60,
                                     compound="left",
                                     image=self.copy_icon)
        ToolTip(self.copy_button,
                msg="Copy log information to clipboard",
                delay=0.25)

        def _close_cmd():
            """
            Fix for LogWindow preventing app from closing if there was an error
            """
            self.destroy()
            parent.destroy()
            sys.exit(1)

        self.close_button = tk.Button(self.button_frame,
                                      text='Close',  # window',
                                      command=self.destroy if not is_error else
                                      _close_cmd,
                                      padx=10, pady=5, width=60,
                                      compound=tk.LEFT, image=self.close_icon)

        # Make close window button do same thing as regular close button
        self.protocol("WM_DELETE_WINDOW",
                      self.destroy if not is_error else lambda: sys.exit(1))

        ToolTip(self.close_button,
                msg="Close this window" if not is_error else
                "Close the application; make sure to copy the log if you need!",
                delay=0.25)

        self.text_label.grid(column=0, row=0, sticky=tk.SW)
        self.text.grid(column=0, row=1, sticky=tk.NSEW)
        self.s_v.grid(column=1, row=1, sticky=tk.NS)
        self.s_h.grid(column=0, row=2, sticky=tk.EW)
        self.button_frame.grid(row=3, column=0, sticky=tk.S, ipadx=10)
        self.copy_button.grid(row=0, column=0, sticky=tk.E, padx=10)
        self.close_button.grid(row=0, column=1, sticky=tk.W, padx=10)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.focus_force()
        if is_error:
            self.change_close_button(1, tk.DISABLED)
            self.after(1000, lambda: self.change_close_button(0, tk.ACTIVE))

    def change_close_button(self, num_to_show, state=tk.DISABLED):
        if num_to_show == 0:
            self.close_button.configure(text='Close', state=state)
        else:
            self.close_button.configure(
                text='Close (%d})' % num_to_show,
                state=state
            )
        self.close_button.grid(row=0, column=1, sticky=tk.W, ipadx=10, padx=10)

    def copy_text_to_clipboard(self):
        text_content = self.text.get('1.0', 'end')
        self.clipboard_clear()
        if sys.platform == 'win32':
            text_content = text_content.replace('\n', '\r\n')

        self.clipboard_append(text_content)
        self.update()


class NoteWindow(tk.Toplevel):
    def __init__(self, parent, is_error=False):
        """
        Create and raise a window showing a text input field so users can add
        session note to the current session; the last saved session note will
        gets written to the session log database when user ends the current
        session

        Parameters
        ----------
        parent : MainApp
            The MainApp (or other widget) this NoteWindow is associated with
        is_error : bool
            If True, closing the Note window will close the whole application
        """
        super(NoteWindow, self).__init__(parent, padx=3, pady=3)
        self.screen_res = parent.screen_res
        self.transient(parent)
        self.grab_set()
        self.geometry(self.screen_res.get_center_geometry_string(450, 450))
        self.title('Add Note to the Current Session')
        self.parent = parent

        # prepare some variables
        self.old_note = self.parent.db_logger.session_note
        self.old_note = self.old_note.replace("''", "'")
        self.note = tk.StringVar()
        self.note.set(self.old_note)

        self.session_note = tk.Text(self,
                                    width=40,
                                    height=10,
                                    wrap='word',
                                    font=("TkDefaultFont", 14))
        self.s_v = ttk.Scrollbar(self,
                                 orient=tk.VERTICAL,
                                 command=self.session_note.yview)
        self.s_h = ttk.Scrollbar(self,
                                 orient=tk.HORIZONTAL,
                                 command=self.session_note.xview)

        self.session_note['yscrollcommand'] = self.s_v.set
        self.session_note['xscrollcommand'] = self.s_h.set
        self.session_note.insert("1.0", self.old_note)

        # add functional buttons
        self.button_frame = tk.Frame(self, padx=15, pady=10)

        self.save_icon = tk.PhotoImage(file=resource_path('save.png'))
        self.clear_icon = tk.PhotoImage(file=resource_path('clear.png'))
        self.close_icon = tk.PhotoImage(file=resource_path('window-close.png'))

        self.clear_button = tk.Button(self.button_frame,
                                      text='Clear',  # clear saved note',
                                      command=lambda: self.delete_note(),
                                      padx=10,
                                      pady=5,
                                      width=60,
                                      compound="left",
                                      image=self.clear_icon)

        self.save_button = tk.Button(self.button_frame,
                                     text='Save',  # log to clipboard',
                                     command=lambda: self.save_note(),
                                     padx=10,
                                     pady=5,
                                     width=60,
                                     compound="left",
                                     image=self.save_icon)
        ToolTip(self.save_button,
                msg="Save session note before closing this window",
                delay=0.25)

        def _close_cmd():
            """
            Fix for LogWindow preventing app from closing if there was an error
            """
            parent.notes = self.old_note
            self.destroy()
            parent.destroy()
            sys.exit(1)

        self.close_button = tk.Button(self.button_frame,
                                      text='Close',  # window',
                                      command=self.destroy if not is_error else
                                      _close_cmd,
                                      padx=10, pady=5, width=60,
                                      compound=tk.LEFT, image=self.close_icon)
        # Make close window button do same thing as regular close button
        self.protocol("WM_DELETE_WINDOW",
                      self.destroy if not is_error else lambda: sys.exit(1))

        ToolTip(self.close_button,
                msg="Close this window" if not is_error else
                "Close the application; make sure to copy the log if you need!",
                delay=0.25)

        # self.text_label.grid(column=0, row=0, sticky=(S, W))
        self.session_note.grid(column=0, row=1, sticky=tk.NSEW)
        self.s_v.grid(column=1, row=1, sticky=tk.NS)
        self.s_h.grid(column=0, row=2, sticky=tk.EW)
        self.button_frame.grid(row=3, column=0, sticky=tk.S, ipadx=10)
        self.clear_button.grid(row=0, column=1, sticky=tk.E, padx=10)
        self.save_button.grid(row=0, column=0, sticky=tk.E, padx=10)
        self.close_button.grid(row=0, column=2, sticky=tk.W, padx=10)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.focus_force()
        if is_error:
            self.change_close_button(1, tk.DISABLED)
            self.after(1000, lambda: self.change_close_button(0, tk.ACTIVE))

    def save_note(self):
        # Save the current session note in the text box, overwrite previous saved note
        self.note = self.session_note.get("1.0", tk.END)
        # escape single quote by doubling it so it won't cause
        # issues with sql insert_statement
        self.note = self.note.replace("'", "''")
        if self.note != self.old_note:
            self.old_note = self.note
            # self.parent.notes = self.note
            self.parent.db_logger.session_note = self.note

    def delete_note(self):
        # delete the current session note in the text box
        self.session_note.delete("1.0", tk.END)

    def change_close_button(self, num_to_show, state=tk.DISABLED):
        if num_to_show == 0:
            self.close_button.configure(text='Close', state=state)
        else:
            self.close_button.configure(text='Close ({})'.format(
                num_to_show), state=state)
        self.close_button.grid(row=0, column=1, sticky=tk.W, ipadx=10, padx=10)

    def copy_text_to_clipboard(self):
        text_content = self.text.get('1.0', 'end')
        self.clipboard_clear()
        if sys.platform == 'win32':
            text_content = text_content.replace('\n', '\r\n')

        self.clipboard_append(text_content)
        self.update()


class ToolTip(tk.Toplevel):
    """
    Provides a ToolTip widget for Tkinter.
    To apply a ToolTip to any Tkinter widget, simply pass the widget to the
    ToolTip constructor
    """

    def __init__(self, wdgt, tooltip_font="TkDefaultFont", msg=None,
                 msgFunc=None, header_msg=None, delay=1, follow=True):
        """
        Initialize the ToolTip

        Parameters
        ----------
        wdgt :
            The widget this ToolTip is assigned to
        tooltip_font : str
            Font to be used
        msg : str
            A static string message assigned to the ToolTip
        msgFunc : object
            A function that retrieves a string to use as the ToolTip text
        delay : float
            The delay in seconds before the ToolTip appears
        follow : bool
            If True, the ToolTip follows motion, otherwise hides
        """
        self.wdgt = wdgt
        # The parent of the ToolTip is the parent of the ToolTips widget
        self.parent = self.wdgt.master
        # Initialise the Toplevel
        tk.Toplevel.__init__(self, self.parent, bg='black', padx=1, pady=1)
        # Hide initially
        self.withdraw()
        # The ToolTip Toplevel should have no frame or title bar
        self.overrideredirect(True)

        # The msgVar will contain the text displayed by the ToolTip
        self.msgVar = tk.StringVar()
        self.header_msgVar = tk.StringVar()
        if msg is None:
            self.msgVar.set('No message provided')
        else:
            self.msgVar.set(msg)
        if header_msg is None:
            self.header_msgVar.set('')
        else:
            self.header_msgVar.set(header_msg)
        self.msgFunc = msgFunc
        self.delay = delay
        self.follow = follow
        self.visible = 0
        self.lastMotion = 0

        if header_msg is not None:
            hdr_wdgt = tk.Message(self, textvariable=self.header_msgVar,
                                  bg='#FFFFDD', font=(tooltip_font, 8, 'bold'),
                                  aspect=1000, justify='left', anchor=tk.W, pady=0)
            msg_wdgt = tk.Message(self, textvariable=self.msgVar, bg='#FFFFDD',
                                  font=tooltip_font, aspect=1000, pady=0)

            hdr_wdgt.grid(row=0, sticky=(tk.W, tk.E, tk.S), pady=(0, 0))
            msg_wdgt.grid(row=1)

        else:
            # The text of the ToolTip is displayed in a Message widget
            tk.Message(self, textvariable=self.msgVar, bg='#FFFFDD',
                       font=tooltip_font, aspect=1000).grid()

        # Add bindings to the widget.  This will NOT override
        # bindings that the widget already has
        self.wdgt.bind('<Enter>', self.spawn, '+')
        self.wdgt.bind('<Leave>', self.hide, '+')
        self.wdgt.bind('<Motion>', self.move, '+')

    def spawn(self, event=None):
        """
        Spawn the ToolTip.  This simply makes the ToolTip eligible for display.
        Usually this is caused by entering the widget

        Arguments:
          event: The event that called this function
        """
        self.visible = 1
        # The after function takes a time argument in milliseconds
        self.after(int(self.delay * 1000), self.show)

    def show(self):
        """
        Displays the ToolTip if the time delay has been long enough
        """
        if self.visible == 1 and time.time() - self.lastMotion > self.delay:
            self.visible = 2
        if self.visible == 2:
            self.deiconify()

    def move(self, event):
        """
        Processes motion within the widget.
        Arguments:
          event: The event that called this function
        """
        self.lastMotion = time.time()
        # If the follow flag is not set, motion within the
        # widget will make the ToolTip disappear
        #
        if self.follow is False:
            self.withdraw()
            self.visible = 1

        # Offset the ToolTip 20x10 pixes southwest of the pointer
        self.geometry('+%i+%i' % (event.x_root + 20, event.y_root - 10))
        try:
            # Try to call the message function.  Will not change
            # the message if the message function is None or
            # the message function fails
            self.msgVar.set(self.msgFunc())
        except Exception:
            pass
        self.after(int(self.delay * 1000), self.show)

    def hide(self, event=None):
        """
        Hides the ToolTip.  Usually this is caused by leaving the widget
        Arguments:
          event: The event that called this function
        """
        self.visible = 0
        self.withdraw()
