"""LoggerTEM GUI"""
import io
import logging
import os
import platform
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox
from tkinter import ttk

import zmq

from .utils import resource_path

COMPUTER_NAME = platform.node().split('.')[0]


class App(tk.Tk):
    def __init__(self, hubaddr, watchdir,
                 user=None, screen_res=None, logger=None, log_text=None):
        super(App, self).__init__()

        # zmq socket
        self.hubaddr = hubaddr
        self.zmqcxt = zmq.Context()

        self.watchdir = watchdir
        self.user = user

        # screen res
        self.screen_res = screen_res or ScreenRes()

        # logging
        self.logger = logger or logging.getLogger('GUI')
        self.logger.info('Creating the session logger instance')
        self.log_text = log_text or io.StringIO()

        # computer name
        self.computer_name = COMPUTER_NAME

        # button container
        self.buttons = []

        # start/end thread
        self.startup_thread_queue = queue.Queue()
        self.end_thread_queue = queue.Queue()

        # GUI styling
        self.style = ttk.Style(self)
        self.info_font = 'TkDefaultFont 16 bold'
        self.geometry(self.screen_res.get_center_geometry_string(350, 600))
        self.resizable(False, False)
        self.title("NexusLIMS Session Logger")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.icon = tk.PhotoImage(master=self, file=resource_path("logo_bare.png"))
        self.wm_iconphoto(True, self.icon)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)  # logo
        self.rowconfigure(1, weight=3)  # info
        self.rowconfigure(2, weight=1)  # button
        self.logger.info('Created the top level window')

        self.create_widgets()
        self.logger.info("Widgets created.")

        # start session
        self.session_started = False
        self.session_note = ''
        self.session_startup()

    def on_closing(self):
        """actions when user is closing the main window."""

        resp = PauseOrEndDialogue(self).show()
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

    def create_widgets(self):
        """draw widgets on main frame."""

        self.draw_logo()
        self.draw_info()
        self.draw_buttons()

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
        """information section

        incl. loading text, progress bar, instrument label, datetime
        """

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
                                         command=lambda: self.generate_data(),
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

    def session_startup(self):
        """start ``startup_thread``, update loading progress bar."""

        self.startup_thread = threading.Thread(
            target=self.session_startup_worker
        )
        self.startup_thread.start()
        self.loading_pbar_length = 5.0
        self.after(100, self.watch_for_startup_result)

    def session_startup_worker(self):
        """communicate with hub via socket to perform start session tasks."""
        start_success = False

        socket = self.zmqcxt.socket(zmq.REQ)
        socket.connect(self.hubaddr)
        with socket:
            socket.send_json({'client_id': self.computer_name, 'user': self.user,  'cmd': 'SETUP'})
            msg = socket.recv_json()
            if msg['exception']:
                self.startup_thread_queue.put(Exception(msg['message']))
                return
            self.startup_thread_queue.put((msg['message'], msg['progress']))

            socket.send_json({'client_id': self.computer_name,
                              'user': self.user,  'cmd': 'LAST_SESSION_CHECK'})
            msg = socket.recv_json()
            if msg['exception']:
                self.startup_thread_queue.put(Exception(msg['message']))
                return

            if msg['state']:
                self.startup_thread_queue.put((msg['message'], msg['progress']))

                socket.send_json({'client_id': self.computer_name,
                                  'user': self.user,  'cmd': 'START_PROCESS'})
                msg = socket.recv_json()
                if msg['exception']:
                    self.startup_thread_queue.put(Exception(msg['message']))
                    return
                self.startup_thread_queue.put((msg['message'], msg['progress']))

                socket.send_json({'client_id': self.computer_name,
                                  'user': self.user,  'cmd': 'START_PROCESS_CHECK'})
                msg = socket.recv_json()
                if msg['exception']:
                    self.startup_thread_queue.put(Exception(msg['message']))
                    return
                self.startup_thread_queue.put((msg['message'], msg['progress']))

                socket.send_json({'client_id': self.computer_name,
                                  'user': self.user,  'cmd': 'TEAR_DOWN'})
                msg = socket.recv_json()
                # put more information for TEARDOWN
                self.startup_thread_queue.put((msg['message'], msg['progress']))

                start_success = True

            else:
                # we got an inconsistent state from the DB, so ask user
                # what to do about it
                response = HangingSessionDialog(self).show()
                if response == 'new':
                    # we need to end the existing session that was found
                    # and then create a new one by changing the session_id to
                    # a new UUID4 and running process_start
                    self.loading_pbar_length = 7.0
                    # self.db_logger.session_id = self.db_logger.last_session_id
                    self.logger.info('Chose to start a new session; '
                                     'ending the existing session with id')

                    socket.send_json({'client_id': self.computer_name,
                                      'user': self.user, 'cmd': 'END_PROCESS'})
                    msg = socket.recv_json()
                    if msg['exception']:
                        self.startup_thread_queue.put(Exception(msg['message']))
                        return
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name,
                                      'user': self.user,  'cmd': 'END_PROCESS_CHECK'})
                    msg = socket.recv_json()
                    if msg['exception']:
                        self.startup_thread_queue.put(Exception(msg['message']))
                        return
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name, 'user': self.user,
                                      'cmd': 'UPDATE_START_RECORD'})
                    msg = socket.recv_json()
                    if msg['exception']:
                        self.startup_thread_queue.put(Exception(msg['message']))
                        return
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name, 'user': self.user,
                                      'cmd': 'UPDATE_START_RECORD_CHECK'})
                    msg = socket.recv_json()
                    if msg['exception']:
                        self.startup_thread_queue.put(Exception(msg['message']))
                        return
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name,
                                      'user': self.user,  'cmd': 'START_PROCESS'})
                    msg = socket.recv_json()
                    if msg['exception']:
                        self.startup_thread_queue.put(Exception(msg['message']))
                        return
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name, 'user': self.user,
                                      'cmd': 'START_PROCESS_CHECK'})
                    msg = socket.recv_json()
                    if msg['exception']:
                        self.startup_thread_queue.put(Exception(msg['message']))
                        return
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name,
                                      'user': self.user,  'cmd': 'TEAR_DOWN'})
                    msg = socket.recv_json()
                    # put more information for TEARDOWN
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    start_success = True
                elif response == 'continue':
                    # we set the session_id to the one that was previously
                    # found (and set the time accordingly, and only run the
                    # teardown instead of process_start
                    self.loading_pbar_length = 2.0
                    self.running_Label_1.configure(text='Continuing the last session for the')
                    self.running_Label_2.configure(text=' started at ')
                    self.logger.info('Chose to continue the existing '
                                     'session; setting the logger\'s '
                                     'session_id to the existing value')
                    socket.send_json({'client_id': self.computer_name, 'user': self.user,
                                      'cmd': 'CONTINUE_LAST_SESSION'})
                    msg = socket.recv_json()
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    socket.send_json({'client_id': self.computer_name,
                                      'user': self.user,  'cmd': 'TEAR_DOWN'})
                    msg = socket.recv_json()
                    # put more information for TEARDOWN
                    self.startup_thread_queue.put((msg['message'], msg['progress']))

                    start_success = True

            if start_success:
                socket.send_json({'client_id': self.computer_name, 'user': self.user,
                                  'cmd': 'START_SYNC', 'watchdir': self.watchdir})
                msg = socket.recv_json()
                if msg['exception']:
                    self.startup_thread_queue.put(Exception(msg['message']))
                    return
                self.logger.info("Sync thread started.")

    def watch_for_startup_result(self):
        """Check if there is something in the queue.

        update loading text and progress bar.
        """

        try:
            res = self.startup_thread_queue.get(0)
            self.show_error_if_needed(res)
            msg, progress = res
            if isinstance(msg, str):
                self.loading_status_text.set(msg)
            self.loading_pbar['value'] = \
                int(progress / self.loading_pbar_length * 100)
            self.update()
            if isinstance(msg, dict):
                self.loading_status_text.set('TEARDOWN')
                self.instr_string.set(msg['instrument_schema'])
                self.datetime_string.set(msg['session_start_ts'])
                self.session_note = msg['session_note']
                self.logger.info("Session started.")
                self.session_started = True
                self.done_loading()

            else:
                self.after(100, self.watch_for_startup_result)
        except queue.Empty:
            self.after(100, self.watch_for_startup_result)

    def session_end(self):
        """routines for session ending.

        change the frame, update loading text and progress bar.
        """

        # signal the startup thread to exit (if it's still running)
        # self.startup_thread_exit_queue.put(True)

        # do this in a separate end_thread (since it could take some time)
        if not self.session_started:
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
        """communicate with hub via socket to perform end session tasks."""
        socket = self.zmqcxt.socket(zmq.REQ)
        socket.connect(self.hubaddr)
        with socket:
            socket.send_json({'client_id': self.computer_name,
                             'user': self.user, 'cmd': 'END_PROCESS'})
            msg = socket.recv_json()
            if msg['exception']:
                self.end_thread_queue.put(Exception(msg['message']))
                return
            self.end_thread_queue.put((msg['message'], msg['progress']))

            socket.send_json({'client_id': self.computer_name,
                             'user': self.user, 'cmd': 'END_PROCESS_CHECK'})
            msg = socket.recv_json()
            if msg['exception']:
                self.end_thread_queue.put(Exception(msg['message']))
                return
            self.end_thread_queue.put((msg['message'], msg['progress']))

            socket.send_json({'client_id': self.computer_name,
                              'user': self.user, 'cmd': 'UPDATE_START_RECORD'})
            msg = socket.recv_json()
            if msg['exception']:
                self.end_thread_queue.put(Exception(msg['message']))
                return
            self.end_thread_queue.put((msg['message'], msg['progress']))

            socket.send_json({'client_id': self.computer_name, 'user': self.user,
                              'cmd': 'UPDATE_START_RECORD_CHECK'})
            msg = socket.recv_json()
            if msg['exception']:
                self.end_thread_queue.put(Exception(msg['message']))
                return
            self.end_thread_queue.put((msg['message'], msg['progress']))

            prog_num = msg['progress']  # keep using the same progress number for next

            socket.send_json({'client_id': self.computer_name,
                              'user': self.user,  'cmd': 'STOP_SYNC'})
            msg = socket.recv_json()
            if msg['exception']:
                self.end_thread_queue.put(Exception(msg['message']))
                return
            self.end_thread_queue.put((msg['message'], prog_num))

            self.logger.debug("Final sync finished.")

            socket.send_json({'client_id': self.computer_name,
                              'user': self.user,  'cmd': 'TEAR_DOWN'})
            msg = socket.recv_json()
            self.end_thread_queue.put((msg['message'], msg['progress']))

    def watch_for_end_result(self):
        """Check if there is something in the queue.

        update loading text and progress bar.
        """

        try:
            res = self.end_thread_queue.get(0)
            self.show_error_if_needed(res)
            msg, progress = res
            if isinstance(msg, str):
                self.loading_status_text.set(msg)
            self.loading_pbar['value'] = \
                int(progress / self.loading_pbar_length * 100)
            self.update()
            if isinstance(msg, dict):
                self.loading_status_text.set('TEARDOWN')
                self.after(1000, self.destroy)
                self.close_warning(1)
                self.after(1000, lambda: self.close_warning(0))
            else:
                self.after(100, self.watch_for_end_result)
        except queue.Empty:
            self.after(100, self.watch_for_end_result)

    def close_warning(self, num_to_show):
        """set loading text to remind the closing action"""

        msg = "Closing window in %d seconds..." % num_to_show
        self.loading_status_text.set(msg)

    def generate_data(self):
        """communicate with hub via socket to generate data"""
        socket = self.zmqcxt.socket(zmq.REQ)
        socket.connect(self.hubaddr)
        socket.send_json({'client_id': self.computer_name,
                          'user': self.user,
                          'cmd': 'MAKE_DATA',
                          'outputdir': self.watchdir})
        msg = socket.recv_json()
        self.logger.info(msg['message'])
        socket.close()

    def show_error_if_needed(self, res):
        """show error box if ``res`` is an ``Exception``"""
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
        """actions by the end of loading.

        put off ``setup_frame``, put up ``running_frame`` and labels, enable buttons.
        """

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
        """actions by the start of ending.

        put off ``running_frame``; putup ``setup_frame``, diable buttons
        """

        # Remove the setup_frame contents
        self.running_frame.grid_forget()

        # grid the setup_frame contents again
        self.setup_frame.grid(row=1, column=0)

        # disable the buttons
        self.disable_buttons()

    def save_note(self):
        socket = self.zmqcxt.socket(zmq.REQ)
        socket.connect(self.hubaddr)
        with socket:
            socket.send_json({'client_id': self.computer_name,
                              'user': self.user,
                              'cmd': 'SAVE_NOTE',
                              'argv': [self.session_note]})
            msg = socket.recv_json()
            self.logger.info(msg['message'])

    def destroy(self):
        socket = self.zmqcxt.socket(zmq.REQ)
        socket.connect(self.hubaddr)
        with socket:
            socket.send_json({'client_id': self.computer_name,
                             'user': self.user,  'cmd': 'DESTROY'})
            msg = socket.recv_json()
            self.logger.info(msg['message'])
        super(App, self).destroy()


