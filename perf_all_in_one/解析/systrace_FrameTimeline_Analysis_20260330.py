import collections
import os
import subprocess
import sys

import time
from datetime import datetime

import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter
from perfetto.trace_processor import TraceProcessorConfig, TraceProcessor
from sqlalchemy.util import OrderedDict


def get_headerIndex(name):
    for index in range(len(headers)):
        col_name = headers[index]
        if name in col_name:
            return index

    return -1


# trace = r"H:\2025importantPart\systraceAnalysis\systrace\拨号退出不卡顿-5s.perfetto-trace"
# trace = r"H:\2025importantPart\systraceAnalysis\systrace\拨号退出卡顿-5s.perfetto-trace"
# bin_path = r"H:\2025importantPart\systraceAnalysis\trace_processor_shell.exe"


other_sql = """
select expected_table.ts as expected_ts,  actual_table.ts as  actual_ts, expected_table.surface_frame_token as vsyncId, expected_table.dur as expected_dur, actual_table.dur as actual_dur,expected_table.name as name ,actual_table.jank_type as jank_type , actual_table.on_time_finish as on_time_finish 
from 

( select ts, dur, surface_frame_token , display_frame_token, jank_type,jank_tag, on_time_finish, present_type, layer_name, process.name  as name 
from actual_frame_timeline_slice left join process using(upid)  
where process.name  !="/system/bin/surfaceflinger" and dur !=1 )  actual_table  

join 

( select ts, dur, surface_frame_token , display_frame_token , process.name as name from expected_frame_timeline_slice 
left join process using(upid) where process.name  !="/system/bin/surfaceflinger"  ) expected_table  

on  
(
actual_table.surface_frame_token = expected_table.surface_frame_token
and  actual_table.name = expected_table.name)
order by  actual_ts
"""

sf_sql = """
select expected_table.ts as expected_ts,  actual_table.ts as  actual_ts, expected_table.display_frame_token as vsyncId, expected_table.dur as expected_dur, actual_table.dur as actual_dur,expected_table.name as name,actual_table.jank_type as jank_type , actual_table.on_time_finish as on_time_finish  
from

 ( select ts, dur, surface_frame_token as app_token, display_frame_token, jank_type, on_time_finish, present_type, layer_name, process.name  as name 
 from actual_frame_timeline_slice 
 left join process using(upid)  
 where process.name  ="/system/bin/surfaceflinger" and  dur !=1 )  actual_table  

 join

 ( select ts, dur, surface_frame_token , display_frame_token , process.name as name 
 from expected_frame_timeline_slice left join process using(upid) 
 where process.name  ="/system/bin/surfaceflinger"  )  expected_table  

 on  
 (
actual_table.display_frame_token = expected_table.display_frame_token
and  
actual_table.name = expected_table.name
)
order by  actual_ts
"""

Vsync_app_sql = """
SELECT counter.id, counter.ts, counter.value FROM counter WHERE counter.track_id IN (     SELECT track.id     FROM track     WHERE track.name = 'VSYNC-app' )
order by  counter.ts
"""

Vsync_sf_sql = """
SELECT counter.id, counter.ts, counter.value FROM counter WHERE counter.track_id IN (     SELECT track.id     FROM track     WHERE track.name = 'VSYNC-sf' )
order by  counter.ts
"""

activeMode_fps_sql = """
SELECT ts,value,name   FROM counter JOIN process_counter_track ON process_counter_track.id = counter.track_id WHERE process_counter_track.name like '%ActiveModeFps%' 
order by  ts
"""

NextFrameInterval_sql = """
SELECT * FROM slice where slice.name like "NextFrameInterval%" 
"""

VSP_setPeriod_sql = """
SELECT * FROM counter JOIN process_counter_track ON process_counter_track.id = counter.track_id WHERE process_counter_track.name like "VSP-setPeriod%" 
"""

VsyncWorkDuration_appSF_sql = """
SELECT * FROM counter JOIN process_counter_track ON process_counter_track.id = counter.track_id WHERE process_counter_track.name = "VsyncWorkDuration-appSf" 
"""

iq_sql = """
 SELECT * FROM counters c WHERE c.name = "iq" order by  ts
"""

main_thread_sql = """
SELECT    p.pid as pid, p.name as pthread_name, t.tid as tid, t.name as thread_name , t.is_main_thread as  is_main_thread   FROM process p JOIN thread t ON t.tid = p.pid WHERE p.name IS NOT NULL ; 
"""

transition_playing_sql = """
               SELECT      
                   slice.*,     
                   track.name as track_name,     
                   track.id as track_id,     
                   process.name as process_name,     
                   process.pid as process_id,     
                   thread.name as thread_name,     
                   thread.tid as thread_id 
               FROM slice 
               JOIN track ON slice.track_id = track.id 
               LEFT JOIN thread_track ON slice.track_id = thread_track.id 
               LEFT JOIN thread ON thread_track.utid = thread.utid 
               LEFT JOIN process ON thread.upid = process.upid 
               WHERE track.name = 'Transition'   
               AND slice.name like 'playing' 
               ORDER BY slice.ts
           """

Transition_open_syncReady_sql= """
            SELECT      
               slice.*,     
               track.name as track_name,     
               track.id as track_id,     
               process.name as process_name,     
               process.pid as process_id,     
               thread.name as thread_name,     
               thread.tid as thread_id 
           FROM slice 
           JOIN track ON slice.track_id = track.id 
           LEFT JOIN thread_track ON slice.track_id = thread_track.id 
           LEFT JOIN thread ON thread_track.utid = thread.utid 
           LEFT JOIN process ON thread.upid = process.upid 
           WHERE track.name = 'Transition'   
           AND
            (slice.name like 'Transition-OPEN-SyncReady%' 
            OR 
            slice.name like 'Transition-TO_FRONT-SyncReady%' )
           ORDER BY slice.ts
"""


fps_dur_map = {30: 33300000, 60: 16600000, 90: 11100000, 120: 8300000}

# headers = ["时间戳", "时间", "vsyncId", "进程名","线程名",  "expected_dur", "actual_dur","出帧时长(doframe+drawFrame时间)", "备注信息",   "丢帧数(出帧时长/expected_dur-1)", "fps监控的关键字",
#            "fps",
#            "丢帧数(出帧时长/fps-1)",
#            "vsync类型(vsync_sf,vsync_app)", "vsync开始时间戳", "vsync开始结束时间戳", "vsync持续时间", "丢帧数（出帧时长/vsync持续时间-1)",
#            "丢帧数(过滤前)",
#            "丢帧数类型", "是否需要过滤iq信息", "丢帧数（过滤iq）",
#            "丢帧数（过滤堆buffer）", "堆buffer起始VsyncId",
#            "是否正在滑动", "丢帧数（只保留滑动区间）",
#            "滑动区间监控的关键字", "丢帧数(通过bufferTX计算)","无效rt插帧数",  "连续丢帧数", "是否丢帧", "1s内总丢帧总数"]

headers = ["时间戳", "时间", "vsyncId", "进程名", "线程名", "滑动区间监控的关键字", "丢帧数(通过bufferTX计算)",
           "无效rt插帧数", "连续丢帧数", "是否丢帧", "1s内总丢帧总数", "expected_dur", "actual_dur",
           "出帧时长(doframe+drawFrame时间)", "丢帧数(actual_dur/expected_dur-1)", "fps监控的关键字",
           "fps",
           "丢帧数(出帧时长/fps-1)",
           "vsync类型(vsync_sf,vsync_app)", "vsync开始时间戳", "vsync开始结束时间戳", "vsync持续时间",
           "丢帧数（出帧时长/vsync持续时间-1)",
           "丢帧数(过滤前)",
           "丢帧数类型", "是否需要过滤iq信息", "丢帧数（过滤iq）",
           "丢帧数（过滤堆buffer）", "堆buffer起始VsyncId",
           "是否正在滑动", "丢帧数（只保留滑动区间）", "备注信息"
           ]

actual_ts_index = headers.index("时间戳")
actual_time_index = headers.index("时间")
actual_vsyncId_index = headers.index("vsyncId")
pthread_name_index = headers.index("进程名")
thread_name_index = headers.index("线程名")
expected_dur_index = headers.index("expected_dur")
actual_dur_index = headers.index("actual_dur")
do_draw_dur_index = headers.index("出帧时长(doframe+drawFrame时间)")
vsync_check_info_index = headers.index("备注信息")
drop_frames_byExpected_index = headers.index("丢帧数(actual_dur/expected_dur-1)")
fps_keyInfo_index = headers.index("fps监控的关键字")
fps_index = headers.index("fps")
drop_frames_byFps_index = headers.index("丢帧数(出帧时长/fps-1)")
vsync_type_index = headers.index("vsync类型(vsync_sf,vsync_app)")
vsync_start_time_index = headers.index("vsync开始时间戳")
vsync_end_time_index = headers.index("vsync开始结束时间戳")
vsync_dur_index = headers.index("vsync持续时间")
drop_frames_byVsync_index = headers.index("丢帧数（出帧时长/vsync持续时间-1)")
drop_frames_before_filter_index = headers.index("丢帧数(过滤前)")
drop_frames_type_before_filter_index = headers.index("丢帧数类型")
filter_iq_or_not_index = headers.index("是否需要过滤iq信息")
drop_frames_filter_iq_index = headers.index("丢帧数（过滤iq）")
drop_frames_filter_buffer_index = headers.index("丢帧数（过滤堆buffer）")
filter_buffer_start_index = headers.index("堆buffer起始VsyncId")
is_scrolling_index = headers.index("是否正在滑动")
drop_frames_filter_scrolling_index = headers.index("丢帧数（只保留滑动区间）")
scrolling_keyInfo_index = headers.index("滑动区间监控的关键字")
bufferTX_index = headers.index("丢帧数(通过bufferTX计算)")
noUseful_rt_count_index = headers.index("无效rt插帧数")
drop_frames_index = headers.index("连续丢帧数")
drop_frame_or_not_index = headers.index("是否丢帧")
drop_frames_sum_1s_index = headers.index("1s内总丢帧总数")

# 针对动画字段泄漏/ 指定动画关键字，但trace中无相关信息 情况丢弃该动画
Discard_reports = False
Discard_info = ""
Discarad_limit = 50
same_iq_checkTime = 50000000
# 部分线程没有对应frameTimeLine 也是有效数据
thread_without_frameTimeLine = ["launcher.anim"]
# 部分进程只关注doframe，不做drawFrame
thread_without_drawFrame = ["launcher.anim"]
# 在做某些动画的时候只需要关注部分线程： 桌面应用图标缩放动画只需要关注launch.anim
thread_with_anim = {"window_animation: GESTURE_TO_HOME": ["launcher.anim"],
                    "window_animation: LAUNCH_APP": ["launcher.anim"],
                    "menu_window_animation: MENU_BACK_TO_HOME": ["launcher.anim"],
                    "light_menu_window_animation: LIGHT_MENU_BACK_TO_HOME": ["launcher.anim"],
                    "light_window_animation: LIGHT_LAUNCH_APP": ["launcher.anim"]
                    }

# 时间戳	时间	vsyncId	进程名	expected_dur	actual_dur	丢帧数(actual_dur/expected_dur-1)	fps	丢帧数(actual_dur/fps-1)	vsync类型(vsync_sf,vsync_app)	vsync开始时间戳
# vsync开始结束时间戳	vsync持续时间	丢帧数（actual_dur/vsync持续时间-1)	丢帧数(过滤前)	丢帧数类型	丢帧数（过滤后）	是否丢帧	1s内总丢帧总数
tp = None
tp_resource = None
# 相对本脚本目录，避免 cwd 不是「解析」文件夹时找不到 shell
bin_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace_processor_shell.exe")
trace = None
sql_result_map = {}
scroll_track_name = ""
filter_scroll = ""
main_thread_map = {}
_use_google_tag = False
_all_scrolling_info = None
_traintion_playing_middleTime = 50000000
# 如果launching:xxxx 是包含以下关键字，则playing_start 在[launching_start-20ms,launching_end]认为有效
playing_start_tag = [".launcher"]
launching_ignore_tag = ["permissioncontroller"]

on_finish_message = "本帧有frameTimeLine,on_time_finish="





def before_analysis(trace):
    # 判断trace_processor_shell.exe 是否存在，不存在则下载
    global tp, tp_resource
    config = TraceProcessorConfig(bin_path, verbose=False)
    print(bin_path)
    print(trace)
    tp = TraceProcessor(trace=trace, config=config, addr=None)
    tp_resource = tp.__enter__()


def after_analysis():
    if tp is not None:
        tp.__exit__(None, None, None)


def write_excel_xlsx(path, sheet_name, value, ):
    """

    :param path:
    :param sheet_name:
    :param value:
    :return:
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
    sheet_name = sheet_name.replace("/", "_")
    sheet_name = sheet_name.replace(":", "_")
    fill_color = PatternFill(patternType='solid', fgColor='c00000')
    if not os.path.exists(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))
    if not os.path.exists(path):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = sheet_name
        workbook.save(path)

        # 新建
    index = len(value)
    workbook = openpyxl.load_workbook(path)
    if sheet_name not in workbook.sheetnames:
        workbook.create_sheet(sheet_name)
    sheet = workbook[sheet_name]

    for i in range(0, index):
        # 第一个sheet页
        if len(value[i]) < len(headers):
            for j in range(0, len(value[i])):
                sheet.cell(row=i + 1, column=j + 1, value=str(value[i][j]))
            continue
        # 其余sheet页
        drop_frame = value[i][drop_frames_index]
        drop_frames_sum_1s = value[i][drop_frames_sum_1s_index]
        is_drop = value[i][drop_frame_or_not_index]
        red_color = False
        try:
            if isinstance(is_drop, bool) and is_drop is True:
                if drop_frame > 1 or drop_frames_sum_1s > 4:
                    red_color = True
        except:
            print("统计异常，是否无指定动画关键字,是否不需要统计1s总丢帧数")

        for j in range(0, len(value[i])):
            if red_color:
                sheet.cell(row=i + 1, column=j + 1, value=str(value[i][j])).fill = fill_color
            else:
                sheet.cell(row=i + 1, column=j + 1, value=str(value[i][j]))

    # 固定每列列宽为 20
    for col in sheet.columns:
        sheet.column_dimensions[get_column_letter(col[0].column)].width = 20
    workbook.save(path)


def kill_trace_processor_shell():
    # 使用tasklist获取所有进程列表
    process = subprocess.run(['tasklist'], capture_output=True, text=True, encoding='utf-8', errors='ignore')
    process_list = process.stdout.splitlines()

    for line in process_list:
        # 检查进程名
        if 'trace_processor_shell.exe' in line:
            # 提取进程ID (PID)
            pid = int(line.split()[1])
            try:
                print(f'Killing process with PID {pid}')
                # 使用taskkill终止进程
                os.system(f'taskkill /F /PID {pid}')
            except Exception as e:
                print(f'Error: {e}')


def need_handle_longInterval_between_frame():
    """
    判断是否需要判断两帧之间的丢帧： 需要的情况如下
    1.使用大数据埋点
    2. 使用google 原生埋点，但是filter_scroll为0， 并且存在应用启动
    """
    if check_use_gooogle_scroll():
        if "0" == filter_scroll.strip():
            transition_playing_info = query_transition_playing_info()
            launching_info_list = query_launching_info()
            return  len(transition_playing_info)>0 and len(launching_info_list)>0
        return False
    return True

def check_use_gooogle_scroll():
    """
    判断是否要使用google 原生的滑动判断
    1. 宏指定使用google原生判断
    2. trace 内无任何动画埋点
    """
    global  _use_google_tag, _all_scrolling_info
    if _all_scrolling_info is None:
        _all_scrolling_info = exe_scrollingSql("surfaceflinger")

    if not _use_google_tag and len(_all_scrolling_info)<2:
        _use_google_tag = True

    return _use_google_tag


def calculate_Vsync_ts(vsync_sql):
    """
    用vsync-app试试吧，用两个相邻的ts相减的结果拟合成帧率，比如8.33ms对应是120hz。注意取的ts要和你关注的时间区间对应上
    @param trace:
    @param sql:
    @return:
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

    # 结构：[[header], [pre_vsync_startTs, current_vsync_startTs, 时间差, value], ...]
    # 其中 value 为上一条记录的 counter.value，用于判断 vsync 信号的状态（例如 0/1）
    refresh_rate_list = [["pre_vsync_startTs", "current_vsync_startTs", "时间差", "value"]]
    qr_it = tp_resource.query(vsync_sql)
    pre_ts = 0
    pre_value = None
    for index, row in enumerate(qr_it, start=1):
        if index == 1:
            pre_ts = row.ts
            pre_value = row.value
        else:
            current_ts = row.ts
            refresh_rate_list.append(
                [pre_ts, current_ts, round((current_ts - pre_ts), 1), pre_value]
            )
            pre_ts = current_ts
            pre_value = row.value

    # 最后一段区间：[pre_ts, +inf)
    refresh_rate_list.append([pre_ts, float("inf"), float("inf"), pre_value])

    return refresh_rate_list


def find_google_anim_scene(iq_info_list, use_in_launch = False):
    """
    通过google原生字段，圈定原生动画场景：（）
    """

    if filter_scroll == '0':
        click_animation_map = {}
        # 针对启动场景
        transition_playing_info = query_transition_playing_info()
        transition_info_list = query_transition_playing_info(Transition_open_syncReady_sql)

        # 2. 启动退出场景的playing 信息的scroll_type 单独标注
        # 针对前台应用对playing 进行过滤

        # 先根据launching 过滤 只保留和launching 有交集的playing
        launching_info_list =  query_launching_info()
        playing_info = filter_playing(launching_info_list, transition_playing_info, iq_info_list,
                                                      transition_info_list)
        scrolling_info =  filter_0_playing_anim(launching_info_list, transition_playing_info, transition_info_list)
        if use_in_launch:
            return playing_info

        click_animation_map['launcher'] = scrolling_info
        click_animation_map['gallery']  = [["scrolling_start", "scrolling_end", "scrolling_otherInfo"]] + query_animator_slice()
        click_animation_map['surfaceflinger'] = scrolling_info+click_animation_map['gallery'][1:]
        return click_animation_map
    else:
        return exe_rv_scroll_sql()




def filter_playing(launching_info_list, playing_info_list, iq_list, transition_open_cache):
    """
    1.先根据launching 过滤 只保留和launching 有交集的playing
    2.在根据iq 过滤，只保留在iq后的第一个playing
    3.根据transition 信息，只保留[playing-50ms， playing end] 和transition区间有交集的数据(只有这部分数据为冷热启动数据)
    4.有效的playing 区间即为动画区间，可进行流畅性丢帧判断
    """
    # 计算时延：先根据launching 过滤 只保留和launching 有交集的playing
    playing_info_list = filter_launching_playing_info(launching_info_list, playing_info_list)
    # 在根据iq 过滤，只保留在iq后的第一个playing
    playing_info_list = filter_playing_by_iq_list(playing_info_list, iq_list)
    # 根据transition 信息，只保留[playing-50ms， playing end] 和transition区间有交集的数据(只有这部分数据为冷热启动数据)
    playing_info_list = find_trasition_open(playing_info_list, transition_open_cache)
    # 针对丢帧单独做计算滑动时延
    playing_info_list.insert(0, ["scrolling_start", "scrolling_end", "scrolling_otherInfo", "launching_dur"])


    return playing_info_list

def filter_0_playing_anim(launching_info_list, playing_info_list, transition_open_cache):
    """
    方法用法: 筛选启动退出时的动画区间
    过滤方法：只保留如下过滤出来的playing
    1、找到launching起点前最近的一个 transition
    2、找到transition 后最近的一个playing
    """
    filtered_playing_list = []
    if not launching_info_list or not playing_info_list or not transition_open_cache:
        return filtered_playing_list

    # 跳过 playing 标题行（如果有）
    start_index = 0

    # 按开始时间排序
    sorted_launching = sorted(launching_info_list, key=lambda x: x[0] if x[0] is not None else 0)
    sorted_playing = sorted(
        playing_info_list[start_index:],
        key=lambda x: x[0] if x[0] is not None else float('inf')
    )


    for launching in sorted_launching:
        launch_start = launching[0]
        launching_message = launching[1]

        # 1. 找到 launching 起点前最近的一个 transition（transition 的 end <= launch_start，且 end 最大）
        nearest_transition_end = None
        for t in transition_open_cache:
            t_start = t[0]
            if t_start <= launch_start:
                if nearest_transition_end is None or t_start > nearest_transition_end:
                    nearest_transition_end = t[1]
        if nearest_transition_end is None:
            continue
        # 2. 找到该 transition 后最近的一个 playing（playing_start >= transition_end，且 start 最小）
        nearest_playing = None
        for p in sorted_playing:
            p_start = p[0]
            if p_start is None:
                continue
            if p_start >= nearest_transition_end:
                nearest_playing = p
                break
        if nearest_playing is not None and nearest_playing not in filtered_playing_list:
            nearest_playing_copy = nearest_playing.copy()
            nearest_playing_copy[-2] = f"{launching_message} playing"
            playing_end   = nearest_playing_copy[1]
            # 如果playing 长度超过launching 则取launching结束点为动画的结束点
            if playing_end > launching[3]:
                playing_end = launching[3]
                nearest_playing_copy[1] = playing_end
            filtered_playing_list.append(nearest_playing_copy[:-1])
    filtered_playing_list.insert(0, ["scrolling_start", "scrolling_end", "scrolling_otherInfo"])
    return filtered_playing_list




def filter_playing_by_iq_list(playing_info_list, iq_list):
    """
    根据 iq_list 过滤 playing_info_list

    过滤逻辑：
    1. iq 为 1 以及紧接着的 iq 为 0 的范围划分为一个区间
    2. 只保留这个区间的第一个有效 playing 信息
    3. 如果 iq 为 0 前面没有 iq 为 1，则 iq 为 0 单独作为一个区间

    @param playing_info_list: Transition playing 信息列表，每个元素为 [ts, dur, end] 或 [ts, dur, end, process_name]
    @param iq_list: iq 区间列表，每个元素为 [start_ts, end_ts, value]
    @return: 过滤后的 playing 信息列表，格式与输入相同
    """
    filtered_playing_list = []
    # 如果数据为空，直接返回
    if not playing_info_list or not iq_list:
        return filtered_playing_list

    # 按 ts 排序 playing 信息
    sorted_playing = sorted(playing_info_list, key=lambda x: x[0] if x[0] is not None else 0)

    # 按时间排序 iq_list

    sorted_iq_list = sorted(iq_list[1:], key=lambda x: x[0] if x[0] is not None and x[0] != float('inf') else 0)

    # 删除iq一开始为0的情况
    if sorted_iq_list[0][2] ==0:
        del sorted_iq_list[0]

    area_start = 0
    area_end = 0
    for iq_index in range(len(sorted_iq_list)):
        is_end = False
        iq_start = sorted_iq_list[iq_index][0]
        iq_end = sorted_iq_list[iq_index][1]
        iq_value = sorted_iq_list[iq_index][2]

        # 第一个iq 为开始，最后一个iq 为结束
        if iq_index == 0:
            if iq_value ==1:
                area_start = iq_start
            else:
                print("去首后还存在iq为0的情况")

        elif iq_index == len(sorted_iq_list)-1:
            area_end = iq_end
            is_end = True
        else:
            # 中间的iq 如何存在iq=1则可以计算区间
            if iq_value ==1:
                area_end = iq_start
                is_end = True

        if is_end:
            for playing_item in sorted_playing:
                playing_start = playing_item[0]
                if area_start<=playing_start <= area_end :
                    # filtered_playing_list.append(playing_item[:-1])
                    # filtered_playing_list[-1][-1] = ""
                    filtered_playing_list.append(playing_item)
                    # filtered_playing_list[-1][-1] = ""
                    break
            area_start = area_end



    return filtered_playing_list

