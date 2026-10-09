# coding=utf-8
import time
import logging
import os
import json
import argparse
import functools
import threading

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))


class Log(object):
    BASIC_FORMAT = (
        "%(asctime)s %(process)d %(thread)d "
        "[%(filename)s/%(funcName)s]-%(lineno)d %(levelname)s %(message)s"
    )
    DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

    @staticmethod
    def init_logger(debug_enable, file_path=os.path.join(SCRIPT_PATH, "../output/log")):
        ColorfulLogging.init()
        logger = logging.getLogger()

        log_formatter = logging.Formatter(Log.BASIC_FORMAT, Log.DATE_FORMAT)

        # record for console
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        console_handler.setLevel(logging.DEBUG)

        logger.addHandler(console_handler)

        if debug_enable:
            if not os.path.exists(file_path):
                os.makedirs(file_path)
            file_name = "tool_{}.log".format(Utils.get_current_time())
            # record for file
            file_handler = logging.FileHandler(os.path.abspath(os.path.join(file_path, file_name)))
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)


def log_debug(msg):
    logging.debug(msg)


def log_info(msg):
    logging.info(msg)


def log_warning(msg):
    logging.warning(msg)


def log_error(msg):
    logging.error(msg)


class ColorfulLogging(object):
    '''
    logging.basicConfig(level=logging.DEBUG) # set debug level
    colorer.ColorfulLogging.init() # init once
    logging.debug("this is debug")
    logging.info("this is info")
    logging.warning("this is warnning")
    logging.error("this is error")
    logging.critical("this is critical")
    '''

    def __init__(self):
        pass

    @staticmethod
    def init():
        import platform
        if platform.system() == 'Windows':
            # Windows does not support ANSI escapes and we are using API calls to set the console color
            logging.StreamHandler.emit = ColorfulLogging.add_coloring_to_emit_windows(
                logging.StreamHandler.emit)
        else:
            # all non-Windows platforms are supporting ANSI escapes so we use them
            logging.StreamHandler.emit = ColorfulLogging.add_coloring_to_emit_ansi(
                logging.StreamHandler.emit)

    # now we patch Python code to add color support to logging.StreamHandler
    @staticmethod
    def add_coloring_to_emit_windows(fn):
        # add methods we need to the class
        def _out_handle(self):
            import ctypes
            return ctypes.windll.kernel32.GetStdHandle(self.STD_OUTPUT_HANDLE)

        out_handle = property(_out_handle)

        def _set_color(self, code):
            import ctypes
            self.STD_OUTPUT_HANDLE = -11  # Constants from the Windows API
            hdl = ctypes.windll.kernel32.GetStdHandle(self.STD_OUTPUT_HANDLE)
            ctypes.windll.kernel32.SetConsoleTextAttribute(hdl, code)

        setattr(logging.StreamHandler, '_set_color', _set_color)

        def new(*args):
            FOREGROUND_BLUE = 0x0001  # text color contains blue.
            FOREGROUND_GREEN = 0x0002  # text color contains green.
            FOREGROUND_RED = 0x0004  # text color contains red.
            FOREGROUND_INTENSITY = 0x0008  # text color is intensified.
            FOREGROUND_WHITE = FOREGROUND_BLUE | FOREGROUND_GREEN | FOREGROUND_RED
            # winbase.h
            STD_INPUT_HANDLE = -10
            STD_OUTPUT_HANDLE = -11
            STD_ERROR_HANDLE = -12
            # wincon.h
            FOREGROUND_BLACK = 0x0000
            FOREGROUND_BLUE = 0x0001
            FOREGROUND_GREEN = 0x0002
            FOREGROUND_CYAN = 0x0003
            FOREGROUND_RED = 0x0004
            FOREGROUND_MAGENTA = 0x0005
            FOREGROUND_YELLOW = 0x0006
            FOREGROUND_GREY = 0x0007
            FOREGROUND_INTENSITY = 0x0008  # foreground color is intensified.
            BACKGROUND_BLACK = 0x0000
            BACKGROUND_BLUE = 0x0010
            BACKGROUND_GREEN = 0x0020
            BACKGROUND_CYAN = 0x0030
            BACKGROUND_RED = 0x0040
            BACKGROUND_MAGENTA = 0x0050
            BACKGROUND_YELLOW = 0x0060
            BACKGROUND_GREY = 0x0070
            BACKGROUND_INTENSITY = 0x0080  # background color is intensified.
            levelno = args[1].levelno
            if (levelno >= 50):
                color = FOREGROUND_RED | FOREGROUND_INTENSITY | BACKGROUND_INTENSITY
            elif (levelno >= 40):
                color = FOREGROUND_RED | FOREGROUND_INTENSITY
            elif (levelno >= 30):
                color = FOREGROUND_YELLOW | FOREGROUND_INTENSITY
            elif (levelno >= 20):
                color = FOREGROUND_GREEN | FOREGROUND_INTENSITY
            elif (levelno >= 10):
                color = FOREGROUND_MAGENTA | FOREGROUND_INTENSITY
            else:
                color = FOREGROUND_WHITE
            args[0]._set_color(color)
            ret = fn(*args)
            args[0]._set_color(FOREGROUND_WHITE)
            return ret

        return new

    @staticmethod
    def add_coloring_to_emit_ansi(fn):
        # add methods we need to the class
        def new(*args):
            levelno = args[1].levelno
            if (levelno >= 50):
                color = '\x1b[31m'  # red
            elif (levelno >= 40):
                color = '\x1b[31m'  # red
            elif (levelno >= 30):
                color = '\x1b[33m'  # yellow
            elif (levelno >= 20):
                color = '\x1b[32m'  # green
            elif (levelno >= 10):
                color = '\x1b[35m'  # pink
            else:
                color = '\x1b[0m'  # normal
            args[1].msg = color + args[1].msg + '\x1b[0m'  # normal
            return fn(*args)

        return new


