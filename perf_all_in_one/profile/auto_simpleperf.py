# coding =utf-8

import os
import sys
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common.android import AndroidDevice

CURRENT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__)))

from common.utils import Utils


class SimplePerfCapture(object):

    def __init__(self, serial):
        if serial is None:
            raise Exception("device serial is None !!")
        self.device = AndroidDevice(serial)

    def capture_pid_process(self, pid, duration_s, freq, one_flamegraph):
        target_pkg = self.device.get_pid_pkg(pid)
        logging.info("Current pid: {}, pkg: {}".format(pid, target_pkg))
        if not target_pkg:
            raise Exception("pid ={} not exist ,please check again!!".format(pid))
        self.device.capture_simpleperf_data(pid=pid, duration=duration_s, freq=freq)
        self.device.build_simpleperf_html(pkg=target_pkg, one_flamegraph=one_flamegraph)

    def capture_top_app(self, cold_start, duration_s, freq, one_flamegraph):
        top_app = self.device.get_foreground_app_pkg()
        logging.info("Current Top Package: {}".format(top_app))
        self.device.capture_simpleperf_data(pkg=top_app, cold_start=cold_start, duration=duration_s,
                                            freq=freq)
        self.device.build_simpleperf_html(pkg=top_app, one_flamegraph=one_flamegraph)

    def capture_simpleperf_pefetto(self, pid, cold_start, duration_s, freq):
        output_folder_name = "_".join(
            [self.device.get_product_name(), "Simpleperf-Pertetto", Utils.get_current_time()]
        )
        self.device.adb_cmd_without_output("rm -rf /data/misc/perfetto-traces/*.perfetto-trace",
                                           True)
        if pid is None:  # common case
            top_app = self.device.get_foreground_app_pkg()
            self.device.capture_perfetto_and_simpleperf(pkg=top_app,
                                                        cold_start=cold_start,
                                                        duration=duration_s,
                                                        freq=freq)
            self.device.build_simpleperf_html(folder_name=output_folder_name, pkg=top_app)
        else:
            self.device.capture_perfetto_and_simpleperf(pid=pid, duration=duration_s, freq=freq)
            self.device.build_simpleperf_html(folder_name=output_folder_name, pid=pid)

        output_folder_path = os.path.join(Utils.get_output_path(), output_folder_name)
        # pull pefetto-trace
        self.device.dump_info(self.device.get_product_name(), "logcat", False, "logcat -b all -d ",
                              os.path.join(output_folder_path, output_folder_name + "-logcat.txt"))
        self.device.adb_cmd_without_output(
            "pull data/misc/perfetto-traces {}".format(output_folder_path), False)


def test():
    serial = AndroidDevice.get_adb_device_serial()[0]
    spc = SimplePerfCapture(serial)
    spc.capture_top_app(True, 10, 12500, False)


if __name__ == '__main__':
    test()