def filter_launching_playing_info(launching_info_list, playing_info_list):
    """
    剔除无效的playing数据，只保留launching 和playing 有重合的第一个playing数据

    保留playing的依据：
    1. playing 和 launching 需要有时间上的重合（重叠）
    2. 对于每个 launching，只保留第一个有重合的 playing
    3. 保留之后需要同时记录所在launching 的进程名

    重合条件（两个时间段有交集）：
    - launching 开始时间 <= playing 结束时间
    - playing 开始时间 <= launching 结束时间

    @param launching_info_list: launching 信息列表，每个元素为 [ts, systrace_path, process_name, dur, end]
    @param playing_info_list: Transition playing 信息列表，每个元素为 [ts, dur, end]
    @return: 有效的 playing 信息列表，每个元素为 [ts, dur, end, process_name]
    """
    valid_playing_list = []

    # 如果数据为空，直接返回
    if not launching_info_list or not playing_info_list:
        return valid_playing_list

    # 按 ts 排序 launching 信息（确保按时间顺序处理）
    sorted_launching = sorted(launching_info_list, key=lambda x: x[0] if x[0] is not None else 0)

    # 按 ts 排序 playing 信息
    sorted_playing = sorted(playing_info_list, key=lambda x: x[0] if x[0] is not None else 0)

    # 遍历每个 launching 事件
    for launching in sorted_launching:
        launching_ts = launching[0]  # launching 开始时间
        launching_end = launching[-1]  # launching 结束时间
        launching_dur = launching_end - launching_ts
        process_name = launching[1]  # launching 进程名
        if launching_ts is None or launching_end is None:
            continue
        # 针对指定进程开始时间在launching范围内即可
        check_start = False
        for check_name in playing_start_tag:
            if check_name in process_name:
                check_start = True
                break

        # 找到与 launching 有重合的第一个 playing
        # 重合条件：两个时间段有交集
        # 时间段A [A_start, A_end] 和 时间段B [B_start, B_end] 有交集的条件是：
        # A_start <= B_end 且 B_start <= A_end
        # 对于 launching [launching_ts, launching_end] 和 playing [playing_ts, playing_end]：
        # launching_ts <= playing_end 且 playing_ts <= launching_end
        valid_playing = None

        for playing in sorted_playing:
            playing_ts = playing[0]  # playing 开始时间
            playing_end = playing[1]  # playing 结束时间

            if playing_ts is None or playing_end is None:
                continue
            if check_start:
                check_ts = playing_ts
            else:
                check_ts = playing_end
            # 检查 playing 和 launching 是否有重合（交集）
            # 已废弃：重合条件：launching 开始时间 <= playing 结束时间 且 playing 开始时间 <= launching 结束时间
            # 过滤条件：playing的结束时间在(launching_start-20ms,launching_end)之间
            if launching_ts - 20000000 <= check_ts <= launching_end:
                # 找到第一个有重合的 playing，保留它
                valid_playing = playing
                break

        # 如果找到有效的 playing，添加到结果列表，并记录对应的 launching 进程名
        if valid_playing:
            # 格式：[ts, dur, end, process_name]
            valid_playing_list.append([
                valid_playing[0],  # ts
                valid_playing[1],  # end
                f'{process_name} playing',  # process_name
                launching_dur
            ])

    print(
        f"从 {len(playing_info_list)} 条 playing 信息中过滤出 {len(valid_playing_list)} 条有效 playing 信息（与 launching 有重合）")
    return valid_playing_list


def query_launching_info():
    """
    查询 launching 的所有信息

    @param trace_path: perfetto trace 文件路径
    @return: launching 信息列表，每个元素为 [ts, systrace_path, process_name, dur, end]
             其中 end = ts + dur（如果 dur 不为 None）
             如果查询失败或没有数据，返回空列表
    """
    launching_info_list = []

    try:
        # SQL 查询 launching 信息
        launching_sql = "SELECT * FROM slice WHERE slice.name LIKE 'launching:%'"

        qr_it = tp_resource.query(launching_sql)

        for row in qr_it:
            try:
                # 获取 ts 和 dur
                ts = row.ts
                dur = row.dur if hasattr(row, 'dur') else None

                # 计算 end = ts + dur（如果 dur 不为 None）
                end = None
                if ts is not None and dur is not None:
                    end = ts + dur

                # 从 name 中提取进程名
                # 格式：launching: com.dragon.read -> com.dragon.read
                if hasattr(row, 'name'):
                    name = row.name.replace("launching:", "").strip()

                need_ignore = False
                for ignore_item in launching_ignore_tag:
                    if ignore_item in name:
                        need_ignore = True
                if need_ignore:
                    continue
                # 存储到列表中：[ts, systrace_path, process_name, dur, end]
                launching_info_list.append([ts, name, dur, end])

            except Exception as e:
                print(f"处理 launching 数据行时出错: {e}")
                continue

    except Exception as e:
        print(f"查询 launching 信息时出错: {e}")
        import traceback
        traceback.print_exc()

    return launching_info_list

def find_trasition_open(playing_info_list, transition_open_cache):
    """
    过滤 playing_info_list，只保留与 transition 有重合的数据

    过滤逻辑：
    1. 对于每个 playing_info，计算区间 [start - _traintion_playing_middleTime, end]
    2. 检查该区间是否与 _transition_open_cache 中任意 transition 的 [start, end] 有重合
    3. 有重合则保留，无重合则剔除

    @param trace_path: perfetto trace 文件路径
    @param playing_info_list: playing 信息列表，每个元素为 [ts, end, process_name, launching_dur]
    @return: 过滤后的 playing 信息列表
    """
    global _traintion_playing_middleTime

    # 如果没有 playing_info 数据，直接返回
    if not playing_info_list or len(playing_info_list) == 0:
        return []

    # 跳过标题行（如果有）
    filtered_list = []
    start_index = 0
    if len(playing_info_list) > 0 and isinstance(playing_info_list[0], list) and len(playing_info_list[0]) > 0:
        # 检查第一行是否是标题行（通常是字符串）
        if isinstance(playing_info_list[0][0], str):
            filtered_list.append(playing_info_list[0])  # 保留标题行
            start_index = 1

    # 遍历每个 playing_info 项
    for playing_item in playing_info_list[start_index:]:
        playing_start = playing_item[0]  # ts
        playing_end = playing_item[1]  # end

        # 计算检查区间：[playing_start - _traintion_playing_middleTime, playing_end]
        check_start = playing_start - _traintion_playing_middleTime
        check_end = playing_end

        # 检查是否与任意 transition 有重合
        has_overlap = False
        for transition_item in transition_open_cache:
            transition_start = transition_item[0]  # ts
            transition_end = transition_item[1]  # end

            if transition_start is None or transition_end is None:
                continue

            # 判断两个区间是否有交集
            if check_start <= transition_end and transition_start <= check_end:
                has_overlap = True
                break

        # 如果有重合，保留该 playing_info

        playing_item[2] = "Transition " + playing_item[2]

        if has_overlap:
            filtered_list.append(playing_item)

    print(
        f"从 {len(playing_info_list) - start_index} 条 playing 信息中过滤出 {len(filtered_list) - (1 if start_index > 0 else 0)} 条有效 playing 信息（与 transition 有重合）")
    return filtered_list




def query_transition_playing_info(sql=transition_playing_sql):
    """
    查询 Transition 下的所有 playing 信息, 用于原生动画场景圈定

    @param trace_path: perfetto trace 文件路径
    @return: Transition playing 信息列表，每个元素为 [ts, dur, end]
             其中 end = ts + dur（如果 dur 不为 None）
             如果查询失败或没有数据，返回空列表
    """
    transition_playing_info_list = []

    try:
        # SQL 查询 Transition playing 信息

        # 使用 analysis_module 的 tp_resource 执行查询

        qr_it = tp_resource.query(sql)

        for row in qr_it:
            try:
                # 获取 ts 和 dur
                ts = row.ts if hasattr(row, 'ts') else None
                dur = row.dur if hasattr(row, 'dur') else None
                name = row.name
                # 计算 end = ts + dur（如果 dur 不为 None）
                end = None
                if ts is not None and dur is not None:
                    end = ts + dur

                # 存储到列表中：[ts, dur, end]
                transition_playing_info_list.append([ts, end, name, dur])

            except Exception as e:
                print(f"处理 Transition playing 数据行时出错: {e}")
                continue


    except Exception as e:
        print(f"查询 Transition playing 信息时出错: {e}")
        import traceback
        traceback.print_exc()

    return transition_playing_info_list


def exe_iq_sql():
    """
    计算iq信息，iq信号0持续时间超过100ms，则认为是非iq时间
    @param trace:
    @param sql:
    @return:
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
    iq_list = [["start_ts", "end_ts", "value"]]
    qr_it = tp_resource.query(iq_sql)
    pre_ts = 0
    cur_iq_value = -1
    for index, row in enumerate(qr_it, start=1):
        if index == 1:
            pre_ts = row.ts
            pre_iq_value = row.value
        else:
            cur_ts = row.ts
            cur_iq_value = row.value
            if cur_iq_value != pre_iq_value:
                iq_list.append([pre_ts, cur_ts, pre_iq_value])
                pre_ts = cur_ts
                pre_iq_value = cur_iq_value

    iq_list.append([pre_ts, float("inf"), cur_iq_value])

    return iq_list


def calculate_fps_sql():
    """
    计算各类 fps / 时间区间信息，并返回字典：
    - 普通轨道：key 为 fps_type，例如 "VSP-setPeriod" / "ActiveMode" / "VsyncWorkDuration-appSF" / "NextFrameInterval"
    - FRTC：key 为 "frtc_<pthread_name>"，value 为 [[start_ts, end_ts, frtc_value], ...]
    """

    def exe_fpsSql(sql, fps_type):
        """
        执行sql 输出结果每行数据包含 ts， value。 fps 按相邻两点的时间差转换为周期（ns）
        @return:
        """
        fps_list = [["pre_fps_startTs", "current_fps_startTs", "fps_value", "fps_otherInfo"]]
        qr_it = tp_resource.query(sql)
        pre_ts = None
        fps_value = None
        for index, row in enumerate(qr_it, start=1):
            if index == 1:
                pre_ts = row.ts
                fps_value = int(row.value)
                if fps_value > 0 and fps_value < 200:
                    # 将 Hz 转换成周期 ns
                    fps_value = int(1000000000 / fps_value)
            else:
                current_ts = row.ts
                if fps_value is None or fps_value <= 0:
                    pre_ts = current_ts
                    continue
                fps_list.append([pre_ts, current_ts, fps_value, fps_type])
                pre_ts = current_ts
                fps_value = int(row.value)
                if fps_value > 0 and fps_value < 200:
                    fps_value = int(1000000000 / fps_value)
        if pre_ts is not None and fps_value:
            fps_list.append([pre_ts, float("inf"), fps_value, fps_type])
        return fps_list

    def calculate_NextFrameInterval_sql():
        fps_list = [["pre_fps_startTs", "current_fps_startTs", "fps_value", "fps_otherInfo"]]
        qr_it = tp_resource.query(NextFrameInterval_sql)
        for index, row in enumerate(qr_it, start=1):
            ts = row.ts
            dur = row.dur
            print(row.name)
            fps_value = int(row.name.split(",")[0].replace("NextFrameInterval ", "").replace("_Hz", "").strip())
            if fps_value > 0:
                fps_list.append([ts, ts + dur, int(1000000000 / fps_value), "NextFrameInterval"])
        return fps_list

    def calculate_VSP_setPeriod_sql():
        return exe_fpsSql(VSP_setPeriod_sql, "VSP-setPeriod")

    def calculate_VsyncWorkDuration_appSF_sql():
        return exe_fpsSql(VsyncWorkDuration_appSF_sql, "VsyncWorkDuration-appSF")

    def calculate_ActiveMode_fps_sql():
        return exe_fpsSql(activeMode_fps_sql, "ActiveMode")

    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

    # 使用有序字典统一管理各类 fps / 时间信息（保持插入顺序）
    # 普通 fps：key 为 fps_type
    fps_map = collections.OrderedDict()
    # 将各个进程的 FRTC 区间也收集进来，key 为 frtc_<pthread_name>
    try:
        for pthread_name in sql_result_map.keys():
            frtc_key = f"frtc_{pthread_name}"
            try:
                fps_map[frtc_key] = exe_frtc_framerate_sql(pthread_name)
            except Exception as e:
                print(f"exe_frtc_framerate_sql error for {pthread_name}: {e}")
    except Exception as e:
        print(f"collect FRTC in calculate_fps_sql error: {e}")

    fps_map["VSP-setPeriod"] = calculate_VSP_setPeriod_sql()
    fps_map["ActiveMode"] = calculate_ActiveMode_fps_sql()
    fps_map["VsyncWorkDuration-appSF"] = calculate_VsyncWorkDuration_appSF_sql()
    fps_map["NextFrameInterval"] = calculate_NextFrameInterval_sql()

    return fps_map


def frame_is_useful(row_data):
    """
    app 只有主进程 只有doframe 没有drawframe 则认为本帧无用， 两帧间隔时间长假设插入的帧认为本帧无用
    """
    pthread_name = row_data[pthread_name_index]
    if "surfaceflinger" in pthread_name:
        return True

    if "不统计该帧" in row_data[vsync_check_info_index]:
        return False

    if "前后两帧时间差超过fps时间" in row_data[vsync_check_info_index]:
        return False

    return True


def is_first_or_end_frame(sheet_data, row_index_start, pthread, scrolling_list_item):
    """
    判断是首帧 / 尾帧 (surfaceflinger ， launcher.anim 不过滤首尾帧， scroll动画只过滤首帧， )
    """
    cur_thread_name = sheet_data[row_index_start][thread_name_index]
    # surfaceflinger or 不在滑动区间 or 动画线程， 不需要过滤首尾帧，
    if "surfaceflinger" in pthread or len(scrolling_list_item) == 0 or cur_thread_name in thread_without_drawFrame:
        return False

    # 当前帧无效，不统计首尾帧
    if not frame_is_useful(sheet_data[row_index_start]):
        return False

    pre_index = None
    next_index = None
    # 找到 相同线程的前一帧
    for i in range(row_index_start - 1, 0, -1):
        pre_thread_thread = sheet_data[i][thread_name_index]
        pre_thread_check = sheet_data[i][vsync_check_info_index]
        if pre_thread_thread == cur_thread_name and frame_is_useful(sheet_data[i]):
            pre_index = i
            break
    # 找到 相同线程的后一帧
    for i in range(row_index_start + 1, len(sheet_data), 1):
        next_thread_thread = sheet_data[i][thread_name_index]
        next_thread_check = sheet_data[i][vsync_check_info_index]
        if next_thread_thread == cur_thread_name and frame_is_useful(sheet_data[i]):
            next_index = i
            break

    # 没有上一帧，没有下一帧的情况，直接过滤首尾帧
    if pre_index is None or next_index is None:
        return True  # 过滤
    pre_frame_start = sheet_data[pre_index][actual_ts_index]
    next_frame_end = sheet_data[next_index][actual_ts_index] + sheet_data[next_index][do_draw_dur_index]
    cur_frame_start = sheet_data[row_index_start][actual_ts_index]
    cur_frame_end = sheet_data[row_index_start][actual_ts_index] + sheet_data[row_index_start][do_draw_dur_index]
    scroll_start = scrolling_list_item[0]
    scroll_end = scrolling_list_item[1]
    scroll_type = scrolling_list_item[-1]
    # 前一帧起点不在动画区间内，当前帧在动画区间内，则为首帧
    if pre_frame_start < scroll_start and cur_frame_start >= scroll_start:
        return True
    # 当前帧终点在动画区间内，后一帧的终点不在动画区间内, 则为尾帧
    if cur_frame_end <= scroll_end and next_frame_end > scroll_end:
        if "scroll" == scroll_type.lower():
            return False
        else:
            return True

    return False


def exe_frtc_framerate_sql(pthread_name):
    """
    执行 FRTC-framerate 相关 sql，指定进程名，输出 [start_ts, end_ts, value] 区间形式
    @return: [["start_ts", "end_ts", "value"], ...]
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
    frtc_list = [["start_ts", "end_ts", "value", "fps_type"]]
    frtc_framerate_sql = f"""
    SELECT counter.ts AS ts, counter.value AS value
    FROM counter
    JOIN process_counter_track ON process_counter_track.id = counter.track_id
    JOIN process ON process.upid = process_counter_track.upid
    WHERE process_counter_track.name = 'FRTC-framerate'
      AND process.name = '{pthread_name}'
    ORDER BY counter.ts
    """
    qr_it = tp_resource.query(frtc_framerate_sql)

    pre_ts = None
    pre_value = None
    for index, row in enumerate(qr_it, start=1):
        ts = row.ts
        value = row.value
        if pre_ts is None:
            # 第一条记录，初始化
            pre_ts = ts
            pre_value = value
        else:
            # 遇到 value 变化时，结算上一段区间 [pre_ts, ts)
            if value != pre_value:
                if pre_value != 0:
                    frtc_list.append([pre_ts, ts, int(1000000000 / pre_value), "frtc"])
                pre_ts = ts
                pre_value = value

    # 最后一段，以 +∞ 作为结束时间戳
    if pre_ts is not None and pre_value != 0:
        frtc_list.append([pre_ts, float("inf"), int(1000000000 / pre_value), "frtc"])

    return frtc_list


def find_scrolling(start_ts, dur, scrolling_list, thread_name):
    for index in range(len(scrolling_list)):
        if index == 0:
            continue
        scrolling_type = scrolling_list[index][-1]
        if "RV Scroll" in scrolling_type:
            if start_ts <= scrolling_list[index][0]<= start_ts + dur:
                return True, scrolling_list[index][-1], scrolling_list[index]
        else:
            if start_ts >= scrolling_list[index][0] and start_ts + dur <= scrolling_list[index][1]:
                scroll_type =  scrolling_list[index][-1]
                if scroll_type in  thread_with_anim.keys() and thread_name not in thread_with_anim[scroll_type]:
                    continue
                return True, scrolling_list[index][-1], scrolling_list[index]


    return False, "", []


def find_fps_data(frame_start_ts, frame_dur, all_fps_map, phtread_name=None):
    """
    @param frame_timeLine_ts:
    @param fps_list:
    @return:  return_data = 0,0,0 返回ts之前最近的一个fps时间周期的开始时间，结束时间，fps
    """
    fps_iter = all_fps_map.items()

    for key, fps_list in fps_iter:
        # 跳过 FRTC 相关信息，这里只用于找“刷新率”
        # 不传入pthread ，则按照常规规则查询frtc
        if phtread_name is None and key.startswith("frtc_"):
            continue
        # 传入pthread 则优先查询frtc
        if isinstance(key, str) and key.startswith("frtc_") and phtread_name not in key:
            continue
        if not isinstance(fps_list, list):
            continue
        for i in range(1, len(fps_list)):
            start_ts = fps_list[i][0]
            end_ts = fps_list[i][1]
            fps = fps_list[i][2]
            fps_otherInfo = fps_list[i][3]
            if start_ts <= frame_start_ts and end_ts >= frame_start_ts:
                # 根据slice的起点去匹配刷新率
                return fps, fps_otherInfo

            if fps_otherInfo == "NextFrameInterval" and frame_start_ts < start_ts and frame_start_ts + frame_dur + 1000000000 / 120 > start_ts:
                # 兼容 NextFrameInterval  刷新率出现在slice 时间范围的情况
                return fps, fps_otherInfo

    return None, ""


def find_vsync_data(frame_timeLine_ts, vsync_list):
    """
    看ts 落在哪个Vsync周期内
    @param ts:
    @return: return_data = 0,0,0 返回ts之前最近的一个vsnc时间周期的开始时间，结束时间，时间间隔
    """
    return_data = 0, 0, 0
    for i in range(1, len(vsync_list)):
        vsync_ts_item = vsync_list[i]
        start_ts, end_ts, dur_ts = vsync_ts_item[0], vsync_ts_item[1], vsync_ts_item[2]
        if start_ts <= frame_timeLine_ts and end_ts >= frame_timeLine_ts:
            return_data = vsync_ts_item[0], vsync_ts_item[1], vsync_ts_item[2]
            return return_data

    return return_data


def get_app_duration(start_ts, vsync_app_list, vsync_sf_list, frame_interval_ns):
    """
    传入 vsync-app 列表、vsync-sf 列表和当前帧起点 start_ts，计算 app_duration（ns）。
    步骤：
    1. 在 vsync_app_list 中找到 start_ts 之前最近一次 value==1 的 vsync-app 上升沿 prev_app_start
    2. 在 vsync_sf_list 中找到 start_ts 之后最近一次 value==1 的 vsync-sf 上升沿 next_sf_start
    3. 计算 app_duration_ns = ((vsync_sf - vsync_app) % frameInterval + frameInterval)（正模），保持与原逻辑一致
    """
    if not isinstance(frame_interval_ns, (int, float)) or frame_interval_ns <= 0:
        return None

    frame_start_ts = start_ts

    # 1) 找到该帧之前最近一次 vsync-app 上升沿（value == 1）
    prev_app_start = 0
    if vsync_app_list and len(vsync_app_list) > 1:
        for seg in vsync_app_list[1:]:
            seg_start = seg[0]
            seg_value = seg[3] if len(seg) > 3 else None
            if not isinstance(seg_value, (int, float)) or seg_value != 1:
                continue
            if seg_start <= frame_start_ts:
                prev_app_start = seg_start
            else:
                break

    # 2) 找到该帧之后最近一次 vsync-sf 上升沿（value == 1）
    next_sf_start = 0
    if vsync_sf_list and len(vsync_sf_list) > 1:
        for seg in vsync_sf_list[1:]:
            seg_start = seg[0]
            seg_value = seg[3] if len(seg) > 3 else None
            if not isinstance(seg_value, (int, float)) or seg_value != 1:
                continue
            if seg_start >= frame_start_ts:
                next_sf_start = seg_start
                break

    if prev_app_start == 0 or next_sf_start == 0:
        return None

    # 3) 按原公式计算 app_duration_ns（正模）
    delta_ns = next_sf_start - prev_app_start
    app_duration_mod_ns = ((delta_ns % frame_interval_ns) + frame_interval_ns) % frame_interval_ns + frame_interval_ns
    if app_duration_mod_ns == 0:
        app_duration_mod_ns = frame_interval_ns

    return app_duration_mod_ns


