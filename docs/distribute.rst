.. _distribute:

============================
Compile source to executable
============================

Both LoggerTEM and LoggerHUB are compiled to binary executable using PyInstaller.

On Windows PowerShell:

.. code-block:: powershell

   # under src/nexuslims_logger
   # LoggerTEM
   pyinstaller -y -F -w `
        -n "NexusLIMS LoggerTEM" `
        -i "resources\\logo_bare_xp.ico" `
        --add-data "resources;resources" loggertem.py

   # LoggerHUB
   pyinstaller -y -F -w `
        -n "NexusLIMS LoggerHUB" `
        -i "resources\\logo_bare_xp.ico" `
        --add-data "resources;resources" loggerhub.py


On MacOS / Linux terminal:

.. code-block:: bash

   # under src/nexuslims_logger
   # LoggerTEM
   pyinstaller -y -F -w \
       -n "NexusLIMS LoggerTEM" \
       -i "resources/logo_bare_xp.ico" \
       --add-data "resources:resources" loggertem.py

   # LoggerHUB
   pyinstaller -y -F -w \
      -n "NexusLIMS LoggerHUB" \
      -i "resources/logo_bare_xp.ico" \
      --add-data "resources:resources" loggerhub.py
