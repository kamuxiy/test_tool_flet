# coding=utf-8

import logging
import os
import shutil
import sys
import threading
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.android import AndroidDevice
from common.utils import Utils


class SystraceCapture(object):

    def __init__(self, timeout, multi_device):
        self.timeout = timeout
        self.multi_device = multi_device

    def start(self):
        logging.info("[start] timeout:{}, multi_device: {}".format(self.timeout, self.multi_device))
        if self.multi_device:
            self.run_multi_device()
        else:
            self.run_one_device()

    def run_one_device(self):
        serial = AndroidDevice.get_adb_device_serial()[0]
        device = AndroidDevice(serial)
        device.capture_systrace(self.timeout)

    def run_multi_device(self):
        device_list = AndroidDevice.get_adb_device_serial()
        thread_list = []
        for s in device_list:
            t = AtraceThread(s, self.timeout)
            thread_list.append(t)
            t.start()

        for t in thread_list:
            t.join()


class PerfettoTraceCapture(object):

    def __init__(self, timeout, multi_device):
        self.timeout = timeout
        self.multi_device = multi_device

    def start(self):
        logging.info("timeout:{}, multi_device: {}".format(self.timeout, self.multi_device))
        if self.multi_device:
            self.run_multi_device()
        else:
            self.run_one_device()

    @staticmethod
    def is_mtrace_enable():
        """Check if mtrace is enabled by looking for mtrace-monitor threads

        Returns:
            bool: True if mtrace-monitor threads are found, False otherwise
        """
        try:
            serial = AndroidDevice.get_adb_device_serial()[0]
            device = AndroidDevice(serial)

            # Execute ps -AT command to get all threads and filter for mtrace-monitor
            output = device.adb_shell_output("ps -AT | grep mtrace-monitor")

            # If grep finds mtrace-monitor threads, output will not be empty
            # If no threads found, grep returns empty string or error
            if output and "mtrace-monitor" in output:
                logging.info("mtrace is enabled - found mtrace-monitor threads")
                return True
            else:
                logging.info("mtrace is not enabled - no mtrace-monitor threads found")
                return False

        except Exception as e:
            logging.warning("Failed to check mtrace status: {}".format(e))
            return False

    @staticmethod
    def setup_mtrace_env(device, mtrace_target_app):
        """Setup mtrace environment for the target app
        Args:
            device: AndroidDevice instance
            mtrace_target_app: target app package name
        Raises:
            Exception: if mtrace package not found
        """
        # check eroot status
        device.make_sure_debugged_device()

        if not PerfettoTraceCapture.is_mtrace_enable():
            raise Exception(
                "device not install mtrace !! please install it first ! \n"
                "See: https://odocs.myoas.com/docs/8Nk6MJlLWxFGjNqL/   Password: kkrwpw \n")

        # clean up old mtrace files
        if mtrace_target_app == "top":
            mtrace_target_app, user_id = device.get_foreground_app_pkg_and_uid()
        else:
            user_id = 0

        # storage/emulated/0/Download/com.tencent.mm/files/
        mtrace_dir = "/storage/emulated/{}/Download/{}/files".format(user_id, mtrace_target_app)
        device.adb_cmd_without_output("rm -rf {}".format(mtrace_dir), with_shell=True)

        return mtrace_target_app, user_id

    @staticmethod
    def capture_full_ptrace(mtrace_target_app=None):
        serial = AndroidDevice.get_adb_device_serial()[0]
        device = AndroidDevice(serial)

        if mtrace_target_app is not None:  # Add for oplus mtrace
            mtrace_target_app, user_id = PerfettoTraceCapture.setup_mtrace_env(device,
                                                                               mtrace_target_app)

        ptrace_cfg_file = os.path.join(Utils.get_config_folder_path(), "config",
                                       "perfetto_cfg.pbtx")
        trace_file = device.capture_full_ptrace(ptrace_cfg_file, mtrace_app=mtrace_target_app)

        if mtrace_target_app is not None:
            PerfettoTraceCapture.mtrace_convert(device, trace_file, mtrace_target_app, user_id)

    @staticmethod
    def mtrace_convert(device, trace_file, mtrace_target_app, user_id):
        os.chdir(Utils.get_mtrace_path())
        # replace ":" -> "_" for process name
        mtrace_target_app = mtrace_target_app.replace(":", "_")
        # Get mtrace file from device
        mtrace_dir = "/storage/emulated/{}/Download/{}/files".format(user_id, mtrace_target_app)
        device_files = device.adb_shell_output("ls {}".format(mtrace_dir))
        mtrace_filename = [f for f in device_files.split() if f.endswith('.mtrace')][0]
        mtrace_device_path = "{}/{}".format(mtrace_dir, mtrace_filename)

        # Pull mtrace file to current directory
        mtrace_file = os.path.join(os.getcwd(), mtrace_filename)
        device.adb_cmd_without_output("pull {} {}".format(mtrace_device_path, mtrace_file),
                                      with_shell=False)

        logging.warning("start convert mtrace into perfetto ...")
        # Convert mtrace to perfetto format
        convert_cmd = "mtrace_converter.exe -m {} {}".format(trace_file, mtrace_file)
        os.system(convert_cmd)

        mtrace_file_name = os.path.basename(mtrace_file)
        ptrace_file_name = mtrace_file_name + '.ptrace'

        # Create new file names with trace prefix
        # like 21001V-xxx_Perfetto_xx_.perfetto-trace-data.4709.mtrace.ptrace
        new_mtrace_name = trace_file + "-" + mtrace_target_app + "_" + mtrace_file_name
        new_ptrace_name = trace_file + "-" + mtrace_target_app + "_" + ptrace_file_name

        # Move and rename files
        shutil.move(mtrace_file_name, new_mtrace_name)
        shutil.move(ptrace_file_name, new_ptrace_name)
        logging.info("Mtrace convert done")

    @staticmethod
    def capture_long_ptrace():
        serial = AndroidDevice.get_adb_device_serial()[0]
        device = AndroidDevice(serial)
        ptrace_cfg_file = os.path.join(Utils.get_config_folder_path(),
                                       "config",
                                       "long_perfetto_cfg.pbtx")
        device.capture_full_ptrace(ptrace_cfg_file)

    def run_one_device(self):
        serial = AndroidDevice.get_adb_device_serial()[0]
        device = AndroidDevice(serial)
        device.capture_perfetto_trace(self.timeout)

    def run_multi_device(self):
        device_list = AndroidDevice.get_adb_device_serial()
        thread_list = []
        for s in device_list:
            t = PerfettoThread(s, self.timeout)
            thread_list.append(t)
            t.start()

        for t in thread_list:
            t.join()


class ThreadObject(threading.Thread):

    def __init__(self, serial, timeout):
        super(ThreadObject, self).__init__()
        self.serial = serial
        self.timeout = timeout
        self.__running = True

    def stop(self):
        self.__running = False

    def run(self):
        pass


class AtraceThread(ThreadObject):

    def __init__(self, serial, timeout):
        super(AtraceThread, self).__init__(serial, timeout)

    def run(self):
        logging.debug("tid : {}".format(threading.current_thread().ident))
        device = AndroidDevice(self.serial)
        device.capture_systrace(self.timeout)


class PerfettoThread(ThreadObject):
    def __init__(self, serial, timeout):
        super(PerfettoThread, self).__init__(serial, timeout)

    def run(self):
        logging.debug("tid : {}".format(threading.current_thread().ident))
        device = AndroidDevice(self.serial)
        device.capture_perfetto_trace(self.timeout)


def atrace_test():
    serial = AndroidDevice.get_adb_device_serial()[0]
    capture = SystraceCapture(5, True)
    capture.start()


def perfetto_test():
    serial = AndroidDevice.get_adb_device_serial()[0]
    capture = PerfettoTraceCapture(10, False)
    capture.start()


if __name__ == '__main__':
    perfetto_test()