def merge_All_info(frameTimeLine_Map={}, fps_map=[], vsync_sf_list=[], vsync_app_list=[]):
    """
    merge  fps Vsync 等信息
    @return:
    """

    # merge fps 信息
    def merge_doFrame_drawFrame():
        """
        合并merge_doFrame_drawFrame信息
        :return:
        """
        for pthread, frameTimeLine_pthread in frameTimeLine_Map.items():
            if "surfaceflinger" not in pthread:
                doFrame_orderDcit = exe_do_frame(pthread)
                drawFrame_orderDcit = exe_draw_frame(pthread)
                do_drawFrame_sum_dict = do_drawFrame_time_sum(doFrame_orderDcit, drawFrame_orderDcit, pthread)
                merge_do_drawFrameInfo(pthread, frameTimeLine_pthread, do_drawFrame_sum_dict)
            else:
                surfaceflinger_Format_adaption(frameTimeLine_pthread)

    def merge_fps():
        for pthread, frameTimeLine_pthread in frameTimeLine_Map.items():
            for i in range(len(frameTimeLine_pthread)):
                if i == 0:
                    # 增加fps相关的标题

                    frameTimeLine_pthread[i][fps_keyInfo_index], frameTimeLine_pthread[i][fps_index], \
                    frameTimeLine_pthread[i][drop_frames_byFps_index] = headers[fps_keyInfo_index], headers[fps_index], \
                    headers[drop_frames_byFps_index]
                    if "surfaceflinger" in pthread:
                        frameTimeLine_pthread[i][drop_frames_byFps_index] = "丢帧数(两次composite时间差/fps-1)"
                        frameTimeLine_pthread[i][drop_frames_byExpected_index] = "丢帧数(actul_dur-expected_dur/fps-1)"
                else:
                    do_draw_ts = frameTimeLine_pthread[i][actual_ts_index]
                    do_draw_dur = frameTimeLine_pthread[i][do_draw_dur_index]
                    actual_dur = frameTimeLine_pthread[i][actual_dur_index]
                    
                    # 对于 surfaceflinger，如果 do_draw_dur_index 是 None（无对应 composite），不计算 drop_frame_fps
                    if "surfaceflinger" in pthread:
                        if do_draw_dur is None or (isinstance(do_draw_dur, str) and ("None" in do_draw_dur or len(do_draw_dur) == 0)):
                            # 无对应 composite 的 FrameTimeLine，不计算 drop_frame_fps
                            fps = -1
                            drop_frame_fps = -1
                            fps_otherInfo = ""
                        else:
                            # 使用两次composite时间差（do_draw_dur_index）来计算
                            do_draw_dur = do_draw_dur if do_draw_dur else actual_dur
                            fps, fps_otherInfo = find_fps_data(do_draw_ts, do_draw_dur, fps_map, pthread)
                            if fps:
                                frame_dur = frameTimeLine_pthread[i][do_draw_dur_index]
                                drop_frame_fps = frame_dur / int(fps) - 1
                                drop_frame_fps = 0 if drop_frame_fps < 0 else drop_frame_fps
                            else:
                                fps = -1
                                drop_frame_fps = -1
                    else:
                        # 其他进程使用原有逻辑
                        do_draw_dur = actual_dur if len(str(do_draw_dur)) == 0 or "None" in str(
                            do_draw_dur) else do_draw_dur
                        # 有 FRTC 数据，则优先在 FRTC 中找刷新率；否则按原逻辑从 fps_list 中找
                        fps, fps_otherInfo = find_fps_data(do_draw_ts, do_draw_dur, fps_map, pthread)

                        if fps:
                            frame_dur = frameTimeLine_pthread[i][do_draw_dur_index]
                            drop_frame_fps = frame_dur / int(fps) - 1
                            drop_frame_fps = 0 if drop_frame_fps < 0 else drop_frame_fps

                        else:
                            fps = -1
                            drop_frame_fps = -1
                    frameTimeLine_pthread[i][fps_keyInfo_index], frameTimeLine_pthread[i][fps_index], \
                    frameTimeLine_pthread[i][drop_frames_byFps_index] = fps_otherInfo, fps, drop_frame_fps
                    # 根据frtc降帧区间校准刷新率
                    _adjust_bufferTx_by_frtc(pthread, frameTimeLine_pthread, i, do_draw_ts, do_draw_dur, actual_dur,
                                             vsync_app_list, vsync_sf_list, fps_map)

    # merge Vsync 信息
    def merge_vsync():
        for pthread, frameTimeLine_pthread in frameTimeLine_Map.items():
            for i in range(len(frameTimeLine_pthread)):
                if "surfaceflinger" in pthread:
                    vsync_type = "vsync_sf"
                    vsync_list = vsync_sf_list
                else:
                    vsync_type = "vsync_app"
                    vsync_list = vsync_app_list
                if i == 0:
                    # 增加Vsync相关的标题
                    frameTimeLine_pthread[i][vsync_type_index], frameTimeLine_pthread[i][vsync_start_time_index], \
                    frameTimeLine_pthread[i][vsync_end_time_index], frameTimeLine_pthread[i][vsync_dur_index], \
                    frameTimeLine_pthread[i][drop_frames_byVsync_index] = \
                        headers[vsync_type_index], headers[vsync_start_time_index], \
                            headers[vsync_end_time_index], headers[vsync_dur_index], \
                            headers[drop_frames_byVsync_index]

                    if "surfaceflinger" in pthread:
                        frameTimeLine_pthread[i][drop_frames_byVsync_index] = "丢帧数(两次composite时间差/vsync_dur-1)"
                    continue
                else:
                    # 增加Vsync相关数据
                    actual_ts = frameTimeLine_pthread[i][actual_ts_index]
                    vsync_start, vsync_end, vsync_dur = find_vsync_data(actual_ts, vsync_list)
                if vsync_dur == 0:
                    drop_frame_vsync = 0
                else:
                    vsync_Id = frameTimeLine_pthread[i][actual_vsyncId_index]
                    frame_dur = frameTimeLine_pthread[i][do_draw_dur_index]
                    if frame_dur is not None:
                        drop_frame_vsync = frame_dur / vsync_dur - 1
                    else:
                        drop_frame_vsync = 0

                    if drop_frame_vsync < 0:
                        drop_frame_vsync = 0
                frameTimeLine_pthread[i][vsync_type_index], frameTimeLine_pthread[i][vsync_start_time_index], \
                    frameTimeLine_pthread[i][vsync_end_time_index], frameTimeLine_pthread[i][vsync_dur_index], \
                    frameTimeLine_pthread[i][
                        drop_frames_byVsync_index] = vsync_type, vsync_start, vsync_end, vsync_dur, drop_frame_vsync

    def calculate_drop_frames_data():
        for pthread, frameTimeLine_pthread in frameTimeLine_Map.items():
            for i in range(len(frameTimeLine_pthread)):
                if i == 0:
                    # 添加丢帧数相关标题
                    frameTimeLine_pthread[i][drop_frames_before_filter_index], frameTimeLine_pthread[i][
                        drop_frames_type_before_filter_index] = headers[drop_frames_before_filter_index], headers[
                        drop_frames_type_before_filter_index]
                else:

                    # 添加丢帧数相关数据
                    fps = frameTimeLine_pthread[i][fps_index]
                    fps_dropFrames = frameTimeLine_pthread[i][drop_frames_byFps_index]
                    dropframes_by_expected = frameTimeLine_pthread[i][drop_frames_byExpected_index]
                    vsync_check_info = frameTimeLine_pthread[i][vsync_check_info_index]
                    if fps >= 0:
                        # 存在刷新率相关数据
                        print(fps_dropFrames, dropframes_by_expected)
                        if "surfaceflinger" in pthread:
                            if "本帧有frameTimeLine" in vsync_check_info:
                                if  surfaceflinger_drop_checck(vsync_check_info):
                                    dropframes_by_fps_expected = dropframes_by_expected
                                    drop_frames_type_before_filter_info = "actual_dur/expected_dur-1"
                                else:
                                    dropframes_by_fps_expected = 0
                                    drop_frames_type_before_filter_info = "on_time_finish&jankType"
                            else:
                            # fps_dropFrames 已经是 两次composite时间差/fps-1（在 merge_fps 中计算）
                            # dropframes_by_expected 是 actual_dur/expected_dur-1（在 merge_surfaceflinger_composite 中计算）
                                if fps_dropFrames >= 0 and dropframes_by_expected is not None:
                                    if fps_dropFrames < dropframes_by_expected:
                                        dropframes_by_fps_expected = fps_dropFrames
                                        drop_frames_type_before_filter_info = "两次composite时间差/fps-1"
                                    else:
                                        dropframes_by_fps_expected = dropframes_by_expected
                                        drop_frames_type_before_filter_info = "actual_dur/expected_dur-1"
                                elif fps_dropFrames >= 0:
                                    # 只有 fps_dropFrames 有效
                                    dropframes_by_fps_expected = fps_dropFrames
                                    drop_frames_type_before_filter_info = "两次composite时间差/fps-1"
                                elif dropframes_by_expected is not None:
                                    # 只有 dropframes_by_expected 有效
                                    dropframes_by_fps_expected = dropframes_by_expected
                                    drop_frames_type_before_filter_info = "actual_dur/expected_dur-1"
                                else:
                                    # 两者都无效
                                    dropframes_by_fps_expected = -1
                                    drop_frames_type_before_filter_info = "无有效数据"

                        else:
                            # 其余进程取（(doframe drawframe)时间 / fps -1）
                            dropframes_by_fps_expected = fps_dropFrames

                            drop_frames_type_before_filter_info = "出帧时长/fps时间-1"
                        frameTimeLine_pthread[i][drop_frames_before_filter_index], frameTimeLine_pthread[i][
                            drop_frames_type_before_filter_index] = \
                            dropframes_by_fps_expected if dropframes_by_fps_expected > 0 else 0, drop_frames_type_before_filter_info


                    else:
                        if str(frameTimeLine_pthread[i][actual_vsyncId_index]) == "47542224":
                            print("demo")
                        print(frameTimeLine_pthread[i])
                        if "surfaceflinger" in pthread:
                            # 对于 surfaceflinger，如果没有 fps，使用 min(actual_dur/expected_dur-1, vsync持续时间-1)
                            dropframes_by_expected = frameTimeLine_pthread[i][drop_frames_byExpected_index]
                            dropframes_by_vsync = frameTimeLine_pthread[i][drop_frames_byVsync_index]
                            # surfaceflinger  有frameTimeLine on_time_finish=0 丢帧数为actual_dur/expected_dur-1
                            if "本帧有frameTimeLine" in vsync_check_info:
                                if  surfaceflinger_drop_checck(vsync_check_info):
                                    dropframes_by_vync_expected = dropframes_by_expected
                                    drop_frames_type_before_filter_info = "actual_dur/expected_dur-1"
                                else:
                                    dropframes_by_vync_expected = 0
                                    drop_frames_type_before_filter_info = "on_time_finish&jankType"
                            else:
                                # surfaceflinger  on_time_finish=0 则丢帧数为actual_dur/expected_dur-1
                                valid_values = []
                                if dropframes_by_expected is not None:
                                    valid_values.append(("actual_dur/expected_dur-1", dropframes_by_expected))
                                if dropframes_by_vsync is not None and dropframes_by_vsync >= 0:
                                    valid_values.append(("actual_ts/vsync持续时间-1", dropframes_by_vsync))

                                if valid_values:
                                    # 取最小值
                                    valid_values.sort(key=lambda x: x[1])
                                    dropframes_by_vync_expected = valid_values[0][1]
                                    drop_frames_type_before_filter_info = valid_values[0][0]
                                else:
                                    dropframes_by_vync_expected = -1
                                    drop_frames_type_before_filter_info = "无有效数据"


                        else:
                            dropframes_by_vync_expected = frameTimeLine_pthread[i][drop_frames_byVsync_index]
                            drop_frames_type_before_filter_info = "出帧时长/vsync时间-1"


                        frameTimeLine_pthread[i][drop_frames_before_filter_index], frameTimeLine_pthread[i][
                            drop_frames_type_before_filter_index] = dropframes_by_vync_expected if dropframes_by_vync_expected > 0 else 0, drop_frames_type_before_filter_info


    def surfaceflinger_frameTimeLine_drop():
        """
        1遍历surfacflinger的所有数据，计算(actual_dur - expected_dur) / fps
        2. 如果没有对应的fps， 则取(actual_dur - expected_dur) / vsync
        3. 如果同时没有fps， vsync ，则取actual_dur / expected_dur -1
        """
        for pthread, frameTimeLine_pthread in frameTimeLine_Map.items():
            for i in range(len(frameTimeLine_pthread)):
                if str(frameTimeLine_pthread[i][actual_vsyncId_index]) == "47542224":
                    print("demo")
                if "surfaceflinger" in pthread:
                    if i ==0 :
                        continue
                    actual_dur = frameTimeLine_pthread[i][actual_dur_index]
                    expected_dur = frameTimeLine_pthread[i][expected_dur_index]
                    fps = frameTimeLine_pthread[i][fps_index]
                    vsync_dur = frameTimeLine_pthread[i][vsync_dur_index]
                    if expected_dur is not None and actual_dur is not None:
                        if isinstance(fps, int)  and fps>0:
                            frameTimeLine_pthread[i][drop_frames_byExpected_index] = (actual_dur - expected_dur) / fps
                        elif isinstance(vsync_dur, int) and vsync_dur>0:
                            frameTimeLine_pthread[i][drop_frames_byExpected_index] = (actual_dur - expected_dur) / vsync_dur
                        else:
                            frameTimeLine_pthread[i][drop_frames_byExpected_index] = (actual_dur - expected_dur) / expected_dur


    merge_doFrame_drawFrame()
    merge_fps()
    merge_vsync()
    # surfaceflinger 单独处理frameTimeLine丢帧
    surfaceflinger_frameTimeLine_drop()
    if need_handle_longInterval_between_frame():
        handle_longInterval_between_frame(frameTimeLine_Map)
    calculate_drop_frames_data()



def find_doframe_middle_info(pthread_name):
    """
    执行sql，获取主进程的所有信息
    """
    main_thread_allInfo_sql = f"""
      SELECT slice.ts,slice.dur, slice.name, process.name as process_name, thread.name as thread_name
        FROM slice
    	JOIN thread_track ON slice.track_id = thread_track.id
    	JOIN thread USING (utid)
    	JOIN process USING (upid)
        WHERE  process.name='{pthread_name}'   and thread.is_main_thread =1 order by ts
    """
    qr_it = tp_resource.query(main_thread_allInfo_sql)
    # [slice_start, slice_dur,slice_name, thread_name ]
    middle_info_list = []
    doframe_indices = []
    for index, row in enumerate(qr_it, start=1):
        middle_info_list.append([row.ts, row.dur, row.name, row.thread_name])
        # 找到所有Choreographer  # doFrame的坐标
        if 'Choreographer#doFrame' in row.name:
            doframe_indices.append(index - 1)
    # 针对middle_info_list保留所有名字不包含Choreographer#doFrame，并且在两个Choreographer#doFrame之间的所有row（不与Choreographer#doFrame重合）
    filtered_info_list = []
    # 只有一个doframe 或者没有doframe 则不统计
    if len(doframe_indices) < 2:
        return filtered_info_list

    # 遍历每对相邻的Choreographer#doFrame之间的区间
    for i in range(len(doframe_indices) - 1):
        start_idx = doframe_indices[i]
        end_idx = doframe_indices[i + 1]
        doframe_pre_limit = middle_info_list[start_idx][0] + middle_info_list[start_idx][1]
        doframe_end_limit = middle_info_list[end_idx][0]

        # 获取两个doFrame之间的所有记录（不包括doFrame本身）
        for j in range(start_idx + 1, end_idx):
            slice_start = middle_info_list[j][0]
            slice_end = middle_info_list[j][0] + middle_info_list[j][1]
            slice_name = middle_info_list[j][2]
            # 只保留名字不包含Choreographer#doFrame的记录
            if 'Choreographer#doFrame' not in slice_name and slice_start >= doframe_pre_limit and slice_end < doframe_end_limit:
                filtered_info_list.append(middle_info_list[j])
                break

    return filtered_info_list


def exe_rt(pthread_name):
    """
    获取rt插帧是否有效的数据
    """
    rt_sql_1 = f"""
    SELECT slice.ts,slice.dur, slice.name,process.name as process_name, thread.name as thread_name
    FROM slice
    JOIN thread_track ON slice.track_id = thread_track.id
    JOIN thread USING (utid)
    JOIN process USING (upid)
    WHERE slice.name LIKE 'delta in frame is%' and process.name='{pthread_name}' and thread.name like 'RenderThread' order by ts
"""

    rt_sql_2 = f"""
            SELECT slice.ts,slice.dur, slice.name,process.name as process_name, thread.name as thread_name
            FROM slice
            JOIN thread_track ON slice.track_id = thread_track.id
            JOIN thread USING (utid)
            JOIN process USING (upid)
            WHERE slice.name LIKE 'dispatchFrameCallbacks' and process.name='{pthread_name}' and thread.name like 'RenderThread' order by ts
    """
    qr_it = tp_resource.query(rt_sql_1)
    # [rt_start, rt_end,rt_value ]
    rt_list = []
    for index, row in enumerate(qr_it, start=1):
        name = row.name
        value = name.split(" ")[-1]
        useful = False if str(value).strip() == '0' else True
        start_ts = row.ts
        dur = row.dur
        rt_list.append([start_ts, start_ts + dur, useful, value, name])

    # 如果第一次查询结果为空，使用dispatchFrameCallbacks重新查询
    if len(rt_list) == 0:
        qr_it = tp_resource.query(rt_sql_2)
        for index, row in enumerate(qr_it, start=1):
            name = row.name
            value = "1"
            useful = True
            start_ts = row.ts
            dur = row.dur
            rt_list.append([start_ts, start_ts + dur, useful, value, name])
    return rt_list


