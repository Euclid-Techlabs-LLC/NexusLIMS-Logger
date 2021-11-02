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

import contextlib
import os
import pathlib
import platform
import queue
import random
import shutil
import socket
import sqlite3
import string
import subprocess
import sys
from datetime import datetime
from uuid import uuid4


def get_drives():
    """
    Get the drive letters (uppercase) in current use by Windows

    Adapted from https://stackoverflow.com/a/827398/1435788

    Returns
    -------
    drives : :obj:`list` of str
        A list of drive letters currently in use
    """
    drives = []

    from ctypes import windll
    bitmask = windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drives.append(letter)
        bitmask >>= 1

    return drives


def get_free_drives():
    """
    Get currently unused drive letters, leaving out A through G and M for
    safety (since those are often Windows drives and the M drive is used for
    ``mmfnexus``

    Returns
    -------
    not_in_use : :obj:`list` of str
        A list of "safe" drive letters not currently in use
    """
    in_use = get_drives()
    not_in_use = [lett for lett in string.ascii_uppercase if lett not in in_use]
    not_in_use = [lett for lett in not_in_use if lett not in 'ABCDEFGM']
    return not_in_use


def get_first_free_drive():
    """
    Get the first available drive letter that is not being used on this computer

    Returns
    -------
    first_free : str
        The first free drive letter that should be safe to use with colon
        appended
    """
    if sys.platform == "win32":
        first_free = get_free_drives()[0]
        return first_free + ':'
    else:
        res = os.path.expanduser("~/nexuslims/mnt")
        if not os.path.isdir(res):
            os.makedirs(res)
        return res


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
        self.log_text = ""
        self.config = config
        self.verbosity = verbosity
        self.db_name = config["database_name"]
        self.drive_letter = get_first_free_drive()
        self.user = user
        self.hostname = config["networkdrive_hostname"]
        self.filestore_path = None
        self.session_started = False
        self.session_start_time = None
        self.last_entry_type = None
        self.last_session_id = None
        self.last_session_row_number = None
        self.last_session_ts = None
        self.progress_num = 0
        self.session_note = ""

        self.db_path = str(pathlib.Path(config["database_relpath"]))
        self.password = config["networkdrive_password"] if config["networkdrive_password"] else None
        self.full_path = os.path.join(self.drive_letter, self.db_name)
        self.cpu_name = platform.node().split('.')[0]

        self.session_id = str(uuid4())
        self.instr_pid = None
        self.instr_schema_name = None

        if sys.platform == 'win32':
            self.log('Used drives are: {}'.format(get_drives()), 2)
            self.log('Unused drives are: {}'.format(get_free_drives()), 2)
            self.log('First available drive letter is {}'.format(
                self.drive_letter), 2)

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

    def mount_network_share(self, mount_point=None):
        """
        Mount the path containing the database to the first free drive letter
        found using Windows `cmd`. Due to some Windows limitations,
        this requires looking up the server's IP address
        and mounting using the IP rather than the actual domain name

        Parameters
        ----------
        mount_point : str
            The mount point on the network drive. The default points to the
            `self.db_path`.
        """

        if mount_point is None:
            mount_point = self.db_path
        mount_point = str(pathlib.Path(mount_point))

        # we should not have to disconnect anything because we're using free
        # letter:
        # self.log('unmounting existing N:', 2)
        # _ = self.run_cmd(r'net use N: /delete /y')

        ip = socket.gethostbyname(self.hostname)
        self.log('found network drive at {}'.format(ip), 2)

        do_mount = True
        if sys.platform == "win32":
            current_mounts = str(self.run_cmd('net use')).split('\r\n')
            self.log('Currently mounted: ', 2)
            self.log('Looking for '
                    r'{}\{}'.format(ip,
                                    self.db_path).replace(r'\\', '\\'), 2)
            for m in current_mounts:
                self.log(m, 2)
                if r'{}\{}'.format(ip, self.db_path).replace(r'\\', '\\') in m:
                    old_drive_letter = self.drive_letter
                    for item in m.split():
                        if len(item) == 2 and item[1] == ':' \
                            and item[0] in string.ascii_uppercase:
                            self.drive_letter = item
                            break

                    self.full_path = '{}\\{}'.format(self.drive_letter, self.db_name)
                    self.log('{} is already mounted'.format(self.drive_letter), 0)
                    do_mount = False
        else:
            if os.listdir(self.drive_letter):
                # reuse the same mount point, for safety, unmount first
                self.umount_network_share()

        if do_mount:
            workgroup = self.config.get("networkdrive_workgroup")
            username = self.config.get("networkdrive_username")
            password = self.config.get("networkdrive_password")

            if sys.platform == "win32":
                mount_command = 'net use {} \\\\{}\\{} '.format(self.drive_letter,
                                                                ip,
                                                                mount_point)
                credential_part = ""
                if username:
                    if workgroup:
                        credential_part = "/user:%s\\%s" % (workgroup, username)
                    else:
                        credential_part = "/user:%s" % username
                    if password:
                        credential_part += ' ' + password
                if credential_part:
                    mount_command += credential_part
            elif sys.platform == "darwin":
                credential_part = ""
                if workgroup:
                    credential_part += workgroup + ';'
                if username:
                    credential_part += username
                    if password:
                        credential_part += ':' + password
                if credential_part:
                    credential_part += '@'

                # Here assuming network drive is SMB drive
                mount_command = "mount -t smbfs //%s%s/%s %s" % (
                    credential_part, ip, mount_point, self.drive_letter)
            else:
                raise NotImplementedError("Current OS -- %s not supported." % sys.platform)

            self.log('mounting {}'.format(self.drive_letter), 2)

            # mounting requires a security policy:
            # https://support.microsoft.com/en-us/help/968264/error-message-when-
            # you-try-to-map-to-a-network-drive-of-a-dfs-share-by

            command_shown = mount_command
            if self.password is not None:
                command_shown = command_shown.replace(self.password, '********')

            self.log('using {}'.format(command_shown), 2)

            p = self.run_cmd(mount_command)

            if 'error' in str(p):
                if '1312' in str(p):
                    self.log('Visit https://bit.ly/38DvqVh\n'
                             'to see how to allow mounting network drives as '
                             'another user.\n'
                             '(You\'ll need to change HKLM\\System\\'
                             'CurrentControlSet\\Control\\Lsa\\'
                             'DisableDomainCreds '
                             'to 0 in the registry)', 0)
                raise ConnectionError('Could not mount network share to access '
                                      'database' + " (\"DisableDomanCreds\" "
                                                   "error)" if '1312' in str(p)
                                                   else "")
        else:
            self.log('Using existing mount point {}'.format(
                self.drive_letter), 1)

    def umount_network_share(self):
        """
        Unmount the network share using the Windows `cmd`
        """
        self.log('unmounting {}'.format(self.drive_letter), 2)
        if sys.platform == 'win32':
            p = self.run_cmd(r'net use {} /del /y'.format(self.drive_letter))
        elif sys.platform == "darwin":
            p = self.run_cmd("umount %s" % self.drive_letter)
        else:
            raise NotImplementedError("Current OS -- %s not supported." % sys.platform)
        if str(p):
            self.log(str(p).strip(), 0)

    def get_instr_pid(self):
        """
        Using the name of this computer, get the matching instrument PID from
        the database

        Returns
        -------
        instrument_pid : str
            The PID for the instrument corresponding to this computer
        instrument_schema_name : str
            The schema name for the instrument corresponding to this computer
        filestore_path : str
            The filestore path for the instrument corresponding to this computer
        """
        # Get the instrument pid from the computer name of this computer
        with contextlib.closing(sqlite3.connect(self.full_path)) as con:
            self.log('Looking in database for computer name matching '
                     '{}'.format(self.cpu_name), 1)
            with con as cur:
                res = cur.execute('SELECT instrument_pid, schema_name, filestore_path '
                                  'from instruments '
                                  'WHERE '
                                  'computer_name is '
                                  '\'{}\''.format(self.cpu_name))
                one_result = res.fetchone()
                self.log('Database result is {}'.format(one_result), 2)
                if one_result is not None:
                    instrument_pid, instrument_schema_name, filestore_path = one_result
                else:
                    instrument_pid, instrument_schema_name, filestore_path = (None, None, None)

            self.log('instrument_pid: {}, instrument_schema_name: {}, filestore_path: {}'.format(
                *one_result), 2)
            if instrument_pid is None:
                raise sqlite3.DataError('Could not find an instrument matching '
                                        'this computer\'s name '
                                        '({}) '.format(self.cpu_name) +
                                        'in the database!\n\n'
                                        'This should not happen. Please '
                                        'contact miclims@nist.gov as soon as '
                                        'possible.')
            else:
                self.log('Found instrument ID: '
                         '{} using '.format(instrument_pid) +
                         '{}'.format(self.cpu_name), 1)
        return instrument_pid, instrument_schema_name, filestore_path

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

        # Get last inserted line for this instrument that is not a record
        # generation (should be either a START or END)
        query_statement = 'SELECT event_type, session_identifier, ' \
                          'id_session_log, timestamp FROM session_log WHERE ' \
                          'instrument = "{}" '.format(self.instr_pid) + \
                          'AND NOT event_type = "RECORD_GENERATION" ' + \
                          'ORDER BY timestamp DESC LIMIT 1'

        self.log('last_session_ended query: {}'.format(query_statement), 2)

        self.check_exit_queue(thread_queue, exit_queue)
        with contextlib.closing(sqlite3.connect(self.full_path)) as con:
            with con as cur:
                try:
                    self.check_exit_queue(thread_queue, exit_queue)
                    res = cur.execute(query_statement)
                    row = res.fetchone()
                    if row is None:
                        # If there is no result, this must be the first time
                        # we're connecting to the database with this
                        # instrument, so pretend the last session was "END"
                        self.last_entry_type = "END"
                    else:
                        self.last_entry_type, self.last_session_id, \
                        self.last_session_row_number, self.last_session_ts = row
                    if self.last_entry_type == "END":
                        self.log('Verified database consistency for the '
                                 '{}'.format(self.instr_schema_name), 1)
                        if thread_queue:
                            thread_queue.put(('Verified database consistency '
                                              'for the {}'.format(
                                                  self.instr_schema_name),
                                              self.progress_num))
                            self.progress_num += 1
                        return True
                    elif self.last_entry_type == "START":
                        self.log('Database is inconsistent for the '
                                 '{} '.format(self.instr_schema_name) +
                                 '(last entry [id_session_log = '
                                 '{}]'.format(self.last_session_row_number) +
                                 ' was a "START")', 0)
                        if thread_queue:
                            thread_queue.put(('Database is inconsistent!',
                                              self.progress_num))
                            self.progress_num += 1
                        return False
                    else:
                        raise sqlite3.IntegrityError(
                            "Last entry for the "
                            "{} ".format(self.instr_schema_name) +
                            "was neither \"START\" or \"END\" (value was "
                            "\"{}\")".format(self.last_entry_type))
                except Exception as e:
                    if thread_queue:
                        thread_queue.put(e)
                    self.log("Error encountered while verifying "
                             "database consistency for the "
                             "{}".format(self.instr_schema_name), -1)
                    self.log_exception(e)
                    return False
        pass

    def process_start(self, thread_queue=None, exit_queue=None):
        """
        Insert a session `'START'` log for this computer's instrument

        Returns True if successful, False if not
        """
        insert_statement = "INSERT INTO session_log (instrument, " \
                           " event_type, session_identifier, session_note" + \
                           (", user) " if self.user else ") ") + \
                           "VALUES ('{}', 'START', ".format(self.instr_pid) + \
                           "'{}'".format(self.session_id) + \
                           ", '{}'".format(self.session_note) + \
                           (", '{}');".format(self.user) if self.user else ");")

        self.log('insert_statement: {}'.format(insert_statement), 2)

        self.check_exit_queue(thread_queue, exit_queue)
        # Get last entered row with this session_id (to make sure it's correct)
        with contextlib.closing(sqlite3.connect(self.full_path)) as con:
            with con as cur:
                try:
                    self.check_exit_queue(thread_queue, exit_queue)
                    _ = cur.execute(insert_statement)
                    self.session_started = True
                    if thread_queue:
                        thread_queue.put(('"START" session inserted into db',
                                          self.progress_num))
                        self.progress_num += 1
                except Exception as e:
                    if thread_queue:
                        thread_queue.put(e)
                    self.log("Error encountered while inserting \"START\" "
                             "entry into database", -1)
                    return False
            with con as cur:
                try:
                    self.check_exit_queue(thread_queue, exit_queue)
                    r = cur.execute("SELECT * FROM session_log WHERE "
                                    "session_identifier="
                                    "'{}' ".format(self.session_id) +
                                    "AND event_type = 'START'"
                                    "ORDER BY timestamp DESC " +
                                    "LIMIT 1;")
                except Exception as e:
                    if thread_queue:
                        thread_queue.put(e)
                    self.log("Error encountered while verifying that session"
                             "was started", -1)
                    return False
                id_session_log = r.fetchone()
            self.check_exit_queue(thread_queue, exit_queue)
            self.log('Verified insertion of row {}'.format(id_session_log), 1)
            self.session_start_time = datetime.strptime(
                id_session_log[3], "%Y-%m-%dT%H:%M:%S.%f")
            if thread_queue:
                thread_queue.put(('Verified "START" session inserted into db',
                                  self.progress_num))
                self.progress_num += 1

            return True

    def process_end(self, thread_queue=None, exit_queue=None):
        """
        Insert a session `'END'` log for this computer's instrument,
        and change the status of the corresponding `'START'` entry from
        `'WAITING_FOR_END'` to `'TO_BE_BUILT'`
        """
        user_string = "AND user='{}'".format(self.user) if self.user else ''

        insert_statement = "INSERT INTO session_log " \
                           "(instrument, event_type, " \
                           "record_status, session_identifier, session_note" + \
                           (", user) " if self.user else ") ") + \
                           "VALUES ('{}',".format(self.instr_pid) + \
                           "'END', 'TO_BE_BUILT', " + \
                           "'{}'".format(self.session_id) + \
                           ", '{}'".format(self.session_note) + \
                           (", '{}');".format(self.user) if self.user else ");")

        # Get the most 'START' entry for this instrument and session id
        get_last_start_id_query = "SELECT id_session_log FROM session_log " + \
                                  "WHERE instrument = " + \
                                  "'{}' ".format(self.instr_pid) + \
                                  "AND event_type = 'START' " + \
                                  "{} ".format(user_string) + \
                                  "AND session_identifier = " + \
                                  "'{}'".format(self.session_id) + \
                                  "AND record_status = 'WAITING_FOR_END';"
        self.log('query: {}'.format(get_last_start_id_query), 2)

        with sqlite3.connect(self.full_path) as con:
            self.log('Inserting END; insert_statement: {}'.format(
                insert_statement), 2)
            try:
                self.check_exit_queue(thread_queue, exit_queue)
                _ = con.execute(insert_statement)
                if thread_queue:
                    thread_queue.put(('"END" session log inserted into db',
                                      self.progress_num))
                    self.progress_num += 1
            except Exception as e:
                if thread_queue:
                    thread_queue.put(e)
                self.log("Error encountered while insert \"END\" log for "
                         "session", -1)
                return False

            try:
                self.check_exit_queue(thread_queue, exit_queue)
                res = con.execute("SELECT * FROM session_log WHERE "
                                  "session_identifier="
                                  "'{}' ".format(self.session_id) +
                                  "AND event_type = 'END'"
                                  "ORDER BY timestamp DESC " +
                                  "LIMIT 1;")
            except Exception as e:
                if thread_queue:
                    thread_queue.put(e)
                self.log("Error encountered while verifying that session"
                         "was ended", -1)
                return False
            id_session_log = res.fetchone()
            self.log('Inserted row {}'.format(id_session_log), 1)
            if thread_queue:
                thread_queue.put(('Verified "END" session inserted into db',
                                  self.progress_num))
                self.progress_num += 1

            try:
                self.check_exit_queue(thread_queue, exit_queue)
                res = con.execute(get_last_start_id_query)
                results = res.fetchall()
                if len(results) == 0:
                    raise LookupError("No matching 'START' event found")
                elif len(results) > 1:
                    raise LookupError("More than one 'START' event found with "
                                      "session_identifier = "
                                      "'{}'".format(self.session_id))
                last_start_id = results[-1][0]
                self.log('SELECT instrument results: {}'.format(last_start_id),
                         2)
                if thread_queue:
                    thread_queue.put(('Matching "START" session log found',
                                      self.progress_num))
                    self.progress_num += 1
            except Exception as e:
                if thread_queue:
                    thread_queue.put(e)
                self.log("Error encountered while getting matching \"START\" "
                         "log", -1)
                return False

            try:
                # Update previous START event record status
                self.check_exit_queue(thread_queue, exit_queue)
                res = con.execute("SELECT * FROM session_log WHERE " +
                                  "id_session_log = {}".format(last_start_id))
                self.log('Row to be updated: {}'.format(res.fetchone()), 1)
                if thread_queue:
                    thread_queue.put(('Matching "START" session log found',
                                      self.progress_num))
                    self.progress_num += 1
                update_statement = "UPDATE session_log SET " + \
                                   "record_status = 'TO_BE_BUILT' WHERE " + \
                                   "id_session_log = {}".format(last_start_id)
                self.check_exit_queue(thread_queue, exit_queue)
                _ = con.execute(update_statement)
                if thread_queue:
                    thread_queue.put(('Matching "START" session log\'s status '
                                      'updated',
                                      self.progress_num))
                    self.progress_num += 1

                self.check_exit_queue(thread_queue, exit_queue)
                res = con.execute("SELECT * FROM session_log WHERE " +
                                  "id_session_log = {}".format(last_start_id))
                if thread_queue:
                    thread_queue.put(('Verified updated row',
                                      self.progress_num))
                    self.progress_num += 1
            except Exception as e:
                if thread_queue:
                    thread_queue.put(e)
                self.log("Error encountered while updating matching \"START\" "
                         "log's status", -1)
                return False

            self.log('Row after updating: {}'.format(res.fetchone()), 1)
            self.log('Finished ending session {}'.format(self.session_id), 1)

            return True

    def db_logger_setup(self, thread_queue=None, exit_queue=None):
        """
        setup routine:
        1) mount network share.
        2) check db exists.
        3) get instrument info (pid, schema name).
        """

        self.log('username is {}'.format(self.user), 1)
        self.log('computer name is {}'.format(self.cpu_name), 1)
        try:
            self.check_exit_queue(thread_queue, exit_queue)
            self.log('running `mount_network_share()`', 2)
            self.mount_network_share()
            if not os.path.isfile(self.full_path):
                raise FileNotFoundError('Could not find NexusLIMS database at '
                                        '{}'.format(self.full_path))
            else:
                self.log('Path to database is {}'.format(self.full_path), 1)
        except Exception as e:
            thread_queue.put(e)
            self.log("Could not mount the network share holding the "
                     "database. Details:", -1)
            self.log_exception(e)
            return False
        if thread_queue:
            self.progress_num = 1
            thread_queue.put(('Mounted network share', self.progress_num))
            self.progress_num += 1
        self.log('running `get_instr_pid()`', 2)
        try:
            self.check_exit_queue(thread_queue, exit_queue)
            self.instr_pid, self.instr_schema_name, self.filestore_path = self.get_instr_pid()
        except Exception as e:
            thread_queue.put(e)
            self.log("Could not fetch instrument PID and name from database. "
                     "Details:", -1)
            self.log_exception(e)
            return False
        self.log('Found PID: {} and name: {}'.format(self.instr_pid,
                                                     self.instr_schema_name), 2)
        if thread_queue:
            thread_queue.put(('Instrument PID found', self.progress_num))
            self.progress_num += 1

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
        1) unmount network share.
        """

        try:
            if thread_queue:
                thread_queue.put(('Unmounting the database network share',
                                  self.progress_num))
                self.progress_num += 1
            self.check_exit_queue(thread_queue, exit_queue)
            self.log('running `umount_network_share()`', 2)
            self.umount_network_share()
        except Exception as e:
            if thread_queue:
                thread_queue.put(e)
            self.log("Could not unmount the network share holding the "
                     "database. Details:", -1)
            self.log_exception(e)
            return False
        if thread_queue:
            thread_queue.put(('Unmounted network share', self.progress_num))
            self.progress_num += 1

        self.log('Finished unmounting network share', 2)
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


def cmdline_args():
    # Make parser object
    import argparse
    p = argparse.ArgumentParser(
        description="""This program will mount the nexuslims directory
                       on CFS2E, connect to the nexuslims_db.sqlite
                       database, and insert an entry into the session log.""",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    p.add_argument("event_type", type=str,
                   help="the type of event")
    p.add_argument("user", type=str, nargs='?',
                   help="NIST username associated with this session (current "
                        "windows logon name will be used if not provided)",
                   default=None)
    p.add_argument("-v", "--verbosity", type=int, choices=[0, 1, 2], default=0,
                   help="increase output verbosity")

    return p.parse_args()


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
