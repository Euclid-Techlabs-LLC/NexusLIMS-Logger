.. _installconfig:

=======================
Install & Configuration
=======================


Install
=======

NexusLIMS-Logger is distributed as portable binary executable compiled in corresponding
OS. There is no installation (or pre-requisites) required to run the executable, except
proper configuration (see below).

NexusLIMS-Logger can also be excuted as normal Python program as well with the source
code. Developers can take following steps:

.. code-block:: bash

    $ git clone https://github.com/Euclid-Techlabs-LLC/NexusLIMS-Logger.git -b devhub
    $ cd NexusLIMS-Logger && pip install -e ".[dev]"

Configuration
=============

NexusLIMS-Logger requires several configuration settings to run, which must be properly
set. The settings are read from:

1. environment variables. (priority)
2. ``$HOME/nexuslims/gui/config.json`` for **LoggerTEM**;
   ``$HOME/nexuslims/gui/hubconfig.json`` for **LoggerHUB**.

The settings includes the following item:

``config.json``
---------------

.. list-table::
   :widths: 30 50
   :header-rows: 1

   * - Setting Name
     - Explaination
   * - ``NEXUSLIMSGUI_FILESTORE_PATH``
     - system directory path of instrument raw data output folder,
       file changes therein will be watched and sync-ed to the cloud storage
   * - ``NEXUSLIMSGUI_HUB_ADDRESS``
     - LoggerHUB host and port

An example can be seen (``$ROOT/src/nexuslims_logger/config.json``)

.. literalinclude:: ../src/nexuslims_logger/config.json
   :language: json
   :linenos:

``hubconfig.json``
------------------

.. list-table::
 :widths: 30 50
 :header-rows: 1

 * - Setting Name
   - Explaination
 * - ``NEXUSLIMSHUB_DBAPI_URL``
   - root URL of database API
 * - ``NEXUSLIMSHUB_DBAPI_USERNAME``
   - user name to validate database API request
 * - ``NEXUSLIMSHUB_DBAPI_PASSWORD``
   - password to validate database API request
 * - ``NEXUSLIMSHUB_FILETYPES_SYNC``
   - list of file types allowed to be watched and sync-ed
 * - ``NEXUSLIMSHUB_SYNC_INTERVAL_SECONDS``
   - file transfer interval in seconds
 * - ``NEXUSLIMSHUB_DATA_BUCKET``
   - bucket name of cloud storage which raw data is sync-ed to
 * - ``NEXUSLIMSHUB_PORT``
   - port number which the socket will bind to



An example can be seen (``$ROOT/src/nexuslims_logger/hubconfig.json``)

.. literalinclude:: ../src/nexuslims_logger/hubconfig.json
 :language: json
 :linenos:

Additionally, LoggerHUB requires credential JSON file to be able to write
to GCP cloud storage bucket. The credential JSON file can be downloaded from GCP
project IAM section, a service account can be created for this purpose.
NexusLIMS-Logger reads the credential JSON from ``$HOME/nexuslims/gui/creds.json``.

Start
=====

Both LoggerHUB and LoggerTEM can be started by double-clicking on the icon,
like normal desktop GUI.

To start with source code, run the following in the terminal:

- **LoggerTEM**: ``python -m nexuslims_logger.loggertem`` or ``nexuslimsloggertem``
- **LoggerHUB**: ``python -m nexuslims_logger.loggerhub`` or ``nexuslimsloggerhub``


Help
====

Please contact developers in :ref:`authors`.