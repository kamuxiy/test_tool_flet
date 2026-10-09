# coding=utf-8

import argparse
import os


def get_arg():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path", type=str,
                        dest="path", help="your systrace full path")
    args = parser.parse_args()
    path = args.path
    replace_path = path.replace("\\", "/")
    return replace_path


def main():
    origin_file_path = get_arg()
    if not os.path.exists(origin_file_path):
        raise Exception("{} is not exits !!".format(origin_file_path))

    file_path, file_name = os.path.split(origin_file_path)
    file_name_list = os.path.splitext(file_name)
    new_file_name = "".join([file_name_list[0], "_ignore", file_name_list[1]])
    new_file_path = os.path.join(file_path, new_file_name)

    p_new_file = open(new_file_path, "wb")
    with open(origin_file_path, "rb") as f:
        for line in f:
            if ": mm_vmscan_direct_reclaim_end:" in line:
                continue
            p_new_file.write(line)

    print("Write done: \n {}".format(new_file_path))
    p_new_file.close()


if __name__ == '__main__':
    main()
