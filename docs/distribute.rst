.. _distribute:

============================
Compile source to executable
============================

NexusLIMS-Logger is compiled to binary executable using PyInstaller.

On Windows PowerShell:

.. code-block:: powershell

   # under src/nexuslims_logger
   pyinstaller -y -F -w `
        -n "NexusLIMS Session Logger" `
        -i "resources\\logo_bare_xp.ico" `
        --add-data "resources;resources" run.py


On MacOS / Linux terminal:

.. code-block:: bash

   # under src/nexuslims_logger
   pyinstaller -y -F -w \
       -n "NexusLIMS Session Logger" \
       -i "resources/logo_bare_xp.ico" \
       --add-data "resources:resources" run.py