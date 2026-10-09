# coding=utf-8

"""
PerfsHelperAllInOne tool want to simple RD analyze performance issue flow. now support below feature:

1. integrate common profile tool including systrace,traceview, simplerperf one-key capture.
also support multi-device capture.
2. auto parse systrace file for App cold launch time parse, will output simple statics diff data
for REF and DUT device. more detail ,please refs to README.md
3. split big systrace to small files when big-size systrace cannot load by chrome
4. atrace2html for atracce raw data when you using log-tool capture systrace
5. TODO:
 (1) common script for pin cpu ,gpu freq for MTK & Qcom platform
 (2) response time parse.
 (3) more detail parse for cold launch time ,such tp -> first frame show

other: will continue dev for perfs tool

Author: liuyun@oppo.com
Date: 2019/6/14
"""

import argparse
import os
import logging

from profile.auto_traceview import TraceviewCapture
from profile.auto_simpleperf import SimplePerfCapture
from profile.auto_systrace import SystraceCapture
from profile.auto_systrace import PerfettoTraceCapture

from parse.systrace_parser import LaunchTimeParser
from common.utils import ProfileType, ParseType
from common.android import AndroidDevice, SystraceFileHelper
from common.utils import Log, Utils, consume_time
# from common import raw_data_trace_convert

import sys

sys.path.append("./lib/systrace")


def get_opts():
    """ Get script config if have """

    parser = argparse.ArgumentParser(description="""Perfs Tools config parameter""")
    args_group = parser.add_argument_group("Perfs Options")
    args_group.add_argument('--profile_type', type=str, help="""profiler type support
                            systrace, traceview, simpleperf and so on..""")
    args_group.add_argument('--parse_type', type=str, help=""" now support app cold_start parse""")

    args_group.add_argument('-t', "--timeout", type=int, dest="timeout",
                            help="""capture duration """)

    args_group.add_argument('-b', "--buffer_size", type=int, dest="buffer_size",
                            help=""" systrace or traceview buffer size """)
    args_group.add_argument('-si', "--sampling_internal", type=int,
                            help=""" traceview simpling internal(us)""")
    args_group.add_argument('-c', "--cold_start", action='store_true',
                            help=""" caputre app cold launch method trace""")

    args_group.add_argument('-p', "--pid", type=int, dest="pid",
                            help="""process id""")

    args_group.add_argument('-pkg', "--app", type=str, dest="app",
                            help="""Oplus mtrace target package""")

    args_group.add_argument('-f', "--freq", type=int, help=""" simpleperf record freq """)
    args_group.add_argument('--one_flamegraph', action='store_true', help="""Generate one
                              flamegraph instead of one for each thread.""")

    args_group.add_argument('-fp', "--file_path", type=str, help="""store file path""")

    args_group.add_argument('-m', "--multi_device", action='store_true',
                            help=""" start to multi-device capture
                            systrace ,simpleperfs, traceview support """)
    args_group.add_argument('-d', "--debug", action='store_true', default=False,
                            help=""" enable debug """)

    args = parser.parse_args()
    print_head_info(args)
    return args


def handle_raw_data_to_systrace(args):
    from lib.systrace import raw_data_trace_convert  # 懒加载（仅此功能需要，Python3 兼容）
    target_path = args.file_path.replace("\\", "/")
    perfetto_convert_lib_path = Utils.get_global_config()["perfetto_convert_lib_path"]
    raw_data_trace_convert.start(perfetto_convert_lib_path, target_path)


def handle_traceview_capture(args):
    logging.debug(("[start] type: ", args.profile_type, ",multi-device:", args.multi_device,
                   ",timeout:", args.timeout, ",buffer:", args.buffer_size, ",sampling_internal:",
                   args.sampling_internal))
    tvc = TraceviewCapture(not args.cold_start, args.timeout, args.buffer_size,
                           args.sampling_internal, args.multi_device)
    tvc.start()


