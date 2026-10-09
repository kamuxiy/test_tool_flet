@echo off
set PATH=%cd%/lib/python2.7.11-x86
echo PATH: %PATH%
adb logcat -c -b all
adb logcat -G 4M
adb shell "echo fpsgo_main_systrace fpsgo_main_trace >> sys/kernel/tracing/set_event"
@echo off
title long perfetto-trace capture

:: timeout config : config/perfetto_config.pbtx: duration_ms: 10000, default 10s

set /a count=0
:START
set /a count+=1
echo Running iteration %count% of 10...
python main.py --profile_type=long_perfetto

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