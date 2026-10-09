adb wait-for-device
adb remount
adb shell setprop persist.oplus.qualityprotect.jankalertenabled true
rem adb shell setprop persist.sys.oplus.jankalertpackage com.oplus.wallpapers
adb reboot
adb wait-for-device
adb shell getprop persist.oplus.qualityprotect.jankalertenabled
adb shell logcat | findstr "JankAlertManager"
