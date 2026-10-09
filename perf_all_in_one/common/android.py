# coding=utf-8
import logging
import os
import re
import shutil
import subprocess
import time

from common.utils import Utils, ProfileType

# timeout config
_FORCE_STOP_APP_TIMEOUT = 2
_TRACE_VIEW_CAPTURED_TIMEOUT = 5
SCREEN_RECORD_TIMEOUT = 10
SCREEN_RECORD_RESOLUTION = "960x640"  # 640x480 960x640
DEVICE_RECORD_FILE_PATH = "data/local/tmp/"
ANDROID_VERSION_DIR = {
    "35": "V", "34": "U", "33": "T", "32": "S", "31": "S", "30": "R", "29": "Q", "28": "P",
    "27": "O1",
    "26": "O"}

# simpleperf data format
PERF_DATA_NAME = "perf.data"
PERF_REPORT_DATA_NAME = "perf_report.txt"

# simpleperf record cmd
SIMPLEPERF_RECORD_CMD = (
    "{PRE}simpleperf record {PROFILE_PROCESS} --duration {DURATION}  -f {FREQ} "
    "--call-graph dwarf -o /data/local/tmp/perf.data&"
)
SIMPLEPERF_CALLCHAIN_CMD = (
    "{PRE}simpleperf report-sample --show-callchain -i /data/local/tmp/perf.data "
    "-o /data/local/tmp/perf_report.txt"
)

# Pefetto core cmd
PERFETTO_TRACE_FOLDER = "/data/misc/perfetto-traces/"
PERFETTO_CMD = (
    "perfetto -o {OUTPUT} "
    "-b {BUFFER_SIZE} -t {TIMEOUT}{UNIT} {EVENT_TAG} &"
)

MTRACE_START = "setprop debug.oplus.mtrace {PKG}"
MTRACE_STOP = "setprop debug.oplus.mtrace {PKG}:disabled"


