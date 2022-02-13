# cliniq-rtc-server
An RTC server that acts as a peer for the [cliniq-app](https://github.com/Mahesh-Ironcoder/cliniq.git) client

## To Install run

clone the repo

`cd cliniq-rtc-server `

`conda env create -p ./env -f ./requirements.yml`

## To run the server

`conda activate ./env`

`python server.py --port 6061 --host 127.0.0.1`

**Note:** the above works assuming you have conda installation in you machine. If you haven't install conda installation first or use the equivalent pip cmds for the conda cmds.
