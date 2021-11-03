================
NexusLIMS-Logger
================


Logger (TKinter) GUI branched off from original NexusLIMS repository.

To run the Logger GUI, a file named ``config.json`` must be created and stored in the location::

    $HOME/nexuslims/gui/config.json

The default ``$HOME`` directory is unique for different operating systems.  A discription of
the default ``$HOME`` directories for Linux, MacOS, and Windows can be found `here <https://en.wikipedia.org/wiki/Home_directory>`_.
The ``config.json`` file contains information about the user that is required by the Logger GUI
to store data.  The required information is as follows::

    {
        "database_name": "nexuslims_db.sqlite",
        "database_relpath": "TEMdata/nexuslims",
        "networkdrive_hostname": "192.168.0.166",
        "networkdrive_workgroup": "",
        "networkdrive_username": "",
        "networkdrive_password": "",
        "daq_relpath": "TEMdata/daq"
    }

``database_name``, ``database_relpath``, ``networkdrive_hostname`` and ``daq_relpath`` must have the values specified
in the above example. ``networkdrive_workgroup`` and ``networkdrive_password`` are not required entities when the Logger GUI
is installed but they can be configfured by administrators to be required. The ``networkdrive_username`` entity
must be filled in prior to running the Logger GUI or the program will not run.

There are two methods to run the Logger GUI: through a command line or as an executable file

Run in command line
===================

To run the Logger GUI in the command line, clone the NexusLIMS-Logger repository to your local drive::

    git clone https://github.com/Euclid-Techlabs-LLC/NexusLIMS-Logger.git
    cd NexusLIMS-Logger

then run the commands::

    pip install .
    python -m nexuslims_logger.main

Packaging as a single executable
================================

Requires ``pyinstaller`` to be installed::

    pip install pyinstaller

in the directory ``src/nexuslims_logger/``.  Then run the commands shown below.

On Windows PowerShell::

    pyinstaller -y -F -w `
        -n "NexusLIMS Session Logger" `
        -i "resources\\logo_bare_xp.ico" `
        --add-data "resources;resources" main.py

On MacOS::

   pyinstaller -y -F -w \
       -n "NexusLIMS Session Logger" \
       -i "resources/logo_bare_xp.ico" \
       --add-data "resources:resources" main.py