class Utils(object):
    CONFIG = None

    @staticmethod
    def get_current_time():
        return time.strftime("%Y%m%d_%H%M%S", time.localtime())

    @staticmethod
    def get_global_config():
        if Utils.CONFIG is None:
            file_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "../config/profile_cfg.json"))
            with open(file_path, "r+") as f:
                Utils.CONFIG = json.load(f)
        return Utils.CONFIG

    @staticmethod
    def get_output_path():
        env_dir = os.environ.get("PERFETTO_OUTPUT_DIR")
        if env_dir:
            return env_dir
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "../output"))

    @staticmethod
    def get_mtrace_path():
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib/mtrace"))

    @staticmethod
    def get_mtrace_pkg():
        # Get mtrace directory path
        mtrace_path = Utils.get_mtrace_path()
        # Find .apex file in mtrace directory
        for file in os.listdir(mtrace_path):
            if file.endswith('.apex'):
                return os.path.abspath(os.path.join(mtrace_path, file))
        # Return None if no .apex file found
        return None

    @staticmethod
    def get_spf_path():
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "../lib/simpleperf"))

    @staticmethod
    def open_report_in_browser(report_path):
        import webbrowser
        try:
            # Try to open the report with Chrome
            browser = webbrowser.get('google-chrome')
            browser.open(report_path, new=0, autoraise=True)
        except webbrowser.Error:
            # webbrowser.get() doesn't work well on darwin/windows.
            webbrowser.open_new_tab(report_path)

    @staticmethod
    def check_path_exist(path):
        if not os.path.exists(path):
            raise Exception("{} is not exist !!".format(path))

    @staticmethod
    def make_sure_path_exist(path):
        if not os.path.exists(path):
            os.makedirs(path)

    @staticmethod
    def get_config_folder_path():
        return os.path.join(SCRIPT_PATH, "..")


def consume_time(func):
    @functools.wraps(func)
    def wrap(*args, **kwargs):
        start_time = time.time()
        func(*args, **kwargs)
        spend = round((time.time() - start_time), 2)
        logging.info("Task done.. total spend: {} s".format(spend))

    return wrap


# TODO, multi-device should refactor
# class ThreadObject(threading.Thread):
#
#     def __init__(self):
#         super(ThreadObject, self).__init__()
#         self.__running = True
#
#     def stop(self):
#         self.__running = False
#
#     def run(self):
#         logging.info("run...")
#         pass


class ProfileType(object):
    SYSTRACE = "systrace"
    TRACEVIEW = "traceview"
    SIMPLEPERF = "simpleperf"
    LIGHT_PERFETTO = "light_perfetto"
    FULL_PERFETTO = "full_perfetto"
    MTRACE_PERFETTO = "mtrace_perfetto"
    LONG_PERFETTO = "long_perfetto"
    SIMPLEPERF_PERFETTO = "simpleperf_perfetto"


class ParseType(object):
    LAUNCH_TIME_COLD_START = "launch_time_cold_start"
    ANR = "anr"
    RAWDATA_CONVERT = "rawdata_convert"
    SYSTRACE_ENHANCE = "systrace_enhance"


Utils.get_global_config()

if __name__ == '__main__':
    pass