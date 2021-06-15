"""FileWatcher will watch a directory,and sync with Cloud periodically.

It will upload any files (require file types match if specified) (modified after
certain time if specified) that checksum changed wrt. cache (if any) to a GCP
cloud bucket in a specified interval.
"""
import base64
import hashlib
import json
import logging
import os
import time

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
                 logger=None):
        self.watch_dir = watch_dir
        self._bucket_dir = bucket_dir
        self.client = storage.Client.from_service_account_json(credential_fn)
        self.bucket = self.client.get_bucket(bucket_name)

        self.cache_fn = cache_fn
        self.cache = json.load(open(cache_fn))
        self.file_types = file_types
        self._mtime_since = mtime_since
        self._interval = interval
        self.logger = logger or logging.getLogger("FW")
        self.logger.info("FileWatcher initialized.")
        msg = "watching directory `%s` every %d seconds" % (watch_dir, interval)
        if mtime_since:
            msg += " for files modified after %s" % time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(mtime_since))
        self.logger.debug(msg)

    @classmethod
    def from_config(cls, config, credential_fn, cache_fn, logger=None):
        return cls(config["filestore_path"],
                   config["gcp_bucket_name"],
                   "",
                   credential_fn,
                   cache_fn,
                   interval=config["sync_interval_seconds"],
                   file_types=config["filetypes_sync"],
                   logger=logger)

    @property
    def mtime_since(self):
        return self._mtime_since

    @mtime_since.setter
    def mtime_since(self, t):
        self._mtime_since = t
        msg = "only watch files modified after %s" % time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(t))
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

    def get_files_to_upload(self):
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
        files = self.get_files_to_upload()
        for f, md5 in files:
            relpath = os.path.relpath(f, self.watch_dir)
            bucket_path = os.path.join(self.bucket_dir, relpath)

            blob = self.bucket.blob(bucket_path)
            blob.upload_from_filename(f)
            self.cache[f] = md5
        with open(self.cache_fn, 'w') as f:
            f.write(json.dumps(self.cache, indent=4))

        if files:
            self.logger.info("%d files uploaded." % len(files))
