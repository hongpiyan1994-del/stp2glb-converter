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
import ctypes
from pathlib import Path

# ─── 全局崩溃捕获 + 日志 ───
LOG_FILE = os.path.join(os.path.dirname(sys.argv[0] if getattr(sys, 'frozen', False) else __file__), "startup.log")

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except:
        pass

def show_error(msg):
    """弹窗 + 日志，双保险"""
    log("FATAL ERROR: " + msg)
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "STP->GLB 转换工具 错误", 0x10)
    except:
        pass
    print("FATAL ERROR: " + msg, file=sys.stderr)

# 全局异常捕获
def except_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log("UNCAUGHT %s: %s" % (exc_type.__name__, str(exc_value)))
    show_error("程序遇到错误:\n\n%s: %s\n\n详细信息已写入 startup.log" % (exc_type.__name__, str(exc_value)))
    sys.exit(1)

sys.excepthook = except_hook

log("=" * 40)
log("Startup: " + " ".join(sys.argv))
log("Python: " + sys.version)
log("CWD: " + os.getcwd())

# ─── 验证关键依赖 ───
try:
    import dearpygui.dearpygui as dpg
    log("DearPyGUI imported OK, version: " + str(dpg.get_app_configuration() if hasattr(dpg, 'get_app_configuration') else 'OK'))
except ImportError as e:
    log("DearPyGUI ImportError: " + str(e))
    show_error("缺少 DearPyGUI 依赖。\n\n请在命令提示符运行:\npip install dearpygui\n\n然后重新启动程序。")
    sys.exit(1)
except Exception as e:
    log("DearPyGUI init error: " + str(e))
    show_error("DearPyGUI 初始化失败:\n\n" + str(e) + "\n\n请尝试:\npip install dearpygui --force-reinstall")
    sys.exit(1)

# ─── 全局配置 ───
VERSION = "1.0.0"
SUPPORTED_EXTENSIONS = [".stp", ".step", ".STP", ".STEP"]

# ─── Blender 路径检测 ───
def get_blender_path():
    """从多个位置找 blender.exe"""
    candidates = []
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
        exe_dir = Path(sys.argv[0]).parent
        candidates += [
            base / "blender" / "blender.exe",
            base / "blender.exe",
            exe_dir / "blender" / "blender.exe",
            exe_dir / "blender.exe",
        ]
    else:
        base = Path(__file__).parent
        candidates += [base / "blender" / "blender.exe", base / "blender.exe"]

    candidates += [Path(os.environ.get("BLENDER_PATH", ""))]
    if os.environ.get("ProgramFiles"):
        candidates.append(Path(os.environ["ProgramFiles"]) / "Blender" / "blender.exe")

    for p in candidates:
        if p.exists():
            log("Blender candidate found: " + str(p))
            return str(p)
    log("No blender.exe found, candidates checked: " + str(candidates))
    return ""


