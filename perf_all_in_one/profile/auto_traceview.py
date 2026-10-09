# coding=utf-8

import argparse
import sys
import os
import threading
import logging

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.android import AndroidDevice


class TraceviewCapture(object):
    """
    This class will capture current top package App traceview
    """

    def __init__(self, activity_start, timeout, buffer_size, sampling_internal, multi_device):
        self.activity_start = activity_start
        self.timeout = timeout
        self.buffer_size = buffer_size
        self.sampling_internal = sampling_internal
        self.multi_device_enable = multi_device

    def run_one_device(self):
        serial = AndroidDevice.get_adb_device_serial()[0]
        tv = TraceviewThreadObject(serial, self.activity_start, self.timeout, self.buffer_size,
                                   self.sampling_internal)
        tv.run()

    def run_multi_device(self):
        serial_list = AndroidDevice.get_adb_device_serial()
        thread_list = []
        for s in serial_list:
            t = TraceviewThreadObject(s, self.activity_start, self.timeout, self.buffer_size,
                                      self.sampling_internal)
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()

    def start(self):
        logging.debug("start")
        if self.multi_device_enable:
            self.run_multi_device()
        else:
            self.run_one_device()


class TraceviewThreadObject(threading.Thread):

    def __init__(self, serial, activity_start, timeout, buffer_size, sampling_internal):
        super(TraceviewThreadObject, self).__init__()
        self.serial = serial
        self.activity_start = activity_start
        self.timeout = timeout
        self.buffer_size = buffer_size
        self.sampling_internal = sampling_internal
        self.__running = True

    def stop(self):
        self.__running = False

    def run(self):
        logging.debug("tid : {}".format(threading.current_thread().ident))
        device = AndroidDevice(self.serial)
        device.capture_traceview(self.activity_start,
                                 buffer_size_mb=self.buffer_size,
                                 timeout=self.timeout,
                                 sampling_interval_us=self.sampling_internal)


def main():
    pass


if __name__ == '__main__':
    main()
