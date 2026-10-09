# coding=utf-8

'''
[About Tool]
Large size systrace(more than 300 MB) file cannot load by chrome when you analyze performance issue.
now that ,this tool can help you to cut this file into some small size file which can load normally.

Usage:
python auto_systrace_split.py -t %threshold% -p %SCRIPT_PATH%

Author: liuyun@oppo.com
Date: 2018-11-24
'''

import argparse
import sys
import io
import os
import time
from collections import OrderedDict

# print("Use {}\n".format(sys.version))
DEBUG = False
FLAG_TRACE_BEGIN = "tracer: nop"
FLAG_TRACE_TAIL_INFO = (
"""
  </script>
<!-- END TRACE -->
</body>
</html>
"""
)


def get_file_size(path):
    if not os.path.exists(path):
        raise Exception(path, " is not exist !!")
    size = os.path.getsize(path)
    debug((path, "size: ", size >> 20, "MB"))
    return size


class SimpleSpliter(object):
    def __init__(self, threshold_size, file_path):
        self.file_path = file_path
        self.total_size_byte = get_file_size(file_path)
        self.threshold_size_byte = threshold_size
        self.new_file_dir = OrderedDict()
        self.head_info_list = []
        self.head_info_size_byte = 0
        self.cache_head_done = False

    def init_new_file_list(self):
        file_folder_path = os.path.abspath(os.path.dirname(self.file_path))
        file_base_name = os.path.basename(self.file_path)
        file_order = 0
        total_size = self.total_size_byte
        while total_size > 0:
            file_order += 1
            new_file_path = self.build_new_file_path(file_folder_path,
                                                     file_order, file_base_name)
            if total_size > self.threshold_size_byte:
                self.new_file_dir[new_file_path] = self.threshold_size_byte
            else:
                self.new_file_dir[new_file_path] = total_size
            total_size -= self.threshold_size_byte

    @staticmethod
    def build_new_file_path(file_folder_path, file_order, file_base_name):
        prefix_name, suffix_name = os.path.splitext(file_base_name)
        return os.path.join(file_folder_path,
                            "".join([prefix_name, "_{}".format(file_order), suffix_name]))

    def cache_head_info(self, line):
        if FLAG_TRACE_BEGIN in line.lower():
            self.head_info_list.append(line)
            self.cache_head_done = True
        if not self.cache_head_done:
            self.head_info_list.append(line)
            self.head_info_size_byte += len(line)

    def main(self):
        if self.total_size_byte < self.threshold_size_byte:
            print("The file size < overflow_size({} MB), no need split !!".format(
                str(self.threshold_size_byte >> 20)))
            return

        start_time = time.time()
        self.init_new_file_list()
        # split file
        p_file_dir = OrderedDict()
        for path, size in self.new_file_dir.items():
            p_file_dir[open(path, "wb")] = size

        max_file_count = len(p_file_dir)
        last_file_head_filled = False
        middle_file_head_filled = False

        with open(self.file_path, "rb") as old_file:
            file_index = 0
            for line in old_file:
                self.cache_head_info(line)
                cur_file = p_file_dir.keys()[file_index]
                if file_index == 0:  # write tail only
                    cur_file.write(line)
                    if p_file_dir[cur_file] > 0:
                        p_file_dir[cur_file] -= len(line)
                    else:
                        cur_file.write(FLAG_TRACE_TAIL_INFO)
                        file_index += 1
                elif file_index == (max_file_count - 1):  # write head only
                    if not last_file_head_filled:
                        cur_file.writelines(self.head_info_list)
                        cur_file.write(line)
                        last_file_head_filled = True
                    else:
                        cur_file.write(line)
                        p_file_dir[cur_file] -= len(line)
                else:  # write head and tail
                    if not middle_file_head_filled:
                        cur_file.writelines(self.head_info_list)
                        middle_file_head_filled = True
                    cur_file.write(line)
                    if p_file_dir[cur_file] > 0:
                        p_file_dir[cur_file] -= len(line)
                    else:
                        cur_file.write(FLAG_TRACE_TAIL_INFO)
                        file_index += 1

        # close
        for f in p_file_dir.keys():
            print("\tWrite done: {}\n".format(f.name))
            f.close()

        print("Split Done. total spend time: {} s \n".format((int)(time.time() - start_time)))


def get_arg():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--threshold", type=int, dest="threshold",
                        help="split threshold size(MB)")
    parser.add_argument("-p", "--path", type=str,
                        dest="path", help="your systrace full path")
    args = parser.parse_args()
    threshold_size = args.threshold
    path = args.path
    if (not threshold_size) or (not path):
        raise Exception(
            "threshold or path is None: threshold={},path={}".format(threshold_size, path))
    replace_path = path.replace("\\", "/")
    debug(("replaced_path:", replace_path))
    return threshold_size, replace_path


def debug(msg):
    if DEBUG:
        print(msg)


if __name__ == "__main__":
    threshold_size_mb, file_path = get_arg()
    splitter = SimpleSpliter(threshold_size_mb * 1024 * 1024, file_path)
    splitter.main()
