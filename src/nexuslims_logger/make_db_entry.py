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

import os
import platform
import queue
import random
import shutil
import subprocess
import sys
from datetime import datetime
from urllib.parse import urljoin
from uuid import uuid4

import requests


class DBSessionLogger:
    def __init__(self, config, verbosity=0, user=None):
        """
        Parameters
        ----------
        config : dict
        verbosity : int
            -1: 'ERROR', 0: ' WARN', 1: ' INFO', 2: 'DEBUG'
        user : str
            The user to attach to this record
        """
        self.config = config
        self.verbosity = verbosity
        self.user = user

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

        self.log_text = ""
        self.session_note = ""

    def log(self, to_print, this_verbosity):
        """
        Log a message to the console, only printing if the given verbosity is
        equal to or lower than the global threshold. Also save it in this
        instance's ``log_text`` attribute (regardless of verbosity)

        Parameters
        ----------
        to_print : str
            The message to log
        this_verbosity : int
            The verbosity level (higher is more verbose)
        """
        level_dict = {-1: 'ERROR', 0: ' WARN', 1: ' INFO', 2: 'DEBUG'}
        str_to_log = '{}'.format(datetime.now().isoformat()) + \
                     ':{}'.format(level_dict[this_verbosity]) + \
                     ': {}'.format(to_print)
        if this_verbosity <= self.verbosity:
            print(str_to_log)
        self.log_text += str_to_log + '\n'

    def log_exception(self, e):
        """
        Log an exception to the console and the ``log_text``

        Parameters
        ----------
        e : Exception
        """
        indent = " " * 34
        template = indent + "Exception of type {0} occurred. Arguments:\n" + \
                            indent + "{1!r}"
        message = template.format(type(e).__name__, e.args)
        print(message)
        self.log_text += message + '\n'

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
                    self.log("Received termination signal from GUI thread", 0)
                    thread_queue.put(ChildProcessError("Terminated from GUI "
                                                       "thread"))
                    sys.exit("Saw termination queue entry")
            except queue.Empty:
                pass

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
            self.log('command {} returned with error (code {}): {}'.format(
                e.cmd.replace(self.password, '**************'),
                e.returncode,
                e.output), 0)
        return output

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
            self.log("Error encountered while checking that last record for "
                     "this instrument was an \"END\" log", -1)
            return False

        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.config["api_url"], "/api/lastsession")
        res = requests.get(url, params={"instrument": self.instr_pid})

        if res.status_code >= 500:
            msg = str(res.content)
            self.log(msg, -1)
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
            self.log(msg, 2)
            if thread_queue:
                thread_queue.put((msg, self.progress_num))
                self.progress_num += 1
            return True
        elif self.last_entry_type == "START":
            msg = "Database is inconsistent for the %s. " \
                  "(last entry [id_session_log = %s] was a `START`)" % (
                      self.instr_schema, self.last_session_row_number)
            self.log(msg, 0)
            if thread_queue:
                thread_queue.put((msg, self.progress_num))
                self.progress_num += 1
            return False

        msg = "Last entry for the %s was neither `START` or `END` (value was %s)" % (
            self.instr_schema, self.last_entry_type)
        self.log(msg, -1)
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
        url = urljoin(self.config["api_url"], "/api/session")
        payload = {
            "event_type": "START",
            "instrument": self.instr_pid,
            "user": self.user,
            "session_identifier": self.session_id,
            "session_note": self.session_note
        }
        res = requests.post(url, data=payload)
        if res.status_code >= 500:
            msg = "Error inserting `START` into DB. " + str(res.content)
            self.log(msg, -1)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        self.session_started = True
        if thread_queue:
            msg = "`START` session inserted into db."
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # verify insertion success by query db
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.config["api_url"], "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "START",
        }
        res = requests.get(url, params=payload)
        if res.status_code != 200:
            msg = "Error verifying that session was started. " + str(res.content)
            self.log(msg, -1)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        self.check_exit_queue(thread_queue, exit_queue)
        self.session_start_time = datetime.strptime(
            data["timestamp"], "%a, %d %b %Y %H:%M:%S %Z")
        msg = "Verified insertion of row " + str(data)
        self.log(msg, 2)
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
        url = urljoin(self.config["api_url"], "/api/session")
        payload = {
            "instrument": self.instr_pid,
            "event_type": "END",
            "record_status": "TO_BE_BUILT",
            "session_identifier": self.session_id,
            "session_note": self.session_note,
            "user": self.user,
        }
        res = requests.post(url, data=payload)
        if res.status_code != 200:
            msg = "Error inserting `END` log for session"
            self.log(msg, -1)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        msg = "`END` session log inserted into db"
        self.log(msg, 1)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # verify insertion success by querying
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.config["api_url"], "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "END",
        }
        res = requests.get(url, params=payload)
        if res.status_code != 200:
            msg = "Error verifying that session was ended. " + str(res.content)
            self.log(msg, -1)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Verified `END` session inserted into db. " + str(data)
        self.log(msg, 2)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # Query matched last start
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.config["api_url"], "/api/lastsession")
        payload = {
            "session_identifier": self.session_id,
            "event_type": "START",
        }
        res = requests.get(url, params=payload)
        if res.status_code != 200:
            msg = "Error getting matching `START` log. " + str(res.content)
            self.log(msg, -1)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Found matched `START` log: " + str(data)
        self.log(msg, 2)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        last_start_id = data["id_session_log"]

        # Update matched last start
        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.config["api_url"], "/api/session")
        payload = {
            "id_session_log": last_start_id,
        }
        res = requests.put(url, data=payload)
        if res.status_code != 200:
            msg = "Error updating matching `START` log's status. " + str(res.content)
            self.log(msg, -2)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        msg = "Matching `START` session log's status updated."
        self.log(msg, 1)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        # Verify update success by querying
        self.check_exit_queue(thread_queue, exit_queue)
        res = requests.get(url, params=payload)
        if res.status_code != 200:
            msg = "Error updating matching `START` log's status. " + str(res.content)
            self.log(msg, -2)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Verified updated row: " + str(data)
        self.log(msg, 2)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        self.log("Finished ending session %s" % self.session_id, 1)

        return True

    def db_logger_setup(self, thread_queue=None, exit_queue=None):
        """
        get instrument info (pid, schema name).
        """

        self.log("Username: %s" % self.user, 1)
        self.log("Computer Name: %s" % self.cpu_name, 1)
        self.log("Session ID: %s" % self.session_id, 1)

        self.check_exit_queue(thread_queue, exit_queue)
        url = urljoin(self.config["api_url"], "/api/instrument")
        payload = {
            "computer_name": self.cpu_name,
        }
        res = requests.get(url, params=payload)
        if res.status_code != 200:
            msg = "Error fetching instrument information from DB. " + str(res.content)
            self.log(msg, -1)
            if thread_queue:
                thread_queue.put(Exception(msg))
            return False

        data = res.json()["data"]
        msg = "Connected to db"
        self.log(msg, 1)
        self.log("Instrument info: " + str(data), 2)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1

        self.instr_info = data
        self.instr_pid = self.instr_info["instrument_pid"]
        self.instr_schema = self.instr_info["schema_name"]

        return True

    def _copydata_setup(self, thread_queue=None, exit_queue=None):
        """
        copydata routine:
        1) mount network share.
        """

        try:
            self.check_exit_queue(thread_queue, exit_queue)
            self.log('running `mount_network_share()`', 2)
            self.mount_network_share(mount_point=self.config["daq_relpath"])
        except Exception as e:
            if thread_queue:
                thread_queue.put(e)
            self.log("Could not mount the network share holding the "
                     "database. Details:", -1)
            self.log_exception(e)
            return False
        if thread_queue:
            self.progress_num = 1
            thread_queue.put(('Mounted network share', self.progress_num))
            self.progress_num += 1

        return True

    def db_logger_teardown(self, thread_queue=None, exit_queue=None):
        """
        teardown routine
        """
        msg = "TEARDOWN"
        self.log(msg, 2)
        if thread_queue:
            thread_queue.put((msg, self.progress_num))
            self.progress_num += 1
        return True

    def _copydata(self, srcdir='mock'):
        """ Take a data file randomly from **mock** data folder,
        copy it to ``filestore_path`` of this instument, to mock the
        behavior of generating experiment data.
        """

        src_dir = os.path.join(self.drive_letter, srcdir)
        dst_dir = os.path.join(self.drive_letter, self.filestore_path)
        if not os.path.isdir(dst_dir):
            os.makedirs(dst_dir)

        datafiles = [f for f in os.listdir(src_dir) if not f.startswith('.')]
        src_file = random.choice(datafiles)
        suffix = src_file.split('.')[-1]
        timestamp = datetime.strftime(datetime.now(), "%y%m%d_%H%M%S")
        dst_file = '%s.%s' % (timestamp, suffix)

        logstr = 'COPY {} --> {}'.format(
            os.path.join(src_dir, src_file),
            os.path.join(dst_dir, dst_file)
        )

        try:
            shutil.copy(os.path.join(src_dir, src_file),
                        os.path.join(dst_dir, dst_file))
            self.log(logstr, 2)
        except Exception as e:
            self.log('Failed to ' + logstr, -1)
            self.log_exception(e)

    def copydata(self, thread_queue=None, exit_queue=None):
        """copy a data file from mock folder to instument ``filestore_path``.

        Returns True if successful, False if not
        """
        self.check_exit_queue(thread_queue, exit_queue)
        if self._copydata_setup(thread_queue, exit_queue):
            self._copydata()
            self.db_logger_teardown(thread_queue, exit_queue)
            return True


def gui_start_callback(config, verbosity=2):
    """
    Process the start of a session when the GUI is opened

    Returns
    -------
    db_logger : DBSessionLogger
        The session logger instance for this session (contains all the
        information about instrument, computer, session_id, etc.)
    """
    db_logger = DBSessionLogger(config, verbosity=verbosity)
    db_logger.db_logger_setup()
    db_logger.process_start()
    db_logger.db_logger_teardown()

    return db_logger


def gui_end_callback(db_logger):
    """
    Process the end of a session when the button is clicked or the GUI window
    is closed.

    Parameters
    ----------
    db_logger : DBSessionLogger
        The session logger instance for this session (contains all the
        information about instrument, computer, session_id, etc.)
    """
    db_logger.db_logger_setup()
    db_logger.process_end()
    db_logger.db_logger_teardown()
