#!/usr/bin/env python

import os
import sys
import systrace
import Queue
import re
import subprocess
import sys
import threading
import time
import zlib

import threading
from agents.atrace_agent import *
import util

import logging
import shutil

SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
PERFETTO_DST_PATH = None


def _collect_trace_data(file):
    # Read the output from ADB in a worker thread.  This allows us to monitor
    # the progress of ADB and bail if ADB becomes unresponsive for any reason.

    # Limit the stdout_queue to 128 entries because we will initially be reading
    # one byte at a time.  When the queue fills up, the reader thread will
    # block until there is room in the queue.  Once we start downloading the
    # trace data, we will switch to reading data in larger chunks, and 128
    # entries should be plenty for that purpose.
    stdout_queue = Queue.Queue(maxsize=128)

    if True:
        # Use stdout.write() (here and for the rest of this function) instead
        # of print() to avoid extra newlines.
        sys.stdout.write('Capturing trace...')

    # Use a chunk_size of 1 for stdout so we can display the output to
    # the user without waiting for a full line to be sent.
    stdout_thread = FileReaderThread(file, stdout_queue,
                                     text_file=False, chunk_size=1)
    stdout_thread.start()

    # Holds the trace data returned by ADB.
    trace_data = []
    # Keep track of the current line so we can find the TRACE_START_REGEXP.
    current_line = ''
    # Set to True once we've received the TRACE_START_REGEXP.
    reading_trace_data = False

    last_status_update_time = time.time()

    while (stdout_thread.isAlive() or
           not stdout_queue.empty()):

        # Read stdout from adb.  The loop exits if we don't get any data for
        # ADB_STDOUT_READ_TIMEOUT seconds.
        while True:
            try:
                chunk = stdout_queue.get(True, ADB_STDOUT_READ_TIMEOUT)
            except Queue.Empty:
                # Didn't get any data, so exit the loop to check that ADB is still
                # alive and print anything sent to stderr.
                break

            if reading_trace_data:
                # Save, but don't print, the trace data.
                trace_data.append(chunk)
            else:
                if not True:
                    sys.stdout.write(chunk)
                else:
                    # Buffer the output from ADB so we can remove some strings that
                    # don't need to be shown to the user.
                    current_line += chunk
                    if re.match(TRACE_START_REGEXP, current_line):
                        # We are done capturing the trace.
                        sys.stdout.write('Done.\n')
                        # Now we start downloading the trace data.
                        sys.stdout.write('Downloading trace...')

                        current_line = ''
                        # Use a larger chunk size for efficiency since we no longer
                        # need to worry about parsing the stream.
                        stdout_thread.set_chunk_size(4096)
                        reading_trace_data = True
                    elif chunk == '\n' or chunk == '\r':
                        # Remove ADB output that we don't care about.
                        current_line = re.sub(ADB_IGNORE_REGEXP, '', current_line)
                        if len(current_line) > 1:
                            # ADB printed something that we didn't understand, so show it
                            # it to the user (might be helpful for debugging).
                            sys.stdout.write(current_line)
                        # Reset our current line.
                        current_line = ''

    if True:
        if reading_trace_data:
            # Indicate to the user that the data download is complete.
            sys.stdout.write('Done.\n')
        else:
            # We didn't receive the trace start tag, so something went wrong.
            sys.stdout.write('ERROR.\n')
            # Show any buffered ADB output to the user.
            current_line = re.sub(ADB_IGNORE_REGEXP, '', current_line)
            if current_line:
                sys.stdout.write(current_line)
                sys.stdout.write('\n')

    # The threads should already have stopped, so this is just for cleanup.
    stdout_thread.join()

    file.close()

    return trace_data


def write_trace_html(html_filename, script_dir, agents):
    """Writes out a trace html file.

    Args:
      html_filename: The name of the file to write.
      script_dir: The directory containing this script.
      agents: The systrace agents.
    """
    systrace_dir = os.path.abspath(os.path.dirname(__file__))
    html_prefix = read_asset(systrace_dir, 'prefix.html')
    html_suffix = read_asset(systrace_dir, 'suffix.html')
    trace_viewer_html = read_asset(script_dir, 'systrace_trace_viewer.html')

    # Open the file in binary mode to prevent python from changing the
    # Open the file in binary mode to prevent python from changing the
    # line endings.
    html_file = open(html_filename, 'wb')
    html_file.write(html_prefix.replace('{{SYSTRACE_TRACE_VIEWER_HTML}}',
                                        trace_viewer_html))

    html_file.write('<!-- BEGIN TRACE -->\n')
    for a in agents:
        html_file.write('  <script class="')
        html_file.write("trace-data")
        html_file.write('" type="application/text">\n')
        html_file.write(a)
        html_file.write('  </script>\n')
    html_file.write('<!-- END TRACE -->\n')

    html_file.write(html_suffix)
    html_file.close()
    print('\n    wrote file://%s\n' % os.path.abspath(html_filename))


def read_asset(src_dir, filename):
    return open(os.path.join(src_dir, filename)).read()


# =========================================================

