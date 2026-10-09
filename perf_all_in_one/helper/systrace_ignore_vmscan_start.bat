@echo off
echo [Systrace ignore vmscan]
echo please input your systrace path (drag file into terminal):
set/p SCRIPT_PATH=%1

echo=
echo Start ...
python systrace_ignore_vmscan_event.py -p %SCRIPT_PATH%

@pause