class AndroidDevice(object):
    def __init__(self, serial=None):
        if serial is None:
            raise Exception("AndroidDevice Instantiation error : serial is None !!")
        self.serial = serial
        self.config = Utils.get_global_config()
        self.output_folder = Utils.get_output_path()

    def adb_cmd_without_output(self, cmd, with_shell):
        run_cmd = self.get_shell_cmd(cmd, with_shell=with_shell)
        logging.info("start cmd : {}".format(run_cmd))
        os.system(run_cmd)

    def adb_shell_output(self, cmd):
        is_ok, output = AndroidDevice.run_cmd(self.get_shell_cmd(cmd))
        if is_ok:
            raise Exception(("error --> {}: ".format(cmd), output))
        return output

    def get_shell_cmd(self, cmd, with_shell=True):
        if with_shell:
            return 'adb -s {SERIAL} shell "{CMD}"'.format(SERIAL=self.serial, CMD=cmd)
        else:
            return 'adb -s {SERIAL} {CMD}'.format(SERIAL=self.serial, CMD=cmd)

    def set_serial(self, serial_number):
        self.serial = serial_number

    @staticmethod
    def run_cmd(cmd):
        """ if sucess, rst_code=None else throw exception"""

        output = None
        is_ok = None
        logging.debug(("[run_cmd] Start to cmd: ", cmd))
        try:
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode("utf-8", errors="ignore")
        except subprocess.CalledProcessError as e:
            output = e.output.decode("utf-8", errors="ignore")
            is_ok = e.returncode
        logging.debug(("[run_cmd] Cmd:", cmd, ",is_ok:", is_ok, ",output:", output))
        return (is_ok, output)

    def get_foreground_activity_name(self):
        output = self.adb_shell_output("am stack list")
        m = re.search(r'topActivity=ComponentInfo{(.*?)}', output)
        return m.group(1)

    def get_foreground_app_pkg(self):
        return self.get_foreground_activity_name().split("/")[0]

    def get_foreground_app_pkg_and_uid(self):
        """Get current top app package name and user ID using am stack list command

        Returns:
            tuple: (pkg_name, userId) e.g., ("com.android.launcher", 0)
        """
        output = self.adb_shell_output("am stack list")

        # Extract userId - look for userId=X pattern
        user_match = re.search(r'userId=(\d+)', output)
        user_id = int(user_match.group(1)) if user_match else 0

        # Extract topActivity - look for topActivity=ComponentInfo{pkg_name/activity_name}
        activity_match = re.search(r'topActivity=ComponentInfo\{([^/]+)/[^}]+\}', output)
        pkg_name = activity_match.group(1) if activity_match else None

        if pkg_name is None:
            raise Exception("Failed to extract top package name!")

        return pkg_name, user_id

    @staticmethod
    def _get_device_serial():
        is_ok, rst = AndroidDevice.run_cmd("adb devices")
        if not is_ok:
            logging.warning("adb devices: {}".format(rst.strip()))
        device_list = [line.split()[0] for line in rst.splitlines(False) if
                       line.strip().endswith("device")]
        return device_list

    @staticmethod
    def get_adb_device_serial():
        rst = AndroidDevice._get_device_serial()
        if len(rst) == 0:
            logging.error("No devices, waiting...")
            AndroidDevice.run_cmd("adb wait-for-device")
            logging.info("device had connectted, continue...")
            rst = AndroidDevice._get_device_serial()
        return rst

    @staticmethod
    def wait(timeout_s):
        time.sleep(timeout_s)

    def __get_prop(self, prop_str):
        logging.debug("[__get_prop] start to getprop:{}".format(prop_str))
        prop_str = self.adb_shell_output("getprop {}".format(prop_str))
        return prop_str.strip().replace(" ", "_")

    def is_device_debug(self):
        return self.__get_prop("ro.debuggable")

    def force_stop_app(self, app_pkg):
        force_stop_cmd = "am force-stop {PKG}".format(PKG=app_pkg)
        self.adb_shell_output(force_stop_cmd)

    def capture_traceview(self, start_activity_first, buffer_size_mb=40, timeout=10,
                          sampling_interval_us=None):
        """ make sure ro.debuggable=1 for traceView """

        self.make_sure_debugged_device()
        logging.info("Start capture traceview...")
        top_activity = self.get_foreground_activity_name()
        logging.info("Current Top Activity : {}".format(top_activity))
        app_pkg = top_activity.split('/')[0]
        product_name = self.get_product_name()
        current_time = Utils.get_current_time()
        trace_file_name = "{PRJ}_{PKG}_{TIME}.trace".format(PRJ=product_name,
                                                            PKG=app_pkg,
                                                            TIME=current_time)
        trace_path = "/data/local/tmp/" + trace_file_name
        trace_cmd_list = ["am"]
        if start_activity_first:
            trace_cmd_list.append(
                " profile start {PKG} {PATH}".format(PKG=app_pkg, PATH=trace_path))
        else:
            trace_cmd_list.append(
                " start -n {ACTIVITY} -W -S --start-profiler {PATH}".format(ACTIVITY=top_activity,
                                                                            PATH=trace_path))
        if sampling_interval_us is not None:
            trace_cmd_list.append(" --sampling {}".format(sampling_interval_us))

        trace_cmd = "".join(trace_cmd_list)
        logging.info("cmd: {}".format(trace_cmd))
        cmd_list = [
            "setprop debug.traceview-buffer-size-mb {SIZE}".format(SIZE=buffer_size_mb),
            trace_cmd
        ]
        for cmd in cmd_list:
            self.adb_cmd_without_output(cmd, True)

        self.wait(timeout)
        #  profile end
        self.adb_shell_output("am profile stop {PKG}".format(PKG=app_pkg))
        self.wait(_TRACE_VIEW_CAPTURED_TIMEOUT)
        self.adb_cmd_without_output(
            'pull {SRC_FILE} "{DST_PATH}"'.format(SRC_FILE=trace_path,
                                                  DST_PATH=self.output_folder),
            False)
        logging.info("Traceview captured done !! \n\t Wrote file: {}\n".format(
            os.path.join(self.output_folder, trace_file_name)))
        self.adb_cmd_without_output("rm -rf {}".format(trace_path), True)

    def make_sure_debugged_device(self):
        if self.is_device_debug() != "1":
            raise Exception("Device() not debugged, Need root device ! ".format(self.serial))
        self.adb_cmd_without_output("root", with_shell=False)

    def get_product_name(self):
        vendor = self.__get_prop("ro.product.vendor.manufacturer").lower()
        rst = ""
        platform = ""
        if vendor in ("oppo", "oneplus", "realme"):
            platform = "-" + self.__get_prop("ro.product.board") + "-" + self.__get_prop(
                "ro.product.brand")
            rst = self.__get_prop("ro.separate.soft")
        elif vendor == "alps":
            rst = "MTK_DO_"
        else:
            if vendor == "xiaomi":
                rst = self.__get_prop("ro.product.marketname")  # xiaomi
            elif vendor == "huawei":
                rst = self.__get_prop("ro.config.marketing_name")  # HuaWei
            if not rst:
                rst = self.__get_prop("net.hostname")
                if not rst:
                    rst = self.__get_prop("ro.product.model")

        return rst + self.get_android_version() + platform

    def get_atrace_category(self):
        self.change_systrace_folder()  # enable systrace env.
        rst = None
        if self.config[ProfileType.SYSTRACE]["light_mode"]:
            rst = self.config[ProfileType.SYSTRACE]["event_tag"]
        else:
            output = self.adb_shell_output("atrace --list_categories")
            category_list = output.split(os.linesep)
            category_list_available = [item.split("-")[0].strip() for item in category_list]
            ignore_event = self.config[ProfileType.SYSTRACE]["ignore_event"]
            rst_list = [event for event in category_list_available if event not in ignore_event]
            rst = " ".join(rst_list)
        logging.info("get atrace event done")
        return rst

    def change_systrace_folder(self):
        os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib")))

    def get_android_version(self):
        sdk_version = self.__get_prop("ro.build.version.sdk")
        return ANDROID_VERSION_DIR.get(sdk_version, "-" + sdk_version)

    def update_path_if_need(self, trace_file_full_name):
        """
        if config new_folder, it will new folder and return new folder path, else it return default path
        :param trace_file_full_name: 20121R_Sytrace_2020_xx.html
        :return: folder path
        """
        path_list = os.path.splitext(trace_file_full_name)
        folder_name = path_list[0]
        rst = os.path.join(self.output_folder, trace_file_full_name)
        if self.config["need_new_folder"]:
            new_folder_path = os.path.join(self.output_folder, folder_name)
            if not os.path.exists(new_folder_path):
                os.makedirs(new_folder_path)
            rst = os.path.join(new_folder_path, trace_file_full_name)
        return rst

    def capture_systrace(self, timeout_s, logcat=True):
        """
        python systrace.py -t %systraceTime% -o "%cmd_path%\%traceFile%" %LIST% -b
        %buffSize% -a com.sohu.inputmethod.sogouoem
        :return:
        """
        category_list = self.get_atrace_category()
        product_name = self.get_product_name()
        trace_file_path = "_".join([product_name, "Systrace", Utils.get_current_time(), ".html"])
        # enable_record_screen = self.config[ProfileType.SYSTRACE]["screenrecord"]
        # if enable_record_screen:
        #     record_file_name = DEVICE_RECORD_FILE_PATH + trace_file_path.replace(".html", ".mp4")
        #     self.start_screen_record_bg(timeout_s + SCREEN_RECORD_TIMEOUT,
        #                                 record_file_name)  # add record time timeout
        trace_file_path = self.update_path_if_need(trace_file_path)
        self.adb_cmd_without_output("echo 1 > proc/oplus_scheduler/sched_assist/debug_enabled",
                                    True)
        debug_pkg = self.config[ProfileType.SYSTRACE]["debug_pkg"]
        logging.info("Device({}) systrace capturing...".format(product_name))
        cmd = " ".join(["python ./systrace/systrace.py",
                        "-e {}".format(self.serial),
                        "-t {}".format(timeout_s),
                        "-b {}".format(
                            timeout_s * self.config[ProfileType.SYSTRACE]["buffer_size_ratio"]),
                        '-o "{}"'.format(trace_file_path),
                        category_list,
                        "-a {}".format(debug_pkg if debug_pkg else "com.sohu.inputmethod.sogouoem"),
                        ]
                       )
        logging.warning("cmd: {}".format(cmd))
        os.system(cmd)
        self.dump_log(product_name, (os.path.splitext(trace_file_path)[0])[0:-1] + ".html")
        # if enable_record_screen:
        #     self.adb_cmd_without_output(
        #         "pull {RECORD_FILE} {TARGET_PATH}".format(RECORD_FILE=record_file_name,
        #                                                   TARGET_PATH=os.path.dirname(
        #                                                       trace_file_path)),
        #         False)
        #     self.adb_cmd_without_output("rm -rf {}/*.mp4".format(DEVICE_RECORD_FILE_PATH), True)
        if self.config[ProfileType.SYSTRACE]["enhance"]:
            SystraceFileHelper(trace_file_path).start_enhance()
            os.remove(trace_file_path)
        logging.info("{} Systrace capture done !".format(product_name))

    def get_pefetto_core_cmd(self, output_file, timeout_s):
        cmd = PERFETTO_CMD.format(
            OUTPUT=output_file,
            TIMEOUT=timeout_s,
            UNIT=self.config[ProfileType.LIGHT_PERFETTO]["unit"],
            BUFFER_SIZE=self.config[ProfileType.LIGHT_PERFETTO]["buffer"],
            EVENT_TAG=self.config[ProfileType.LIGHT_PERFETTO]["event_tag"]
        )
        return cmd

    def make_sure_traced_enable(self):
        """Perfetto need this prop"""

        is_open = self.__get_prop("persist.traced.enable")
        if is_open != "1":
            self.adb_cmd_without_output("setprop persist.traced.enable 1", with_shell=True)

    def capture_full_ptrace(self, config_file_path=None, mtrace_app=None):
        """Get full perfetto trace.

        Support different perfetto cfg for user case
        :param config_file_path: capture perfetto cfg
        :return:
        """
        if not os.path.exists(config_file_path):
            raise Exception("cfg: {} is not exist !!".format(config_file_path))

        self.make_sure_traced_enable()

        cfg_name = os.path.split(config_file_path)[1]

        # push config file
        # make sure userdebug build to turn off ftrace in case miss raw data
        self.adb_cmd_without_output("echo 0 > /sys/kernel/tracing/tracing_on", True)
        self.adb_cmd_without_output("echo 1 > proc/oplus_scheduler/sched_assist/debug_enabled",
                                    True)
        if "long_perfetto_cfg.pbtx" in config_file_path:
            self.adb_cmd_without_output('push "{}" /data/local/tmp/long_perfetto_cfg.pbtx'.format(config_file_path), False)
        else:
            self.adb_cmd_without_output('push "{}" /data/local/tmp'.format(config_file_path), False)

        product_name = self.get_product_name()

        device_trace_file_name = "_".join(
            [product_name, "Perfetto", Utils.get_current_time(), ".perfetto-trace"])
        trace_file_name = self.update_path_if_need(device_trace_file_name)
        perfetto_file = PERFETTO_TRACE_FOLDER + device_trace_file_name

        logging.info("Device({}) full ptrace capturing...".format(product_name))
        cmd = "cat /data/local/tmp/{} | perfetto --txt -c - -o {} &".format(cfg_name, perfetto_file)

        logging.warning("cmd: {}".format(cmd))

        enable_record_screen = self.config[ProfileType.SYSTRACE]["screenrecord"]
        if enable_record_screen:
            record_file_name = DEVICE_RECORD_FILE_PATH + device_trace_file_name.replace(
                ".perfetto-trace", ".mp4")
            self.start_screen_record_bg(SCREEN_RECORD_TIMEOUT,
                                        record_file_name)  # add record time timeout

        if mtrace_app is not None:
            top_app = self.get_foreground_app_pkg() if mtrace_app == "top" else mtrace_app
        else:
            top_app = None

        # enable mtrace
        if top_app is not None:
            logging.warning("Mtrace start for {PKG}".format(PKG=top_app))
            self.adb_cmd_without_output(MTRACE_START.format(PKG=top_app), with_shell=True)

        self.adb_cmd_without_output(cmd, True)  # run perfetto

        if top_app is not None:
            logging.warning("Mtrace stop for {PKG}".format(PKG=top_app))
            self.adb_cmd_without_output(MTRACE_STOP.format(PKG=top_app), with_shell=True)

        self.dump_log(product_name, trace_file_name)
        # pull
        target_folder_name = os.path.dirname(trace_file_name)
        pull_cmd = "pull {SRC} {OUTPUT}".format(SRC=perfetto_file, OUTPUT=target_folder_name)
        logging.info("\n\tWrote done: {}".format(target_folder_name))
        self.adb_cmd_without_output(pull_cmd, False)
        # remove
        self.adb_cmd_without_output("rm -rf {}".format(perfetto_file), True)
        if enable_record_screen:
            self.adb_cmd_without_output(
                "pull {RECORD_FILE} {TARGET_PATH}".format(RECORD_FILE=record_file_name,
                                                          TARGET_PATH=target_folder_name),
                False)
            self.adb_cmd_without_output("rm -rf {}/*.mp4".format(DEVICE_RECORD_FILE_PATH), True)

        logging.info("{} perfetto-trace capture done !".format(product_name))
        return trace_file_name

    def start_screen_record_bg(self, time_s, file_name):
        # --bit-rate 2000000
        cmd = "screenrecord --size {RESOLUTION} --bugreport --time-limit {TIME} {PATH} > /dev/null 2>&1 &".format(
            RESOLUTION=SCREEN_RECORD_RESOLUTION,
            TIME=time_s,
            PATH=file_name)
        logging.warning("start record {}".format(cmd))
        self.adb_cmd_without_output(cmd, True)

    def capture_perfetto_trace(self, timeout_s):
        self.make_sure_traced_enable()
        product_name = self.get_product_name()
        device_trace_file_name = "_".join(
            [product_name, "Perfetto", Utils.get_current_time(), ".perfetto-trace"])
        trace_file_name = self.update_path_if_need(device_trace_file_name)

        perfetto_file = PERFETTO_TRACE_FOLDER + device_trace_file_name
        logging.info("Device({}) perfetto-trace capturing...".format(product_name))

        cmd = self.get_pefetto_core_cmd(perfetto_file, timeout_s)
        enable_record_screen = self.config[ProfileType.SYSTRACE]["screenrecord"]

        logging.warning("cmd: {}".format(cmd))
        self.adb_cmd_without_output(cmd, True)
        self.dump_log(product_name, trace_file_name)
        # pull
        target_folder_name = os.path.dirname(trace_file_name)
        pull_cmd = "pull {SRC} {OUTPUT}".format(SRC=perfetto_file, OUTPUT=target_folder_name)
        logging.info("\n\tWrote done: {}".format(target_folder_name))
        self.adb_cmd_without_output(pull_cmd, False)
        # remove
        self.adb_cmd_without_output("rm -rf {}".format(perfetto_file), True)
        logging.info("{} perfetto-trace capture done !".format(product_name))

    def dump_log(self, product_name, trace_file_path):
        """ we use feature option to turn on/off this dump info"""

        # get ps
        if self.config[ProfileType.SYSTRACE]["dump_ps"]:
            self.dump_info(product_name, "ps", True, "ps -AT", trace_file_path + "-ps.txt")

        # get logcat
        if self.config[ProfileType.SYSTRACE]["dump_logcat"]:
            self.dump_info(product_name, "logcat", False, "logcat -b all -d ",
                           trace_file_path + "-logcat.txt")

        # get dump pkgs
        if self.config[ProfileType.SYSTRACE]["dump_pkgs"]:
            self.dump_info(product_name, "dump_packages", True, "dumpsys package",
                           trace_file_path + "-dump_packages.txt")
        # get dump meminfo
        if self.config[ProfileType.SYSTRACE]["dump_meminfo"]:
            self.dump_info(product_name, "dump_meminfo", True, "dumpsys meminfo",
                           trace_file_path + "-dump_meminfo.txt")

    def dump_info(self, device_name, log_tag, enable_shell, raw_cmd, output_file_path):
        logging.info("Device({NAME}) capture {TAG} start..".format(NAME=device_name, TAG=log_tag))
        cmd = 'adb -s {SERIAL} {ENABLE_SHELL} {RAW_CMD} > "{OUTPUT}"'.format(
            SERIAL=self.serial,
            ENABLE_SHELL="shell" if enable_shell else "",
            RAW_CMD=raw_cmd,
            OUTPUT=output_file_path
        )
        os.system(cmd)

    def get_pkg_pid(self, pkg):
        output = self.adb_shell_output("ps -A |grep {}".format(pkg))
        logging.debug(("output:", output))
        return [s for s in output.split(" ") if s][1]

    def get_pid_pkg(self, pid):
        output = self.adb_shell_output("ps {}".format(pid))
        return [s.strip() for s in output.split(" ") if s][-1]

    def check_simpleperf_bin_env(self):
        """Make sure simpleperf bin env."""

        rst = False
        is_need = self.is_need_replace_simpleperf_bin()
        if is_need:
            lib_path = os.path.join(Utils.get_spf_path(), "bin/android/arm64/simpleperf")
            logging.info("lib_path:" + lib_path)
            self.adb_cmd_without_output("push {} /data/local/tmp/".format(lib_path), False)
            self.adb_cmd_without_output("chmod a+x /data/local/tmp/simpleperf", True)
            rst = True

        return rst

    def is_need_replace_simpleperf_bin(self):
        """Check simpleperf on cur tool.

        1. on android S(sdk=31,32),we need replace simpleperf bin file instead of device-self.
        2. other using simpleperf bin device-self.
        """
        sdk_version = int(self.__get_prop("ro.build.version.sdk"))
        if sdk_version in (31, 32):  # Only For Android S
            return True
        return False

    def capture_simpleperf_data(self, pkg=None, pid=None, cold_start=False, duration=10,
                                freq=1000):
        """
        Android Q build-in simpleperf file, so can record directly on device
        instead of push simpleperf bin file
        TODO: compatible android build version < Android.Q
        """
        self.make_sure_debugged_device()
        logging.debug(
            ("[capture_simpleperf_data] pkg:", pkg, "pid:", pid, "cold_start:",
             cold_start, "duration:", duration, "freq:", freq))

        is_replace_bin = self.check_simpleperf_bin_env()

        if pkg is None and pid is None:
            raise Exception("profile pkg and pid is all None , please check !!!!")

        # cold start
        if cold_start and pkg:
            logging.info("[capture_simpleperf_data] force-stop: {}".format(pkg))
            self.force_stop_app(pkg)
            self.wait(1)

        cmd = SIMPLEPERF_RECORD_CMD.format(
            PRE="/data/local/tmp/" if is_replace_bin else "",
            PROFILE_PROCESS="--app {}".format(pkg) if pkg else "-p {}".format(pid),
            DURATION=duration,
            FREQ=freq)
        self.adb_cmd_without_output(cmd, True)
        self.wait(2)

        report_cmd = SIMPLEPERF_CALLCHAIN_CMD.format(
            PRE="/data/local/tmp/" if is_replace_bin else "")
        self.adb_cmd_without_output(report_cmd, True)

    def capture_perfetto_and_simpleperf(self, pkg=None, pid=None, cold_start=False, duration=10,
                                        freq=1000):
        self.make_sure_debugged_device()

        is_replace_bin = self.check_simpleperf_bin_env()

        if pkg is None and pid is None:
            raise Exception("profile pkg and pid is all None , please check !!!!")

        simpleperf_cmd = SIMPLEPERF_RECORD_CMD.format(
            PRE="/data/local/tmp/" if is_replace_bin else "",
            PROFILE_PROCESS="--app {}".format(pkg) if pkg else "-p {}".format(pid),
            DURATION=duration,
            FREQ=freq
        )

        product_name = self.get_product_name()
        device_trace_file_name = "_".join([
            product_name, "Perfetto", Utils.get_current_time(), ".perfetto-trace"
        ])
        trace_file = PERFETTO_TRACE_FOLDER + device_trace_file_name
        perfetto_cmd = self.get_pefetto_core_cmd(trace_file, duration)

        # cold start
        if cold_start and pkg:
            logging.info("force-stop: {}".format(pkg))
            self.force_stop_app(pkg)
            self.wait(1)

        cmd = simpleperf_cmd + perfetto_cmd
        self.adb_cmd_without_output(cmd, True)
        self.wait(2)
        # report_cmd = SIMPLEPERF_CALLCHAIN_CMD.format(
        #     PRE="/data/local/tmp/" if is_replace_bin else "")
        # self.adb_cmd_without_output(report_cmd, True)

    def build_simpleperf_html(self, folder_name=None, pkg=None, pid=None,
                              one_flamegraph=False):
        if pkg is None and pid is None:
            raise Exception("Error: pkg={PKG}, pid={PID} !!".format(PKG=pkg, PID=pid))
        spf_path = Utils.get_spf_path()

        # pull perf.data, perf_report.txt
        self.adb_cmd_without_output(
            "pull /data/local/tmp/{DATA} {DST}".format(DATA=PERF_DATA_NAME,
                                                       DST=spf_path), False)
        self.adb_cmd_without_output(
            "pull /data/local/tmp/{DATA} {DST}".format(DATA=PERF_REPORT_DATA_NAME,
                                                       DST=spf_path), False)
        # build flamegraph
        os.chdir(spf_path)
        base_folder_name = folder_name
        debug_pkg = pkg if pkg else pid
        if base_folder_name is None:
            base_folder_name = "_".join(
                [self.get_product_name(), "Simpleperf", debug_pkg.replace(":", "-"),
                 Utils.get_current_time()]
            )
        base_folder_path = os.path.join(Utils.get_output_path(), base_folder_name)
        if not os.path.exists(base_folder_path):
            os.makedirs(base_folder_path)
        flamegraph_file_name = base_folder_name.replace("Simpleperf", "Flamegraph")
        simple_flamegraph_file = "_".join([flamegraph_file_name, ".html"])
        simple_flamegraph_file_path = os.path.join(base_folder_path, simple_flamegraph_file)
        detail_flamegraph_file = "_".join([flamegraph_file_name, "detail.html"])
        detail_flamegraph_file_path = os.path.join(base_folder_path, detail_flamegraph_file)

        # build detail file with chart statistics, sample table, flamegraphs
        # os.system("python report_html.py  -o {OUTPUT_PATH}".format(
        #     OUTPUT_PATH=detail_flamegraph_file_path
        # ))

        # build simple file with only flamegraph
        # os.system("python inferno/inferno.py -sc -o {REPORT_PATH} {FLAMEGRAPH}".format(
        #     REPORT_PATH=simple_flamegraph_file_path,
        #     FLAMEGRAPH="--one-flamegraph" if one_flamegraph else ""))

        # copy raw data -> output
        shutil.move(PERF_DATA_NAME, base_folder_path)
        # shutil.move(PERF_REPORT_DATA_NAME, base_folder_path)


