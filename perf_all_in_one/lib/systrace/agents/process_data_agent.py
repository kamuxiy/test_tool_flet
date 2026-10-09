#!/usr/bin/env python
"""Use this module to add process name."""
import systrace_agent
from systrace import util

PS_COMMAND_PROC = "ps -A -o USER,PID,PPID,VSIZE,RSS,WCHAN,ADDR=PC,S,NAME,COMM" \
                  "&& ps -AT -o USER,PID,TID,CMD"


def try_create_agent(options, categories):
    return AndroidProcessDataAgent(options, categories)


class AndroidProcessDataAgent(systrace_agent.SystraceAgent):
    def __init__(self, options, categories):
        super(AndroidProcessDataAgent, self).__init__(options, categories)
        self._trace_data = ""
        self.options = options

    def start(self):
        # self._trace_data += self.dump_once()
        pass

    def collect_result(self):
        self._trace_data += self.dump_once()

    def expect_trace(self):
        return True

    def dump_once(self):
        cmd_args = [PS_COMMAND_PROC]
        adb_output, adb_return_code = util.run_adb_shell(cmd_args,
                                                         self.options.device_serial)
        return adb_output + "\n"

    def get_trace_data(self):
        return 'PROCESS DUMP\n' + self._trace_data

    def get_class_name(self):
        return 'trace-data'