def check_blender(blender_path):
    if not blender_path:
        return False, "未指定 blender.exe"
    try:
        result = subprocess.run([blender_path, "--version"],
                                capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return True, result.stdout.strip().split('\n')[0]
        return False, "Blender 返回退出码 " + str(result.returncode)
    except FileNotFoundError:
        return False, "文件不存在: " + blender_path
    except Exception as e:
        return False, str(e)


# ─── 文件解析 ───
def get_stp_info(stp_path):
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
    try:
        size_mb = round(Path(glb_path).stat().st_size / 1024 / 1024, 2)
        with open(glb_path, 'rb') as f:
            if f.read(4) != b'glTF':
                return {"error": "文件格式不是有效的 GLB"}
        return {"size_mb": size_mb, "valid": True}
    except Exception as e:
        return {"error": str(e)}


# ─── Blender 转换 ───
def convert_stp_to_glb(stp_path, output_glb_path, blender_exe, progress_callback=None):
    if not blender_exe or not Path(blender_exe).exists():
        return False, "blender.exe 未找到: " + str(blender_exe)

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

    log("Launching Blender: " + blender_exe)
    log("STP: " + stp_path + " -> " + output_glb_path)

    try:
        process = subprocess.Popen(
            [blender_exe, "--background", "--python", script_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
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
            for pat in [r"IMPORT_ERROR:(.+)", r"EXPORT_ERROR:(.+)", r"Error: (.+)"]:
                m = re.search(pat, error_msg)
                if m:
                    return False, m.group(1).strip()
            return False, "Blender 异常退出 (code " + str(returncode) + ")"

        if not os.path.exists(output_glb_path):
            return False, "GLB 文件未生成"

        log("Conversion SUCCESS: " + output_glb_path)
        return True, output_glb_path

    except Exception as e:
        log("convert exception: " + str(e))
        return False, "转换过程异常: " + str(e)


# ─── 状态 ───
dpg.destroy_context()
dpg.create_context()

state = {
    "stp_path": "", "output_path": "", "blender_exe": "",
    "stp_info": {}, "is_converting": False,
    "blender_ok": False, "blender_version": "",
}


def on_blender_selected(sender, app_data, user_data):
    path = app_data.get("file_path_name", "")
    if path:
        state["blender_exe"] = path
        dpg.set_value("blender_path_text", path)
        ok, msg = check_blender(path)
        state["blender_ok"] = ok
        state["blender_version"] = msg
        color = (0, 255, 0, 255) if ok else (255, 80, 80, 255)
        dpg.configure_item("blender_status", default_value=msg, color=color)
        dpg.configure_item("start_btn", enabled=ok)


def on_file_selected(sender, app_data, user_data):
    path = app_data.get("file_path_name", "")
    if path and any(path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        state["stp_path"] = path
        dpg.set_value("file_path_text", path)
        info = get_stp_info(path)
        state["stp_info"] = info
        if "error" not in info:
            dpg.set_value("info_text", "零件数: %d 个\n示例: %s" % (info['parts'], ", ".join(info.get("sample_parts", [])[:5])))
            dpg.configure_item("info_text", color=(0, 255, 0, 255))
            state["output_path"] = str(Path(path).with_suffix(".glb"))
            dpg.set_value("output_path_text", state["output_path"])
        else:
            dpg.set_value("info_text", "读取失败: " + info['error'])
            dpg.configure_item("info_text", color=(255, 80, 80, 255))


def on_output_selected(sender, app_data, user_data):
    path = app_data.get("file_path_name", "")
    if path:
        state["output_path"] = path
        dpg.set_value("output_path_text", path)


def on_start_convert(sender, app_data, user_data):
    if not state["stp_path"] or not state["output_path"] or not state["blender_exe"]:
        dpg.set_value("status_text", "请填写所有步骤")
        return

    state["is_converting"] = True
    dpg.configure_item("start_btn", enabled=False)
    dpg.configure_item("cancel_btn", enabled=True)
    dpg.set_value("status_text", "正在转换，请稍候...")
    dpg.set_value("progress_text", "0%")
    dpg.configure_item("progress_bar", default_value=0.0)

    def worker():
        ok, result = convert_stp_to_glb(
            state["stp_path"], state["output_path"], state["blender_exe"],
            progress_callback=lambda l: dpg.set_value("status_text", l[:80] if l else "...")
        )
        state["is_converting"] = False

        if ok:
            glb_info = parse_glb_stats(result)
            dpg.set_value("progress_bar", 1.0)
            dpg.set_value("progress_text", "100%")
            dpg.set_value("status_text", "成功! GLB: %.1f MB\n%s" % (glb_info.get('size_mb', 0), result))
        else:
            dpg.set_value("progress_bar", 0.0)
            dpg.set_value("progress_text", "失败")
            dpg.set_value("status_text", "转换失败: " + result)

        dpg.configure_item("start_btn", enabled=True)
        dpg.configure_item("cancel_btn", enabled=False)

    threading.Thread(target=worker, daemon=True).start()


# ─── 窗口布局 ───
WIN_W = 640
with dpg.window(tag="main_window", label="STP -> GLB 转换工具", width=WIN_W, height=550, pos=(100, 100)):
    dpg.add_text("STP -> GLB 转换工具 v" + VERSION, color=(0, 200, 255, 255))
    dpg.add_text("Powered by Blender + DearPyGUI | 提示: 请先选择 blender.exe", color=(150, 150, 150, 255))
    dpg.add_separator()

    dpg.add_text("第一步: 选择 blender.exe (必填)", color=(200, 200, 200, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="blender_path_text", default_value="", width=440, readonly=True, hint="点击浏览选择 blender.exe")
        dpg.add_button(label="浏览...", callback=lambda s, a, u: dpg.show_item("blender_dialog"), width=80)
    with dpg.group(horizontal=True):
        dpg.add_text("状态: ", color=(180, 180, 180, 255))
        dpg.add_text("未选择", tag="blender_status", color=(255, 200, 0, 255))

    dpg.add_spacer(height=5)
    dpg.add_separator()
    dpg.add_spacer(height=5)

    dpg.add_text("第二步: 选择 STP/STEP 文件", color=(200, 200, 200, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="file_path_text", default_value="", width=440, readonly=True, hint="点击浏览选择文件")
        dpg.add_button(label="浏览...", callback=lambda s, a, u: dpg.show_item("file_dialog"), width=80)
    dpg.add_text("等待选择文件...", tag="info_text", color=(200, 200, 200, 255), wrap=WIN_W - 40)

    dpg.add_spacer(height=5)
    dpg.add_separator()
    dpg.add_spacer(height=5)

    dpg.add_text("第三步: 保存 GLB 位置", color=(200, 200, 200, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="output_path_text", default_value="", width=440, readonly=True, hint="点击浏览选择保存位置")
        dpg.add_button(label="浏览...", callback=lambda s, a, u: dpg.show_item("output_dialog"), width=80)

    dpg.add_spacer(height=15)

    dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=WIN_W - 40, height=22)
    dpg.add_text("", tag="progress_text", color=(150, 150, 150, 255))

    dpg.add_spacer(height=10)
    with dpg.group(horizontal=True):
        dpg.add_button(label="开始转换", tag="start_btn", callback=on_start_convert, width=140, enabled=False)
        dpg.add_button(label="取消", tag="cancel_btn", callback=None, width=80, enabled=False)

    dpg.add_spacer(height=10)
    dpg.add_separator()
    dpg.add_text("就绪", tag="status_text", color=(150, 150, 150, 255), wrap=WIN_W - 40)


# ─── 文件对话框 ───
with dpg.file_dialog(tag="blender_dialog", label="选择 blender.exe",
        directory_selector=False, show=False, modal=True,
        callback=on_blender_selected, min_size=(500, 400)):
    dpg.add_file_extension(".exe", color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))

with dpg.file_dialog(tag="file_dialog", label="选择 STP 文件",
        directory_selector=False, show=True, modal=True,
        callback=on_file_selected, min_size=(500, 400),
        default_path=os.path.expanduser("~/Desktop")):
    for ext in SUPPORTED_EXTENSIONS:
        dpg.add_file_extension(ext, color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))

with dpg.file_dialog(tag="output_dialog", label="保存 GLB 文件",
        directory_selector=False, show=False, modal=True,
        callback=on_output_selected, min_size=(500, 400), file_name="output.glb"):
    dpg.add_file_extension(".glb", color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))


# ─── Blender 自动检测 ───
auto_blender = get_blender_path()
if auto_blender:
    state["blender_exe"] = auto_blender
    dpg.set_value("blender_path_text", auto_blender)
    ok, msg = check_blender(auto_blender)
    state["blender_ok"] = ok
    state["blender_version"] = msg
    if ok:
        dpg.configure_item("blender_status", default_value=msg, color=(0, 255, 0, 255))
        log("Blender auto-detected and OK: " + msg)
    else:
        dpg.configure_item("blender_status", default_value=msg + " (请手动选择)", color=(255, 200, 0, 255))
        log("Blender auto-detected but check FAILED: " + msg)
else:
    log("No Blender auto-detected")
    dpg.set_value("blender_status", "未检测到，请手动选择 blender.exe")


# ─── 启动 ───
log("Showing viewport")
dpg.set_primary_window("main_window", True)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
log("Shutdown OK")