def handle_systrace_capture(args):
    capture = SystraceCapture(args.timeout, args.multi_device)
    capture.start()


def handle_full_ptrace_capture(args):
    capture = PerfettoTraceCapture(args.timeout, args.multi_device)
    capture.capture_full_ptrace()


def handle_mtrace_perfetto(args):
    capture = PerfettoTraceCapture(args.timeout, args.multi_device)
    mtrace_target_app = args.app
    logging.info("start capture mtrace with perfetto for app: {}".format(mtrace_target_app))
    capture.capture_full_ptrace(mtrace_target_app)


def handle_long_ptrace_capture(args):
    capture = PerfettoTraceCapture(args.timeout, args.multi_device)
    capture.capture_long_ptrace()


def handle_light_ptrace_capture(args):
    capture = PerfettoTraceCapture(args.timeout, args.multi_device)
    capture.start()


def handle_simpleperf_capture(args):
    spc = SimplePerfCapture(AndroidDevice.get_adb_device_serial()[0])
    if args.pid:
        spc.capture_pid_process(args.pid, args.timeout, args.freq, args.one_flamegraph)
    else:
        spc.capture_top_app(args.cold_start, args.timeout, args.freq, args.one_flamegraph)


def handle_simpleperf_pefetto_capture(args):
    spc = SimplePerfCapture(AndroidDevice.get_adb_device_serial()[0])
    spc.capture_simpleperf_pefetto(args.pid, args.cold_start, args.timeout, args.freq)


def handle_systrace_parse(args):
    logging.debug("start ...")
    to_parse_path = args.file_path
    if not os.path.exists(to_parse_path):
        raise Exception(" parser file patch not exist: {}".format(to_parse_path))
    to_parse_path = to_parse_path.replace("\\", "/")
    LaunchTimeParser(to_parse_path).start()


def handle_systrace_enhance(args):
    target_path = args.file_path.replace("\\", "/")
    trace_enhance_helper = SystraceFileHelper(target_path, True)
    trace_enhance_helper.start_enhance()


def print_head_info(args):
    print("*" * 20 + " PerfAllInOne " + "*" * 20)
    input_config = vars(args)
    print("[Input options]")
    print(str(input_config))
    print("*" * 60)


@consume_time
def main():
    Utils.make_sure_path_exist(Utils.get_output_path())
    args = get_opts()
    Log.init_logger(args.debug)
    if args.profile_type:
        if args.profile_type == ProfileType.TRACEVIEW:
            handle_traceview_capture(args)
        elif args.profile_type == ProfileType.SYSTRACE:
            handle_systrace_capture(args)
        elif args.profile_type == ProfileType.LIGHT_PERFETTO:
            handle_light_ptrace_capture(args)
        elif args.profile_type == ProfileType.FULL_PERFETTO:
            handle_full_ptrace_capture(args)
        elif args.profile_type == ProfileType.MTRACE_PERFETTO:
            handle_mtrace_perfetto(args)
        elif args.profile_type == ProfileType.LONG_PERFETTO:
            handle_long_ptrace_capture(args)
        elif args.profile_type == ProfileType.SIMPLEPERF:
            handle_simpleperf_capture(args)
        elif args.profile_type == ProfileType.SIMPLEPERF_PERFETTO:
            handle_simpleperf_pefetto_capture(args)
        else:
            logging.error("unknown: profile type {}".format(args.profile_type))
    elif args.parse_type:
        if args.parse_type == ParseType.LAUNCH_TIME_COLD_START:
            handle_systrace_parse(args)
        elif args.parse_type == ParseType.RAWDATA_CONVERT:
            handle_raw_data_to_systrace(args)
        elif args.parse_type == ParseType.SYSTRACE_ENHANCE:
            handle_systrace_enhance(args)
    else:
        logging.error("type not support !!")


if __name__ == '__main__':
    main()