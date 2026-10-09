#!/usr/bin/env python

import os
import logging
import shutil

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
PERFETTO_DST_PATH = None


class ThreadObject(object):
    pass


class PerfettoToSystrace(object):

    def __init__(self, path):
        self.input_path = path

    def start(self):
        logging.info("Perfetto trace convert start ...")

        if os.path.isdir(self.input_path):
            self.handle_batch_convert()
        else:
            self.handle_one_convert()

    def handle_one_convert(self):
        pass

    def handle_batch_convert(self):
        pass

    @staticmethod
    def get_systrace_list(path):
        if not os.path.exists(path):
            raise Exception("{} is not exits !".format(path))

        rst_list = []
        for root, _, files in os.walk(path):
            rst_list += [os.path.abspath(os.path.join(root, f)) for f in files if
                         f.endswith(".html")]
        return rst_list


class AtraceToSystrace(object):

    def __init__(self, path):
        super(AtraceToSystrace, self).__init__(path)

    def handle_one_convert(self):
        pass

    def handle_batch_convert(self):
        pass

    def start(self):
        pass


def is_perfetto_trace(to_parse_path):
    rst = False
    if os.path.isfile(to_parse_path):
        rst = True if to_parse_path.endswith(".perfetto-trace") else False
    else:
        folder_list = os.listdir(to_parse_path)
        logging.debug(("folder_list", folder_list))
        if len(folder_list) == 0:
            raise Exception("{} is empty..".format(to_parse_path))
        rst = True if folder_list[0].endswith(".perfetto-trace") else False
    return rst


def start():
    pass


if __name__ == '__main__':
    pass
