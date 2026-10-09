# coding=utf-8

import os
import sys
import re
import time
import functools
from collections import OrderedDict
import logging

# import pyecharts
import csv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common import utils
from common.utils import Utils, consume_time


class LaunchTimeParser(object):
    TAG = "Cold Launch Timer Parser"
    BAR_MODE = "device"

    _COLD_LAUNCHING_KEY = "LaunchingTime"
    _SHOW_EVENT = [_COLD_LAUNCHING_KEY,
                   "ActivityThreadMain",
                   "bindApplication",
                   "activityStart",
                   "activityResume",
                   "Choreographer#doFrame"]

    _FLAG_LAUNCHING = "|launching:"

    # TODO: regular express is too slow ,need to optimize
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

    def __init__(self, folder_path):
        self.to_parse_path = folder_path
        self.launch_pkg = None
        self.target_event_list = []
        self.rst_data_list = []  # include dir

    def get_ps_file(self, trace_file):
        split_list = os.path.split(trace_file)
        prefix = os.path.splitext(split_list[1])[0]
        ps_file_name = split_list[1]  # Systrace_2033.html
        match = re.match(r"(?P<name>.*)\s*(?P<time>-\d+ms)", prefix)
        if match:
            ps_file_name = match.groupdict()["name"] + ".html"
        rst = os.path.join(split_list[0], ps_file_name + "-ps.txt")
        logging.debug(("trace_file:", trace_file, "ps_file_name:", ps_file_name, "rst:", rst))
        return rst

    def start(self):
        logging.info("launch time parse start ...")
        file_list = self.get_file_list(self.to_parse_path)
        trace_file_list = [f for f in file_list if f.endswith(".html")]
        logging.debug(("[start] trace_file_list:", trace_file_list))

        for trace_file_path in trace_file_list:
            current_data_dir = self.collect_data(trace_file_path, self.get_ps_file(trace_file_path))
            if current_data_dir:
                self.rst_data_list.append(current_data_dir)
        logging.debug(("rst_data_list:", str(self.rst_data_list)))
        self.statics_data()
        logging.info("parse done !!")

    def collect_data(self, trace_file_path, trace_ps_file_path):
        logging.info("collect start for \n\ttrace_file_path= {}\n\ttrace_ps_file_path={}".format(
            trace_file_path,
            trace_ps_file_path))
        Utils.check_path_exist(trace_file_path)
        Utils.check_path_exist(trace_ps_file_path)

        flag_start_grep = False
        target_event_list = []
        launch_app = App()
        with open(trace_file_path, "rb") as trace_file:
            for line in trace_file:
                line = line.strip()
                if LaunchTimeParser._FLAG_LAUNCHING in line:
                    flag_start_grep = True
                    self.build_app_info(launch_app, line, trace_ps_file_path)
                    continue
                if flag_start_grep:
                    main_event = self.build_event(launch_app.pid, line)
                    if main_event:
                        target_event_list.append(main_event)
        logging.debug(("[start] target_event_list:", str(target_event_list)))

        for e in target_event_list:
            logging.debug(("e: ", str(e)))

        if launch_app.launch_start_time is None or launch_app.launch_end_time is None:
            logging.error(
                "\n{FILE} dont have launching stage !! ignore this trace ,pls check !!!".format(
                    FILE=trace_file_path))
            return None

        launching_time = round(
            (launch_app.launch_end_time - launch_app.launch_start_time) * 1000, 3)

        project_name = os.path.basename(trace_file_path).split("_")[0]
        rst_dir = OrderedDict()
        rst_dir[LaunchTimeParser.BAR_MODE] = project_name
        rst_dir[LaunchTimeParser._COLD_LAUNCHING_KEY] = launching_time
        return self.parse_data(rst_dir, target_event_list)

    def statics_data(self):
        logging.info("start to statics data ...")
        # bar = pyecharts.Bar(LaunchTimeParser.TAG, self.launch_pkg, height=800)
        show_data_list = []
        for rst_dir in self.rst_data_list:
            web_show_data = OrderedDict()
            csv_show_data = OrderedDict(
                [(LaunchTimeParser.BAR_MODE, rst_dir.get(LaunchTimeParser.BAR_MODE))])
            show_event = LaunchTimeParser._SHOW_EVENT
            for key, val in rst_dir.items():
                if key in show_event or key.split("@")[0] in show_event:
                    web_show_data[key] = val
                    csv_show_data[key] = val

            # bar.add(rst_dir.get(LaunchTimeParser.BAR_MODE), web_show_data.keys(),
            #         web_show_data.values(),
            #         is_more_utils=True, xaxis_rotate=-20, is_label_show=True)

            show_data_list.append(csv_show_data)

        # output
        output_path = os.path.join(self.to_parse_path,
                                   "Launch_time_diff_{}.html".format(Utils.get_current_time()))
        # bar.render(output_path)
        utils.Utils.open_report_in_browser(output_path)
        csv_path = output_path.replace("html", "csv")
        self.save_to_csv(show_data_list, csv_path)

    def save_to_csv(self, data_dir_list, csv_path):
        """ data save to csv file """
        logging.info("start to build csv..")
        logging.debug(("data_dir_list", data_dir_list, "csv_path", csv_path))

        rst_row_list = []
        column_data_list = []
        max_column_size = len(data_dir_list[0].keys())
        function_name_list = data_dir_list[0].keys()

        # find the max function name list to show
        for i, data_dir in enumerate(data_dir_list):
            size = len(data_dir_list[i].keys())
            if size > max_column_size:
                max_column_size = size
                function_name_list = data_dir_list[i].keys()

        column_data_list.append(function_name_list)  # append function name list
        for i in range(max_column_size):  # construct rst list
            rst_row_list.append([])

        # build data.
        # Note: cannot make sure doFrame absolute order such as some activity more one Frame
        for cur_row, row_list in enumerate(rst_row_list):
            cur_function_name = function_name_list[cur_row]
            row_list.append(cur_function_name)

            for data_dir in data_dir_list:
                cur_function_data = data_dir.get(cur_function_name, None)
                row_list.append(cur_function_data if cur_function_data is not None else " no data")
                logging.debug((
                    "cur_func_data:", cur_function_name, "cur_row:", cur_row, "row_list:",
                    row_list))

        with open(csv_path, "wb") as f:
            csv_writer = csv.writer(f)
            for data_list in rst_row_list:
                csv_writer.writerow(data_list)

    def build_app_info(self, launch_app, line, ps_file_path):
        """ For launch node we only care pkg and pid """

        Utils.check_path_exist(ps_file_path)
        match = re.match(LaunchTimeParser._LINE_PATTERN, line)
        if match:
            match_dict = match.groupdict()
            data = match_dict.get("data", None)
            timestamp = float(match_dict.get("timestamp", -1))
            if data is None:
                raise Exception("get launch app info error !!")

            data_list = data.split("|")
            flag = data_list[0]
            if flag == "S" and launch_app.launch_end_time is None:
                launch_app.launch_start_time = timestamp
            elif flag == "F":
                launch_app.launch_end_time = timestamp

            if launch_app.pkg is None:
                current_pkg = self.get_pkg_from_data(data_list[2])
                launch_app.pkg = current_pkg
                self.launch_pkg = current_pkg
            if launch_app.pid is None:
                launch_app.pid = self.get_target_ps_pid(launch_app.pkg, ps_file_path)

        logging.debug("[build_app_info] app: {}".format(str(launch_app)))

    def handle_duplicate_func(self, func, spend_time, to_parse_dir):
        """
        Some func of UI thread are the same(such as activitystart/resume ..) in order to handle this
        key will add number suffix like that activitystart ,activitystart@1,
        :param func:
        :param spend_time:
        :param to_parse_dir:
        :return:
        """
        current_key_list = to_parse_dir.keys()
        rst_func = ""
        for key in current_key_list:
            if func in key:
                rst_func = key
        logging.debug("rst_func: {}".format(rst_func))
        func_str_list = rst_func.split("@@")
        suffix_number = 0 if len(func_str_list) == 1 else int(func_str_list[-1])
        to_parse_dir["{}@@{}".format(func, suffix_number + 1)] = spend_time

    def build_event(self, target_pid, event_line):
        """
        <...>-19598 [004] .... 11244.346750: tracing_mark_write: B|19598|Setup proxies
        <...>-3816  [007] .... 11244.222391: tracing_mark_write: S|1670|launching: performance.oppo.com.helloworld|0
        :param event_line: to parse event line
        :return: Event object
        """
        current_event = Event()
        rst_event = None
        match = re.match(LaunchTimeParser._LINE_PATTERN, event_line)
        if match:
            match_dict = match.groupdict()
            logging.debug(("[build_event] target_pid", target_pid, ",match_dict: ", match_dict))
            current_event.task_name = match_dict.get("name", "")
            tgid = match_dict.get("tgid", -1)
            current_event.tgid = int(tgid) if tgid else -1  # if case tgid is white space
            current_event.pid = int(match_dict.get("pid", -1))
            current_event.timestamp = float(match_dict.get("timestamp", -1))
            current_event.trace_point = match_dict.get("tracepoint", "")
            data = match_dict.get("data", None)

            # build main event
            if (target_pid == current_event.pid == current_event.tgid) and (
                    current_event.trace_point == "tracing_mark_write"):
                data_list = data.split("|")
                logging.debug(("data_list:", data_list))
                size = len(data_list)
                current_event.flag = data_list[0] if size > 0 else ""
                current_event.tid = int(data_list[1]) if size > 1 else ""
                current_event.func = data_list[2] if size > 2 else ""
                rst_event = current_event
                logging.debug(("[build_event] add event: ", str(rst_event)))
        return rst_event

    def get_pkg_from_data(self, event_data):
        """
        launching: performance.oppo.com.helloworld
        :param event:
        :return:
        """
        logging.debug(("[get_pkg_from_data] event: ", str(event_data)))
        tmp_list = [e for e in re.split(r"[:|\s]", event_data) if e]
        launch_pkg = tmp_list[1]
        logging.debug(("[get_pkg_from_data] launch_pkg: ", launch_pkg, ",tmp_list:", tmp_list))
        return launch_pkg

    def get_file_list(self, folder_path):
        Utils.check_path_exist(folder_path)
        all_file_list = [os.path.abspath(os.path.join(root, f)) for root, _, files in
                         os.walk(folder_path) for f in files if not f.startswith("Launch_time")]
        logging.debug(("[get_file_list] all_file_list:", all_file_list))
        return all_file_list

    def parse_data(self, rst_dir, target_event_list):
        logging.info("start to parse data ...")
        func_stack = FunctionStack()
        for event in target_event_list:
            if event.flag == "B":
                logging.debug(("push -> ", str(event)))
                func_stack.push(event)
            elif event.flag == "E":
                if func_stack.size() == 0:
                    logging.warning("tag_stack empty !!, ignore this End !")
                    continue
                stack_top_event = func_stack.peek()  # compute top func spend time
                func = stack_top_event.func
                spend_time = round((event.timestamp - stack_top_event.timestamp) * 1000, 3)  # ms
                logging.debug(("current func: ", func))
                if rst_dir.get(func, None) is not None:
                    self.handle_duplicate_func(func, spend_time, rst_dir)
                else:
                    rst_dir[func] = spend_time
                func_stack.pop()
                logging.debug(("pop-> spend-time:", spend_time, "current event:", str(event),
                               ",top event,", str(stack_top_event)))

        for key, val in rst_dir.items():
            logging.debug("{} -> {}".format(key, val))
        return rst_dir

    def get_target_ps_pid(self, target_pkg, ps_file_path):
        logging.debug(
            ("[get_target_ps_pid] target_pkg:", target_pkg, ",ps_file_path:", ps_file_path))
        Utils.check_path_exist(ps_file_path)
        rst_pid = 0
        with open(ps_file_path, "rb") as ps_file:
            for ps_line in ps_file:
                current_pkg = ps_line.split(" ")[-1].strip()
                logging.debug(
                    ("[get_target_ps_pid] current_pkg: ", current_pkg, ",target_pkg:", target_pkg,
                     ",ps_line:", ps_line))
                if current_pkg and (current_pkg in target_pkg):
                    logging.debug("[get_target_ps_pid] catch ...")
                    thread_info_list = [s for s in ps_line.split(" ") if s]
                    thread_pid = thread_info_list[1]
                    thread_tid = thread_info_list[2]
                    if thread_pid == thread_tid:
                        rst_pid = int(thread_tid)
                        break
        logging.debug(("[get_ps_pid_for_target] rst_pid: ", rst_pid))
        return rst_pid