def filter(frameTimeLine_Map={}, iq_List=[], vsync_sf_list=[], vsync_app_list_raw=None, vsync_sf_list_raw=None,
           fps_map=[]):
    """
    1.过滤丢帧数差值小于1的数据
    2.过滤iq及iq 前后两帧的数据
    @return:
    """

    def add_rt_info():
        # 添加标题

        for pthread in frameTimeLine_Map:
            sheet_data = frameTimeLine_Map[pthread]
            rt_list = exe_rt(pthread)
            for line_index in range(len(sheet_data)):
                if line_index == 0:
                    sheet_data[0][noUseful_rt_count_index] = headers[noUseful_rt_count_index]
                else:

                    start = sheet_data[line_index][actual_ts_index]

                    if len(str(sheet_data[line_index][do_draw_dur_index])) == 0 or "None" in str(
                            sheet_data[line_index][do_draw_dur_index]):
                        dur = sheet_data[line_index][actual_dur_index]
                    else:
                        dur = sheet_data[line_index][do_draw_dur_index]

                    sheet_data[line_index][noUseful_rt_count_index] = rt_not_useful(start, start + dur, rt_list)

    def filter_buffer():
        """
        1.圈定堆buffer的区间（判断区间的起点：每一行都可能是起点, 终点：随后第一次出现abs(cur_丢帧数 - pre_丢帧数)>=1 或者是第一行）
        2. 记录开始堆buffer的数据（Vsync_id）
        3. 记录区间内的连续丢帧数
        """

        # 是否在堆buffer区间内
        for pthread in frameTimeLine_Map:
            sheet_data = frameTimeLine_Map[pthread]
            start_heap_buffer_index = 1
            # 记录该进程一共有哪些线程
            thread_name_list = []
            if "surfaceflinger" in pthread:
                # surfaceflinger 不会存在堆buffer
                for row_index_start in range(len(sheet_data)):
                    if row_index_start == 0:
                        sheet_data[row_index_start][drop_frames_filter_buffer_index], sheet_data[row_index_start][
                            filter_buffer_start_index] = \
                            headers[drop_frames_filter_buffer_index], headers[filter_buffer_start_index]
                    else:
                        sheet_data[row_index_start][drop_frames_filter_buffer_index], sheet_data[row_index_start][
                            filter_buffer_start_index] = sheet_data[row_index_start][
                            drop_frames_before_filter_index], ""
                continue
            # 其余进程统计堆buffer
            for row_index_start in range(len(sheet_data)):
                if row_index_start != 0:
                    thread_name = sheet_data[row_index_start][thread_name_index]
                    if thread_name not in thread_name_list:
                        thread_name_list.append(thread_name)
            # 线程维度统计堆buffer
            for thread_name_item in thread_name_list:
                # launcher 进程统计 主进程 + launcher.anim ,其余进程只统计主线程

                pre_index = None
                for row_index_start in range(len(sheet_data)):
                    # 第一行写标题
                    if row_index_start == 0:
                        sheet_data[row_index_start][drop_frames_filter_buffer_index], sheet_data[row_index_start][
                            filter_buffer_start_index] = \
                            headers[drop_frames_filter_buffer_index], headers[filter_buffer_start_index]
                        continue
                    thread_name = sheet_data[row_index_start][thread_name_index]
                    if thread_name != thread_name_item:
                        continue
                    # 找到该线程的上一帧
                    if pre_index is None:
                        pre_index = row_index_start

                    drop_frames = sheet_data[row_index_start][drop_frames_before_filter_index]
                    pre_drop_frame = sheet_data[pre_index][
                        drop_frames_before_filter_index] if row_index_start > pre_index else 0
                    pre_index = row_index_start
                    if row_index_start < start_heap_buffer_index:
                        # 跳转到下一个堆buffer区间的开头
                        continue
                    # 找到区间的终点
                    if abs(drop_frames - pre_drop_frame) > 1 or row_index_start == len(sheet_data) - 1 or round(
                            drop_frames) == 0:
                        # 循环时range 不访问最后一个元素
                        if row_index_start == len(sheet_data) - 1:
                            end_heap_buffer_index = row_index_start + 1
                        else:
                            end_heap_buffer_index = row_index_start

                        # 堆buffer 区间内找到最大值，其余值的丢帧数赋值为0，记录开始计算堆buffer的 vsync_id
                        max_index = None
                        max_dropFrames = -1
                        # todo  无效帧是否会存在 五统计的情况
                        start_vsyncId = sheet_data[start_heap_buffer_index][actual_vsyncId_index]
                        for buffer_index in range(start_heap_buffer_index, end_heap_buffer_index):
                            buffer_dropFrames = sheet_data[buffer_index][drop_frames_before_filter_index]
                            print(f"buffer_dropFrames {buffer_dropFrames}")
                            print(f"max_dropFrames {max_dropFrames}")
                            # 只取不在iq范围的最大值， 筛选非iq范围内，滑动区间的数据
                            if buffer_dropFrames > max_dropFrames and "是" not in sheet_data[buffer_index][
                                filter_iq_or_not_index] and "否" not in \
                                    sheet_data[buffer_index][is_scrolling_index]:
                                max_index = buffer_index
                                max_dropFrames = sheet_data[max_index][drop_frames_before_filter_index]
                        if max_index is None:
                            max_index = start_heap_buffer_index
                        # 过滤堆buffer的数据：只保留堆buffer区间 非iq， 在动画区间的最大连续丢帧数
                        for buffer_index in range(start_heap_buffer_index, end_heap_buffer_index):
                            if buffer_index != max_index:
                                sheet_data[buffer_index][drop_frames_filter_buffer_index], sheet_data[buffer_index][
                                    filter_buffer_start_index] = 0, start_vsyncId
                            else:
                                max_drop_frames = sheet_data[max_index][drop_frames_before_filter_index]

                                sheet_data[buffer_index][drop_frames_filter_buffer_index], sheet_data[buffer_index][
                                    filter_buffer_start_index] = max_drop_frames, start_vsyncId
                        # 堆buffer结束之后赋值start_heap_buffer_index：  本区间的终点的就是下一个区间的开始
                        start_heap_buffer_index = end_heap_buffer_index

    def filter_iq():
        """
        过滤iq信息:
        离屏滑动（iq区间小于等于800ms）：忽略所有iq 及iq前后60ms的丢帧数据
        按压滑动（iq区间大于800ms）： 忽略部分iq信息（忽略iq区间前200ms， 保留剩余iq信息）
        @return:
        """
        tick_num = 2
        # 过滤iq区间前后60ms信息
        notIq_filter_time = 60000000
        # 过滤按压滑动前100ms信息
        iq_filter_time = 100000000
        # iq区间时长在400ms以上，认为是按压滑动
        pressSlide_checkTime = 400000000
        # 判断iq持续时间在50ms以内则属于同一个iq区间
        global same_iq_checkTime
        not_iq_list = []
        not_filter_list = []
        # 筛选所有非iq滑动期间的数据
        first_iq_start = None
        last_iq_end = None
        for iq_item in iq_List:
            start_ts, end_ts, iq_value = iq_item[0], iq_item[1], iq_item[2]
            if iq_value == 0 and end_ts - start_ts > same_iq_checkTime:
                not_iq_list.append([start_ts, end_ts, iq_value])
            if first_iq_start is None and iq_value == 1:
                first_iq_start = start_ts
            if iq_value == 1:
                last_iq_end = end_ts
        # 单独处理一开始测试就是按压滑动，按压前无iq信息的情形：sw
        if len(not_iq_list) > 0:
            if first_iq_start is not None and not_iq_list[0][0] - first_iq_start > pressSlide_checkTime:
                not_filter_list.append([first_iq_start + iq_filter_time, not_iq_list[0][0], 1])
        else:
            # 处理全部是按压滑动，没有iq为0的场景
            if last_iq_end is not None and first_iq_start is not None and last_iq_end - first_iq_start > pressSlide_checkTime:
                not_filter_list.append([first_iq_start + iq_filter_time, last_iq_end, 1])

        # 获取所有不需要过滤iq的时间段
        for index in range(0, len(not_iq_list)):
            # 计算iq范围大于1s，认为是按压滑动取（start+100ms, end）
            notIq_start_ts = not_iq_list[index][0]
            notIq_end_ts = not_iq_list[index][1]
            not_filter_list.append(
                [notIq_start_ts + notIq_filter_time, notIq_end_ts - notIq_filter_time, not_iq_list[index][2]])
            if index < len(not_iq_list) - 1:
                iq_start = notIq_end_ts
                iq_end = not_iq_list[index + 1][0]
                if iq_end - iq_start > pressSlide_checkTime:
                    not_filter_list.append([iq_start + iq_filter_time, iq_end, 1])

        # 不在not_iq_tem 的赋值为0

        for pthread in frameTimeLine_Map:
            sheet_data = frameTimeLine_Map[pthread]

            for row_index_start in range(len(frameTimeLine_Map[pthread])):
                # 写标题
                if row_index_start == 0:
                    sheet_data[0][filter_iq_or_not_index], sheet_data[0][drop_frames_filter_iq_index] = \
                        headers[filter_iq_or_not_index], headers[drop_frames_filter_iq_index]
                    continue
                # 赋值
                sheet_data[row_index_start][filter_iq_or_not_index] = "否"
                sheet_data[row_index_start][drop_frames_filter_iq_index] = sheet_data[row_index_start][
                    drop_frames_before_filter_index]

                is_iq_data = True
                actual_ts = sheet_data[row_index_start][actual_ts_index]
                for not_iq_item in not_filter_list:
                    not_iq_start, not_iq_end = not_iq_item[0], not_iq_item[1]
                    if actual_ts >= not_iq_start and actual_ts <= not_iq_end:
                        is_iq_data = False
                        break
                # 如果iq 信息和滑动/动画埋点信息冲突，则不过滤iq信息
                if is_iq_data and "是" not in sheet_data[row_index_start][is_scrolling_index]:
                    sheet_data[row_index_start][filter_iq_or_not_index] = "是"
                    sheet_data[row_index_start][drop_frames_filter_iq_index] = 0

    def filter_scrolling():
        global scroll_track_name, filter_scroll, Discard_info, Discard_reports
        # 只保留滑动场景的丢帧数据：Scrolling， slideScene_listview_slide
        if  len(scroll_track_name[-1]) != 0:
            Discard_reports = True
            Discard_info = f"trace中无指定动画关键字{scroll_track_name}相关信息， 丢弃该报告"
        # 判断是否使用google 原生的动画tag
        if check_use_gooogle_scroll():
            anim_map = find_google_anim_scene(iq_info_list=iq_List)

        for pthread in frameTimeLine_Map:
            sheet_data = frameTimeLine_Map[pthread]

            if  check_use_gooogle_scroll():
                #google 原生tag
                scrolling_list = []
                for key, scroll_item_list in anim_map.items():
                    if key  in pthread:
                        scrolling_list = scroll_item_list
                        break
            else:
                # 大数据动画tag
                scrolling_list = exe_scrollingSql(pthread)
            for row_index_start in range(len(frameTimeLine_Map[pthread])):
                thread_name = frameTimeLine_Map[pthread][row_index_start][thread_name_index]

                if row_index_start == 0:
                    sheet_data[0][is_scrolling_index], sheet_data[0][drop_frames_filter_scrolling_index], sheet_data[0][
                        scrolling_keyInfo_index] = headers[is_scrolling_index], headers[
                        drop_frames_filter_scrolling_index], headers[scrolling_keyInfo_index]
                    continue
                if filter_scroll == '0' or filter_scroll == '1':
                    actual_ts = sheet_data[row_index_start][actual_ts_index]
                    frame_dur = sheet_data[row_index_start][do_draw_dur_index] if "None" not in str(
                        sheet_data[row_index_start][do_draw_dur_index]) and 0 != len(
                        str(sheet_data[row_index_start][do_draw_dur_index])) else sheet_data[row_index_start][
                        actual_dur_index]
                    # 判断是否在动画区间内
                    is_scroll, scroll_otherInfo, scroll_list_item = find_scrolling(actual_ts, frame_dur, scrolling_list,
                                                                                  thread_name)
                    if  len(scroll_track_name[-1]) != 0 and scroll_otherInfo in scroll_track_name:
                        Discard_reports = False
                        Discard_info = ""


                    # 判断是否在首帧，或者是尾帧
                    need_filter = is_first_or_end_frame(sheet_data, row_index_start, pthread, scroll_list_item)

                    drop_frames = sheet_data[row_index_start][drop_frames_before_filter_index]
                    if len(scrolling_list) > 1:
                        if is_scroll:
                            if not need_filter:
                                sheet_data[row_index_start][is_scrolling_index], sheet_data[row_index_start][
                                    drop_frames_filter_scrolling_index], sheet_data[row_index_start][
                                    scrolling_keyInfo_index] = "是", drop_frames, scroll_otherInfo
                            else:
                                sheet_data[row_index_start][is_scrolling_index], sheet_data[row_index_start][
                                    drop_frames_filter_scrolling_index], sheet_data[row_index_start][
                                    scrolling_keyInfo_index] = "否", drop_frames, scroll_otherInfo
                                sheet_data[row_index_start][vsync_check_info_index] += " 当前为首帧/尾帧" if \
                                sheet_data[row_index_start][vsync_check_info_index] is None else \
                                sheet_data[row_index_start][vsync_check_info_index] + " 当前为首帧/尾帧"
                        else:
                            sheet_data[row_index_start][is_scrolling_index], sheet_data[row_index_start][
                                drop_frames_filter_scrolling_index], sheet_data[row_index_start][
                                scrolling_keyInfo_index] = "否", 0, scroll_otherInfo
                    else:
                        # 处理进程无动画字段，但是前后两帧时间差超过fps时间的情况
                        if isinstance(sheet_data[row_index_start][vsync_check_info_index], str) and "前后两帧时间差超过fps时间" in sheet_data[row_index_start][vsync_check_info_index]:
                            sheet_data[row_index_start][is_scrolling_index], sheet_data[row_index_start][
                                drop_frames_filter_scrolling_index], sheet_data[row_index_start][
                                scrolling_keyInfo_index] = "否", 0, scroll_otherInfo
                            sheet_data[row_index_start][vsync_check_info_index] += " 进程无动画字段，不统计此行丢帧"
                        else:
                            # 兼容不输入滑动关键字，并且在trace中无法找到对应滑动字段的情况
                            sheet_data[row_index_start][is_scrolling_index], sheet_data[row_index_start][
                                drop_frames_filter_scrolling_index], sheet_data[row_index_start][
                                scrolling_keyInfo_index] = "", "", ""

                else:
                    sheet_data[row_index_start][is_scrolling_index], sheet_data[row_index_start][
                        drop_frames_filter_scrolling_index], sheet_data[row_index_start][
                        scrolling_keyInfo_index] = "", "", ""

    def is_drop():
        """
        四舍五入丢帧数据， 判断是否丢帧
        """
        for pthread in frameTimeLine_Map:
            sheet_data = frameTimeLine_Map[pthread]
            for row_index_start in range(len(sheet_data)):
                # 写标题
                if row_index_start == 0:
                    sheet_data[row_index_start][drop_frames_index], sheet_data[row_index_start][
                        drop_frame_or_not_index] = headers[drop_frames_index], headers[drop_frame_or_not_index]
                else:
                    filter_buffer_drop_frame = sheet_data[row_index_start][drop_frames_filter_buffer_index]
                    drop_frame_before_filter = sheet_data[row_index_start][drop_frames_before_filter_index]
                    need_filter_iq = sheet_data[row_index_start][filter_iq_or_not_index]
                    need_filter_scroll = sheet_data[row_index_start][is_scrolling_index]
                    bufferTx = sheet_data[row_index_start][bufferTX_index]
                    rt_not_useful_count = sheet_data[row_index_start][noUseful_rt_count_index]
                    thread_name = sheet_data[row_index_start][thread_name_index]
                    drop_frames_byExpected = sheet_data[row_index_start][drop_frames_byExpected_index]
                    drop_frames_byExpected = round(drop_frames_byExpected) if (isinstance(drop_frames_byExpected, int) or isinstance(drop_frames_byExpected, float)) else float('inf')
                    app_duration =  sheet_data[row_index_start][expected_dur_index]
                    do_draw_dur = sheet_data[row_index_start][do_draw_dur_index]
                    # 然后判断应用的每帧耗时：do frame+draw ，如果超过当前的vsync，再去看这帧中间错过了多少个vsync-sf
                    # 不在iq过滤范围内&在动画区间&bufferTX =
                    vsync_id  = sheet_data[row_index_start][actual_vsyncId_index]
                    if drop_frame_before_filter > 0 \
                            and "是" not in need_filter_iq \
                            and "否" not in need_filter_scroll:
                        if "surfaceflinger" in pthread:
                            # surfaceflinger不过滤堆buffer
                            sheet_data[row_index_start][drop_frames_index] = round(drop_frame_before_filter)
                        else:
                            # 应用判断出帧时长是否> app_duration
                            # if isinstance(do_draw_dur, int) and isinstance(app_duration, int) and app_duration > do_draw_dur:
                            #     sheet_data[row_index_start][drop_frames_index] = 0
                            #     print(f" app_duration test：{sheet_data[row_index_start][actual_vsyncId_index]}")
                            # else:
                            #     # 没有bufferTX 相关信息， 不需要考虑rt插帧，直接过滤iq， 动画，堆buffer
                            #     # 针对两帧之间的间隔大于fps的情况，丢帧选取bufferTX 为0 时total_slice_dur/max_fps
                            if  (isinstance(bufferTx, str) or thread_name in thread_without_drawFrame ):
                                sheet_data[row_index_start][drop_frames_index] = min(round(filter_buffer_drop_frame), drop_frames_byExpected)
                            else:
                                if not isinstance(rt_not_useful_count, int):
                                    sheet_data[row_index_start][drop_frames_index] = bufferTx
                                else:
                                    sheet_data[row_index_start][drop_frames_index] = bufferTx + rt_not_useful_count
                            # 针对某些滑动类型，只关注某些进程的丢帧
                            scrolling_type = sheet_data[row_index_start][scrolling_keyInfo_index]
                            thread_name = sheet_data[row_index_start][thread_name_index]
                            # 滑动类型在thread_with_anim内 并且将线程不为对应线程则设置丢帧为0
                            if scrolling_type in thread_with_anim and thread_name not in thread_with_anim.get(
                                    scrolling_type):
                                sheet_data[row_index_start][drop_frames_index] = 0

                    else:
                        sheet_data[row_index_start][drop_frames_index] = 0

                    sheet_data[row_index_start][drop_frame_or_not_index] = (
                                sheet_data[row_index_start][drop_frames_index] > 0)

    def add_bufferTx_info():
        """
        frameTime 结束点匹配bufferTX数据，并调用 _adjust_bufferTx_by_frtc 做 FRTC / vsync 相关的 bufferTX 校正。
        """
        nonlocal vsync_sf_list

        split_vsync_sf_list = vsync_sf_list.copy()
        for pthread in frameTimeLine_Map:
            if "com.android.systemui" in pthread:
                bufferTX_sql = f"""
                SELECT * FROM counter JOIN process_counter_track ON process_counter_track.id = counter.track_id WHERE process_counter_track.name like 'BufferTX - NotificationShade%' or process_counter_track.name like 'BufferTX - StatusBar%'  or process_counter_track.name like 'BufferTX - VRI-NotificationShade%' or process_counter_track.name like 'BufferTX - VRI-StatusBar%'  order by ts
                """
            else:

                bufferTX_sql = f"""
                SELECT * FROM counter JOIN process_counter_track ON process_counter_track.id = counter.track_id WHERE process_counter_track.name like 'BufferTX - {pthread}%' or process_counter_track.name like 'BufferTX - VRI-{pthread}%' order by ts
                """
            bufferTX_list = exe_bufferTX_sql(bufferTX_sql)
            sheet_data = frameTimeLine_Map[pthread]
            # 如果是frtc 数据，则需要重新切割vsync-sf todo
            frtc_key = find_frtc_key(fps_map, pthread)
            if frtc_key is not None:
                split_vsync_sf_list = split_vsync_sf(vsync_sf_list_raw, vsync_app_list_raw, fps_map, pthread,
                                                     split_by_app_duration=True)

            for row_index_start in range(len(sheet_data)):
                if row_index_start == 0:
                    sheet_data[0][bufferTX_index] = headers[bufferTX_index]
                    continue
                # 根据前一帧的情况计算bufferTX的起点
                bufferTX_start_ts = calculate_bufferTX_start_ts(sheet_data, row_index_start)
                
                do_draw_dur = sheet_data[row_index_start][do_draw_dur_index]
                actual_dur = sheet_data[row_index_start][actual_dur_index]
                dur = actual_dur if len(str(do_draw_dur)) == 0 else do_draw_dur
                dur = 0 if dur is None else dur
                
                # 使用计算后的起点和当前帧的终点来计算bufferTX
                current_start_ts = sheet_data[row_index_start][actual_ts_index]
                bufferTX_end_ts = current_start_ts + dur if current_start_ts is not None and dur is not None else None
                if bufferTX_end_ts is None:
                    bufferTX_value = "无有效时间范围"
                elif isinstance(sheet_data[row_index_start][vsync_check_info_index], str) and "FRTC降帧" in \
                        sheet_data[row_index_start][vsync_check_info_index]:
                    bufferTX_value = find_droFrames_by_bufferTX(bufferTX_start_ts, bufferTX_end_ts, bufferTX_list,
                                                                split_vsync_sf_list)
                else:
                    bufferTX_value = find_droFrames_by_bufferTX(bufferTX_start_ts, bufferTX_end_ts, bufferTX_list, vsync_sf_list)
                # 写入bufferTX丢帧，及相关信息
                sheet_data[row_index_start][bufferTX_index] = bufferTX_value
                if current_start_ts < bufferTX_start_ts:
                    if sheet_data[row_index_start][vsync_check_info_index] is None:
                        sheet_data[row_index_start][vsync_check_info_index] = ""
                    sheet_data[row_index_start][vsync_check_info_index] += f" 当前帧与上一帧重叠,本帧开始时间为{bufferTX_start_ts},结束时间为 {bufferTX_end_ts} "



    add_rt_info()
    filter_scrolling()
    filter_iq()
    filter_buffer()
    add_bufferTx_info()
    # 区分surfaceflinger？
    is_drop()




def _adjust_bufferTx_by_frtc(
        pthread,
        sheet_data,
        row_index_start,
        start_ts,
        do_draw_dur,
        actual_dur,
        vsync_app_list_raw,
        vsync_sf_list_raw,
        fps_map,

):
    """
    bufferTX > 0 且满足 FRTC 降帧（frtc_rate < 刷新率）时：
    1. 用“原始” vsync-app 列表（包含 value）找到该帧之前最近一次 value==1 的 vsync-app 上升沿
    2. 用“原始” vsync-sf 列表找到该帧之后最近一次 value==1 的 vsync-sf 上升沿
    3. 计算 app_duration = ((vsync_sf - vsync_app) % frameInterval + frameInterval)（正模），并按 ms 级向上取整
    若 doframe+drawframe 时间 < app_duration，则认为该 bufferTX 不应计入，置 0。
    """
    # 仅当 bufferTX > 0 且传入了“原始” vsync-app / vsync-sf 列表（包含 value）时，才做 FRTC 降帧相关判断


    # 只处理刷新率为frtc 的数据,         # surfaceflinger 本身不做 FRTC 判定
    if "frtc" not in sheet_data[row_index_start][fps_keyInfo_index] or "surfaceflinger" in pthread:
        return

    frame_start_ts = start_ts
    # doframe+drawframe 时长
    do_draw_dur_val = do_draw_dur if len(str(do_draw_dur)) != 0 and "None" not in str(do_draw_dur) else actual_dur
    if not isinstance(do_draw_dur_val, (int, float)) or do_draw_dur_val <= 0:
        return


    # 获取正常刷新率及frtc刷新率
    fps_dur, fps_otherInfo = find_fps_data(start_ts, do_draw_dur, fps_map)
    if fps_dur is None:
        print(f"vsyncid:{sheet_data[row_index_start][actual_vsyncId_index]} 处理找不着真实刷新率，只有frtc刷新率的情况")
        return
    fps_hz = int(1_000_000_000 / fps_dur)

    frtc_rate, frtc_type = find_fps_data(start_ts, do_draw_dur, fps_map, pthread)
    frtc_hz = int(1_000_000_000 / frtc_rate)

    if not isinstance(fps_dur, (int, float)) or fps_dur <= 0:
        return
    # 只有frtc降帧区间，按照app_duration 去切割vsync-sf，获取bufferTX
    if frtc_rate is None or frtc_rate <= 0 or int(frtc_hz) >= int(fps_hz):
        sheet_data[row_index_start][
            vsync_check_info_index] += f" FRTC-framerate:{frtc_hz}hz, fps:{fps_hz}hz, fps_type:{fps_otherInfo}"
        return
    # frtc降帧区间,获取app_duraion 作为刷新率
    frame_interval_ns = fps_dur
    app_duration_mod_ns = get_app_duration(frame_start_ts, vsync_app_list_raw, vsync_sf_list_raw, frame_interval_ns)
    if app_duration_mod_ns is None:
        return
    # 将app duration变更为刷新率
    sheet_data[row_index_start][fps_index] = app_duration_mod_ns
    sheet_data[row_index_start][fps_keyInfo_index] = frtc_type
    sheet_data[row_index_start][drop_frames_byFps_index] = do_draw_dur_val / int(app_duration_mod_ns) - 1
    sheet_data[row_index_start][
        vsync_check_info_index] += f" FRTC-framerate:{frtc_hz}hz, app_duraion:{app_duration_mod_ns}ns, fps:{fps_hz}hz FRTC降帧"


def find_frtc_key(fps_map, pthread_name):
    """
    在 fps_map 的 key 里查找既包含 'frtc' 又包含 pthread_name 的 key。
    找到则返回该 key，找不到返回 None。
    """
    for key in fps_map.keys():
        if not isinstance(key, str):
            continue
        if "frtc" in key and pthread_name in key:
            return key
    return None


def find_previous_frame(sheet_data, current_index):
    """
    查找当前帧的前一帧（往前数，找到出帧时长不为0或None，且thread_name相同的一行数据）
    @param sheet_data: sheet数据列表
    @param current_index: 当前帧的行索引
    @return: 前一帧的行索引，如果找不到则返回None
    """
    if current_index <= 1:  # 跳过标题行，至少从第2行开始
        return None
    
    current_thread_name = sheet_data[current_index][thread_name_index]
    
    # 往前查找
    for i in range(current_index - 1, 0, -1):  # 从当前行往前查找，跳过标题行
        prev_do_draw_dur = sheet_data[i][do_draw_dur_index]
        prev_thread_name = sheet_data[i][thread_name_index]
        
        # 检查出帧时长是否有效（不为0且不为None）
        is_valid_dur = (
            prev_do_draw_dur is not None 
            and prev_do_draw_dur != 0 
            and str(prev_do_draw_dur) != "0"
            and str(prev_do_draw_dur).lower() != "none"
        )
        
        # 检查线程名是否相同
        is_same_thread = (
            prev_thread_name is not None 
            and current_thread_name is not None
            and str(prev_thread_name) == str(current_thread_name)
        )
        
        if is_valid_dur and is_same_thread:
            return i
    
    return None


def frames_overlap(prev_frame_start, prev_frame_end, current_frame_start, current_frame_end):
    """
    判断前一帧与当前帧是否有重叠
    @param prev_frame_start: 前一帧的起点（actual_ts_index）
    @param prev_frame_end: 前一帧的终点（actual_ts_index + do_draw_dur_index）
    @param current_frame_start: 当前帧的起点（actual_ts_index）
    @param current_frame_end: 当前帧的终点（actual_ts_index + do_draw_dur_index）
    @return: True表示有重叠，False表示无重叠
    """
    # 检查参数有效性
    if None in [prev_frame_start, prev_frame_end, current_frame_start, current_frame_end]:
        return False
    
    # 转换为数值类型进行比较
    try:
        prev_start = float(prev_frame_start)
        prev_end = float(prev_frame_end)
        curr_start = float(current_frame_start)
        curr_end = float(current_frame_end)
    except (ValueError, TypeError):
        return False
    
    # 判断两个区间是否有重叠：两个区间有交集
    # 重叠条件：prev_end > curr_start 且 prev_start < curr_end
    return prev_end > curr_start and prev_start < curr_end


def calculate_bufferTX_start_ts(sheet_data, current_index):
    """
    根据前一帧的情况计算当前帧计算bufferTX的起点
    @param sheet_data: sheet数据列表
    @param current_index: 当前帧的行索引
    @return: 计算bufferTX的起点时间戳
    """
    current_start_ts = sheet_data[current_index][actual_ts_index]
    
    # 查找前一帧
    prev_index = find_previous_frame(sheet_data, current_index)
    
    # 如果没有前一帧，使用当前帧的起点
    if prev_index is None:
        return current_start_ts
    
    # 获取前一帧和当前帧的时间信息
    prev_start_ts = sheet_data[prev_index][actual_ts_index]
    prev_do_draw_dur = sheet_data[prev_index][do_draw_dur_index]
    
    # 计算前一帧的终点（只使用prev_do_draw_dur）
    prev_dur = prev_do_draw_dur
    if prev_dur is None or str(prev_dur) == "0" or str(prev_dur).lower() == "none" or str(prev_dur) == "":
        prev_dur = 0
    prev_end_ts = prev_start_ts + prev_dur if prev_start_ts is not None and prev_dur is not None else None
    
    # 获取当前帧的时间信息
    current_do_draw_dur = sheet_data[current_index][do_draw_dur_index]
    
    # 计算当前帧的终点（只使用current_do_draw_dur）
    current_dur = current_do_draw_dur
    if current_dur is None or str(current_dur) == "0" or str(current_dur).lower() == "none" or str(current_dur) == "":
        current_dur = 0
    current_end_ts = current_start_ts + current_dur if current_start_ts is not None and current_dur is not None else None
    
    # 判断是否有重叠
    if prev_end_ts is None or current_end_ts is None:
        return current_start_ts
    
    has_overlap = frames_overlap(prev_start_ts, prev_end_ts, current_start_ts, current_end_ts)
    
    if has_overlap:
        # 检查前一帧是否有bufferTX丢帧
        prev_bufferTX = sheet_data[prev_index][bufferTX_index]
        pre_drop_frame_before_filter, pre_need_filter_iq, pre_need_filter_scroll = sheet_data[prev_index][drop_frames_before_filter_index], sheet_data[prev_index][filter_iq_or_not_index],sheet_data[prev_index][is_scrolling_index]
        prev_has_bufferTX_drop = False
        pre_vsyncId = sheet_data[prev_index][actual_vsyncId_index]
        if "3905544" in str(pre_vsyncId):
            print("demo")
        if prev_bufferTX is not None and prev_bufferTX != "":
            try:
                # 尝试转换为数值类型，如果成功且大于0，则认为有bufferTX丢帧
                prev_bufferTX_value = float(prev_bufferTX)
                prev_has_bufferTX_drop = prev_bufferTX_value > 0 and pre_drop_frame_before_filter >0 and "是" not in pre_need_filter_iq and "否" not in pre_need_filter_scroll
            except (ValueError, TypeError):
                # 如果是字符串（如"无相关buffer信息"），则认为无bufferTX丢帧
                prev_has_bufferTX_drop = False
        
        if prev_has_bufferTX_drop:
            # 前一帧有bufferTX丢帧，使用前一帧的终点作为当前帧的起点
            return prev_end_ts
        else:
            # 前一帧无bufferTX丢帧，使用当前帧的起点
            return current_start_ts
    else:
        # 不重叠，使用当前帧的起点
        return current_start_ts