class SystraceFileHelper(object):
    comm = r' comm=(.*) pid=(\d+) '
    pre_comm = r' prev_comm=(.*) prev_pid=(\d+) '
    next_comm = r' next_comm=(.*) next_pid=(\d+) '
    empty_tag_pattern = r'(<...>)-(\d+) '
    _LINE_PATTERN = re.compile(
        r"""
        (?P<name>.+) # task name
        \D
        (?P<pid>\d+) # pid
        \s+
        \D*(?P<tgid>\d*)\D* # tgid
        \s*
        \[(?P<cpu>\d+)\] # cpu
        \s+
        (?P<irqs_off>[d|X|\.]) # irqs-off
        (?P<need_resched>[N|n|p|\.]) # need-resched
        (?P<irq_type>[H|h|s|.]) # irq(hardware/software)
        (?P<preempt_depth>[0-9|.]) # preempt-depth
        \s+
        (?P<timestamp>\d+\W{1}\d+) # timestamp
        \W{1}\s+
        (?P<tracepoint>\w+) # trace point
        \W{1}\s+
        (?P<data>.+) # data   """,
        re.X | re.M
    )

    _LINE_PATTERN_DOT = re.compile(
        r"""
        (?P<name>.+) # task name
        \D
        (?P<pid>\d+) # pid
        \s+
        \D*(?P<tgid>\d*)\D* # tgid
        \s*
        \[(?P<cpu>\d+)\] # cpu
        \s+
        (?P<irqs_off>[d|X|\.]) # irqs-off
        (?P<need_resched>[N|n|p|\.]) # need-resched
        (?P<irq_type>[H|h|s|.]) # irq(hardware/software)
        (?P<preempt_depth>[0-9|.]) # preempt-depth
        (?P<migrate_disable_delay>[0-9|.]) # migrate-disable-delay
        \s+
        (?P<timestamp>\d+\W{1}\d+) # timestamp
        \W{1}\s+
        (?P<tracepoint>\w+) # trace point
        \W{1}\s+
        (?P<data>.+) # data   """,
        re.X | re.M
    )

    def __init__(self, input_file, from_convert=False):
        self.input_file = input_file

    @staticmethod
    def get_output_path(input_file, from_convert):
        file_name = os.path.splitext(input_file)[0]
        return file_name + "_enhance.html" if from_convert else file_name[0:-1] + ".html"

    def start_enhance(self):
        logging.warning("start enhance systrace file ...")
        if not os.path.exists(self.input_file):
            raise Exception("{} not exist,please check ...".format(self.input_file))

        # rm more ftrace dot for kernel>=5.15
        output_file = self.get_output_path(self.input_file, True)
        self.fix_redundant_dot(self.input_file, output_file)

        # fix all process name
        other_output_file = self.get_output_path(output_file, True)
        self.fix_all_process_name(output_file, other_output_file)

    def fix_redundant_dot(self, input_file, output_file):
        print("enhance to fix ftrace incompatible dot ..")
        if input_file is None or output_file is None:
            raise Exception("input or output file is None...")

        output_file_fp = open(output_file, "wb")
        with open(input_file, "rb") as trace_file:
            for line in trace_file:
                match = re.match(self._LINE_PATTERN_DOT, line)
                if match:
                    match_dict = match.groupdict()
                    irqs_off = match_dict.get("irqs_off", None)
                    need_resched = match_dict.get("need_resched", None)
                    irq_type = match_dict.get("irq_type", None)
                    preempt_depth = match_dict.get("preempt_depth", None)
                    migrate_disable_delay_flag = match_dict.get("migrate_disable_delay", None)
                    # print(migrate_disable_delay_flag)
                    if migrate_disable_delay_flag == ".":
                        raw_flag = "{}{}{}{}{}".format(irqs_off, need_resched, irq_type,
                                                       preempt_depth, migrate_disable_delay_flag)
                        new_flag = "{}{}{}{}".format(irqs_off, need_resched, irq_type,
                                                     preempt_depth)
                        new_line = line.replace(raw_flag, new_flag)
                        output_file_fp.write(new_line)
                    else:
                        output_file_fp.write(line)
                else:
                    output_file_fp.write(line)

        output_file_fp.close()

        pass

    def fix_all_process_name(self, input_file=None, output_file=None):
        print("enhance to fix <...> task name...")
        if input_file is None or output_file is None:
            raise Exception("input or output file is None...")

        all_tid_dict = self.collect_pid_dict(input_file)
        self.fix_all_task_name(all_tid_dict, input_file, output_file)

    def collect_pid_dict(self, input_file):
        rst_tid_dict = {}
        if input_file is None:
            raise Exception("file: {} is None".format(input_file))

        with open(input_file, "rb") as trace_file:
            for line in trace_file:
                comm_m = re.search(self.comm, line)
                if comm_m:
                    pid = comm_m.group(2)
                    tag = comm_m.group(1)
                    if rst_tid_dict.get(pid) is None:
                        rst_tid_dict[pid] = tag
                        continue

                pre_comm_m = re.search(self.pre_comm, line)
                if pre_comm_m:
                    pid = pre_comm_m.group(2)
                    tag = pre_comm_m.group(1)
                    if rst_tid_dict.get(pid) is None:
                        rst_tid_dict[pid] = tag
                        continue

                next_comm_m = re.search(self.next_comm, line)
                if next_comm_m:
                    pid = next_comm_m.group(2)
                    tag = next_comm_m.group(1)
                    if rst_tid_dict.get(pid) is None:
                        rst_tid_dict[pid] = tag
                        continue

        return rst_tid_dict

    def fix_all_task_name(self, tid_name_dict, input_file, output_file):
        """
        1.add pid name for all task name and add pid for all un-RenderThread task
        2.fix <...> for right task name
        :return:
        """
        if input_file is None or output_file is None:
            raise Exception("input or output file is None...")

        output_file_fp = open(output_file, "wb")
        with open(input_file, "rb") as trace_file:
            for line in trace_file:
                match = re.match(self._LINE_PATTERN, line)
                if match:
                    match_dict = match.groupdict()
                    name = match_dict.get("name", None)
                    pid = match_dict.get("pid", None)
                    target_pid_name = tid_name_dict.get(pid, None)
                    if self.check_filter(name):
                        new_line = line.replace(name, target_pid_name + " {}".format(
                            pid) if target_pid_name != "RenderThread" else target_pid_name)
                        output_file_fp.write(new_line)
                    else:
                        output_file_fp.write(line)
                else:
                    output_file_fp.write(line)

        output_file_fp.close()

    def fix_cpu_freq_limit(self):
        """perfetto to systrace dont show cpu_freq_limit info """

        output_file_fp = open(self.output_file, "wb")
        with open(self.input_file, "rb") as trace_file:
            for line in trace_file:
                match = re.match(self._LINE_PATTERN, line)
                if match:
                    match_dict = match.groupdict()
                    trace_point = match_dict.get("tracepoint", None)
                    data = match_dict.get("data", None)
                    if trace_point == "cpu_frequency_limits":
                        logging.info(("trace_point=", trace_point, ",data=", data))
                        remove_freq_data = data.replace("_freq", "")
                        new_list = remove_freq_data.split(" ")
                        new_data = " ".join(new_list[1:] + [new_list[0]])
                        new_line = line.replace(data, new_data)
                        logging.debug(("new_data", new_data))
                        output_file_fp.write(new_line)
                    else:
                        output_file_fp.write(line)
                else:
                    output_file_fp.write(line)

        output_file_fp.close()

    @staticmethod
    def check_filter(process_name):
        return process_name.strip() not in ("<idle>", "RenderThread")


# =====================================  For Test ======================================

def test_systrace():
    # systrace test
    serial = AndroidDevice.get_adb_device_serial()[0]
    device = AndroidDevice(serial)
    print(device.get_product_name())
    device.capture_systrace(5, False)


def traceview_test():
    # traceview test
    serial = AndroidDevice.get_adb_device_serial()[0]
    device = AndroidDevice(serial)
    # device.capture_traceview()
    pass


def simpleperf_test():
    serial = AndroidDevice.get_adb_device_serial()[0]
    device = AndroidDevice(serial)


if __name__ == '__main__':
    test_systrace()