def _preprocess_trace_data(trace_data, dir):
    """Performs various processing on atrace data.

    Args:
      trace_data: The raw trace data.
    Returns:
      The processed trace data.
    """
    trace_data = ''.join(trace_data)
    if trace_data:
        trace_data = strip_and_decompress_trace(trace_data)

    if not trace_data:
        print >> sys.stderr, ('No data was captured.  Output file was not '
                              'written.')
        sys.exit(1)

    if True:
        if os.path.exists(dir + "/ps.txt"):
            f = open(dir + "/ps.txt", 'r')
            ps_dump = f.read()
            if ps_dump is not None:
                thread_names = extract_thread_list(ps_dump)
                trace_data = fix_thread_names(trace_data, thread_names)

    if True:
        # Issue printf command to device and patch tgids
        if os.path.exists(dir + "/task.txt"):
            f = open(dir + "/task.txt", 'r')
            procfs_dump = f.read()
            if procfs_dump is not None:
                pid2_tgid = extract_tgids(procfs_dump)
                trace_data = fix_missing_tgids(trace_data, pid2_tgid)

    if True:
        trace_data = fix_circular_traces(trace_data)

    return trace_data


# ============================================================================================


class BaseConvert(object):

    def __init__(self, path):
        self.input_path = path

    def handle_one_convert(self):
        raise NotImplementedError

    def handle_batch_convert(self):
        raise NotImplementedError

    def start(self):
        raise NotImplementedError


class PerfettoTraceToSystrace(BaseConvert):

    def __init__(self, src_path, perfetto_lib_path):
        super(PerfettoTraceToSystrace, self).__init__(src_path)
        self.perfetto_lib_path = perfetto_lib_path

    def start(self):
        logging.info("Perfetto trace convert start ...")
        # 1.copy file to linux and wait to covert
        src_dir_path = self.input_path
        logging.warning("start to copy, waiting...")
        dst_path = None
        if os.path.isdir(src_dir_path):
            dst_path = os.path.join(self.perfetto_lib_path, "perfetto-trace")  # copy whole folder
            if os.path.exists(dst_path):
                shutil.rmtree(dst_path)
            shutil.copytree(self.input_path, dst_path)
        else:
            shutil.copy(self.input_path, self.perfetto_lib_path)  # copy single file
            # for file ,update src_dir_path dir name
            src_dir_path = os.path.abspath(os.path.dirname(src_dir_path))

        logging.warning(
            "copy done. wait linux env convert done then click ENTER KEY to continue...")
        raw_input()

        # 2.cut the result back to path
        logging.info("start to copy file to src...")
        target_list = self.get_systrace_list(self.perfetto_lib_path)
        for f in target_list:
            try:
                target_name = os.path.basename(f)
                target_file = os.path.join(src_dir_path, target_name)
                if os.path.exists(target_file):
                    logging.warning("{} exits, will update..".format(target_file))
                    os.remove(target_file)
                shutil.move(f, src_dir_path)
                os.remove(f.split("_systrace.html")[0])
                logging.info("\n\tWrote done: {} ".format(target_file))
            except Exception as e:
                print(e.message)

        # if folder exist,remove it
        if dst_path and os.path.exists(dst_path):
            shutil.rmtree(dst_path)

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


class AtraceToSystrace(BaseConvert):

    def __init__(self, path):
        super(AtraceToSystrace, self).__init__(path)

    def handle_one_convert(self):
        """"input_path is one systrace folder"""

        atrace_raw_path = ""
        if os.path.splitext(self.input_path)[1] in (".atrace", ".ctrace"):
            atrace_raw_path = self.input_path
        elif os.path.split(self.input_path)[1] == "atrace_raw":
            atrace_raw_path = self.input_path
        if not os.path.exists(atrace_raw_path):
            logging.debug("not support atrace type: " + self.input_path)
            return
        logging.info("atrace file convert start: " + self.input_path)
        try:
            with open(atrace_raw_path, "rb") as f:
                atrace_raw = _collect_trace_data(f)
                atrace_data = _preprocess_trace_data(atrace_raw, self.input_path)
                write_trace_html(self.input_path + "_assmble_trace.html", SCRIPT_PATH,
                                 [atrace_data])
        except Exception as e:
            pass

    # TODO
    def handle_batch_convert(self):
        logging.warning("atrace batch convert start..")
        all_file_list = []
        for root, _, files in os.walk(self.input_path):
            all_file_list += [os.path.abspath(os.path.join(root, f)) for f in files]
        logging.debug(("rst_list: ", all_file_list))
        for one_file in all_file_list:
            self.input_path = one_file
            self.handle_one_convert()

    def start(self):
        logging.info("atrace type data convert start ...")
        is_single = os.path.isfile(self.input_path)
        if is_single:
            self.handle_one_convert()
        else:
            self.handle_batch_convert()


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


def start(perfetto_lib_path, to_parse_path):
    """ support raw data convert , we should support below format

    1. atrace_raw(<=Android Q), .atrace, .ctrace, .perfetto-trace (>= Android R) single convert
    2. batch convert
    """

    logging.info((perfetto_lib_path, to_parse_path))
    is_perfetto = is_perfetto_trace(to_parse_path)
    if is_perfetto:
        PerfettoTraceToSystrace(to_parse_path, perfetto_lib_path).start()
    else:
        AtraceToSystrace(to_parse_path).start()


def test():
    pass


if __name__ == '__main__':
    test()