def find_bufferTX(endTS, bufferTX_list):
    """
    获取frameTimeLine 技术时bufferTX的状态
    @param endTS:
    @param bufferTX_list:
    @return:
    """
    for index in range(len(bufferTX_list)):
        if index == 0:
            continue
        bufferTX_start = bufferTX_list[index][0]
        bufferTX_end = bufferTX_list[index][1]
        bufferTX_value = bufferTX_list[index][2]
        if bufferTX_start < endTS and endTS <= bufferTX_end:
            return bufferTX_value
    return ""


def split_vsync_sf(vsync_sf_list, vsync_app_list, all_fps_list, phtread_name=None, split_by_app_duration=False):
    """
    针对vsync-sf 信号异常的情况， 根据fps，vsync-app 将vsync_sf信号做切割
    """
    new_vsyncSF_list = []
    for vsyncSF_item in vsync_sf_list:
        start_ts = vsyncSF_item[0]
        end_ts = vsyncSF_item[1]
        vsyncSF_dur = vsyncSF_item[2]
        vsyncSF_value = vsyncSF_item[3]

        if isinstance(start_ts, str):
            new_vsyncSF_list.append([start_ts, end_ts, vsyncSF_dur, vsyncSF_value])
            continue

        fps_time, fps_other_info = find_fps_data(start_ts, end_ts - start_ts, all_fps_list, phtread_name)

        if split_by_app_duration:
            # 获取非frtc 的刷新率
            fps_time, fps_other_info = find_fps_data(start_ts, end_ts - start_ts, all_fps_list)
            # 获取vsync-sf 对应的app_duration, 后续根据app_duration切割fps
            fps_time = get_app_duration(start_ts, vsync_app_list, vsync_sf_list, fps_time)

        if fps_time is None:
            vsync_start, vsync_end, fps_time = find_vsync_data(start_ts, vsync_app_list)

            # 异常的vsync-sf 区间不足两个fps 时间，则算作一个
        if fps_time > 0:
            while end_ts != float("inf") and end_ts - (start_ts + fps_time) >= 0.5 * fps_time:
                print(f"卡死检测-循环内{start_ts}， fpstime{fps_time}， vsyncId：{vsyncSF_item}")
                new_vsyncSF_list.append([start_ts, start_ts + fps_time, fps_time, vsyncSF_value])
                start_ts = start_ts + fps_time

        new_vsyncSF_list.append([start_ts, end_ts, vsyncSF_dur, vsyncSF_value])
    return new_vsyncSF_list


def find_droFrames_by_bufferTX(start, end, bufferTX_list, vsync_sf_list):
    """
    1.找到每帧区间内bufferTX为0的区间t
    2.找到区间t内 有几个vsync-sf 信号变化
    """
    if len(bufferTX_list) == 1:
        # 针对该线程没有buffer
        return "无相关buffer信息"
    drop_frames = 0
    # 一帧内可能存在多个bufferTX为0的情况
    for buffertx_item in bufferTX_list:
        buffer_value = buffertx_item[2]
        buffer_start_ts = buffertx_item[0]
        buffer_end_ts = buffertx_item[1]
        if isinstance(buffer_value, str) or buffer_value != 0:
            continue
        # t区间开始
        drop_start = 0
        # t区间结束
        drop_end = 0
        drop_start = max(start, buffer_start_ts)
        drop_end = min(end, buffer_end_ts)
        if drop_end < drop_start:
            continue

        if 0 == drop_start or 0 == drop_end:
            continue
        # 找到buffer为0区间内，vsyncsf 变更的次数
        pre_vsyncsf_value = None
        for vsync_sf_item in vsync_sf_list:
            cur_vsync_sf_start = vsync_sf_item[0]
            cur_vsync_sf_value = vsync_sf_item[2]
            if isinstance(cur_vsync_sf_value, str):
                continue

            # if cur_vsync_sf_start>=drop_start and cur_vsync_sf_start<=drop_end and cur_vsync_sf_value != pre_vsyncsf_value  :
            if cur_vsync_sf_start >= drop_start and cur_vsync_sf_start <= drop_end:
                print(vsync_sf_item)
                drop_frames += 1
            pre_vsyncsf_value = cur_vsync_sf_value

    return drop_frames


def exe_bufferTX_sql(bufferTX_sql):
    """

    @param sql: 获取进程对应的bufferTX相关信息[bufferTX状态开始时间， bufferTX状态结束时间, bufferTX状态值]
    @return:
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

    bufferTX_list = [["pre_bufferTX_startTs", "current_bufferTX_startTs", "时间差"]]
    qr_it = tp_resource.query(bufferTX_sql)
    buffer_per_thread = {}
    name_list = []
    # 统计每个buffer区间(没一个buffer变化就将buffer区间划分为1块)
    pre_ts = None
    qr_it_list = []
    for index, row in enumerate(qr_it, start=1):
        name = row.name
        ts = row.ts
        value = row.value
        qr_it_list.append([name, ts, value])

        if name not in name_list:
            name_list.append(name)

        if pre_ts is None:
            pre_ts = row.ts
        else:
            cur_ts = row.ts
            bufferTX_list.append([pre_ts, cur_ts])
            pre_ts = cur_ts
    # 按照线程去统计buffer的值
    for name in name_list:
        pre_value = None
        buffer_per_thread[name] = []
        for row in qr_it_list:
            row_name = row[0]
            ts = row[1]
            value = row[2]
            if row_name == name:
                if pre_value is None:
                    pre_ts = ts
                    pre_value = value
                else:
                    current_ts = ts
                    current_value = value
                    # 赋值
                    buffer_per_thread[name].append([pre_ts, current_ts, pre_value])
                    pre_ts = current_ts
                    pre_value = current_value
    # 找到bufferTX对应的value 并填充
    for buffer_item in bufferTX_list:
        start = buffer_item[0]
        end = buffer_item[1]
        if isinstance(start, str) and isinstance(end, str):
            continue
        buffer_value = 0
        for thread_buffer in buffer_per_thread.values():
            for thread_buffer_item in thread_buffer:
                if start >= thread_buffer_item[0] and end <= thread_buffer_item[1]:
                    buffer_value = max(buffer_value, thread_buffer_item[2])
        buffer_item.append(buffer_value)

    # bufferTX_list.append([pre_ts, float("inf"), pre_value])

    return bufferTX_list


def exe_frameTimeLine_sql(sql, pthread_list = []):
    """
        pthread_list 为空则解析所有进程的丢帧数据，否则只解析list中对应进程的丢帧数据
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

    global sql_result_map
    qr_it = tp_resource.query(sql)
    # 往每个sheet页里面填写 "时间戳", "时间", "vsyncId", "进程名", "expected_dur", "actual_dur", 相关数据
    # 获取坐标
    vsync_id_map = {}
    for index, row in enumerate(qr_it):
        # "Dropped Frame" in row.jank_type 兼容有FrameTimeLine 没有Doframe/DrameFrame的case
        if row.actual_ts <= 0:
            continue
        # 如果传入了pthread_list且不为空，则只统计pthread_list内的进程
        if pthread_list and len(pthread_list) > 0:
            need_continue = True
            for pthread in pthread_list:
                if pthread in row.name:
                    need_continue = False
            if need_continue:
                continue

        if row.name not in sql_result_map:
            sql_result_map[row.name] = []
            sql_result_map[row.name].append([None] * len(headers))
            # 添加标题： frameTimeLine相关数据
            sql_result_map[row.name][0][actual_ts_index] = headers[actual_ts_index]
            sql_result_map[row.name][0][actual_time_index] = headers[actual_time_index]
            sql_result_map[row.name][0][actual_vsyncId_index] = headers[actual_vsyncId_index]
            sql_result_map[row.name][0][pthread_name_index] = headers[pthread_name_index]
            sql_result_map[row.name][0][expected_dur_index] = headers[expected_dur_index]
            sql_result_map[row.name][0][actual_dur_index] = headers[actual_dur_index]
            sql_result_map[row.name][0][thread_name_index] = headers[thread_name_index]

        #
        if row.name not in vsync_id_map:
            vsync_id_map[row.name] = []

        if row.vsyncId in vsync_id_map[row.name]:
            continue
        else:
            vsync_id_map[row.name].append(row.vsyncId)

        sql_result_map[row.name].append([None] * len(headers))


        date = datetime.fromtimestamp(int(row.actual_ts / 1000000000))

        # 添加数据
        sql_result_map[row.name][-1][actual_ts_index], sql_result_map[row.name][-1][actual_time_index], \
        sql_result_map[row.name][-1][actual_vsyncId_index], sql_result_map[row.name][-1][pthread_name_index], \
        sql_result_map[row.name][-1][expected_dur_index], sql_result_map[row.name][-1][
            actual_dur_index] = row.actual_ts, date, row.vsyncId, row.name, row.expected_dur, row.actual_dur
        sql_result_map[row.name][-1][vsync_check_info_index] = f"{on_finish_message}{row.on_time_finish}"
        sql_result_map[row.name][-1][vsync_check_info_index] += f"jank_type: {row.jank_type}"


def calculate_1s_maxFrameSum(*maps):
    """
    统计1s 最大丢帧总数
    @param maps:
    @return:
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
    if Discard_reports:
        maxFrameSum_1s = [[Discard_info]]
        return maxFrameSum_1s

    maxFrameSum_1s = [["进程", "1s内总丢帧数", "起始VsyncID（1s内总丢帧数）", "结束VsyncID（1s内总丢帧数）", "连续丢帧数",
                       "vsyncID(统计丢帧最大的那一帧)"]]
    # 遍历 surfacefinger map /other_info map
    for sql_map in maps:
        # 遍历map中的每个进程
        for key in sql_map:
            sheet_data = sql_map.get(key)
            framesum_1s_allRow = 0
            maxFrameSum_1s_pthread = [key, 0, 0, 0]
            # 遍历每个进程每个时间戳的丢帧数据
            for row_index_start in range(len(sheet_data)):
                if row_index_start == 0:
                    sheet_data[row_index_start][drop_frames_sum_1s_index] = headers[drop_frames_sum_1s_index]
                    continue
                # 当前时间戳开始往后的1s丢帧总数
                framesum_1s_currentRow = 0
                # 从下一行开始遍历，寻找进程1s内丢帧总数最大的值
                start_time = sheet_data[row_index_start][actual_ts_index]
                start_vsyncId = sheet_data[row_index_start][actual_vsyncId_index]
                end_time = start_time + 1000000000
                for row_index_current in range(row_index_start, len(sheet_data)):
                    cur_vsyncId = sheet_data[row_index_current][actual_vsyncId_index]
                    current_time = sheet_data[row_index_current][actual_ts_index]
                    current_frame = sheet_data[row_index_current][drop_frames_index]
                    if current_time <= end_time:
                        framesum_1s_currentRow += current_frame
                        # 所有数据中1s连续丢帧数总和为：framesum_1s_allRow， 当前数据1s丢帧数总和为framesum_1s_currentRow
                        # 判断当前行开始的1s丢帧数总和 为最大，则替换统计开始时间、结束时间 和1s丢帧数总和数
                        if framesum_1s_allRow < framesum_1s_currentRow:
                            framesum_1s_allRow = framesum_1s_currentRow
                            maxFrameSum_1s_pthread = [key, framesum_1s_allRow, start_vsyncId, cur_vsyncId]
                    else:
                        break
                sheet_data[row_index_start][drop_frames_sum_1s_index] = framesum_1s_currentRow
            # 计算进程连续丢帧数
            pthread_max_dropFrames = 0
            pthread_max_vsyncID = 0
            for row_index in range(len(sheet_data)):
                if row_index == 0:
                    continue
                else:
                    if pthread_max_dropFrames < sheet_data[row_index][drop_frames_index]:
                        pthread_max_dropFrames = sheet_data[row_index][drop_frames_index]
                        pthread_max_vsyncID = sheet_data[row_index][actual_vsyncId_index]

            maxFrameSum_1s.append(maxFrameSum_1s_pthread + [pthread_max_dropFrames, pthread_max_vsyncID])
    return maxFrameSum_1s


def filter_iq_info(not_iq_info_list, *maps):
    """
    过滤iq信息
    @param iq_info_list:
    @param map:
    @return:
    """
    for j in len(not_iq_info_list):
        if j == 0:
            continue
        notIq_start = not_iq_info_list[j][0]
        notIq_end = not_iq_info_list[j][-1]

        for sql_map in maps:
            start_pop_num = 2
            end_pop_num = 2
            for pthreadName in sql_map:
                for i in len(sql_map[pthreadName]):
                    if i == 0:
                        continue
                    actual_ts = ""
                    # 判断是第一行则continue
                    # 找到当前的时间戳，时间戳不在iq_info_list 范围内，直接过滤
                    if actual_ts >= notIq_start and actual_ts <= notIq_end:
                        pass

                # 时间戳在iq_info_list范围内，过滤到开始和结束的最后两帧
def logic_per_perfetto(trace_path,  spycify_filter_scroll, spycify_scroll_track_name=[''], specify_pthread=[], specify_use_google_tag = False):
    """
    1.每个perfetto 进行处理的逻辑
    2. specify_use_google_tag = False：默认使用大数据动画tag 处理逻辑 specify_use_google_tag = True
    3. specify_use_google_tag = True：默认使用google原生动画tag 处理逻辑
    4. 当识别到trace内没有大数据tag 时候，使用使用google原生动画tag 处理逻辑
    5.specify_pthread  传入并且不为空，则只统计传入进程的丢帧情况
    """
    # 初始化参数
    if not is_file_larger_than_1mb(trace_path):
        print(f"skip tiny trace (<100KB): {trace_path}")
        return

    # 初始化
    global trace, sql_result_map, Discard_info, Discard_reports, _use_google_tag, _all_scrolling_info, filter_scroll, scroll_track_name
    Discard_reports = False
    Discard_info = ""
    _all_scrolling_info = None
    # 初始化参数：如下参数皆开发给外界调用直接指定
    _use_google_tag = specify_use_google_tag
    filter_scroll =  spycify_filter_scroll
    scroll_track_name = spycify_scroll_track_name
    trace = trace_path
    sql_result_map = {}
    print(f"trace path:{trace_path}")
    result_path = os.path.join(f"{trace_path}_2026_0330_1448_按{filter_scroll}解析.xlsx")
    # 开始perfetto 解析的实际逻辑
    if os.path.exists(result_path):
        os.remove(result_path)
    before_analysis(trace)
    try:

        # 计算frameTime 相关数据（时间戳	时间	vsyncId	进程名	expected_dur	actual_dur	自动化丢帧数(actual_dur/expected_dur-1)	vsync类型(vsync_sf/vsync_app)）
        main_pthread()
        exe_frameTimeLine_sql(sf_sql, specify_pthread)
        exe_frameTimeLine_sql(other_sql, specify_pthread)
        # 计算iq 相关信息
        iq_info_list = exe_iq_sql()
        # 计算Vsync周期相关数据（vsync开始时间戳	vsync开始结束时间戳	vsync持续时间）
        vsync_app_list_raw = calculate_Vsync_ts(Vsync_app_sql)
        vsync_sf_list_raw = calculate_Vsync_ts(Vsync_sf_sql)
        fps_map = calculate_fps_sql()

        merge_All_info(sql_result_map, fps_map, vsync_sf_list_raw, vsync_app_list_raw)
        print("卡死检测")
        new_vsyncSF_list = split_vsync_sf(vsync_sf_list_raw, vsync_app_list_raw, fps_map)
        print("卡死检测")
        # 过滤iq 及iq前后两帧的数据，并在 add_bufferTx_info 中结合 FRTC / vsync 调整 bufferTX
        filter(sql_result_map, iq_info_list, new_vsyncSF_list, vsync_app_list_raw, vsync_sf_list_raw, fps_map)

        # 计算1s内总丢帧
        maxFrameSum_1s = calculate_1s_maxFrameSum(sql_result_map)
        result_info_sheetname, result_infolist = result_information(sql_result_map)
        write_excel_xlsx(result_path, result_info_sheetname, result_infolist)
        write_excel_xlsx(result_path, "1s内总丢帧", maxFrameSum_1s)
        # 写入excel
        for p_name in sql_result_map:
            write_excel_xlsx(result_path, p_name, sql_result_map.get(p_name, [[]]))

    except Exception as e:
        raise e
    finally:
        after_analysis()






def main_logic(perfettoPath):
    global trace
    global sql_result_map
    for root, dirs, files in os.walk(perfettoPath):
        for file in files:
            if not file.endswith(".perfetto-trace"):
                continue

            trace = os.path.join(root, file)
            logic_per_perfetto(trace,filter_scroll, scroll_track_name,specify_use_google_tag=False)
    kill_trace_processor_shell()


def result_information(sql_result_map):
    # 解析结果说明
    info_list = [
        ["各sheet页标记说明", "中度卡顿及以上标记红色"],
        ["统计的数值", "关注每个sheet页：AD（连续丢帧数）和AF（1s内总丢帧总数）列的值"],
        ["Perfetto-Trace自动解析丢帧方法说明",
         "https://odocs.myoas.com/docs/e1Az47mzRnfeGdqW/ 《Perfetto-Trace自动解析丢帧方法说明》"],
        ["丢帧标准",
         """
三方应用：
S（流畅）：
连续丢帧数：0
1S总丢帧数：0
A（轻微卡顿，无感知）：
连续丢帧数：[1,2)
1S总丢帧数：(1,4]
B（中度卡顿，敏感用户可感知）:
连续丢帧数：[2,4)
1S总丢帧数：(4,8]
C（严重卡顿，用户均可感知）:
连续丢帧数：[4,8]
1S总丢帧数：[9,12]
        """],

        ["丢帧标准",
         """
系统应用：
S（流畅）：
连续丢帧数：0
1S总丢帧数：0
A（轻微卡顿，无感知）：
连续丢帧数：[1,2)
1S总丢帧数：(1,4]
B（中度卡顿，敏感用户可感知）:
连续丢帧数：[2,4)
1S总丢帧数：(4,6]
C（严重卡顿，用户均可感知）:
连续丢帧数：[4,6]
1S总丢帧数：(6,8]
        """]
    ]
    return "解析结果说明", info_list


def exe_rv_scroll_sql():
    """
    查询 RV Scroll 相关信息
    @return: 字典，key 为 process_name，value 是二维列表，每个元素为 [ts, end, dur, name]
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
    
    rv_scroll_sql = """
    SELECT           
        slice.ts, 
        slice.dur,  
        slice.name,                 
        process.name as process_name,                 
        thread.name as thread_name  
    FROM slice  
    JOIN track ON slice.track_id = track.id  
    LEFT JOIN thread_track ON slice.track_id = thread_track.id  
    LEFT JOIN thread ON thread_track.utid = thread.utid  
    LEFT JOIN process ON thread.upid = process.upid  
    WHERE slice.name LIKE 'RV Scroll'  
    ORDER BY slice.ts
    """
    
    rv_scroll_map = {}
    all_rv_scroll_list = []  # 存储所有 RV Scroll 信息
    qr_it = tp_resource.query(rv_scroll_sql)
    
    for index, row in enumerate(qr_it, start=1):
        ts = row.ts
        dur = row.dur
        name = row.name
        process_name = row.process_name
        
        # 如果 process_name 为 None，使用空字符串作为 key
        if process_name is None:
            process_name = ""
        
        # 计算结束时间
        end = ts + dur if dur is not None and dur > 0 else ts
        
        # 构建 RV Scroll 信息项
        rv_item = [ts, end, name]
        
        # 初始化该进程的列表
        if process_name not in rv_scroll_map:
            rv_scroll_map[process_name] = []
        
        # 添加 [ts, end, dur, name] 到对应进程的列表中
        rv_scroll_map[process_name].append(rv_item)
        
        # 同时添加到所有 RV Scroll 列表中
        all_rv_scroll_list.append(rv_item)
    
    # 添加 surfaceflinger key，包含所有 RV Scroll 信息
    rv_scroll_map["surfaceflinger"] = all_rv_scroll_list
    
    return rv_scroll_map


def query_animator_slice(key_process = "gallery"):
    """
    查询所有进程的 animator slice
    @return: 字典，key 为进程名，value 是二维列表，每个元素为 [起始点, 结束点, 'animator']
    """
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))
    
    animator_sql = """
    SELECT           
    slice.ts, 
    slice.dur,  
    slice.name,                 
    COALESCE(process_from_thread.name, process_from_track.name) as process_name
FROM slice  
JOIN track ON slice.track_id = track.id  
LEFT JOIN thread_track ON slice.track_id = thread_track.id  
LEFT JOIN thread ON thread_track.utid = thread.utid  
LEFT JOIN process as process_from_thread ON thread.upid = process_from_thread.upid
LEFT JOIN process_track ON slice.track_id = process_track.id
LEFT JOIN process as process_from_track ON process_track.upid = process_from_track.upid
WHERE slice.name LIKE 'animator%'  
ORDER BY slice.ts
    """

    animator_map = {}
    qr_it = tp_resource.query(animator_sql)
    
    for index, row in enumerate(qr_it, start=1):
        ts = row.ts
        dur = row.dur
        process_name = row.process_name
        slice_name = row.name
        if key_process in process_name:
            key_process = process_name
        # 如果 process_name 为 None，使用空字符串作为 key
        if process_name is None:
            process_name = ""
        
        # 跳过无效的 dur
        if dur is None or dur == -1:
            continue
        
        # 计算结束时间
        end = ts + dur if dur > 0 else ts
        
        # 构建 animator 信息项：[起始点, 结束点, 'animator']
        animator_item = [ts, end, slice_name]
        
        # 初始化该进程的列表
        if process_name not in animator_map:
            animator_map[process_name] = []
        
        # 添加到对应进程的列表中
        animator_map[process_name].append(animator_item)
    print(animator_map)
    return animator_map.get(key_process, [])


