Administrator Documentation
===========================

This document is meant for administrators to understand how to properly configure the Logger GUI 
and NexusLIMS back end for users.

Cloning the NexusLIMS Back End
++++++++++++++++++++++++++++++++

All administrators need to clone the NexusLIMS Github repository on a computer that is connected to the 
central file server where measurement data is to be saved.  This can be done by either forking the NexusLIMS 
repository to your own account, or directly cloning the NexusLIMS repository to your local drive using the Git bash
command shown below::

    git clone https://github.com/euclidtechlabs/nexuslims.git

Locating the Instruments Table
++++++++++++++++++++++++++++++++++++
The information to be inputted into the Instruments table is in a csv file named ``instruments.csv`` located 
in the directory ``/path_to_repository/nexuslims/scripts/instruments.csv``.  Each row in the instruments.csv file
corrosponds to a different user and each column corrosponds to a different entry.  Starting from left to
right, the Instrument table entries are as follows: ``instrument_pid``, ``api_url``, ``calendar_name``, 
``calendar_url``, ``location``, ``schema_name``, ``property_tag``, ``filestore_path``, ``computer_name``, 
``computer_ip``, and ``computer_mount``.  More information on the Instruments table entries can be found
`here <https://euclid-techlabs-llc.github.io/NexusLIMS/database.html>`_.


Configuring the Instruments Table
++++++++++++++++++++++++++++++++++++

In order for users to run the Logger GUI, some user information must be loaded into the Instruments table
located in the NexusLIMS database prior to using the Logger GUI. While some entries in the 
Instruments table are not required by the Logger GUI to run, entries such as ``computer_name``,
``filestore_path``, and ``instrument_pid`` must conform to strict guidlines for the Logger GUI to operate.
The ``instrument_pid`` is a unique instrument identifier used by the Logger GUI and cannot match the 
``instrument_pid`` of any other users. The ``computer_name`` corrosponds to the hostname of the support PC 
connected to the instrument that runs the Logger GUI.  If the ``computer_name`` in the Instruments table 
does not match the hostname of the user's computer, the Logger GUI will display an error. Information on 
finding your computer hostname can be found `here <https://drexel.edu/it/help/a-z/computer-names/#:~:text=computer%20name%20listed.-,Windows%2010,find%20the%20computer%20name%20listed.>`_.
The ``filestore_path`` corrosponds to the central file storage where the instrument stores its data, and
should be entered as ``./`` + ``hostname`` of the instrument computer. For example, if the dedicated computer's 
host name is DESKTOP-12345, the ``filestore_path`` would be ``./DESKTOP-12345``.


Building the Instruments Table
++++++++++++++++++++++++++++++
When all the necessary user information has been inserted into the instruments.csv file, a step must be 
taken to convert the .csv file into a .db database table.  Running the Python script ``create_db.py`` 
(located at ``/path_to_repository/nexuslims/scripts/create_db.py``) will input the instruments.csv data into a table contained 
in the NexusLIMS database.