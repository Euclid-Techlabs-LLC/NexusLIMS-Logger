#  NIST Public License - 2019
#
#  This software was developed by employees of the National Institute of
#  Standards and Technology (NIST), an agency of the Federal Government
#  and is being made available as a public service. Pursuant to title 17
#  United States Code Section 105, works of NIST employees are not subject
#  to copyright protection in the United States.  This software may be
#  subject to foreign copyright.  Permission in the United States and in
#  foreign countries, to the extent that NIST may hold copyright, to use,
#  copy, modify, create derivative works, and distribute this software and
#  its documentation without fee is hereby granted on a non-exclusive basis,
#  provided that this notice and disclaimer of warranty appears in all copies.
#
#  THE SOFTWARE IS PROVIDED 'AS IS' WITHOUT ANY WARRANTY OF ANY KIND,
#  EITHER EXPRESSED, IMPLIED, OR STATUTORY, INCLUDING, BUT NOT LIMITED
#  TO, ANY WARRANTY THAT THE SOFTWARE WILL CONFORM TO SPECIFICATIONS, ANY
#  IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE,
#  AND FREEDOM FROM INFRINGEMENT, AND ANY WARRANTY THAT THE DOCUMENTATION
#  WILL CONFORM TO THE SOFTWARE, OR ANY WARRANTY THAT THE SOFTWARE WILL BE
#  ERROR FREE.  IN NO EVENT SHALL NIST BE LIABLE FOR ANY DAMAGES, INCLUDING,
#  BUT NOT LIMITED TO, DIRECT, INDIRECT, SPECIAL OR CONSEQUENTIAL DAMAGES,
#  ARISING OUT OF, RESULTING FROM, OR IN ANY WAY CONNECTED WITH THIS SOFTWARE,
#  WHETHER OR NOT BASED UPON WARRANTY, CONTRACT, TORT, OR OTHERWISE, WHETHER
#  OR NOT INJURY WAS SUSTAINED BY PERSONS OR PROPERTY OR OTHERWISE, AND
#  WHETHER OR NOT LOSS WAS SUSTAINED FROM, OR AROSE OUT OF THE RESULTS OF,
#  OR USE OF, THE SOFTWARE OR SERVICES PROVIDED HEREUNDER.
#

# Code must be able to work under Python 3.4 (32-bit) due to limitations of
# the Windows XP-based microscope PCs. Using this version of Python with
# pyinstaller 3.5 seems to work on the 642 Titan

__all__ = ["DBSessionLogger"]

import logging
import platform
import queue
import sys
from urllib.parse import urljoin
from uuid import uuid4

import requests
from dateutil.parser import parse
from dateutil.tz import tzlocal


class DBSessionLogger:
    """communicate with database."""

    def __init__(self, dbapi_url,
                 dbapi_username=None,
                 dbapi_password=None,
                 user=None,
                 logger=None):
        """
        Parameters
        ----------
        dbapi_url : str
        dbapi_username : str
        dbapi_password : str
        user : str
            The user to attach to this record
        logger : logging.Logger
        """
        self.dbapi_url = dbapi_url
        self.dbapi_auth = (dbapi_username, dbapi_password)
        self.user = user
        self.logger = logger or logging.getLogger("DSL")

        self.cpu_name = platform.node().split('.')[0]
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
    def from_config(cls, config, user=None, logger=None):
        return cls(config["NEXUSLIMSGUI_DBAPI_URL"],
                   dbapi_username=config["NEXUSLIMSGUI_DBAPI_USERNAME"],
                   dbapi_password=config["NEXUSLIMSGUI_DBAPI_PASSWORD"],
                   user=user,
                   logger=logger)

    def check_exit_queue(self, thread_queue, exit_queue):
        """
        Check to see if a queue (``exit_queue``) has anything in it. If so,
        immediately exit.

        Parameters
        ----------
        thread_queue : queue.Queue
        exit_queue : queue.Queue
        """
        if exit_queue is not None:
            try:
                res = exit_queue.get(0)
                if res:
                    self.logger.info("Received termination signal from GUI thread", 0)
                    thread_queue.put(ChildProcessError("Terminated from GUI "
                                                       "thread"))
                    sys.exit("Saw termination queue entry")
            except queue.Empty:
                pass

    def last_session_ended(self, thread_queue=None, exit_queue=None):
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
        try:
            self.check_exit_queue(thread_queue, exit_queue)
            if self.instr_pid is None:
                raise AttributeError(
                    "Instrument PID must be set before checking "
                    "the database for any related sessions")
        except Exception as e:
            if thread_queue:
                thread_queue.put(e)
            self.logger.error("Error encountered while checking that last "
                              "record for this instrument was an \"END\" log")
            return False

        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/lastsession")
        res = requests.get(url, params={"instrument": self.instr_pid}, auth=self.dbapi_auth)

        if res.status_code >= 500:
            msg = str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False
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
            if thread_queue:
                thread_queue.put((msg, self.progress_num))
                self.progress_num += 1
            return True
        elif self.last_entry_type == "START":
            msg = "Database is inconsistent for the %s. " \
                  "(last entry [id_session_log = %s] was a `START`)" % (
                      self.instr_schema, self.last_session_row_number)
            self.logger.warning(msg)
            if thread_queue:
                thread_queue.put((msg, self.progress_num))
                self.progress_num += 1
            return False

        msg = "Last entry for the %s was neither `START` or `END` (value was %s)" % (
            self.instr_schema, self.last_entry_type)
        self.logger.error(msg)
        if thread_queue:
            thread_queue.put(Exception(msg))
        return False

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

    def db_logger_setup(self, thread_queue=None, exit_queue=None):
        """
        get instrument info (pid, schema name).
        """

        self.logger.info("Username: %s" % self.user)
        self.logger.info("Computer Name: %s" % self.cpu_name)
        self.logger.info("Session ID: %s" % self.session_id)

        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.dbapi_url, "/api/instrument")
        payload = {
            "computer_name": self.cpu_name,
        }
        res = requests.get(url, params=payload, auth=self.dbapi_auth)
        if res.status_code != 200:
            msg = "Error fetching instrument information from DB. " + str(res.content)
            self.logger.error(msg)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Connected to db"
        self.logger.info(msg)
        self.logger.debug("Instrument info: %s" % str(data))
        if thread_queue:
            self.progress_num = 1
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        self.instr_info = data
        self.instr_pid = self.instr_info["instrument_pid"]
        self.instr_schema = self.instr_info["schema_name"]

        return True

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