def exe_scrollingSql(pthread_name):
    """
    执行sql 输出结果每行数据包含 ts， value。 fps持续时间为上下两行的时间差
    @return:
    """
    global scroll_track_name, Discard_reports, Discard_info
    if len(scroll_track_name[-1]) == 0:
        if filter_scroll == '0':
            scroll_track_name_list = ["window_animation: GESTURE_TO_HOME", "window_animation: MENU_TO_RECENTS",
                                      "window_animation: GESTURE_TO_RECENTS", "window_animation:   GESTURE_TO_NEW_TASK",
                                      "window_animation: LAUNCH_APP", "animator:translationX,translationY",
                                      "menu_window_animation: MENU_BACK_TO_HOME", "window_animation: LIGHT_LAUNCH_APP",
                                      "light_menu_window_animation: LIGHT_MENU_BACK_TO_HOME", "light_window_animation: LIGHT_LAUNCH_APP",
                                      "menu_window_animation: LIGHT_MENU_BACK_TO_HOME", "appSceneType_2",
                                      "window_animation: GESTURE_TO_CLIENT_HOME"]
            # 上滑退出到桌面、应用上滑进入多任务、应用点击进入多任务、导航手势切换应用、打开收起图片/视频、应用启动、图片点击弹出分享、点击home键返回桌面
        else:
            scroll_track_name_list = ["window_animation: GESTURE_TO_HOME",
                                      "window_animation: GESTURE_TO_RECENTS", "window_animation: GESTURE_TO_NEW_TASK",
                                      "view_animation: DRAG_WORKSPACE", "view_animation: DRAG_ALL_APPS",
                                      "menu_window_animation: MENU_BACK_TO_HOME", "window_animation: LIGHT_LAUNCH_APP",
                                      "menu_window_animation: LIGHT_MENU_BACK_TO_HOME",
                                      "light_menu_window_animation: LIGHT_MENU_BACK_TO_HOME",
                                      "light_window_animation: LIGHT_LAUNCH_APP",
                                      "appSceneType_2",
                                      "slideScene_listview_slide", "slideScene_video_slide", "Scroll","Fling",
                                      "CaptureEnter", "ScrollProcess", "window_animation: GESTURE_TO_CLIENT_HOME",
                                      "Scrolling", "ScrollingWhenMove"]
            # 离屏滑动、视频界面滑动、按压滑动、滑动（MTK埋点）、滑动（友商埋点）、上滑退出到桌面、应用上滑进入多任务、应用点击进入多任务、按压滑动多任务卡片、按压慢滑桌面、桌面调出抽屉过程
    else:
        scroll_track_name_list = scroll_track_name

    scrolling_list = [["scrolling_start", "scrolling_end", "scrolling_otherInfo"]]
    for scrolling_type in scroll_track_name_list:
        if "surfaceflinger" in pthread_name:
            # surfaceflinger统计所有动画区间的丢帧
            slide_scene_sql = f"select ts, dur,  track.name from slice join track on slice.track_id = track.id  where track.name like '{scrolling_type}' order by ts"
        else:
            slide_scene_sql = \
                f""" SELECT slice.ts as ts,slice.dur as dur, slice.name as name, process.name as process_name
        FROM slice
        JOIN process_track  ON slice.track_id = process_track.id
        JOIN process USING (upid)
        WHERE slice.name LIKE '{scrolling_type}' and process.name='{pthread_name}'  order by ts"""

        qr_it = tp_resource.query(slide_scene_sql)
        for index, row in enumerate(qr_it, start=1):
            start_ts = row.ts
            dur = row.dur
            scroll_type = row.name
            if dur == -1:
                continue
            if dur <= 1000000000 / 120:
                continue
            scrolling_list.append([start_ts, start_ts + dur, row.name])
    if (len(scroll_track_name[-1]) != 0 and len(scrolling_list) > 1) or len(scroll_track_name[-1]) == 0:
        Discard_reports = False
        Discard_info = ""
    # 系统应用埋点和通用埋点有重叠部分，只取系统应用埋点; 有通用埋点，无系统应用埋点，取通用埋点
    scrolling_list = merge_system_Universal_tracking(scroll_track_name_list, scrolling_list)
    return scrolling_list


def merge_system_Universal_tracking(scroll_track_name_list, scroll_list):
    """
    按照优先级顺序合并滚动事件，高优先级重叠时只保留高优先级时间段
    优先级顺序：window_animation > view_animation > menu_window_animation > appSceneType > slideScene > Scroll/Fling/Scrolling > CaptureEnter/ScrollProcess
    """
    # 按优先级排序的事件类型列表
    priority_events = scroll_track_name_list

    # 按优先级分组事件
    priority_groups = {}
    for scroll_item in scroll_list[1:len(scroll_list)]:
        scroll_type = scroll_item[-1]
        if scroll_type in priority_events:
            priority = priority_events.index(scroll_type)
            if priority not in priority_groups:
                priority_groups[priority] = []
            priority_groups[priority].append(scroll_item)

    # 按优先级从高到低处理事件
    final_list = []

    for priority in sorted(priority_groups.keys()):
        current_priority_items = priority_groups[priority]

        # 检查与已选高优先级事件的重叠
        for item in current_priority_items:
            has_overlap = False
            for selected_item in final_list:
                if has_Overlapping_section(item, selected_item):
                    has_overlap = True
                    break

            # 如果没有重叠，添加到最终列表
            if not has_overlap:
                final_list.append(item)
    final_list.insert(0, scroll_list[0])
    return final_list


def has_Overlapping_section(list1, list2):
    # 判断两个列表是否有重叠部分
    start1 = list1[0]
    end1 = list1[1]
    start2 = list2[0]
    end2 = list2[1]

    if (start1 > start2 and start1 < end2) or (end1 > start2 and end1 < end2):
        return True
    if (start2 > start1 and start2 < end1) or (end2 > start1 and end2 < end1):
        return True
    return False


def exe_do_frame(pthread_name):
    """
    1.执行sql 获取进程的doFrame 信息
    """

    doFrame_sql = f"""
        SELECT slice.ts,slice.dur, slice.name, process.name as process_name, thread.name as thread_name
        FROM slice
    	JOIN thread_track ON slice.track_id = thread_track.id
    	JOIN thread USING (utid)
    	JOIN process USING (upid)
        WHERE slice.name LIKE '%Choreographer#doFrame %' and slice.name not like '%-%' and process.name='{pthread_name}'  order by ts
        """
    qr_it = tp_resource.query(doFrame_sql)
    doFrame_orderDcit = collections.OrderedDict()
    memory_leak_count = 0
    global Discarad_limit, Discard_reports, Discard_info
    for index, row in enumerate(qr_it, start=1):
        name = row.name
        vsync_id = name.split(" ")[-1]
        start_ts = row.ts
        dur = row.dur
        # 某帧内存泄漏，后续的帧都不处理
        if dur == -1:
            memory_leak_count += 1
        # 只在没有检测到泄漏前，才记录 doFrame 信息
        else:
            thread_name = row.thread_name
            doFrame_orderDcit[vsync_id] = ([int(start_ts), int(dur), name, thread_name, vsync_id])
    # doFrame 泄漏次数过多时，整份 trace 认为不可信
    if memory_leak_count > Discarad_limit:
        Discard_reports = True
        Discard_info = "trace 内 doFrame slice 泄漏超过阈值"
    # 标题[doframe开始时间， doFrame 持续时间，slice名字，线程名字， syncId]
    return doFrame_orderDcit


def exe_draw_frame(pthread_name):
    """
    1.执行sql 获取进程的drawFrame 信息
    """
    drawFrame_sql = f"""
    SELECT slice.ts,slice.dur, slice.name,process.name as process_name, thread.name as thread_name
    FROM slice
	JOIN thread_track ON slice.track_id = thread_track.id
	JOIN thread USING (utid)
	JOIN process USING (upid)
    WHERE slice.name LIKE 'DrawFrames%' and process.name='{pthread_name}' and thread.name like 'RenderThread'  order by ts
    """
    qr_it = tp_resource.query(drawFrame_sql)
    if len(qr_it) == 0:
        drawFrame_sql = f"""
            SELECT slice.ts,slice.dur, slice.name,process.name as process_name, thread.name as thread_name
            FROM slice
        	JOIN thread_track ON slice.track_id = thread_track.id
        	JOIN thread USING (utid)
        	JOIN process USING (upid)
            WHERE slice.name LIKE 'DrawFrames%' and process.name='{pthread_name}' order by ts
            """
        qr_it = tp_resource.query(drawFrame_sql)
        if len(qr_it) == 0:
            print(f"{pthread_name} 没有绘帧（renderThread 或者thread 进程）")
    drawFrame_orderDcit = collections.OrderedDict()
    memory_leak_count = 0
    global Discarad_limit, Discard_reports, Discard_info
    for index, row in enumerate(qr_it, start=1):
        name = row.name
        vsync_id = name.split(" ")[-1]
        start_ts = row.ts
        dur = row.dur
        # drawFrame 泄漏（dur == -1），后续帧都认为不可信
        if dur == -1:
            memory_leak_count += 1
        # 只在没有检测到泄漏前，才记录 drawFrame 信息
        else:
            thread_name = row.thread_name
            drawFrame_orderDcit[vsync_id] = ([int(start_ts), int(dur), name, thread_name, vsync_id])

    # drawFrame 泄漏次数过多时，整份 trace 认为不可信
    if memory_leak_count > Discarad_limit:
        Discard_reports = True
        # 如果之前 doFrame 已经写过 Discard_info，这里不覆盖，只在为空时写 drawFrame 信息
        Discard_info += "trace 内 drawFrame slice 泄漏超过阈值"

    # 标题[drawframe开始时间， drawFrame 持续时间，slice名字，vsyncId]
    return drawFrame_orderDcit


def do_drawFrame_time_sum(doFrame_orderDcit, drawFrame_orderDcit, pthread):
    """
    计算doFrame 和DrawFrame 的时间和
    """
    #  返回 OrderedDict，key 为 doFrame_vsyncID，value 为 [doFrame_threadName, doFrame_vsyncID, drawFrame_vsyncId, doFrame_start, drawFrame_end, do_draw_timesum]
    do_drawFrame_sum_dict = collections.OrderedDict()
    drawFrame_list = list(drawFrame_orderDcit.values())
    start_drawIndex = 0

    for doFrame_vsyncID, doFrame_info in doFrame_orderDcit.items():
        doFrame_start = doFrame_info[0]
        doFrame_threadName = doFrame_info[3]
        # vsyncId 一致的do、drawFrame直接存入信息
        if doFrame_vsyncID in drawFrame_orderDcit:

            drawFrame_info = drawFrame_orderDcit.get(doFrame_vsyncID)
            drawFrame_end = drawFrame_info[0] + drawFrame_info[1]
            do_drawFrame_sum_dict[doFrame_vsyncID] = [doFrame_threadName, doFrame_vsyncID, doFrame_vsyncID,
                                          # doFrame 开始时间
                                          doFrame_start,
                                          # drawFrame结束时间
                                          drawFrame_end,
                                          # do+drawFrame_time
                                          drawFrame_end - doFrame_start
                                          ]
        else:
            # 部分子线程（例如launch.anim） 只有doframe 没有drawframe
            if doFrame_threadName in thread_without_drawFrame:
                doFrame_dur = doFrame_info[1]
                do_drawFrame_sum_dict[doFrame_vsyncID] = [doFrame_threadName, doFrame_vsyncID, -1,
                                              # doFrame 开始时间
                                              doFrame_start,
                                              #  doFrame 结束时间
                                              doFrame_start + doFrame_dur,
                                              # do+drawFrame_time
                                              doFrame_dur
                                              ]
            else:

                # 非launcher 进程 doFrame 找不到对应的drawFrame,找到doFrame时间向后找最近一个drawFrame
                doFrame_ts = doFrame_info[0]
                drawFrame_vsyncId = -1
                for index in range(start_drawIndex, len(drawFrame_list)):
                    drawFrame_ts = drawFrame_list[index][0]
                    if drawFrame_ts < doFrame_ts:
                        continue
                    if drawFrame_ts > doFrame_ts:
                        start_drawIndex = index
                        drawFrame_vsyncId = drawFrame_list[index][-1]
                        break
                    # 判断doFrame后最近一个drawFrame 是否有对应的doFrame， 有则只存入doFrame的信息
                if drawFrame_vsyncId in doFrame_orderDcit or drawFrame_vsyncId == -1:

                    doFrame_dur = doFrame_info[1]
                    do_drawFrame_sum_dict[doFrame_vsyncID] = [doFrame_threadName, doFrame_vsyncID, -1,
                                                  # doFrame 开始时间
                                                  doFrame_start,
                                                  #  doFrame 结束时间
                                                  doFrame_start + doFrame_dur,
                                                  # do+drawFrame_time
                                                  doFrame_dur
                                                  ]
                else:

                    # 判断doFrame后最近一个drawFrame 是否有对应的doFrame， 没有则只存入doFrame和DrawFrame的信息
                    drawFrame_start = drawFrame_orderDcit.get(drawFrame_vsyncId)[0]
                    drawFrame_end = drawFrame_start + drawFrame_orderDcit.get(drawFrame_vsyncId)[1]
                    do_drawFrame_sum_dict[doFrame_vsyncID] = [doFrame_threadName,
                                                  doFrame_vsyncID, drawFrame_vsyncId,
                                                  # doFrame 开始时间
                                                  doFrame_start,
                                                  #  drawFrame 结束时间
                                                  drawFrame_end,
                                                  # do+drawFrame_time
                                                  drawFrame_end - doFrame_start
                                                  ]
    # 返回 OrderedDict，key 为 doFrame_vsyncID，value 为 [doframe线程名， doframeVysncId, drawFrameVsyncId, doFrame开始时间, drawFrame结束时间, do+drawFrame时间和]
    return do_drawFrame_sum_dict


def query_composite_info():
    """
    使用 SQL 读取 surfaceflinger 进程的 composite 信息
    @return: composite 列表，每个元素为 [id, ts, dur, name, process_name, thread_name, tid, track_name, depth, parent_id]
    """
    composite_sql = """
    SELECT      
        slice.id,     
        slice.ts,     
        slice.dur,     
        slice.name,     
        process.name as process_name,     
        thread.name as thread_name,     
        thread.tid,     
        track.name as track_name,    
        slice.depth,     
        slice.parent_id 
    FROM slice 
    LEFT JOIN thread_track ON slice.track_id = thread_track.id 
    LEFT JOIN thread ON thread_track.utid = thread.utid 
    LEFT JOIN process ON thread.upid = process.upid 
    LEFT JOIN track ON slice.track_id = track.id 
    WHERE      
        process.name = '/system/bin/surfaceflinger'     
        AND (         
            slice.name LIKE 'composite%'          
            OR slice.name LIKE 'Composite%'        
        ) 
    ORDER BY slice.ts
    """
    qr_it = tp_resource.query(composite_sql)
    composite_list = []
    for row in qr_it:
        composite_list.append([
            row.id,
            row.ts,
            row.dur,
            row.name,
            row.process_name,
            row.thread_name,
            row.tid,
            row.track_name,
            row.depth,
            row.parent_id
        ])
    return composite_list


def extract_vsync_id_from_composite_name(composite_name):
    """
    从 composite 名称中提取 vsyncId
    @param composite_name: composite 的名称
    @return: vsyncId 字符串，如果无法提取则返回 None
    """
    try:
        # composite 名称格式可能是 "composite <vsyncId>" 或 "Composite <vsyncId>"
        parts = composite_name.split()
        if len(parts) > 1:
            return parts[-1]
    except:
        pass
    return None


def filter_overlapping_composites(composite_list):
    """
    过滤重叠的 composite，只保留 ts 最小的 composite
    @param composite_list: composite 列表，每个元素为 [id, ts, dur, name, ...]
    @return: 过滤后的 composite 列表和打印的重叠 composite 信息
    """
    if not composite_list:
        return [], []
    
    # 按 ts 排序
    sorted_composites = sorted(composite_list, key=lambda x: x[1])  # x[1] 是 ts
    
    filtered_list = []
    removed_composites = []
    
    i = 0
    while i < len(sorted_composites):
        current = sorted_composites[i]
        current_ts = current[1]
        current_end = current_ts + current[2]  # ts + dur
        
        # 检查后续是否有重叠的 composite
        # 重叠定义：两个 composite 的时间范围有交集
        j = i + 1
        while j < len(sorted_composites):
            next_comp = sorted_composites[j]
            next_ts = next_comp[1]
            next_end = next_ts + next_comp[2]
            
            # 检查是否重叠：两个区间有交集
            # 重叠条件：next_ts < current_end 且 next_end > current_ts
            if next_ts < current_end and next_end > current_ts:
                # 重叠，移除后续的 composite（保留 ts 最小的，即当前的）
                removed_composites.append(next_comp)
                j += 1
            else:
                # 不重叠，停止检查
                break
        
        # 保留当前的 composite（ts 最小）
        filtered_list.append(current)
        
        # 跳过所有被移除的重叠 composite
        i = j if j > i + 1 else i + 1
    
    # 打印被移除的重叠 composite
    if removed_composites:
        print("以下 composite 因重叠被移除（保留 ts 最小的）:")
        for comp in removed_composites:
            print(f"  Composite ID: {comp[0]}, ts: {comp[1]}, dur: {comp[2]}, name: {comp[3]}")
    
    return filtered_list, removed_composites


def match_composite_with_frametimeline(sheet_info, composite_list, frametimeline_vsync_ids):
    """
    匹配 composite 和 FrameTimeLine
    @param sheet_info: FrameTimeLine 数据（sheet_info）
    @param composite_list: 过滤后的 composite 列表
    @param frametimeline_vsync_ids: 所有 FrameTimeLine 的 vsyncId 集合
    @return: 匹配结果字典 {frametimeline_index: composite_info} 和未匹配的 composite 列表
    """
    # 创建 composite 的 vsyncId 映射（通过名称提取）
    composite_vsync_map = {}  # {vsync_id: [composite_info]}
    composite_time_map = []  # [(ts, end_ts, composite_info)] 用于时间窗口匹配
    
    for comp in composite_list:
        vsync_id = extract_vsync_id_from_composite_name(comp[3])  # comp[3] 是 name
        comp_ts = comp[1]
        comp_end = comp_ts + comp[2]
        
        if vsync_id:
            if vsync_id not in composite_vsync_map:
                composite_vsync_map[vsync_id] = []
            composite_vsync_map[vsync_id].append(comp)
        
        composite_time_map.append((comp_ts, comp_end, comp))
    
    # 按时间排序，便于时间窗口查找
    composite_time_map.sort(key=lambda x: x[0])
    
    # 匹配结果
    match_result = {}  # {frametimeline_index: composite_info}
    used_composites = set()  # 已使用的 composite 索引
    
    # 遍历 FrameTimeLine
    for idx in range(1, len(sheet_info)):  # 跳过标题行
        line_info = sheet_info[idx]
        frametimeline_vsync_id = str(line_info[actual_vsyncId_index])
        frametimeline_ts = line_info[actual_ts_index]
        
        matched_composite = None
        
        # 方法1: 通过 vsyncId 精确匹配
        if frametimeline_vsync_id in composite_vsync_map:
            for comp in composite_vsync_map[frametimeline_vsync_id]:
                comp_idx = composite_list.index(comp)
                if comp_idx not in used_composites:
                    matched_composite = comp
                    used_composites.add(comp_idx)
                    break
        
        # 方法2: 如果精确匹配失败，在 actual_ts 前后 5ms 内查找
        if matched_composite is None:
            time_window_ns = 5000000  # 5ms = 5000000ns
            search_start = frametimeline_ts - time_window_ns
            search_end = frametimeline_ts + time_window_ns
            
            for comp_ts, comp_end, comp in composite_time_map:
                comp_idx = composite_list.index(comp)
                # 检查 composite 是否在时间窗口内，且未使用，且不与任何 FrameTimeLine 的 vsyncID 一致
                comp_vsync_id = extract_vsync_id_from_composite_name(comp[3])
                if (comp_ts >= search_start and comp_ts <= search_end and 
                    comp_idx not in used_composites and
                    (comp_vsync_id is None or comp_vsync_id not in frametimeline_vsync_ids)):
                    matched_composite = comp
                    used_composites.add(comp_idx)
                    break
        
        if matched_composite:
            match_result[idx] = matched_composite
    
    # 找出未匹配的 composite
    unmatched_composites = [comp for i, comp in enumerate(composite_list) if i not in used_composites]
    
    return match_result, unmatched_composites


def calculate_composite_duration(sheet_info, composite_map):
    """
    计算前后 composite 差值，代替 actual_ts 差值填入表格
    只对有 composite 的行计算，跳过无对应 composite 的 FrameTimeLine
    @param sheet_info: FrameTimeLine 数据
    @param composite_map: 行索引到 composite_info 的映射字典 {row_index: composite_info}
    """
    # 获取所有有 composite 的行索引，按索引排序
    composite_indices = sorted([idx for idx in composite_map.keys() if idx > 0 and idx < len(sheet_info)])
    
    if len(composite_indices) < 2:
        return
    
    # 计算相邻两帧的 composite 差值
    # 注意：composite_map 中只包含有 composite 的行（包括匹配的和插入的 orphan composite）
    # 无对应 composite 的 FrameTimeLine 不在 composite_map 中，所以会被自动跳过
    for i in range(len(composite_indices) - 1):
        current_idx = composite_indices[i]
        next_idx = composite_indices[i + 1]
        
        # 检查当前行是否标记为无对应 composite 的 FrameTimeLine（不应该作为起点）
        # 注意：插入的 orphan composite 有 "无对应FrameTimeLine的composite" 标记，可以作为结束点
        current_remark = sheet_info[current_idx][vsync_check_info_index] if current_idx < len(sheet_info) else ""
        if current_remark and "有frameTimeLine无对应composite" in str(current_remark):
            # 如果当前行是 FrameTimeLine 但无对应 composite，不应该在 composite_map 中
            # 但如果出现了，说明逻辑有问题，跳过它
            continue
        
        current_comp = composite_map[current_idx]
        next_comp = composite_map[next_idx]
        
        # composite 的起点是 ts，终点是 ts + dur
        current_comp_ts = current_comp[1]
        cur_comp_name = current_comp[3] if len(current_comp) > 3 else ""
        next_comp_ts = next_comp[1]
        next_comp_name = next_comp[3] if len(next_comp) > 3 else ""

        # 计算差值（使用下一个 composite 的 ts 减去当前 composite 的 ts）
        composite_duration = next_comp_ts - current_comp_ts

        # 填入 do_draw_dur_index（出帧时长）
        # 注意：插入的 orphan composite 的 do_draw_dur_index 应该保持为 None（不计算差值）
        # 只有匹配的 FrameTimeLine 才计算差值
        if current_idx < len(sheet_info):
            # 检查是否是插入的 orphan composite
            sheet_info[current_idx][actual_ts_index] = current_comp_ts
            if current_remark and "有composite无对应的FrameTimeLine" in str(current_remark):
                # 插入的 orphan composite 不计算差值，但可以作为结束点
                sheet_info[current_idx][do_draw_dur_index] = 0
            else:
                # 匹配的 FrameTimeLine，计算差值
                sheet_info[current_idx][do_draw_dur_index] = composite_duration
                
                # 将 composite 信息追加到备注列
                composite_info_str = f"composite时间差:开始={current_comp_ts},composite时间差={composite_duration},end={next_comp_ts}, cur_name = {cur_comp_name},next_name={next_comp_name}"
                current_remark = sheet_info[current_idx][vsync_check_info_index]
                if current_remark is None or current_remark == "":
                    sheet_info[current_idx][vsync_check_info_index] = composite_info_str
                else:
                    sheet_info[current_idx][vsync_check_info_index] = current_remark + " " + composite_info_str


