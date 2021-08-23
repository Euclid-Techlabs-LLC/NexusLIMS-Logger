"""LoggerHub"""
import logging
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from urllib.parse import urljoin
from uuid import uuid4

import requests
import zmq
from dateutil.parser import parse
from dateutil.tz import tzlocal
from timeloop import Timeloop

from .filewatcher import FileWatcher
from .instrument import GCPInstrument
from .utils import LOGGING_FMT, get_logger, resource_path


class DBSessionLogger:
    """communicate with database."""

    def __init__(self, cpu_name, dbapi_url,
                 dbapi_username=None,
                 dbapi_password=None,
                 user=None,
                 logger=None):
        """
        Parameters
        ----------
        cpu_name : str
        user : str
        dbapi_url : str
        dbapi_username : str
        dbapi_password : str
        user : str
        logger : logging.Logger
        """
        self.dbapi_url = dbapi_url
        self.dbapi_auth = (dbapi_username, dbapi_password)
        self.user = user
        self.logger = logger or logging.getLogger("DSL")

        self.cpu_name = cpu_name
        self.session_id = None

        self.instr_info = None
        self.instr_pid = None
        self.instr_schema = None

        self.session_started = False
        self.session_start_time = None
        self.last_entry_type = None
        self.last_session_id = None
        self.last_session_row_number = None
        self.last_session_ts = None
        self.progress_num = 0

        self.session_note = ""

        self.action_map = {
            'SETUP': self.db_logger_setup,
            'LAST_SESSION_CHECK': self.last_session_ended,
            'START_PROCESS': self.process_start,
            'START_PROCESS_CHECK': self.process_start_check,
            'TEAR_DOWN': self.db_logger_teardown,
            'END_PROCESS': self.process_end,
            'END_PROCESS_CHECK': self.process_end_check,
            'UPDATE_START_RECORD': self.update_start,
            'UPDATE_START_RECORD_CHECK': self.update_start_check,
            'CONTINUE_LAST_SESSION': self.continue_last_session,
        }

    @classmethod
    def from_config(cls, config, cpu_name, user=None, logger=None):
        return cls(cpu_name,
                   config["NEXUSLIMSHUB_DBAPI_URL"],
                   dbapi_username=config["NEXUSLIMSHUB_DBAPI_USERNAME"],
                   dbapi_password=config["NEXUSLIMSHUB_DBAPI_PASSWORD"],
                   user=user,
                   logger=logger)

    def handle(self, msg):
        cmd = msg['cmd']
        try:
            is_success, msg = self.action_map[cmd]()
        except Exception as e:
            return {'state': False,
                    'exception': True,
                    'message': str(e)}

        res = {'state': is_success,
               'message': msg,
               'exception': False,
               'progress': self.progress_num}
        self.progress_num += 1
        return res

    def last_session_ended(self):
        """
        Check the database for this instrument to make sure that the last
        entry in the db was an "END" (properly ended). If it's not, return
        False so the GUI can query the user for additional input on how to
        proceed.

        Returns
        -------
        is_success : bool
            If the database is consistent (i.e. the last log for this
            instrument is an "END" log), return True. If not (it's a "START"
            log), return False
        msg : str
        """

        url = urljoin(self.dbapi_url, "/api/lastsession")
        res = requests.get(url, params={"instrument": self.instr_pid}, auth=self.dbapi_auth)

        if res.status_code >= 500:
            msg = str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        if res.status_code == 404:
            self.last_entry_type = "END"

        if res.status_code == 200:
            data = res.json()["data"]
            self.last_entry_type = data["event_type"]
            self.last_session_id = data["session_identifier"]
            self.last_session_row_number = data["id_session_log"]
            self.last_session_ts = data["timestamp"]

        if self.last_entry_type == "END":
            msg = "Verified database consistency for the %s." % self.instr_schema
            self.logger.debug(msg)
            return True, msg
        elif self.last_entry_type == "START":
            msg = "Database is inconsistent for the %s. " \
                  "(last entry [id_session_log = %s] was a `START`)" % (
                      self.instr_schema, self.last_session_row_number)
            self.logger.warning(msg)
            return False, msg
        else:
            msg = "Last entry for the %s was neither `START` or `END` (value was %s)" % (
                self.instr_schema, self.last_entry_type)
            self.logger.error(msg)
            raise Exception(msg)

    def process_start(self):
        """
        Insert a session `'START'` log for this computer's instrument

        Returns True if successful, False if not
        """
        self.session_id = str(uuid4())

        # Insert START log
        url = urljoin(self.dbapi_url, "/api/session")
        payload = {
            "event_type": "START",
            "instrument": self.instr_pid,
            "user": self.user,
            "session_identifier": self.session_id,
            "session_note": self.session_note
        }
        res = requests.post(url, data=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error inserting `START` log into DB. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        self.session_started = True

        msg = "`START` session inserted into db."
        self.logger.info(msg)

        return True, msg

    def process_start_check(self):
        # verify insertion success by query db
        url = urljoin(self.dbapi_url, "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "START",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error verifying that session was started. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        data = res.json()["data"]

        # convert GMT time to local time
        self.session_start_time = parse(data["timestamp"]).astimezone(tzlocal())

        msg = "Verified insertion of row " + str(data)
        self.logger.debug(msg)

        return True, msg

    def process_end(self):
        """
        Insert a session `'END'` log for this computer's instrument,
        and change the status of the corresponding `'START'` entry from
        `'WAITING_FOR_END'` to `'TO_BE_BUILT'`
        """
        # Insert END log
        url = urljoin(self.dbapi_url, "/api/session")
        payload = {
            "instrument": self.instr_pid,
            "event_type": "END",
            "record_status": "TO_BE_BUILT",
            "session_identifier": self.session_id,
            "session_note": self.session_note,
            "user": self.user,
        }
        res = requests.post(url, data=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error inserting `END` log for session"
            self.logger.error(msg)
            raise Exception(msg)

        msg = "`END` session log inserted into db"
        self.logger.info(msg)
        self.progress_num = 1
        return True, msg

    def process_end_check(self):
        # verify insertion success by querying
        url = urljoin(self.dbapi_url, "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "END",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error verifying that session was ended. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        data = res.json()["data"]
        msg = "Verified `END` session inserted into db. " + str(data)
        self.logger.debug(msg)
        return True, msg

    def update_start(self):
        # Query matched last start
        url = urljoin(self.dbapi_url, "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "START",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error getting matching `START` log. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        data = res.json()["data"]
        msg = "Found matched `START` log: " + str(data)
        self.logger.debug(msg)

        self.last_start_id = data["id_session_log"]

        # Update matched last start
        url = urljoin(self.dbapi_url, "/api/session")
        payload = {
            "id_session_log": self.last_start_id,
            "record_status": "TO_BE_BUILT",
        }
        res = requests.put(url, data=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error updating matching `START` log's status. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        msg = "Matching `START` session log's status updated."
        self.logger.info(msg)
        return True, msg

    def update_start_check(self):
        # Verify update success by querying
        url = urljoin(self.dbapi_url, "/api/session")
        payload = {
            "id_session_log": self.last_start_id,
            "record_status": "TO_BE_BUILT",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error updating matching `START` log's status. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        data = res.json()["data"]
        msg = "Verified updated row: " + str(data)
        self.logger.debug(msg)
        self.logger.info("Finished ending session %s" % self.session_id)

        return True, msg

    def continue_last_session(self):
        self.session_id = self.last_session_id
        self.session_started = True
        self.session_start_time = datetime.strptime(
            self.last_session_ts, "%a, %d %b %Y %H:%M:%S %Z")
        msg = 'Set start time/id as last start time/id.'
        return True, msg

    def db_logger_setup(self):
        """
        get instrument info (pid, schema name).
        """

        self.logger.info("Computer Name: %s" % self.cpu_name)

        url = urljoin(self.dbapi_url, "/api/instrument")
        payload = {
            "computer_name": self.cpu_name,
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error fetching instrument information from DB. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        data = res.json()["data"]
        msg = "Loaded instrument information from DB"
        self.logger.info(msg)
        self.logger.debug("Instrument info: %s" % str(data))

        self.progress_num = 1

        self.instr_info = data
        self.instr_pid = self.instr_info["instrument_pid"]
        self.instr_schema = self.instr_info["schema_name"]

        return True, msg

    def db_logger_teardown(self):
        """
        teardown routine
        """

        msg = "TEARDOWN"
        self.logger.debug(msg)
        return True, {
            'instrument_schema': self.instr_schema,
            'session_start_ts': self.session_start_time.strftime("%a %b %d, %Y\n%I:%M:%S %p")
        }


class QueueHandler(logging.Handler):
    """Class to send logging records to a queue
    It can be used from different threads
    The ConsoleUi class polls this queue to display records in a ScrolledText widget
    """
    # Example from Moshe Kaplan: https://gist.github.com/moshekaplan/c425f861de7bbf28ef06
    # (https://stackoverflow.com/questions/13318742/python-logging-to-tkinter-text-widget) is not thread safe!
    # See https://stackoverflow.com/questions/43909849/tkinter-python-crashes-on-new-thread-trying-to-log-on-main-thread

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)


class ConsoleUi:
    """Poll messages from a logging queue and display them in a scrolled text widget"""

    def __init__(self, frame, logger):
        self.frame = frame
        # Create a ScrolledText wdiget
        self.scrolled_text = ScrolledText(frame, state='disabled')
        self.scrolled_text.grid(row=0, column=0, columnspan=5, rowspan=2,
                                sticky=(tk.N, tk.S, tk.W, tk.E))
        self.scrolled_text.configure(font='TkFixedFont')
        self.scrolled_text.tag_config('INFO', foreground='black')
        self.scrolled_text.tag_config('DEBUG', foreground='gray')
        self.scrolled_text.tag_config('WARNING', foreground='orange')
        self.scrolled_text.tag_config('ERROR', foreground='red')
        self.scrolled_text.tag_config('CRITICAL', foreground='red', underline=1)
        # Create a logging handler using a queue
        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter(LOGGING_FMT)
        self.queue_handler.setFormatter(formatter)
        logger.addHandler(self.queue_handler)
        # Start polling messages from the queue
        self.frame.after(100, self.poll_log_queue)

    def display(self, record):
        msg = self.queue_handler.format(record)
        self.scrolled_text.configure(state='normal')
        self.scrolled_text.insert(tk.END, msg + '\n', record.levelname)
        self.scrolled_text.configure(state='disabled')
        # Autoscroll to the bottom
        self.scrolled_text.yview(tk.END)

    def poll_log_queue(self):
        # Check every 100ms if there is a new message in the queue to display
        while True:
            try:
                record = self.log_queue.get(block=False)
            except queue.Empty:
                break
            else:
                self.display(record)
        self.frame.after(100, self.poll_log_queue)


class App(tk.Tk):
    def __init__(self, config, cred_json, cache_json, verbose=logging.INFO):
        super(App, self).__init__()
        self.config = config
        self.cred_json = cred_json
        self.cache_json = cache_json
        self.logger = get_logger('HUB', verbose=verbose)
        self.thread = None

        self.geometry('600x250')
        self.style = ttk.Style(self)
        self.resizable(True, True)
        self.title('NexusLIMS Logger Hub')
        self.protocol('WM_DELETE_WINDOW', self.stop)
        self.wm_iconphoto(True, tk.PhotoImage(master=self, file=resource_path("logo_bare.png")))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        content = ttk.Frame(self, padding=(5, 5, 5, 0))
        self.start_btn = ttk.Button(content, text='Start', command=self.start)
        self.end_btn = ttk.Button(content, text='End', command=self.stop, state=tk.DISABLED)
        self.copy_btn = ttk.Button(content, text='Copy', command=self.copy_text_to_clipboard)

        content.grid(column=0, row=0, sticky=(tk.N, tk.S, tk.E, tk.W))
        self.start_btn.grid(column=1, row=3)
        self.end_btn.grid(column=2, row=3, padx=5, pady=5)
        self.copy_btn.grid(column=3, row=3)
        self.console = ConsoleUi(content, self.logger)

        content.columnconfigure(0, weight=1)
        content.columnconfigure(4, weight=1)
        content.rowconfigure(1, weight=1)

        # zmq socket
        self.zmqcxt = zmq.Context()
        self.socket = self.zmqcxt.socket(zmq.REP)
        p = self.config.get("NEXUSLIMSHUB_PORT")
        self.socket.bind(f'tcp://*:{p}')

        # containers
        self.dbsessionloggers = {}
        self.filewatchers = {}
        self.timeloops = {}
        self.gcpinstruments = {}

    def start(self):
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
        self.start_btn.configure(state=tk.DISABLED)
        self.end_btn.configure(state=tk.NORMAL)

    def run(self):
        while True:
            try:
                msg = self.socket.recv_json()
                self.logger.debug(msg)
            except zmq.error.ContextTerminated:
                break

            client_id = msg.get('client_id')
            dsl = self.dbsessionloggers.setdefault(
                client_id,
                DBSessionLogger.from_config(
                    self.config, client_id, user=msg.get('user'), logger=self.logger)
            )
            cmd = msg.get('cmd')
            res = {}
            if cmd == 'START_SYNC':
                fw = self.filewatchers.setdefault(
                    client_id, FileWatcher.from_config(self.config,
                                                       msg.get('watchdir'),
                                                       credential_fn=self.cred_json,
                                                       cache_fn=self.cache_json,
                                                       logger=self.logger))
                fw.bucket_dir = dsl.instr_info.get('filestore_path', dsl.instr_pid)
                fw.mtime_since = dsl.session_start_time.timestamp()
                fw.instr_info = dsl.instr_info

                tl = self.timeloops.setdefault(client_id, Timeloop())
                tl.logger = self.logger
                tl._add_job(fw.upload, timedelta(seconds=fw.interval))
                tl.start()
                res = {'state': True,
                       'message': 'sync thread started',
                       'exception': False}
            elif cmd == 'STOP_SYNC':
                tl = self.timeloops.get(client_id)
                try:
                    tl.stop()
                except Exception:
                    pass

                fw = self.filewatchers.get(client_id)
                fw.upload()

                res = {'state': True,
                       'message': 'sync thread stopped',
                       'exception': False}
            elif cmd == 'MAKE_DATA':
                instr = self.gcpinstruments.setdefault(
                    client_id, GCPInstrument.from_config(self.config,
                                                         msg.get('outputdir'),
                                                         credential_fn=cred_json,
                                                         logger=self.logger))
                instr.generate_data()
                res = {'state': True,
                       'message': 'copy a datafile',
                       'exception': False}
            elif cmd == 'DESTROY':
                self.dbsessionloggers.pop(client_id, None)
                self.filewatchers.pop(client_id, None)
                self.timeloops.pop(client_id, None)
                self.gcpinstruments.pop(client_id, None)
                res = {'state': True,
                       'message': 'Hub released resources',
                       'exception': False}
            elif cmd == 'HELLO':
                res = {'state': True,
                       'message': 'world',
                       'exception': False}
            else:
                res = dsl.handle(msg)

            self.socket.send_json(res)

    def stop(self):
        if not self.zmqcxt.closed:
            self.zmqcxt.destroy()
        self.destroy()

    def copy_text_to_clipboard(self):
        text = self.console.scrolled_text.get('1.0', 'end')
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()


def validate_config(config):
    # `api_url`
    api_url = config.get("NEXUSLIMSHUB_DBAPI_URL")
    res = requests.get(api_url)
    if res.status_code != 200 or res.text != "API for nexuslims-db":
        raise ValueError("api_url `%s` is not responding" % api_url)

    # `port`
    port = config.get('NEXUSLIMSHUB_PORT')
    if not isinstance(port, int) or port <= 3000:
        raise ValueError('`NEXUSLIMSHUB_PORT` must be set as integer > 3000')

    return True


if __name__ == '__main__':
    import json
    import os
    import pathlib

    from .utils import Config, check_singleton, show_error_msg_box

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

    logger = get_logger("APP", verbose=verbosity)

    # config, credential, cache
    config_fn = os.path.join(pathlib.Path.home(), "nexuslims", "gui", "hubconfig.json")
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

    # app
    app = App(config, cred_json, cache_json, verbose=verbosity)
    app.mainloop()