class Event(object):

    def __init__(self):
        self.task_name = ""
        self.tgid = 0
        self.pid = 0
        self.tid = 0
        self.timestamp = 0.0
        self.func = ""  # function name
        self.flag = ""  # B or E
        self.pkg = ""
        self.trace_point = ""

    def __str__(self):
        return (
            "Event: {NAME}-{PID} ({TGID}) ... {TT}: {POINT}: "
            "{FLAG}|{TID}|{FUNC}, pkg={PKG}".format(
                NAME=self.task_name,
                PID=self.pid,
                TGID=self.tgid,
                TT=self.timestamp,
                TID=self.tid,
                FUNC=self.func,
                FLAG=self.flag,
                POINT=self.trace_point,
                PKG=self.pkg
            )
        )


class App(object):

    def __init__(self, pkg=None, pid=None, launch_start_time=None, launch_end_time=None):
        self.pkg = pkg
        self.pid = pid
        self.launch_start_time = launch_start_time
        self.launch_end_time = launch_end_time

    def __str__(self):
        return "App(pkg={PKG},pid={PID},launch_start_time={S},launch_end_time={E}".format(
            PKG=self.pkg,
            PID=self.pid,
            S=self.launch_start_time,
            E=self.launch_end_time)


class FunctionStack(object):

    def __init__(self):
        self.__items = []

    def push(self, item):
        self.__items.append(item)

    def size(self):
        return len(self.__items)

    def pop(self):
        if self.size() == 0:
            raise Exception(" Stack is None!")
        return self.__items.pop()

    def peek(self):
        if self.size() == 0:
            raise Exception("Stack is None!")
        return self.__items[-1]