def insert_orphan_composite_to_sheet(sheet_info, composite_info, insert_position=None):
    """
    将无对应 FrameTimeLine 的 composite 插入到 sheet 中
    @param sheet_info: FrameTimeLine 数据
    @param composite_info: composite 信息
    @param insert_position: 插入位置（如果为 None，则插入到合适的位置）
    @return: 插入的行索引和 composite 信息（用于后续计算差值）
    """
    comp_ts = composite_info[1]
    comp_dur = composite_info[2]
    comp_name = composite_info[3]
    comp_end = comp_ts + comp_dur
    
    # 创建新行（复制标题行的结构）
    new_row = [None] * len(sheet_info[0])
    
    # 填充基本信息
    new_row[actual_ts_index] = comp_ts
    new_row[actual_vsyncId_index] = extract_vsync_id_from_composite_name(comp_name) or "无对应FrameTimeLine"
    new_row[vsync_check_info_index] = f"有composite无对应的FrameTimeLine:ts={comp_ts},dur={comp_dur},end={comp_end},name={comp_name}"
    new_row[actual_dur_index] = comp_dur
    new_row[do_draw_dur_index] = comp_dur  # 不计算该帧的前后 composite 差值，但可以作为结束点
    
    # 确定插入位置
    if insert_position is None:
        # 找到第一个 ts 大于当前 composite ts 的位置
        insert_pos = 1  # 从第一行数据开始（跳过标题行）
        for i in range(1, len(sheet_info)):
            row_ts = sheet_info[i][actual_ts_index]
            if row_ts is not None and row_ts > comp_ts:
                insert_pos = i
                break
        else:
            insert_pos = len(sheet_info)
    else:
        insert_pos = insert_position
    
    # 插入新行
    sheet_info.insert(insert_pos, new_row)
    return insert_pos, composite_info


def handle_orphan_frametimelines(sheet_info, match_result):
    """
    处理无对应 composite 的 FrameTimeLine
    不计算该帧的丢帧，也不作为某帧计算的起点和终点
    @param sheet_info: FrameTimeLine 数据
    @param match_result: 匹配结果字典
    """
    for idx in range(1, len(sheet_info)):
        if idx not in match_result:
            # 检查是否是插入的 orphan composite（这些行有特殊标记）
            current_remark = sheet_info[idx][vsync_check_info_index]
            if current_remark and "有composite无对应的FrameTimeLine" in str(current_remark):
                # 这是插入的 orphan composite，不是 FrameTimeLine，跳过
                continue
            
            # 标记该 FrameTimeLine 无对应的 composite
            remark_text = "有frameTimeLine无对应composite"
            if current_remark is None or current_remark == "":
                sheet_info[idx][vsync_check_info_index] = remark_text
            else:
                sheet_info[idx][vsync_check_info_index] = current_remark + " " + remark_text
            # 不计算丢帧，将 do_draw_dur_index 设为 None（表示不计算）
            # 这样在计算差值时会被跳过
            sheet_info[idx][do_draw_dur_index] = 0


def merge_surfaceflinger_composite(sheet_info):
    """
    针对 surfaceflinger 进程处理 FrameTimeLine 和 composite 的匹配
    @param sheet_info: FrameTimeLine 数据（sheet_info）
    """
    # 0. 设置标题
    sheet_info[0][do_draw_dur_index] = "两次composite时间差"
    sheet_info[0][drop_frames_byFps_index] = "丢帧数(两次composite时间差/fps-1)"
    sheet_info[0][vsync_check_info_index] = "备注信息"
    # sheet_info[0][drop_frames_byExpected_index] = "丢帧数(actual_dur/expected_dur-1)"
    
    # 1. 读取 composite 信息
    composite_list = query_composite_info()
    if not composite_list:
        print("未找到 surfaceflinger 的 composite 信息")
        return
    
    # 2. 过滤重叠的 composite
    filtered_composites, removed_composites = filter_overlapping_composites(composite_list)
    
    # 3. 先获取所有 FrameTimeLine 的 vsyncId 集合（用于后续匹配）
    frametimeline_vsync_ids = set()
    for idx in range(1, len(sheet_info)):
        vsync_id = str(sheet_info[idx][actual_vsyncId_index])
        if vsync_id:
            frametimeline_vsync_ids.add(vsync_id)
    
    # 4. 先进行初步匹配，找出无对应 FrameTimeLine 的 composite（用于插入）
    # 这里只用于找出哪些 composite 需要插入，不用于最终匹配
    _, unmatched_composites = match_composite_with_frametimeline(
        sheet_info, filtered_composites, frametimeline_vsync_ids
    )
    
    # 5. 先插入无对应 FrameTimeLine 的 composite（在匹配之前插入，避免索引变化）
    # 按时间顺序插入，以便后续计算时能正确找到前后 composite
    unmatched_composites_sorted = sorted(unmatched_composites, key=lambda x: x[1])  # 按 ts 排序
    inserted_composite_map = {}  # {row_index: composite_info} 记录插入的 composite
    
    for comp in unmatched_composites_sorted:
        insert_pos, comp_info = insert_orphan_composite_to_sheet(sheet_info, comp)
        inserted_composite_map[insert_pos] = comp_info
    
    # 6. 插入 orphan composite 后，重新获取所有 FrameTimeLine 的 vsyncId 集合（包括插入的行）
    frametimeline_vsync_ids_updated = set()
    for idx in range(1, len(sheet_info)):
        vsync_id = str(sheet_info[idx][actual_vsyncId_index])
        if vsync_id:
            frametimeline_vsync_ids_updated.add(vsync_id)
    
    # 7. 在插入 orphan composite 之后，重新匹配 composite 和 FrameTimeLine
    match_result, _ = match_composite_with_frametimeline(
        sheet_info, filtered_composites, frametimeline_vsync_ids_updated
    )
    
    # 8. 处理无对应 composite 的 FrameTimeLine（在插入 orphan composite 之后处理）
    handle_orphan_frametimelines(sheet_info, match_result)
    
    # 9. 构建完整的 composite 映射（包括匹配的和插入的）
    all_composite_map = match_result.copy()
    all_composite_map.update(inserted_composite_map)
    
    # 10. 计算前后 composite 差值（包括插入的 composite 作为结束点）
    # 只对有 composite 的行计算，跳过无对应 composite 的 FrameTimeLine
    calculate_composite_duration(sheet_info, all_composite_map)
    
    # 11. 计算 actual_dur/expected_dur-1（用于后续计算 min 值）
    # for idx in range(1, len(sheet_info)):
    #     line_info = sheet_info[idx]
    #     actual_dur = line_info[actual_dur_index]
    #     expected_dur = line_info[expected_dur_index]
    #
    #     # 跳过无对应 composite 的 FrameTimeLine（已经在 handle_orphan_frametimelines 中处理）
    #     if line_info[do_draw_dur_index] == 0 and "有frameTimeLine无对应composite" in str(line_info[vsync_check_info_index] or ""):
    #         sheet_info[idx][drop_frames_byExpected_index] = 0
    #         continue
    #     # 计算 actual_dur/expected_dur-1
    #     if actual_dur and expected_dur and expected_dur > 0:
    #
    #         drop_frames_by_expected = actual_dur / expected_dur - 1
    #         drop_frames_by_expected = 0 if drop_frames_by_expected < 0 else drop_frames_by_expected
    #         sheet_info[idx][drop_frames_byExpected_index] = drop_frames_by_expected
    #     else:
    #         sheet_info[idx][drop_frames_byExpected_index] = None


def surfaceflinger_Format_adaption(sheetInfo):
    """
    保留原有方法作为备用，但主要使用 merge_surfaceflinger_composite
    """
    merge_surfaceflinger_composite(sheetInfo)


# def surfaceflinger_Format_adaption(sheetInfo):
#     """
#     surfaceflinger 没有doFrame 和dropFrame 进行格式自适应
#     """
#     sheetInfo[0][do_draw_dur_index], sheetInfo[0][vsync_check_info_index], sheetInfo[0][drop_frames_byExpected_index] = [ "actual_ts差值", "备注信息", "丢帧数(出帧时长/expected_dur-1)"]
#
#     for index in range(1, len(sheetInfo)):
#         line_info = sheetInfo[index]
#         cur_vsync_id = line_info[actual_vsyncId_index]
#         cur_actual_ts = line_info[actual_ts_index]
#
#         next_actual_ts = -1
#
#         # 针对其余行，将actual_dur 变更为两个actual_ts 之间的时间差
#         for next_index in range(index+1, len(sheetInfo)):
#             next_vsync_id = sheetInfo[next_index][actual_vsyncId_index]
#             if next_vsync_id!=cur_vsync_id:
#                 next_actual_ts = sheetInfo[next_index][actual_ts_index]
#                 break
#         if next_actual_ts == -1:
#             drop_frame_by_actual_dur = line_info[do_draw_dur_index] / line_info[expected_dur_index] - 1
#             line_info[do_draw_dur_index] = line_info[actual_dur_index]
#             line_info[drop_frames_byExpected_index] = drop_frame_by_actual_dur
#             line_info[vsync_check_info_index] = "出帧时长:actual_dur"
#         else:
#
#             try:
#                 drop_frame_by_actual_dur = line_info[do_draw_dur_index]/line_info[expected_dur_index]-1
#             except:
#                 print("demo")
#             fps_time = line_info[do_draw_dur_index][fps_index]
#             if fps_time is None or fps_time == -1:
#                 fps_time = line_info[do_draw_dur_index][vsync_dur_index]
#
#             drop_frame_by_actualTS_diff = (next_actual_ts - cur_actual_ts)/fps_time -1
#
#
#             # sf 统计min（actual/expected-1， 两帧耗时/fps-1）
#
#             if drop_frame_by_actualTS_diff < drop_frame_by_actual_dur:
#                 line_info[do_draw_dur_index] = next_actual_ts - cur_actual_ts
#                 line_info[drop_frames_byExpected_index] = drop_frame_by_actualTS_diff
#                 line_info[vsync_check_info_index] = "出帧时长:actual_ts差值"
#             else:
#                 line_info[do_draw_dur_index] = line_info[actual_dur_index]
#                 line_info[drop_frames_byExpected_index] = drop_frame_by_actual_dur
#                 line_info[vsync_check_info_index] = "出帧时长:actual_dur"
#
#         line_info[drop_frames_byExpected_index] = line_info[do_draw_dur_index]/line_info[expected_dur_index]-1
#         line_info[drop_frames_byExpected_index] = 0 if line_info[drop_frames_byExpected_index] < 0 else line_info[drop_frames_byExpected_index]


def rt_not_useful(start, end, rt_list):
    """
    start, end 范围内存在有效rt插帧的个数

    start, end 范围内不存在rt丢帧：
    返回空字符串

    """
    not_useful_rt_count = 0
    find_rt = False
    for item in rt_list:
        rt_start = item[0]
        useful = item[2]
        if rt_start >= start and rt_start <= end:
            find_rt = True
            if not useful:
                not_useful_rt_count += 1

        if rt_start > end:
            break
    if find_rt:
        # 存在rt插帧，返回无效插帧数
        return not_useful_rt_count
    else:
        # 不存在rt插帧，返回字符串
        return "无rt插帧"


def is_main_thread(pthreadname, threadname):
    if threadname in main_thread_map[pthreadname]:
        return True

    if (pthreadname.split(".")[-1] in threadname) or "fpsHandleTask" in threadname or "main" in threadname:
        return True

    return False


def merge_do_drawFrameInfo(pthreadName, sheet_info, do_drawFrame_dict):
    """
    增加所有do+drawFrame_time 信息
    """

    line_index = 1
    # 存储没有frameTimeLine 对应的doframe 信息
    doframe_without_frameTimeLine = collections.OrderedDict()
    # 遍历所有doFrame 信息, 找到actualFrameTimeLine 对应的doFrame+drawFrame数据
    for doFrame_vsyncId, do_drawFrame_line in do_drawFrame_dict.items():
        doframe_threadName = do_drawFrame_line[0]
        # doFrame_vsyncId 可以从 key 获取，也可以从 value[1] 获取（保持原有结构）

        doFrame_ts = do_drawFrame_line[3]  # 保持原有索引：doFrame_start 在索引3
        find_vsync = False
        # 找vsyncId 一致的actual
        for index in range(line_index, len(sheet_info)):
            timeLine_Lineinfo = sheet_info[index]
            timeLine_vsyncId = timeLine_Lineinfo[actual_vsyncId_index]
            if str(doFrame_vsyncId) == str(timeLine_vsyncId):
                line_index = index
                find_vsync = True
                break
        if not find_vsync:
            for index in range(line_index, len(sheet_info)):
                timeLine_Lineinfo = sheet_info[index]
                actual_start = timeLine_Lineinfo[actual_ts_index]
                actual_vsyncId = timeLine_Lineinfo[actual_vsyncId_index]
                if str(actual_vsyncId) in do_drawFrame_dict.keys():
                    continue
                # 找到（actual起点，actual终点）的第一个doFrame
                # 兼容doframe 比actualFrameTime 时间戳大大概3us的情况
                if actual_start - 1000000 <= doFrame_ts and actual_start + 1000000 >= doFrame_ts:
                    find_vsync = True
                    line_index = index
                    #  兼容存在actualFrameTime  和doframe 小于200ms的情况，找离doframe最近的一个
                    ts_diff = abs(actual_start - doFrame_ts)
                    for index2 in range(index + 1, len(sheet_info)):
                        actual_start = sheet_info[index2][0]
                        if actual_start - 1000000 <= doFrame_ts and actual_start + 1000000 >= doFrame_ts:
                            if ts_diff > abs(actual_start - doFrame_ts):
                                line_index = index2
                                ts_diff = abs(actual_start - doFrame_ts)
                        else:
                            break

                    break
                if actual_start > doFrame_ts:
                    break

        # 有actualTimeLine 也有doFrame 信息，则增加do+drawFrame 信息
        drawFrame_vsyncId = do_drawFrame_line[2]  # 保持原有索引：drawFrame_vsyncId 在索引2
        do_draw_timesum = do_drawFrame_line[-1]  # 最后一个元素

        if find_vsync:
            if str(doFrame_vsyncId) not in  str(sheet_info[line_index][actual_vsyncId_index]):
                print(f"lineIndex 异常数据：doFrame_vsyncId:{doFrame_vsyncId}  timeline vsyncId:{sheet_info[line_index][actual_vsyncId_index]}")
            sheet_info[line_index][thread_name_index] = doframe_threadName
            # launcher 只有doframe 没有drawframe， 故只统计doframe, 其余线程必须保证doframe和drawFrame 都有,并且为主线程
            if (doframe_threadName in thread_without_drawFrame) or \
                    (doframe_threadName not in thread_without_drawFrame and len(
                        str(drawFrame_vsyncId)) != 0 and is_main_thread(pthreadName, doframe_threadName)):
                sheet_info[line_index][thread_name_index] = doframe_threadName
                sheet_info[line_index][actual_ts_index] = doFrame_ts
                sheet_info[line_index][do_draw_dur_index] = do_draw_timesum
                sheet_info[line_index][
                    vsync_check_info_index] = f"出帧时长: doframe+drawFrame时间 doFrameVsyncID:{doFrame_vsyncId}   drawFrame_vsyncId:{drawFrame_vsyncId}"
        else:
            # 针对没有对应frameTimeLine的doframe 信息，存储对应的相关信息
            if  line_index in doframe_without_frameTimeLine:
                doframe_without_frameTimeLine[line_index].append(doFrame_vsyncId)
            else:
                doframe_without_frameTimeLine[line_index] = [doFrame_vsyncId]
    # 针对没有对应frameTimeLine的doframe 信息，按需插入表格
    # 逆序拆入效率最高
    doframe_without_frameTimeLine = OrderedDict(reversed(list(doframe_without_frameTimeLine.items())))
    for index, doframeVsyncId_list in doframe_without_frameTimeLine.items():
        # 同一个插入位置的数据，vsync从大到小排序
        doframeVsyncId_list = sorted([
            int(vsync_id) for vsync_id in doframeVsyncId_list
            if str(vsync_id).strip().isdigit() or (isinstance(vsync_id, (int, float)))
        ], reverse=True)

        for doFrame_vsyncId in doframeVsyncId_list:
            do_drawFrame_line = do_drawFrame_dict.get(str(doFrame_vsyncId))
            # 构造相关信息插入sheetinfo 中
            doframe_threadName = do_drawFrame_line[0]
            drawFrame_vsyncId = do_drawFrame_line[2]
            doFrame_ts = do_drawFrame_line[3]
            do_draw_timesum = do_drawFrame_line[-1]
            if doframe_threadName not in thread_without_frameTimeLine:
                continue
            new_index = index
            for cur_index in range(index, len(sheet_info)):
                cur_index_ts = sheet_info[cur_index][actual_ts_index]
                if cur_index_ts >= doFrame_ts:
                    new_index = cur_index
                    break

            sheet_info.insert(new_index, [None] * len(headers))
            # 补充actualTimeLine相关信息
            sheet_info[new_index][actual_ts_index],sheet_info[index][actual_time_index], \
                sheet_info[new_index][actual_vsyncId_index], sheet_info[index][pthread_name_index], \
                sheet_info[new_index][expected_dur_index], sheet_info[index][
                actual_dur_index] = doFrame_ts, datetime.fromtimestamp(int(doFrame_ts / 1000000000)), doFrame_vsyncId, pthreadName, "", ""
            #更新doframe相关信息
            sheet_info[new_index][thread_name_index] = doframe_threadName
            sheet_info[new_index][do_draw_dur_index] = do_draw_timesum
            sheet_info[new_index][vsync_check_info_index] = f"出帧时长: doframe+drawFrame时间 doFrameVsyncID:{doFrame_vsyncId}   drawFrame_vsyncId:{drawFrame_vsyncId}， 没有frameTimeLine对应"

        # 其余情况不计算丢帧
    sheet_info[0][thread_name_index], sheet_info[0][do_draw_dur_index], sheet_info[0][vsync_check_info_index], \
    sheet_info[0][drop_frames_byExpected_index] = headers[thread_name_index], headers[do_draw_dur_index], headers[
        vsync_check_info_index], headers[drop_frames_byExpected_index]
    for index in range(1, len(sheet_info)):
        line_info = sheet_info[index]
        vsync_check_info = line_info[vsync_check_info_index]
        if vsync_check_info is None or "出帧时长" not  in str(vsync_check_info):
            line_info[do_draw_dur_index] = 0
            line_info[vsync_check_info_index] = f"不统计该帧"
            line_info[drop_frames_byExpected_index] = 0
            if not isinstance(line_info[thread_name_index], str) or len(line_info[thread_name_index])==0:
                line_info[thread_name_index] = ""
        else:
            if (isinstance(line_info[expected_dur_index], float) or isinstance(line_info[expected_dur_index], int)) and \
                (isinstance(line_info[actual_dur_index], float) or isinstance(line_info[actual_dur_index], int)):
                line_info[drop_frames_byExpected_index] = line_info[actual_dur_index] / line_info[expected_dur_index] - 1
                line_info[drop_frames_byExpected_index] = 0 if line_info[drop_frames_byExpected_index] < 0 else line_info[
                    drop_frames_byExpected_index]


def query_main_thread_slices(pthread_name):
    """
    查询主进程的所有slice数据
    @param pthread_name: 进程名
    @return: 所有slice数据列表，每个元素为[ts, dur, name, thread_name]
    """
    main_thread_allInfo_sql = f"""
      SELECT slice.ts,slice.dur, slice.name, process.name as process_name, thread.name as thread_name
        FROM slice
    	JOIN thread_track ON slice.track_id = thread_track.id
    	JOIN thread USING (utid)
    	JOIN process USING (upid)
        WHERE  process.name='{pthread_name}'   and thread.is_main_thread =1 order by ts
    """
    qr_it = tp_resource.query(main_thread_allInfo_sql)

    all_slices = []
    for index, row in enumerate(qr_it, start=1):
        all_slices.append([row.ts, row.dur, row.name, row.thread_name])

    return all_slices


def extract_doframes_from_slices(all_slices):
    """
    从slice列表中提取所有doframe
    @param all_slices: 所有slice数据列表
    @return: doframe列表，每个元素为[ts, dur, name, thread_name, vsync_id]
    """
    doframe_list = []
    for slice_item in all_slices:
        slice_name = slice_item[2]
        if 'Choreographer#doFrame' in slice_name:
            # 从name中提取vsyncID，格式通常是 "Choreographer#doFrame <vsyncID>"
            vsync_id = slice_name.split(" ")[1]
            try:
                vsync_id_int = int(vsync_id)
            except:
                print(f"extract_doframes_from_slices 异常，请查看{slice_name}是否为doframe")
                continue

            doframe_list.append([slice_item[0], slice_item[1], slice_name, slice_item[3], vsync_id])
    return doframe_list


def filter_slices_not_overlapping_doframe(all_slices, doframe_list):
    """
    过滤slice：只保留doframe，以及时间不和doframe重合的slice数据
    @param all_slices: 所有slice数据列表
    @param doframe_list: doframe列表
    @return: 过滤后的slice列表
    """
    filtered_slices = []
    for slice_item in all_slices:
        slice_ts = slice_item[0]
        slice_dur = slice_item[1]
        slice_end = slice_ts + slice_dur
        slice_name = slice_item[2]

        # 保留所有doframe
        if 'Choreographer#doFrame' in slice_name:
            filtered_slices.append(slice_item)
        else:
            # 检查是否与任何doframe重合
            overlaps_with_doframe = False
            for doframe_item in doframe_list:
                doframe_ts = doframe_item[0]
                doframe_dur = doframe_item[1]
                doframe_end = doframe_ts + doframe_dur

                # 判断时间是否重合：slice与doframe有重叠
                if not (slice_end <= doframe_ts or slice_ts >= doframe_end):
                    overlaps_with_doframe = True
                    break

            # 如果不重合，则保留
            if not overlaps_with_doframe:
                filtered_slices.append(slice_item)

    return filtered_slices


def find_sheet_indices_by_vsync_id(sheet, doframe1_vsync_id, doframe2_vsync_id):
    """
    通过vsyncID查找sheet中对应的行索引
    @param sheet: sheet数据
    @param doframe1_vsync_id: 第一个doframe的vsyncID
    @param doframe2_vsync_id: 第二个doframe的vsyncID
    @return: (doframe1_sheet_index, doframe2_sheet_index) 或 (None, None) 如果找不到
    """
    doframe1_sheet_index = None
    doframe2_sheet_index = None

    for sheet_idx in range(1, len(sheet)):
        sheet_vsync_id = sheet[sheet_idx][actual_vsyncId_index]

        # 通过vsyncID匹配
        if doframe1_vsync_id is not None and str(sheet_vsync_id) == str(doframe1_vsync_id):
            doframe1_sheet_index = sheet_idx
        if doframe2_vsync_id is not None and str(sheet_vsync_id) == str(doframe2_vsync_id):
            doframe2_sheet_index = sheet_idx

    if doframe1_sheet_index is not None and doframe2_sheet_index is not None:
        return doframe1_sheet_index, doframe2_sheet_index
    # 针对doframe vsyncID 和actual vsyncID不一致的情况
    for sheet_idx in range(1, len(sheet)):
        vsync_info = sheet[sheet_idx][vsync_check_info_index]
        # 通过vsyncID匹配
        if doframe1_vsync_id is not None and str(doframe1_vsync_id) in vsync_info:
            doframe1_sheet_index = sheet_idx
        if doframe2_vsync_id is not None and str(doframe2_vsync_id) in vsync_info:
            doframe2_sheet_index = sheet_idx

    return doframe1_sheet_index, doframe2_sheet_index


def calculate_max_fps(sheet, doframe1_sheet_index, doframe2_sheet_index):
    """
    计算两个帧之间的最大fps
    @param sheet: sheet数据
    @param doframe1_sheet_index: 第一个doframe在sheet中的索引
    @param doframe2_sheet_index: 第二个doframe在sheet中的索引
    @return: 最大fps值
    """
    cur_fps = sheet[doframe1_sheet_index][fps_index]
    cur_vsync = sheet[doframe1_sheet_index][vsync_dur_index]
    next_fps = sheet[doframe2_sheet_index][fps_index]
    next_vsync = sheet[doframe2_sheet_index][vsync_dur_index]

    # fps为空时，vsync作为刷新率
    if cur_fps is not None and next_fps is not None:
        try:
            return max(cur_fps, next_fps)
        except Exception as e:
            print(f"{cur_fps}  {next_fps}")
            raise e
    else:
        return max(cur_vsync, next_vsync)