class PauseOrEndDialogue(tk.Toplevel):
    """Dialogue window prompts user for actions when the user
     is closing the main window"""

    def __init__(self, parent):
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

        if parent.session_started:
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

        if not parent.session_started:
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
        if parent.session_started:
            self.pause_button.grid(row=0, column=1, padx=10)
        self.cancel_button.grid(row=0, column=2, padx=10)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self.focus_force()
        self.resizable(False, False)
        self.transient(parent)

        if parent.session_started:
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
        """Show the dialogue window, return the user response."""

        self.wm_deiconify()
        self.focus_force()
        self.wait_window()
        return self.response.get()

    def click_end(self):
        """record action, destroy the window."""

        self.response.set('end')
        self.destroy()

    def click_pause(self):
        """record action, destroy the window."""

        self.response.set('pause')
        self.destroy()

    def click_cancel(self):
        """record action, destroy the window."""

        self.response.set('cancel')
        self.destroy()

    def click_close(self):
        """record action, destroy the window."""

        self.click_cancel()

    def destroy(self):
        """destroy the window, enable buttons on the main window."""
        super(PauseOrEndDialogue, self).destroy()
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


class HangingSessionDialog(tk.Toplevel):
    """Dialogue window prompt user for actions when previous session is
    detected not ended properly."""

    def __init__(self, parent):
        super(HangingSessionDialog, self).__init__(parent)
        self.response = tk.StringVar()
        self.parent = parent
        self.screen_res = parent.screen_res
        self.geometry(self.screen_res.get_center_geometry_string(400, 250))
        self.grab_set()
        self.title("Incomplete session warning")
        self.bell()

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
              "instrument. "

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
        """Show the dialogue window, return the user response."""

        self.wm_deiconify()
        self.parent.wait_window(self)
        return self.response.get()

    def click_new(self):
        """record action, destroy the window."""

        self.response.set('new')
        self.destroy()

    def click_continue(self):
        """record action, destroy the window."""

        self.response.set('continue')
        self.destroy()

    def click_close(self):
        """enforce user to choose between **continue**
        or **start** with en error box."""

        msg = "Please choose to either continue the existing session or start a new one."
        tkinter.messagebox.showerror(parent=self, title="Error", message=msg)

    def destroy(self):
        """destroy the window, enable buttons on the main window."""

        self.parent.enable_buttons()
        super().destroy()


