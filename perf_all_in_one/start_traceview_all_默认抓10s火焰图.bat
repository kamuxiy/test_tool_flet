
@echo off
set PATH=%cd%/lib/python2.7.11-x86
echo PATH: %PATH%
adb logcat -c -b all
adb logcat -G 4M
@echo off
title Traceview All 5s

set /a count=0
:START
set /a count+=1
echo Running iteration %count% of 10...
python main.py --profile_type=traceview -t 10 -b 120

if %count% lss 1 (
    goto START
) else (
    echo Completed %count% iterations.
)
echo press ENTER KEY to continue...
@pause
set /a count=0
goto START
@pause
