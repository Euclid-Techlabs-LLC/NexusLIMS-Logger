"""LoggerHub"""
import logging
import platform
import queue
import sys
import zmq
import tkinter as tk
from urllib.parse import urljoin
from uuid import uuid4

import requests
from dateutil.parser import parse
from dateutil.tz import tzlocal


class DBSessionLogger:
    """communicate with database."""

    def __init__(self, cpu_name, dbapi_url,
                 dbapi_username=None,
                 dbapi_password=None,
                 logger=None):
        """
        Parameters
        ----------
        cpu_name : str
        dbapi_url : str
        dbapi_username : str
        dbapi_password : str
        logger : logging.Logger
        """
        self.dbapi_url = dbapi_url
        self.dbapi_auth = (dbapi_username, dbapi_password)
        self.logger = logger or logging.getLogger("DSL")

        self.cpu_name = cpu_name
        self.session_id = str(uuid4())

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

    @classmethod
    def from_config(cls, config, logger=None):
        return cls(config["NEXUSLIMSGUI_DBAPI_URL"],
                   dbapi_username=config["NEXUSLIMSGUI_DBAPI_USERNAME"],
                   dbapi_password=config["NEXUSLIMSGUI_DBAPI_PASSWORD"],
                   logger=logger)

    def reset(self):
        self.session_id = str(uuid4())

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

    def handle(self, msg):
        cmd = msg['cmd']

        if cmd == 'SETUP':
            self.reset()
            try:
                is_success, msg = self.db_logger_setup()
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

        elif cmd == 'LAST_SESSION_CHECK':
            try:
                is_success, msg = self.last_session_ended()
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

    # def check_exit_queue(self, thread_queue, exit_queue):
    #     """
    #     Check to see if a queue (``exit_queue``) has anything in it. If so,
    #     immediately exit.

    #     Parameters
    #     ----------
    #     thread_queue : queue.Queue
    #     exit_queue : queue.Queue
    #     """
    #     if exit_queue is not None:
    #         try:
    #             res = exit_queue.get(0)
    #             if res:
    #                 self.logger.info("Received termination signal from GUI thread", 0)
    #                 thread_queue.put(ChildProcessError("Terminated from GUI "
    #                                                    "thread"))
    #                 sys.exit("Saw termination queue entry")
    #         except queue.Empty:
    #             pass

    def last_session_ended(self):
        """
        Check the database for this instrument to make sure that the last
        entry in the db was an "END" (properly ended). If it's not, return
        False so the GUI can query the user for additional input on how to
        proceed.

        Parameters
        ----------
        thread_queue : queue.Queue
            Main queue for communication with the GUI
        exit_queue : queue.Queue
            Queue containing any errors so the GUI knows to exit as needed

        Returns
        -------
        state_is_consistent : bool
            If the database is consistent (i.e. the last log for this
            instrument is an "END" log), return True. If not (it's a "START"
            log), return False
        """
        # try:
        #     self.check_exit_queue(thread_queue, exit_queue)
        #     if self.instr_pid is None:
        #         raise AttributeError(
        #             "Instrument PID must be set before checking "
        #             "the database for any related sessions")
        # except Exception as e:
        #     if thread_queue:
        #         thread_queue.put(e)
        #     self.logger.error("Error encountered while checking that last "
        #                       "record for this instrument was an \"END\" log")
        #     return False

        # self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/lastsession")
        res = requests.get(url, params={"instrument": self.instr_pid}, auth=self.dbapi_auth)

        if res.status_code >= 500:
            msg = str(res.content)
            self.logger.error(msg)
            raise Exception(msg)

        if res.status_code == 404:
            last_entry_type = "END"

        if res.status_code == 200:
            data = res.json()["data"]
            self.last_entry_type = data["event_type"]
            self.last_session_id = data["session_identifier"]
            self.last_session_row_number = data["id_session_log"]
            self.last_session_ts = data["timestamp"]

        if last_entry_type == "END":
            msg = "Verified database consistency for the %s." % self.instr_schema
            self.logger.debug(msg)
            # if thread_queue:
            #     thread_queue.put((msg, self.progress_num))
            #     self.progress_num += 1
            return True, msg
        elif last_entry_type == "START":
            msg = "Database is inconsistent for the %s. " \
                  "(last entry [id_session_log = %s] was a `START`)" % (
                      self.instr_schema, self.last_session_row_number)
            self.logger.warning(msg)
            # if thread_queue:
            #     thread_queue.put((msg, self.progress_num))
            #     self.progress_num += 1
            return False, msg
        else:
            msg = "Last entry for the %s was neither `START` or `END` (value was %s)" % (
                self.instr_schema, last_entry_type)
            self.logger.error(msg)
            raise Exception(msg)

    def process_start(self, thread_queue=None, exit_queue=None):
        """
        Insert a session `'START'` log for this computer's instrument

        Returns True if successful, False if not
        """
        # Insert START log
        self.check_exit_queue(thread_queue, exit_queue)
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
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        self.session_started = True

        msg = "`START` session inserted into db."
        self.logger.info(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # verify insertion success by query db
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "START",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error verifying that session was started. " + str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        self.check_exit_queue(thread_queue, exit_queue)

        # convert GMT time to local time
        self.session_start_time = parse(data["timestamp"]).astimezone(tzlocal())

        msg = "Verified insertion of row " + str(data)
        self.logger.debug(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        return True

    def process_end(self, thread_queue=None, exit_queue=None):
        """
        Insert a session `'END'` log for this computer's instrument,
        and change the status of the corresponding `'START'` entry from
        `'WAITING_FOR_END'` to `'TO_BE_BUILT'`
        """
        # Insert END log
        self.check_exit_queue(thread_queue, exit_queue)
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
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        msg = "`END` session log inserted into db"
        self.logger.info(msg)
        if thread_queue:
            self.progress_num = 1
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # verify insertion success by querying
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "END",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error verifying that session was ended. " + str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Verified `END` session inserted into db. " + str(data)
        self.logger.debug(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # Query matched last start
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "START",
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error getting matching `START` log. " + str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Found matched `START` log: " + str(data)
        self.logger.debug(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        last_start_id = data["id_session_log"]

        # Update matched last start
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/session")
        payload = {
            "id_session_log": last_start_id,
            "record_status": "TO_BE_BUILT",
        }
        res = requests.put(url, data=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error updating matching `START` log's status. " + str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        msg = "Matching `START` session log's status updated."
        self.logger.info(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # Verify update success by querying
        self.check_exit_queue(thread_queue, exit_queue)
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error updating matching `START` log's status. " + str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Verified updated row: " + str(data)
        self.logger.debug(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        self.logger.info("Finished ending session %s" % self.session_id)

        return True

    def db_logger_setup(self):  # , thread_queue=None, exit_queue=None):
        """
        get instrument info (pid, schema name).
        """

        self.logger.info("Computer Name: %s" % self.cpu_name)
        self.logger.info("Session ID: %s" % self.session_id)

        # self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/instrument")
        payload = {
            "computer_name": self.cpu_name,
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error fetching instrument information from DB. " + str(res.content)
            self.logger.error(msg)
            raise Exception(msg)
            # if thread_queue:
            #     thread_queue.put(Exception(msg))
            # return False

        data = res.json()["data"]
        msg = "Loaded instrument information from DB"
        self.logger.info(msg)
        self.logger.debug("Instrument info: %s" % str(data))
        # if thread_queue:
        self.progress_num = 1
        # thread_queue.put((msg, self.progress_num))
        # self.progress_num += 1

        self.instr_info = data
        self.instr_pid = self.instr_info["instrument_pid"]
        self.instr_schema = self.instr_info["schema_name"]

        return True, msg

    def db_logger_teardown(self, thread_queue=None, exit_queue=None):
        """
        teardown routine
        """

        msg = "TEARDOWN"
        self.logger.debug(msg)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1
        return True


class App(tk.Tk):
    def __init__(self, port) -> None:
        super(App, self).__init__()

        # zmq socket
        self.zmqcxt = zmq.Context()
        self.socket = self.zmqcxt.socket(zmq.REP)
        self.socket.bind(f'tcp://*:{port}')

        # DBSessionLogger container
        self.dbsessionloggers = {}

    def run(self):
        while True:
            msg = self.socket.recv_json()
            client_id = msg.get('client_id')
            self.dbsessionloggers.setdefault(client_id, DBSessionLogger())
            res = self.dbsessionloggers.get(client_id).handle(msg)
            self.socket.send_json(res)