def test_parse_item():
    line = "<...>-19598 [002] .... 11244.280517: tracing_mark_write: B|19598|PostFork"
    current_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../tests/systrace_parse_test"))
    parser = LaunchTimeParser(current_path)
    parser.start()


def test_reg_trace_file():
    s_list = [
        r"C:\Users\80238652\Desktop\360\360\20001Q_Systrace_2020_05_23_10_51_20-7029ms.html",
        r"C:\Users\80238652\Desktop\360\360\20001Q_Systrace_2020_05_23_10_51_20 -7029ms.html",
        r"C:\Users\80238652\Desktop\360\360\20001Q_Systrace_2020_05_23_10_51_20.html"
    ]
    for s in s_list:
        match = re.match(r"(?P<name>.*)\s*(?P<time>-\d+ms)", s)
        if match:
            print(m)
        else:
            print(s, "not match")


def test_result_to_csv():
    """
    1.one file
    2.two file the same
    3.two file not the same
    """

    od_1 = OrderedDict(
        [
            ("device", "20001Q"),
            ("LaunchTime", 2001.32),
            ("bindApplication", 300.21),
            ("activityStart", 400.3),
            ("activityResume", 250),
            ("doFrame", 34)
        ]
    )
    od_2 = OrderedDict(
        [
            ("device", "20001R"),
            ("LaunchTime", 156.32),
            ("bindApplication", 320.21),
            ("activityStart", 365.3),
            ("activityResume", 111),
            ("doFrame", 60)
        ]
    )
    rst_list = []
    show_dir_list = [od_1, od_2]

    colum_list = []
    colum_list.append(show_dir_list[0].keys())
    for device_data in show_dir_list:
        colum_list.append(device_data.values())

    print("colum_list:", colum_list)

    single_list = colum_list[0]

    for i in enumerate(single_list):
        rst_list.append([])

    for row in colum_list:
        for index, item in enumerate(row):
            rst_list[index].append(item if item != "device" else " ")

    print("rst_list", rst_list)

    with open("launch_time_diff.csv", "wb") as f:
        csv_writer = csv.writer(f)
        for data_list in rst_list:
            csv_writer.writerow(data_list)


if __name__ == '__main__':
    test_result_to_csv()
    pass