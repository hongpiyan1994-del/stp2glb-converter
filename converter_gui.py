"""
STP → GLB 转换工具
主程序：DearPyGUI 交互界面 + Blender subprocess 封装
"""
import os
import sys
import subprocess
import threading
import re
import json
import time
import struct
from pathlib import Path

# ─── 启动调试日志（写文件，方便排查崩溃原因） ───
def log(msg):
    log_path = os.path.join(os.path.dirname(sys.argv[0] if getattr(sys, 'frozen', False) else __file__), "startup.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except:
        pass

log("Startup: " + " ".join(sys.argv))

# ─── 全局配置 ───
VERSION = "1.0.0"
SUPPORTED_EXTENSIONS = [".stp", ".step", ".STP", ".STEP"]

# ─── Blender 路径检测 ───
def get_blender_path():
    """从多个位置找 blender.exe"""
    search_paths = []
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
        search_paths += [
            base / "blender" / "blender.exe",
            base / "blender.exe",
            Path(sys.argv[0]).parent / "blender" / "blender.exe",
            Path(sys.argv[0]).parent / "blender.exe",
        ]
    else:
        base = Path(__file__).parent
        search_paths += [
            base / "blender" / "blender.exe",
            base / "blender.exe",
        ]

    search_paths += [
        Path(os.environ.get("BLENDER_PATH", "")),
        Path(os.environ.get("ProgramFiles"), "Blender*", "blender.exe"),
    ]

    for p in search_paths:
        if p.exists():
            log("Blender found at: " + str(p))
            return str(p)

    log("Blender NOT found in any search path")
    return ""


def check_blender():
    """验证 Blender 是否可用"""
    blender_path = get_blender_path()
    if not blender_path:
        return False, "未找到 blender.exe，请确认已放置于工具目录或 PATH 中"
    try:
        result = subprocess.run(
            [blender_path, "--version"],
            capture_output=True,
            text=True,
            timeout=15
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split('\n')[0]
            return True, version_line
        return False, "Blender 返回非零退出码"
    except FileNotFoundError:
        return False, "blender.exe 未找到（路径: " + blender_path + "）"
    except Exception as e:
        return False, "启动 Blender 失败: " + str(e)


# ─── 文件解析 ───
def get_stp_info(stp_path):
    """从 STP 文件头提取产品信息和零件数量"""
    try:
        with open(stp_path, 'r', encoding='utf-8', errors='ignore') as f:
            header = f.read(50000)

        products = re.findall(r"#\d+=PRODUCT\('([^']+)'", header)
        return {
            "filename": Path(stp_path).name,
            "size_mb": round(Path(stp_path).stat().st_size / 1024 / 1024, 2),
            "parts": len(products),
            "sample_parts": products[:10]
        }
    except Exception as e:
        return {"error": str(e)}


def parse_glb_stats(glb_path):
    """验证 GLB 文件"""
    try:
        size_mb = round(Path(glb_path).stat().st_size / 1024 / 1024, 2)
        with open(glb_path, 'rb') as f:
            magic = f.read(4)
            if magic != b'glTF':
                return {"error": "文件格式不是有效的 GLB"}
        return {"size_mb": size_mb, "valid": True}
    except Exception as e:
        return {"error": str(e)}


# ─── Blender 转换 ───
def convert_stp_to_glb(stp_path, output_glb_path, blender_exe, progress_callback=None):
    """
    使用 Blender CLI 将 STP 转为 GLB
    blender_exe: 用户指定的或自动检测的 blender.exe 路径
    """
    if not blender_exe or not Path(blender_exe).exists():
        return False, "blender.exe 未找到: " + str(blender_exe)

    # 直接构造脚本字符串，避免 f-string 嵌套反斜杠
    _stp_ = "__STP__"
    _out_ = "__OUT__"
    _tpl = """
import bpy
import sys

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

stp_path = r"%s"
try:
    bpy.ops.import_mesh.step(filepath=stp_path)
except Exception as e:
    print("IMPORT_ERROR:" + str(e))
    sys.exit(1)

for obj in bpy.data.objects:
    if obj.type == 'MESH':
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')

output_path = r"%s"
try:
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB',
        export_draco=1,
        export_materials='EXPORT',
        export_colors=True,
        use_selection=False
    )
    print("CONVERT_SUCCESS")
except Exception as e:
    print("EXPORT_ERROR:" + str(e))
    sys.exit(1)
""" % (_stp_, _out_)

    script_content = _tpl.replace(_stp_, stp_path).replace(_out_, output_glb_path)

    script_path = output_glb_path + ".convert_script.py"
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    log("Blender script written, launching Blender: " + blender_exe)
    log("STP: " + stp_path)
    log("OUT: " + output_glb_path)

    try:
        process = subprocess.Popen(
            [blender_exe, "--background", "--python", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output_lines = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                output_lines.append(line.strip())
                if progress_callback:
                    progress_callback(line.strip())

        stderr = process.stderr.read()
        returncode = process.wait()

        try:
            os.remove(script_path)
        except:
            pass

        if returncode != 0:
            error_msg = "\n".join(output_lines + [stderr])
            import_err = re.search(r"IMPORT_ERROR:(.+)", error_msg)
            export_err = re.search(r"EXPORT_ERROR:(.+)", error_msg)
            if import_err:
                return False, "STP 导入失败: " + import_err.group(1)
            if export_err:
                return False, "GLB 导出失败: " + export_err.group(1)
            return False, "Blender 异常退出 (code " + str(returncode) + ")"

        if not os.path.exists(output_glb_path):
            return False, "GLB 文件未生成"

        return True, output_glb_path

    except Exception as e:
        return False, "转换过程异常: " + str(e)


# ─── DearPyGUI 界面 ───
try:
    import dearpygui.dearpygui as dpg
    log("DearPyGUI imported OK")
except Exception as e:
    log("DearPyGUI import FAIL: " + str(e))
    print("ERROR: DearPyGUI import failed. Please run: pip install dearpygui")
    print("Failed with:", e)
    sys.exit(1)

dpg.destroy_context()
dpg.create_context()

state = {
    "stp_path": "",
    "output_path": "",
    "blender_exe": "",
    "stp_info": {},
    "is_converting": False,
    "blender_ok": False,
    "blender_version": "",
}


def on_blender_file_selected(sender, app_data, user_data):
    """选择 blender.exe"""
    path = app_data.get("file_path_name", "")
    if path:
        state["blender_exe"] = path
        dpg.set_value("blender_path_text", path)
        ok, msg = check_blender()
        state["blender_ok"] = ok
        state["blender_version"] = msg
        if ok:
            dpg.configure_item("blender_status", default_value=msg, color=(0, 255, 0, 255))
            dpg.configure_item("start_btn", enabled=True)
        else:
            dpg.configure_item("blender_status", default_value=msg, color=(255, 80, 80, 255))


def on_select_file(sender, app_data, user_data):
    """选择 STP 文件"""
    path = app_data.get("file_path_name", "")
    if path and any(path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        state["stp_path"] = path
        dpg.set_value("file_path_text", path)

        info = get_stp_info(path)
        state["stp_info"] = info

        if "error" not in info:
            sample = ", ".join(info.get("sample_parts", [])[:5])
            dpg.set_value("info_text", "零件数: " + str(info['parts']) + " 个\n示例: " + sample)
            dpg.configure_item("info_text", color=(0, 255, 0, 255))
            dpg.configure_item("start_btn", enabled=True)

            state["output_path"] = str(Path(path).with_suffix(".glb"))
            dpg.set_value("output_path_text", state["output_path"])
        else:
            dpg.set_value("info_text", "读取失败: " + info['error'])
            dpg.configure_item("info_text", color=(255, 80, 80, 255))
    else:
        dpg.set_value("info_text", "请选择 .stp 或 .step 文件")
        dpg.configure_item("info_text", color=(255, 200, 0, 255))


def on_select_output(sender, app_data, user_data):
    path = app_data.get("file_path_name", "")
    if path:
        state["output_path"] = path
        dpg.set_value("output_path_text", path)


def on_start_convert(sender, app_data, user_data):
    if not state["stp_path"]:
        dpg.set_value("status_text", "请先选择 STP 文件")
        return
    if not state["output_path"]:
        dpg.set_value("status_text", "请先选择输出路径")
        return
    if not state["blender_exe"]:
        dpg.set_value("status_text", "请先选择 blender.exe")
        return

    state["is_converting"] = True
    dpg.configure_item("start_btn", enabled=False)
    dpg.configure_item("cancel_btn", enabled=True)
    dpg.set_value("status_text", "正在转换，请稍候...")
    dpg.set_value("progress_text", "0%")
    dpg.configure_item("progress_bar", default_value=0.0)

    def worker():
        def progress_handler(line):
            dpg.set_value("progress_text", "处理中...")
            dpg.set_value("status_text", line[:80] if line else "处理中...")

        ok, result = convert_stp_to_glb(
            state["stp_path"],
            state["output_path"],
            state["blender_exe"],
            progress_callback=progress_handler
        )

        state["is_converting"] = False

        if ok:
            glb_info = parse_glb_stats(result)
            dpg.set_value("progress_bar", 1.0)
            dpg.set_value("progress_text", "100%")
            dpg.set_value("status_text", "成功！GLB 大小: " + str(glb_info.get('size_mb', '?')) + " MB\n文件已保存到: " + result)
        else:
            dpg.set_value("progress_bar", 0.0)
            dpg.set_value("progress_text", "失败")
            dpg.set_value("status_text", "转换失败: " + result)

        dpg.configure_item("start_btn", enabled=True)
        dpg.configure_item("cancel_btn", enabled=False)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


# ─── 窗口布局 ───
WIN_W, WIN_H = 620, 540
with dpg.window(tag="main_window", label="STP -> GLB 转换工具", width=WIN_W, height=WIN_H, pos=(80, 80)):
    dpg.add_text("STP -> GLB 转换工具 v" + VERSION, tag="title", color=(0, 200, 255, 255), wrap=WIN_W - 40)
    dpg.add_text("Powered by Blender + DearPyGUI | 请先选择 blender.exe", color=(150, 150, 150, 255))
    dpg.add_separator()

    # Blender 选择
    dpg.add_text("第一步：选择 blender.exe", color=(200, 200, 200, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="blender_path_text", default_value="", width=420, readonly=True, hint="blender.exe 路径")
        dpg.add_button(label="浏览...", callback=lambda s, a, u: dpg.show_item("blender_dialog"), width=80)

    with dpg.group(horizontal=True):
        dpg.add_text("状态: ", color=(180, 180, 180, 255))
        dpg.add_text("未指定", tag="blender_status", color=(255, 200, 0, 255))

    dpg.add_spacer(height=5)
    dpg.add_separator()
    dpg.add_spacer(height=5)

    # STP 文件选择
    dpg.add_text("第二步：选择 STP/STEP 文件", color=(200, 200, 200, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="file_path_text", default_value="", width=420, readonly=True, hint="未选择文件")
        dpg.add_button(label="浏览...", callback=lambda s, a, u: dpg.show_item("file_dialog"), width=80)

    dpg.add_spacer(height=5)

    dpg.add_text("等待选择文件...", tag="info_text", color=(200, 200, 200, 255), wrap=WIN_W - 40)

    dpg.add_spacer(height=5)
    dpg.add_separator()
    dpg.add_spacer(height=5)

    # 输出路径
    dpg.add_text("第三步：保存 GLB 位置", color=(200, 200, 200, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="output_path_text", default_value="", width=420, readonly=True, hint="未设置")
        dpg.add_button(label="浏览...", callback=lambda s, a, u: dpg.show_item("output_dialog"), width=80)

    dpg.add_spacer(height=15)

    # 进度条
    dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=WIN_W - 40, height=20)
    dpg.add_text("", tag="progress_text", color=(150, 150, 150, 255))

    dpg.add_spacer(height=10)

    # 按钮
    with dpg.group(horizontal=True):
        dpg.add_button(label="开始转换", tag="start_btn", callback=on_start_convert, width=140, enabled=False)
        dpg.add_button(label="取消", tag="cancel_btn", callback=None, width=80, enabled=False)

    dpg.add_spacer(height=10)
    dpg.add_separator()
    dpg.add_text("就绪", tag="status_text", color=(150, 150, 150, 255), wrap=WIN_W - 40)


# ─── 文件对话框 ───
with dpg.file_dialog(
    tag="blender_dialog", label="选择 blender.exe",
    directory_selector=False, show=False, modal=True,
    callback=on_blender_file_selected, min_size=(500, 400),
    default_path="C:\\Program Files\\Blender*"):
    dpg.add_file_extension(".exe", color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))

with dpg.file_dialog(
    tag="file_dialog", label="选择 STP 文件",
    directory_selector=False, show=True, modal=True,
    callback=on_select_file, min_size=(500, 400),
    default_path=os.path.expanduser("~/Desktop")):
    for ext in SUPPORTED_EXTENSIONS:
        dpg.add_file_extension(ext, color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))

with dpg.file_dialog(
    tag="output_dialog", label="保存 GLB 文件",
    directory_selector=False, show=False, modal=True,
    callback=on_select_output, min_size=(500, 400),
    file_name="output.glb"):
    dpg.add_file_extension(".glb", color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))


# ─── Blender 自动检测（启动时） ───
log("Initializing Blender detection")
detected = get_blender_path()
if detected:
    log("Auto-detected Blender: " + detected)
    state["blender_exe"] = detected
    dpg.set_value("blender_path_text", detected)
    ok, msg = check_blender()
    state["blender_ok"] = ok
    state["blender_version"] = msg
    if ok:
        dpg.configure_item("blender_status", default_value=msg, color=(0, 255, 0, 255))
        log("Blender check OK: " + msg)
    else:
        dpg.configure_item("blender_status", default_value=msg + " (请手动选择)", color=(255, 200, 0, 255))
        log("Blender check FAIL: " + msg)
else:
    log("No Blender auto-detected, user must select manually")
    dpg.set_value("blender_status", "未自动检测到，请手动选择 blender.exe")


# ─── 启动 ───
log("Showing viewport")
dpg.set_primary_window("main_window", True)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
log("Shutdown complete")