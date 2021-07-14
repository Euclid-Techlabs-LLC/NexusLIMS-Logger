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

    $ git clone https://github.com/Euclid-Techlabs-LLC/NexusLIMS-Logger.git -b devgcp
    $ cd NexusLIMS-Logger && pip install -e ".[dev]"

Configuration
=============

NexusLIMS-Logger requires several configuration settings to run, which must be properly
set. The settings are read from:

1. environment variables. (priority)
2. ``$HOME/nexuslims/gui/config.json``

The settings includes the following item:

.. list-table::
   :widths: 30 50
   :header-rows: 1

   * - Setting Name
     - Explaination
   * - ``NEXUSLIMSGUI_DBAPI_URL``
     - root URL of database API
   * - ``NEXUSLIMSGUI_DBAPI_USERNAME``
     - user name to validate database API request
   * - ``NEXUSLIMSGUI_DBAPI_PASSWORD``
     - password to validate database API request
   * - ``NEXUSLIMSGUI_FILESTORE_PATH``
     - system directory path of instrument raw data output folder,
       file changes therein will be watched and sync-ed to the cloud storage
   * - ``NEXUSLIMSGUI_FILETYPES_SYNC``
     - list of file types allowed to be watched and sync-ed
   * - ``NEXUSLIMSGUI_SYNC_INTERVAL_SECONDS``
     - file transfer interval in seconds
   * - ``NEXUSLIMSGUI_DATA_BUCKET``
     - bucket name of cloud storage which raw data is sync-ed to


An example can be seen (``src/nexuslims_logger/config.json``)

.. literalinclude:: ../src/nexuslims_logger/config.json
   :language: json
   :linenos:

Additionally, NexusLIMS-Logger requires credential JSON file to be able to write
to GCP cloud storage bucket. The credential JSON file can be downloaded from GCP
project IAM section, a service account can be created for this purpose.

Start
=====

NexusLIMS-Logger can be started by double-clicking on the icon, like normal desktop GUI.

To start with source code, run ``python -m nexuslims_logger.run`` or ``nexuslimslogger``
in the terminal.


Help
====

Please contact developers in :ref:`authors`.