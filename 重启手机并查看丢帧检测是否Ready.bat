rem adb install -r -d OppoQualityProtect-release-Oplus_key.apk
adb reboot
adb wait-for-device
rem adb shell pm path com.oplus.qualityprotect
adb shell ps -ef | findstr com.oplus.midas
rem adb shell kill -9 `pidof com.oplus.midas`
adb shell logcat | findstr "JankAlertManager"