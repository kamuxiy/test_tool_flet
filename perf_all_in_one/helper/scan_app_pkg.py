# coding=utf-8

"""
this script is used for scan apk pkg name and version.
input apk folder path, output app_name.txt file which contain
pkg_name --> version formatter line
"""

import argparse
import os
import subprocess
import re

_DEBUG = False
CURRENT_PATH = os.path.abspath(os.path.dirname(__file__))
os.chdir(CURRENT_PATH)
print("current path", os.getcwd())


def get_arg():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--path", type=str, dest="path", help="APK path")
    args = parser.parse_args()
    path = args.path
    replace_path = path.replace("\\", "/")
    print("path: ", path, "replace_path:", replace_path)
    return replace_path


def run_cmd(cmd):
    """ if sucess, rst_code=None else throw exception"""
    output = None
    is_ok = None
    print("Run cmd: {CMD}".format(CMD=cmd))
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        output = e.output
        is_ok = e.returncode
    if _DEBUG:
        print("Cmd:", cmd, "[Debug] is_ok:", is_ok, ",output:", output)
    return (is_ok, output)


def get_pkg(apk_name):
    cmd = " ".join(["../lib/aapt.exe dump badging", apk_name])
    is_ok, output = run_cmd(cmd)
    m = re.search(r"package: name='(.*?)'.*versionName='(.*?)'", output)
    pkg_name = "_".join([m.group(1), m.group(2)])
    return pkg_name


def main():
    apk_path = get_arg()
    all_apk_list = [os.path.join(apk_path, apk) for apk in sorted(os.listdir(apk_path)) if
                    apk.endswith(".apk")]
    print("all_apk_list: ", all_apk_list)

    output_path = os.path.join(apk_path,"app_info.txt")
    with open(output_path, "w+") as f:
        for apk in all_apk_list:
            pkg_name = get_pkg(apk)
            print(apk, " --> ", pkg_name)
            f.write("--".join([apk, pkg_name]))
            f.write("\n")


if __name__ == '__main__':
    main()