class NoteWindow(tk.Toplevel):
    def __init__(self, parent):
        """
        Create and raise a window showing a text input field so users can add
        session note to the current session; the last saved session note will
        gets written to the session log database when user ends the current
        session

        Parameters
        ----------
        parent : MainApp
            The MainApp (or other widget) this NoteWindow is associated with
        """
        super(NoteWindow, self).__init__(parent, padx=3, pady=3)
        self.screen_res = parent.screen_res
        self.transient(parent)
        self.grab_set()
        self.geometry(self.screen_res.get_center_geometry_string(450, 450))
        self.title('Add Note to the Current Session')
        self.parent = parent

        # prepare some variables
        self.note = tk.StringVar(self, value=self.parent.session_note)

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
        self.session_note.insert("1.0", self.note.get())

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

        self.close_button = tk.Button(self.button_frame,
                                      text='Close',  # window',
                                      command=self.destroy,  # TODO prompt user to save or not
                                      padx=10, pady=5, width=60,
                                      compound=tk.LEFT, image=self.close_icon)
        # Make close window button do same thing as regular close button
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        ToolTip(self.close_button,
                msg="Close this window",
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

    def save_note(self):
        # Save the current session note in the text box, overwrite previous saved note
        self.note.set(self.session_note.get("1.0", tk.END))
        if self.note.get() != self.parent.session_note:
            self.parent.session_note = self.note.get()
            self.parent.save_note()

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


def help():
    res = (
        "OPTIONS:  (-s|v|vv|h)\n"
        "   -s  silent\n"
        "   -v  verbose\n"
        "   -vv debug\n"
        "   -h  help\n"
    )
    return res


def validate_config(config):
    """simple validation of config settings"""
    # NEXUSLIMSGUI_HUB_ADDRESS
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 500)
    socket.connect(config.get("NEXUSLIMSGUI_HUB_ADDRESS"))
    socket.send_json({'client_id': COMPUTER_NAME, 'cmd': 'HELLO'})
    if socket.recv_json() != {
        'state': True,
        'message': 'world',
        'exception': False
    }:
        raise ValueError("LoggerHub is not binded to `NEXUSLIMSGUI_HUB_ADDRESS`")

    # `filestore_path`
    filestore_path = config.get("NEXUSLIMSGUI_FILESTORE_PATH")
    if not os.path.isdir(filestore_path):
        raise ValueError("filestore_path `%s` does not exist" % filestore_path)

    return True


if __name__ == '__main__':
    import functools
    import getpass
    import json
    import pathlib

    from .utils import (Config, ScreenRes, check_singleton, get_logger,
                        show_error_msg_box)

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
    verbosity = logging.DEBUG
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
    config = Config()
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

    # app
    sres = ScreenRes(logger=_get_logger("SCREEN"))
    hubaddr = config.get('NEXUSLIMSGUI_HUB_ADDRESS')
    watchdir = config.get('NEXUSLIMSGUI_FILESTORE_PATH')

    app = App(hubaddr, watchdir, user=login, screen_res=sres,
              logger=_get_logger('GUI'),
              log_text=log_text)
    app.mainloop()
