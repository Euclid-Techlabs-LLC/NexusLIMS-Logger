"""FileWatcher will watch a directory,and sync with Cloud periodically.

It will upload any files (require file types match if specified) (modified after
certain time if specified) that checksum changed wrt. cache (if any) to a GCP
cloud bucket in a specified interval.
"""
__all__ = ["FileWatcher"]

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from google.cloud import storage


def calc_file_md5(filename):
    """Get md5 checksum (base64 encoded) of a local file."""
    hash = hashlib.md5()
    with open(filename, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash.update(chunk)
    return base64.b64encode(hash.digest()).decode()


class FileWatcher:
    def __init__(self, watch_dir, bucket_name, bucket_dir, credential_fn,
                 cache_fn, interval=600, file_types=None, mtime_since=None,
                 instr_info=None, logger=None):
        self.watch_dir = watch_dir
        self._bucket_dir = bucket_dir
        self.client = storage.Client.from_service_account_json(credential_fn)
        self.bucket = self.client.get_bucket(bucket_name)

        self.cache_fn = cache_fn
        self.cache = json.load(open(cache_fn))
        self.file_types = file_types
        self._mtime_since = mtime_since
        self._interval = interval
        self._instr_info = instr_info or {}
        self.logger = logger or logging.getLogger("FW")
        self.logger.info("FileWatcher initialized.")
        msg = "watching directory `%s` every %d seconds" % (watch_dir, interval)
        if mtime_since:
            msg += " for files modified after %s" % datetime.fromtimestamp(mtime_since).isoformat()
        self.logger.debug(msg)

    @classmethod
    def from_config(cls, config, credential_fn, cache_fn, logger=None):
        return cls(config["NEXUSLIMSGUI_FILESTORE_PATH"],
                   config["NEXUSLIMSGUI_DATA_BUCKET"],
                   "",
                   credential_fn,
                   cache_fn,
                   interval=config["NEXUSLIMSGUI_SYNC_INTERVAL_SECONDS"],
                   file_types=config["NEXUSLIMSGUI_FILETYPES_SYNC"],
                   logger=logger)

    @property
    def mtime_since(self):
        return self._mtime_since

    @mtime_since.setter
    def mtime_since(self, t):
        self._mtime_since = t
        msg = "only watch files modified after %s" % datetime.fromtimestamp(t).isoformat()
        self.logger.debug(msg)

    @property
    def interval(self):
        return self._interval

    @interval.setter
    def interval(self, t):
        self._interval = t
        self.logger.debug("set file watch interval as %d" % t)

    @property
    def bucket_dir(self):
        return self._bucket_dir

    @bucket_dir.setter
    def bucket_dir(self, d):
        self._bucket_dir = d
        self.logger.debug("set GCP bucket: %s" % d)

    @property
    def instr_info(self):
        return self._instr_info

    @instr_info.setter
    def instr_info(self, d):
        self._instr_info = d
        self.logger.debug("set instrument info")

    def get_files_to_upload(self):
        """find files to upload recursively and return list of abs file names
        and content checksum.

        file satisfying the following condition will be considered for uploading:
        - file type is allowed (set in app config)
        - file modification timestamp is after the set threshold (session start time)
        - file content checksum does not exist in cache or updated.

        Returns
        -------
        List[Tuple[str, str]]
            List of tuple consisting file names and MD5 checksum.
        """
        res = []
        for p, dirs, fs in os.walk(self.watch_dir):
            for f in fs:
                _, ext = os.path.splitext(f)
                if self.file_types and ext not in self.file_types:
                    continue
                absfn = os.path.join(p, f)
                if self.mtime_since and os.path.getmtime(absfn) < self.mtime_since:
                    continue

                md5_checksum = calc_file_md5(absfn)
                if absfn in self.cache and self.cache[absfn] == md5_checksum:
                    continue
                res.append((absfn, md5_checksum))

        self.logger.info("%d files found to upload." % len(res))
        if res:
            self.logger.debug("filenames: %s" % str([f for f, _ in res]))

        return res

    def upload(self):
        """upload to the cloud object storage, set metadata and update the cache.
        """

        files = self.get_files_to_upload()
        for f, md5 in files:
            relpath = os.path.relpath(f, self.watch_dir)
            bucket_path = "%s/%s" % (self.bucket_dir, relpath)

            ts = os.path.getmtime(f)
            mtime = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            blob = self.bucket.blob(bucket_path)
            blob.metadata = {
                "mtime": mtime,
                "instr_name": self.instr_info.get("schema_name")
            }
            blob.upload_from_filename(f)
            self.cache[f] = md5
        with open(self.cache_fn, 'w') as f:
            f.write(json.dumps(self.cache, indent=4))

        if files:
            self.logger.info("%d files uploaded." % len(files))
