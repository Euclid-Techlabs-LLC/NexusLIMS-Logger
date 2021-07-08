"""This fake instrument models the behavior of an instrument.

It will connect to a mock data pool, randomly choose one and copy it to the
specified output folder to mock a real instrument generating some data file.
"""
__all__ = ["GCPInstrument"]

import logging
import os
import random
from datetime import datetime

from google.cloud import storage


class Instrument:
    def generate_data(self):
        pass


class GCPInstrument(Instrument):
    def __init__(self, output_dir, bucket_name, bucket_dir, credential_fn,
                 logger=None):
        super(GCPInstrument, self).__init__()
        self.output_dir = output_dir
        self.bucket_dir = bucket_dir
        self.client = storage.Client.from_service_account_json(credential_fn)
        self.bucket = self.client.get_bucket(bucket_name)
        self.logger = logger or logging.getLogger("GCP")
        self.logger.info("Instrument initialized.")

    def get_file_pool(self):
        """List all files in GCP ``self.bucket_dir``"""
        files = self.bucket.list_blobs(prefix=self.bucket_dir)
        res = [f.name for f in files]
        return res

    def generate_data(self):
        """Download random file from GCP bucket.

        save to ``self.output_dir``, and rename by timestamp.
        """
        fpool = self.get_file_pool()
        fname = random.choice(fpool)
        blob = self.bucket.blob(fname)
        self.logger.debug("select `%s` from GCP bucket to download" % fname)

        timestamp = datetime.strftime(datetime.now(), "%y%m%d_%H%M%S")
        _, ext = os.path.splitext(fname)
        outfn = os.path.join(self.output_dir, timestamp + ext)

        blob.download_to_filename(outfn)
        self.logger.info("`%s` generated." % outfn)
        return outfn

    @classmethod
    def from_config(cls, config, credential_fn, logger=None):
        return cls(config["NEXUSLIMSGUI_FILESTORE_PATH"],
                   config["NEXUSLIMSGUI_DATA_BUCKET"],
                   "MockDataFiles",
                   credential_fn,
                   logger=logger)