def find_interval_slices(filtered_slices, doframe1_end, doframe2_start):
    """
    查找两个doframe之间的slice数据（不包括doframe本身）
    @param filtered_slices: 过滤后的slice列表
    @param doframe1_end: 第一个doframe的结束时间
    @param doframe2_start: 第二个doframe的开始时间
    @return: 区间内的slice列表
    """
    # 先收集区间内的所有 slice（不包括 doframe 本身）
    interval_slices = []
    for slice_item in filtered_slices:
        slice_ts = slice_item[0]
        slice_dur = slice_item[1]
        slice_end = slice_ts + slice_dur
        slice_name = slice_item[2]

        # 排除doframe本身
        if 'Choreographer#doFrame' in slice_name:
            continue

        # 检查slice是否在区间内（不与doframe重合）
        if slice_ts >= doframe1_end and slice_end <= doframe2_start:
            interval_slices.append(slice_item)

    # 仅保留“第一层”slice：在时间轴上不互相重叠的一组（从左到右贪心选择）
    interval_slices_sorted = sorted(interval_slices, key=lambda s: s[0])
    first_layer = []
    current_end = None
    for s in interval_slices_sorted:
        start = s[0]
        end = s[0] + s[1]
        if current_end is None or start >= current_end:
            first_layer.append(s)
            current_end = end

    return first_layer


def find_interval_rt_list(rt_list, doframe1_end, doframe2_start):
    """
    查找两个doframe之间的rt插帧
    @param rt_list: rt插帧列表
    @param doframe1_end: 第一个doframe的结束时间
    @param doframe2_start: 第二个doframe的开始时间
    @return: 区间内的rt插帧列表
    """
    interval_rt_list = []
    for rt_item in rt_list:
        rt_start = rt_item[0]
        rt_end = rt_item[1]

        # 检查rt插帧是否在区间内
        if rt_start >= doframe1_end and rt_end <= doframe2_start:
            interval_rt_list.append(rt_item)

    return interval_rt_list


def insert_row_for_long_interval(sheet, doframe1_sheet_index, doframe2_sheet_index, doframe1_end, interval, max_fps, slice_name_info, total_slice_dur):
    """
    插入长间隔行（无rt插帧情况）
    @param sheet: sheet数据
    @param doframe1_sheet_index: 第一个doframe在sheet中的索引
    @param doframe1_end: 第一个doframe的结束时间
    @param interval: 时间间隔
    @param max_fps: 最大fps
    @param slice_name_info: slice名称信息
    """

    insert_index = doframe1_sheet_index + 1
    pre_vsyncId = sheet[doframe1_sheet_index][actual_vsyncId_index]
    next_vsyncId = sheet[doframe2_sheet_index][actual_vsyncId_index]
    sheet.insert(insert_index, [""] * len(headers))
    sheet[insert_index][actual_ts_index] = doframe1_end
    sheet[insert_index][do_draw_dur_index] = interval
    sheet[insert_index][pthread_name_index] = sheet[doframe1_sheet_index][pthread_name_index]
    sheet[insert_index][thread_name_index] = sheet[doframe1_sheet_index][thread_name_index]
    sheet[insert_index][fps_index] = max_fps
    sheet[insert_index][vsync_dur_index] = max_fps
    sheet[insert_index][drop_frames_byFps_index] = total_slice_dur / max_fps - 1
    sheet[insert_index][drop_frames_byVsync_index] = total_slice_dur / max_fps - 1
    sheet[insert_index][vsync_check_info_index] += f"前后两帧时间差超过fps时间 {slice_name_info}（时间总和：{total_slice_dur}）阻塞出帧"
    sheet[insert_index][actual_vsyncId_index] = f"{pre_vsyncId} 与 {next_vsyncId} 两帧之间时间间隔长"


def split_intervals_by_rt(sorted_rt_list, doframe1_end, doframe2_start, interval_slices, max_fps,
                          doframe1_sheet_index, doframe2_sheet_index, sheet, doframe2):
    """
    按rt插帧分割区间，生成需要插入的行信息
    将doframe和rt插帧都当作时间节点，统一处理它们之间的区间，复用相同的判断逻辑

    @param sorted_rt_list: 排序后的rt插帧列表，每个元素为[rt_start, rt_end, useful, value, name]
    @param doframe1_end: 第一个doframe的结束时间
    @param doframe2_start: 第二个doframe的开始时间
    @param interval_slices: 区间内的slice列表
    @param max_fps: 最大fps
    @param doframe1_sheet_index: 第一个doframe在sheet中的索引
    @param doframe2_sheet_index: 第二个doframe在sheet中的索引
    @param sheet: sheet数据
    @param doframe2: 第二个doframe信息
    @return: 需要插入的行信息列表，每个元素为[insert_index, actual_ts, do_draw_dur, slice_name_info, part_info]
    """
    insert_rows = []

    # 构建时间节点列表：将doframe和rt插帧都当作节点
    # 每个节点为 (时间戳, 节点类型, 节点信息)
    # 节点类型: 'doframe1_end', 'rt_start', 'rt_end', 'doframe2_start'
    time_nodes = []

    # 添加第一个doframe结束节点
    time_nodes.append((doframe1_end, 'doframe1_end', {'sheet_index': doframe1_sheet_index + 1}))

    # 添加所有rt插帧的开始和结束节点
    for rt_idx, rt_item in enumerate(sorted_rt_list):
        rt_start = rt_item[0]
        rt_end = rt_item[1]
        time_nodes.append((rt_start, 'rt_start', {'rt_index': rt_idx + 1}))
        time_nodes.append((rt_end, 'rt_end', {'rt_index': rt_idx + 1}))

    # 添加第二个doframe开始节点
    time_nodes.append((doframe2_start, 'doframe2_start', {'sheet_index': None}))  # 稍后查找

    # 按时间戳排序
    time_nodes.sort(key=lambda x: x[0])

    # 查找doframe2的sheet索引（用于最后一个区间）
    doframe2_sheet_index_current = None
    doframe2_vsync_id = doframe2[4]
    for sheet_idx in range(1, len(sheet)):
        sheet_vsync_id = sheet[sheet_idx][actual_vsyncId_index]
        if doframe2_vsync_id is not None and str(sheet_vsync_id) == str(doframe2_vsync_id):
            doframe2_sheet_index_current = sheet_idx
            break

    # 更新doframe2_start节点的sheet_index
    for i, (ts, node_type, node_info) in enumerate(time_nodes):
        if node_type == 'doframe2_start':
            time_nodes[i] = (ts, node_type, {'sheet_index': doframe2_sheet_index_current})
            break

    # 遍历相邻节点之间的区间，统一处理逻辑
    # 用于跟踪中间区间插入的位置偏移（因为中间区间依次插入doframe1_end之后）
    middle_interval_offset = 0

    for i in range(len(time_nodes) - 1):
        start_node = time_nodes[i]
        end_node = time_nodes[i + 1]

        interval_start_ts = start_node[0]
        interval_end_ts = end_node[0]
        interval_duration = interval_end_ts - interval_start_ts

        # 跳过rt插帧内部的区间（rt_start到rt_end之间）
        if start_node[1] == 'rt_start' and end_node[1] == 'rt_end':
            continue

        # 统计该子区间内 slice 的“可视时长”：考虑与子区间的重叠部分
        interval_slices_in_range = []
        total_slice_dur = 0
        for s in interval_slices:
            slice_start = s[0]
            slice_end = s[0] + s[1]
            # 与子区间求交集
            overlap_start = max(slice_start, interval_start_ts)
            overlap_end = min(slice_end, interval_end_ts)
            if overlap_end <= overlap_start:
                continue  # 无重叠
            partial_dur = overlap_end - overlap_start
            total_slice_dur += partial_dur
            interval_slices_in_range.append(s)

        # 如果没有任何 slice 与该子区间有重叠，跳过
        if len(interval_slices_in_range) == 0:
            continue

        # 判断该子区间内「所有 slice 可见时长之和」是否大于 max_fps，只有大于时才认为是长间隔
        if total_slice_dur <= max_fps:
            continue

        # 使用该子区间第一层所有 slice 的名称拼接为 slice_name_info
        names = [s[2] for s in interval_slices_in_range]
        slice_name_info = " | ".join(names) if names else "未知slice"

        # 插入位置直接按 doframe1_sheet_index 之后依次递增
        insert_index = doframe1_sheet_index + 1 + middle_interval_offset
        middle_interval_offset += 1

        # 文本信息仍区分区间类型，方便排查
        if start_node[1] == 'doframe1_end':
            part_info = "rt插帧分割第一部分"
        elif end_node[1] == 'doframe2_start':
            part_info = "rt插帧分割最后部分"
        else:
            # 中间区间：rt插帧之间的区间（rt_end 到 rt_start）
            prev_rt_idx = start_node[2].get('rt_index', 0) if start_node[1] == 'rt_end' else 0
            next_rt_idx = end_node[2].get('rt_index', 0) if end_node[1] == 'rt_start' else 0
            if prev_rt_idx > 0 and next_rt_idx > 0:
                part_info = f"rt插帧分割中间部分(第{prev_rt_idx}和{next_rt_idx}个rt插帧之间)"
            else:
                part_info = "rt插帧分割中间部分"

        insert_rows.append([insert_index, interval_start_ts, interval_duration, slice_name_info, part_info, total_slice_dur])

    return insert_rows


def calculate_middle_interval_insert_index(sheet, doframe1_sheet_index, actual_ts, doframe2_sheet_index_current,
                                           doframe2):
    """
    计算中间区间的插入位置
    @param sheet: sheet数据
    @param doframe1_sheet_index: 第一个doframe在sheet中的索引
    @param actual_ts: 要插入的时间戳
    @param doframe2_sheet_index_current: doframe2的当前sheet索引
    @param doframe2: 第二个doframe信息
    @return: 插入位置索引
    """
    # 先重新查找doframe2的当前位置（因为之前的插入可能已经改变了索引）
    doframe2_current_pos = None
    if doframe2_sheet_index_current is not None:
        doframe2_vsync_id = doframe2[4]
        for sheet_idx in range(1, len(sheet)):
            if not frame_is_useful(sheet[sheet_idx]):
                continue
            sheet_vsync_id = sheet[sheet_idx][actual_vsyncId_index]
            if doframe2_vsync_id is not None and str(sheet_vsync_id) == str(doframe2_vsync_id):
                doframe2_current_pos = sheet_idx
                break

    insert_idx = doframe1_sheet_index + 1
    # 找到actual_ts应该插入的位置（按时间顺序，在doframe1之后，doframe2之前）
    end_pos = doframe2_current_pos if doframe2_current_pos is not None else len(sheet)
    for existing_idx in range(doframe1_sheet_index + 1, end_pos):
        existing_ts = sheet[existing_idx][actual_ts_index]
        if existing_ts is not None and existing_ts != "":
            # 如果找到时间戳大于actual_ts的行，插入到它之前
            if existing_ts > actual_ts:
                insert_idx = existing_idx
                break

    return insert_idx


def insert_rows_for_rt_split_intervals(sheet, insert_rows, doframe1_sheet_index, doframe2_sheet_index_current, doframe2,
                                       max_fps):
    """
    插入rt分割后的区间行
    @param sheet: sheet数据
    @param insert_rows: 需要插入的行信息列表
    @param doframe1_sheet_index: 第一个doframe在sheet中的索引
    @param doframe2_sheet_index_current: doframe2的当前sheet索引
    @param doframe2: 第二个doframe信息
    @param max_fps: 最大fps值
    """
    # 分离中间区间和其他区间
    middle_rows = []  # 中间区间，按时间顺序依次插入doframe1_end之后
    other_rows = []  # 第一个区间和最后一个区间，从后往前插入

    for row_info in insert_rows:
        insert_idx, actual_ts, do_draw_dur, slice_name_info, part_info ,total_slice_dur= row_info
        if "中间部分" in part_info:
            middle_rows.append(row_info)
        else:
            other_rows.append(row_info)

    # 先按时间顺序插入中间区间（依次插入doframe1_end之后）
    middle_rows_sorted = sorted(middle_rows, key=lambda x: x[1])  # 按时间戳从小到大排序
    for row_info in middle_rows_sorted:
        insert_idx, actual_ts, do_draw_dur, slice_name_info, part_info, total_slice_dur = row_info
        # 中间区间的insert_index已经在split_intervals_by_rt中设置好了，但由于之前的插入，需要动态调整
        # 重新计算：找到doframe1_end之后，按时间顺序应该插入的位置
        current_insert_idx = doframe1_sheet_index + 1
        for existing_idx in range(doframe1_sheet_index + 1, len(sheet)):
            existing_ts = sheet[existing_idx][actual_ts_index]
            if existing_ts is not None and existing_ts != "":
                if existing_ts > actual_ts:
                    current_insert_idx = existing_idx
                    break
            # 如果到达doframe2，停止查找
            if doframe2_sheet_index_current is not None and existing_idx >= doframe2_sheet_index_current:
                break

        sheet.insert(current_insert_idx, [""] * len(headers))
        sheet[current_insert_idx][actual_ts_index] = actual_ts
        sheet[current_insert_idx][do_draw_dur_index] = do_draw_dur
        sheet[current_insert_idx][pthread_name_index] = sheet[doframe1_sheet_index][pthread_name_index]
        sheet[current_insert_idx][thread_name_index] = sheet[doframe1_sheet_index][thread_name_index]
        sheet[current_insert_idx][do_draw_dur_index] = do_draw_dur
        sheet[current_insert_idx][fps_index] = max_fps
        sheet[current_insert_idx][vsync_dur_index] = max_fps
        sheet[current_insert_idx][drop_frames_byFps_index] = total_slice_dur / max_fps - 1
        sheet[current_insert_idx][drop_frames_byVsync_index] = total_slice_dur / max_fps - 1
        sheet[current_insert_idx][
            vsync_check_info_index] += f"前后两帧时间差超过fps时间({part_info}) {slice_name_info}(时长总和{total_slice_dur})阻塞出帧"
        sheet[current_insert_idx][
            actual_vsyncId_index] += f"{slice_name_info}阻塞出帧"


    # 然后从后往前插入其他区间（第一个区间和最后一个区间），避免索引变化影响
    other_rows_sorted = sorted(other_rows, key=lambda x: x[1], reverse=True)  # 按时间戳从大到小排序
    for row_info in other_rows_sorted:
        insert_idx, actual_ts, do_draw_dur, slice_name_info, part_info, total_slice_dur = row_info

        # 如果插入位置是doframe2_sheet_index_current，需要重新查找doframe2的位置
        # 因为之前的插入可能已经改变了索引
        if doframe2_sheet_index_current is not None and insert_idx is not None and insert_idx >= doframe2_sheet_index_current:
            # 重新查找doframe2的位置
            doframe2_vsync_id = doframe2[4]
            for sheet_idx in range(1, len(sheet)):
                if not frame_is_useful(sheet[sheet_idx]):
                    continue
                sheet_vsync_id = sheet[sheet_idx][actual_vsyncId_index]
                if doframe2_vsync_id is not None and str(sheet_vsync_id) == str(doframe2_vsync_id):
                    insert_idx = sheet_idx
                    break

        if insert_idx is not None:
            sheet.insert(insert_idx, [""] * len(headers))
            sheet[insert_idx][actual_ts_index] = actual_ts
            sheet[insert_idx][do_draw_dur_index] = do_draw_dur
            sheet[insert_idx][pthread_name_index] = sheet[doframe1_sheet_index][pthread_name_index]
            sheet[insert_idx][thread_name_index] = sheet[doframe1_sheet_index][thread_name_index]
            sheet[insert_idx][fps_index] = max_fps
            sheet[insert_idx][vsync_dur_index] = max_fps
            sheet[insert_idx][drop_frames_byFps_index] = total_slice_dur / max_fps - 1
            sheet[insert_idx][drop_frames_byVsync_index] = total_slice_dur / max_fps - 1
            sheet[insert_idx][
                vsync_check_info_index] += f"前后两帧时间差超过fps时间({part_info}) {slice_name_info}(时长总和{total_slice_dur})阻塞出帧"
            sheet[insert_idx][actual_vsyncId_index] += f"{slice_name_info}阻塞出帧"


def handle_longInterval_between_frame(frameTimeLine_Map):
    """
    处理帧之间时间过长：使用SQL查询主进程的所有slice，查询结果只保留doframe，以及时间不和doframe重合的slice数据。
    判断两次doframe之间的时间大于max_fps并且这中间有slice数据，并且中间无rt插帧，则插入该行。
    如果中间有rt插帧，则rt插帧把两次doframe时间分割成多个区间，每部分判断是否大于max_fps，以及中间是否有slice数据。
    """
    for pthread, sheet in frameTimeLine_Map.items():
        if "surfaceflinger" in pthread:
            continue

        # 查询主进程的所有slice
        all_slices = query_main_thread_slices(pthread)

        # 提取所有doframe
        doframe_list = extract_doframes_from_slices(all_slices)

        # 如果没有至少两个doframe，则跳过
        if len(doframe_list) < 2:
            continue

        # 获取rt插帧信息
        rt_list = exe_rt(pthread)  # [rt_start, rt_end, useful, value, name]

        # 过滤slice：只保留doframe，以及时间不和doframe重合的slice数据
        filtered_slices = filter_slices_not_overlapping_doframe(all_slices, doframe_list)

        # 遍历每对相邻的doframe
        for i in range(len(doframe_list) - 1):
            doframe1 = doframe_list[i]
            doframe2 = doframe_list[i + 1]

            doframe1_end = doframe1[0] + doframe1[1]  # 第一个doframe的结束时间
            doframe2_start = doframe2[0]  # 第二个doframe的开始时间

            # 计算时间间隔
            interval = doframe2_start - doframe1_end

            # 通过vsyncID查找与doframe对应的sheet行
            doframe1_vsync_id = doframe1[4]
            doframe2_vsync_id = doframe2[4]
            doframe1_sheet_index, doframe2_sheet_index = find_sheet_indices_by_vsync_id(
                sheet, doframe1_vsync_id, doframe2_vsync_id)

            # 如果找不到对应的sheet行，跳过
            if doframe1_sheet_index is None or doframe2_sheet_index is None:
                continue

            # 计算最大fps
            max_fps = calculate_max_fps(sheet, doframe1_sheet_index, doframe2_sheet_index)

            # 查找该区间内的slice数据（不包括doframe本身）
            interval_slices = find_interval_slices(filtered_slices, doframe1_end, doframe2_start)

            # 如果没有slice数据，跳过
            if len(interval_slices) == 0:
                continue

            # 判断「区间内所有 slice_dur 之和」是否大于 max_fps，只有大于时才继续后续计算
            total_slice_dur = sum(s[1] for s in interval_slices)
            if total_slice_dur <= max_fps:
                continue

            # 查找该区间内的rt插帧
            interval_rt_list = find_interval_rt_list(rt_list, doframe1_end, doframe2_start)

            # 如果没有rt插帧，直接插入一行
            if len(interval_rt_list) == 0:
                # 使用第一层所有 slice 的名称拼接为 slice_name_info
                if interval_slices:
                    names = [s[2] for s in interval_slices]
                    slice_name_info = " | ".join(names)
                else:
                    slice_name_info = "未知slice"
                insert_row_for_long_interval(sheet, doframe1_sheet_index,doframe2_sheet_index,  doframe1_end, interval, max_fps,
                                             slice_name_info, total_slice_dur)
            else:
                # 有rt插帧，将时间按照所有rt插帧分割成多个区间
                sorted_rt_list = sorted(interval_rt_list, key=lambda x: x[0])
                # 生成需要插入的行信息
                insert_rows = split_intervals_by_rt(sorted_rt_list, doframe1_end, doframe2_start, interval_slices,
                                                    max_fps, doframe1_sheet_index, doframe2_sheet_index, sheet,
                                                    doframe2)

                # 获取doframe2的当前sheet索引（用于插入时重新查找）
                doframe2_sheet_index_current = None
                doframe2_vsync_id = doframe2[4]
                for sheet_idx in range(1, len(sheet)):
                    if not frame_is_useful(sheet[sheet_idx]):
                        continue
                    sheet_vsync_id = sheet[sheet_idx][actual_vsyncId_index]
                    if doframe2_vsync_id is not None and str(sheet_vsync_id) == str(doframe2_vsync_id):
                        doframe2_sheet_index_current = sheet_idx
                        break

                # 插入rt分割后的区间行
                insert_rows_for_rt_split_intervals(sheet, insert_rows, doframe1_sheet_index,
                                                   doframe2_sheet_index_current, doframe2, max_fps)


def top_app():
    sql = "select * from __query_slice_track__long_battery_tracing_Top_app"
    qr_it = tp_resource.query(sql)
    # 往每个sheet页里面填写 "时间戳", "时间", "vsyncId", "进程名", "expected_dur", "actual_dur", 相关数据
    # 获取坐标
    vsync_id_list = []
    for index, row in enumerate(qr_it):
        print(row)


def is_file_larger_than_1mb(file_path):
    # 原阈值 1MB 会跳过短时长抓取；改为约 100KB，过小仍跳过空/损坏文件
    file_size_bytes = os.path.getsize(file_path)
    return file_size_bytes >= 100 * 1024


def surfaceflinger_drop_checck(vsync_check_info):
    """
    检测surfaceflinger 是否丢帧：判断逻辑
    1.on time finish 为0
    2. surfaceflinger 的jank type 为 SurfaceFlingerCpuDeadlineMissed， SurfaceFlingerGpuDeadlineMissed，DisplayHAL， PredictionError
    """
    if "on_time_finish=0" in  vsync_check_info:
        if "surfaceflingercpudeadlinemissed" in vsync_check_info.replace(" ", "").lower():
            return True
        if "surfaceflingergpudeadlinemissed" in  vsync_check_info.replace(" ", "").lower():
            return True
        if "displayhal" in  vsync_check_info.replace(" ", "").lower():
            return True
        if "predictionerror" in vsync_check_info.replace(" ", "").lower() :
            return True
    return False


def main_pthread():
    """
    获取这份trace内所有的主线程

    """
    global main_thread_map
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))

    main_thread_map = {}
    qr_it = tp_resource.query(main_thread_sql)
    for index, row in enumerate(qr_it, start=1):
        pthread_name = row.pthread_name
        thread_name = row.thread_name
        pid = row.pid
        main_thread_or_not = row.is_main_thread
        if main_thread_or_not:
            main_thread_map[pthread_name] = [thread_name, pid]
    return main_thread_map


if __name__ == '__main__':
    perfettoPath = input("输入perfetto所在文件夹路径:")
    filter_scroll_handleCheck = input("\n是否只计算滑动期间的丢帧\n"
                                      "（操作是滑动或切换(上下左右滑动操作)，输入1\n"
                                      "操作是点击（包括弹出弹框或跳转）（不关注滑动场景）， 输入0\n"
                                      "默认 无动画场景, 直接回车:")
    # 1 操作是滑动或切换(上下左右滑动操作)，输入1
    # 0 操作是点击（包括弹出弹框或跳转）（不关注滑动场景）， 输入0
    # 默认 无动画场景

    filter_scroll = filter_scroll_handleCheck.strip()
    if filter_scroll == '0' or filter_scroll == '1':
        scroll_track_name = input("\n输入trace中判断滑动的关键字，有多个关键字请用英文','分隔"
                                  "；提示如果不设定任何字段，直接回车:").split(",")
    if isinstance(scroll_track_name, str):
        scroll_track_name = ['']

    # perfettoPath = r"D:\Users\80378622\Downloads\新建文件夹\新建文件夹"
    # filter_scroll = '1'
    # scroll_track_name = ['']
    print(f"start:{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

    main_logic(perfettoPath)
    print(f"end:{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))}")

