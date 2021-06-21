================
NexusLIMS-Logger
================


Logger (TKinter) GUI separated from original NexusLIMS repository.


Install
=======
1. ``git clone https://github.com/Euclid-Techlabs-LLC/NexusLIMS-Logger.git -b devgcp``
2. ``cd NexusLIMS-Logger && pip install -e ".[dev]"``

Run in command line
===================

1. Create/Edit config file -- ``$HOME/nexuslims/gui/config.json``
2. ``nexuslimslogger``

Packaging as a single executable
================================

(under ``src/nexuslims_logger/``)

On Windows PowerShell::

    pyinstaller -y -F -w `
        -n "NexusLIMS Session Logger" `
        -i "resources\\logo_bare_xp.ico" `
        --add-data "resources;resources" run.py

On MacOS::

   pyinstaller -y -F -w \
       -n "NexusLIMS Session Logger" \
       -i "resources/logo_bare_xp.ico" \
       --add-data "resources:resources" run.py