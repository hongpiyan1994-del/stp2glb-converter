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
import dearpygui.dearpygui as dpg
from pathlib import Path

# ─── 全局配置 ───
VERSION = "1.0.0"
SUPPORTED_EXTENSIONS = [".stp", ".step", ".STP", ".STEP"]
MAX_FILE_SIZE_MB = 500

# ─── Blender 路径检测 ───
def get_blender_path():
    """优先从同级目录找 blender.exe（PyInstaller 打包后位于 _internal）"""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent

    blender_path = base / "blender" / "blender.exe"
    if blender_path.exists():
        return str(blender_path)

    # 尝试同目录
    local_blender = Path(__file__).parent / "blender.exe"
    if local_blender.exists():
        return str(local_blender)

    # 环境中找（开发模式）
    env_blender = Path(os.environ.get("BLENDER_PATH", "blender"))
    if env_blender.exists():
        return str(env_blender)

    return "blender"  # fallback 到 PATH


def check_blender():
    """验证 Blender 是否可用"""
    blender_path = get_blender_path()
    try:
        result = subprocess.run(
            [blender_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split('\n')[0]
            return True, version_line
        return False, "Blender 返回非零退出码"
    except FileNotFoundError:
        return False, f"未找到 blender.exe，请确认已放置于工具目录或 PATH 中"
    except Exception as e:
        return False, f"启动 Blender 失败: {e}"


# ─── 文件解析（仅头部，不加载全量） ───
def get_stp_info(stp_path):
    """从 STP 文件头提取产品信息和零件数量"""
    try:
        with open(stp_path, 'r', encoding='utf-8', errors='ignore') as f:
            header = f.read(50000)  # 只读头部

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
    """读取 GLB 文件的二进制头部，获取文件大小和基本信息"""
    try:
        size_mb = round(Path(glb_path).stat().st_size / 1024 / 1024, 2)
        with open(glb_path, 'rb') as f:
            magic = f.read(4)
            if magic != b'glTF':
                return {"error": "文件格式不是有效的 GLB"}

        return {
            "size_mb": size_mb,
            "valid": True
        }
    except Exception as e:
        return {"error": str(e)}


# ─── Blender 转换 ───
def convert_stp_to_glb(stp_path, output_glb_path, progress_callback=None):
    """
    使用 Blender CLI 将 STP 转为 GLB

    Blender Python Script:
    1. 导入 STP
    2. 应用所有变换（scale=1, rotation=0, location=0）
    3. 导出 GLB（draco 压缩）
    """
    blender_path = get_blender_path()

    # Blender Python 脚本
    script_content = f"""
import bpy
import sys
import os

# 清除默认场景
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# 导入 STP
stp_path = r"{stp_path.replace('\\', '\\\\')}"
try:
    bpy.ops.import_mesh.step(filepath=stp_path)
except Exception as e:
    print(f"IMPORT_ERROR:{{e}}")
    sys.exit(1)

# 应用变换并居中
for obj in bpy.data.objects:
    if obj.type == 'MESH':
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')

# 导出 GLB
output_path = r"{output_glb_path.replace('\\', '\\\\')}"
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
    print(f"EXPORT_ERROR:{{e}}")
    sys.exit(1)
"""

    # 写临时脚本
    script_path = output_glb_path + ".convert_script.py"
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)

    try:
        # 启动 Blender 后台进程
        process = subprocess.Popen(
            [
                blender_path,
                "--background",
                "--python", script_path
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # 实时读取输出
        output_lines = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                output_lines.append(line.strip())
                # 解析进度（如果有）
                if progress_callback:
                    progress_callback(line.strip())

        stderr = process.stderr.read()
        returncode = process.wait()

        # 清理临时脚本
        try:
            os.remove(script_path)
        except:
            pass

        if returncode != 0:
            error_msg = "\n".join(output_lines + [stderr])
            # 提取 IMPORT_ERROR / EXPORT_ERROR
            import_err = re.search(r"IMPORT_ERROR:(.+)", error_msg)
            export_err = re.search(r"EXPORT_ERROR:(.+)", error_msg)
            if import_err:
                return False, f"STP 导入失败: {import_err.group(1)}"
            if export_err:
                return False, f"GLB 导出失败: {export_err.group(1)}"
            return False, f"Blender 异常退出 (code {returncode}): {stderr[:500]}"

        # 检查输出文件
        if not os.path.exists(output_glb_path):
            return False, f"GLB 文件未生成，可能导出失败"

        return True, output_glb_path

    except Exception as e:
        return False, f"转换过程异常: {e}"


# ─── DearPyGUI 界面 ───
dpg.destroy_context()
dpg.create_context()

# ─── 状态变量 ───
state = {
    "stp_path": "",
    "output_path": "",
    "stp_info": {},
    "is_converting": False,
    "blender_ok": False,
    "blender_version": "",
}

# ─── 字体设置 ───
with dpg.font_registry():
    # 默认使用系统字体（Windows 中文友好）
    default_font = dpg.add_font(range=[(0x4E00, 0x9FFF), (0x0020, 0x007F)])

dpg.bind_font(default_font)


# ─── 回调函数 ───
def on_select_file(sender, app_data, user_data):
    """选择 STP 文件"""
    path = app_data.get("file_path_name", "")
    if path and any(path.endswith(ext) for ext in SUPPORTED_EXTENSIONS):
        state["stp_path"] = path
        dpg.set_value("file_path_text", path)

        # 解析文件信息
        info = get_stp_info(path)
        state["stp_info"] = info

        if "error" not in info:
            sample = ", ".join(info.get("sample_parts", [])[:5])
            dpg.set_value("info_text", f"零件数: {info['parts']} 个\n示例: {sample}")
            dpg.configure_item("info_text", color=(0, 255, 0, 255))
            dpg.configure_item("start_btn", enabled=True)

            # 自动设置输出路径
            output_dir = str(Path(path).parent)
            output_file = str(Path(path).stem + ".glb")
            state["output_path"] = os.path.join(output_dir, output_file)
            dpg.set_value("output_path_text", state["output_path"])
        else:
            dpg.set_value("info_text", f"读取失败: {info['error']}")
            dpg.configure_item("info_text", color=(255, 80, 80, 255))
    else:
        dpg.set_value("info_text", "请选择 .stp 或 .step 文件")
        dpg.configure_item("info_text", color=(255, 200, 0, 255))


def on_select_output(sender, app_data, user_data):
    """选择输出路径"""
    path = app_data.get("file_path_name", "")
    if path:
        state["output_path"] = path
        dpg.set_value("output_path_text", path)


def on_start_convert(sender, app_data, user_data):
    """开始转换"""
    if not state["stp_path"] or not state["output_path"]:
        dpg.set_value("status_text", "请先选择输入文件和输出路径")
        return

    if not state["blender_ok"]:
        dpg.set_value("status_text", f"Blender 不可用: {state['blender_version']}")
        return

    state["is_converting"] = True
    dpg.configure_item("start_btn", enabled=False)
    dpg.configure_item("cancel_btn", enabled=True)
    dpg.set_value("status_text", "正在转换，请稍候...")
    dpg.set_value("progress_text", "0%")
    dpg.configure_item("progress_bar", default_value=0.0)

    def worker():
        def progress_handler(line):
            # 简单进度反馈
            dpg.set_value("progress_text", "处理中...")
            dpg.set_value("status_text", f"Blender: {line[:60]}")

        ok, result = convert_stp_to_glb(
            state["stp_path"],
            state["output_path"],
            progress_callback=progress_handler
        )

        state["is_converting"] = False

        if ok:
            glb_info = parse_glb_stats(result)
            dpg.set_value("progress_bar", 1.0)
            dpg.set_value("progress_text", "100%")
            dpg.set_value("status_text", f"✅ 转换成功！GLB 大小: {glb_info.get('size_mb', '?')} MB")
        else:
            dpg.set_value("progress_bar", 0.0)
            dpg.set_value("progress_text", "失败")
            dpg.set_value("status_text", f"❌ {result}")

        dpg.configure_item("start_btn", enabled=True)
        dpg.configure_item("cancel_btn", enabled=False)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


# ─── 窗口布局 ───
with dpg.window(tag="main_window", label="STP → GLB 转换工具", width=600, height=520, pos=(50, 50)):
    # 标题栏
    dpg.add_text("STP → GLB 转换工具", tag="title", color=(0, 200, 255, 255))
    dpg.add_text(f"版本 {VERSION}  |  Powered by Blender", color=(150, 150, 150, 255))
    dpg.add_separator()

    # Blender 状态
    with dpg.group(horizontal=True):
        dpg.add_text("Blender: ", color=(180, 180, 180, 255))
        dpg.add_text("检测中...", tag="blender_status", color=(255, 200, 0, 255))

    dpg.add_spacer(height=5)

    # 输入文件
    dpg.add_text("输入文件 (.stp / .step)", color=(180, 180, 180, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="file_path_text", default_value="", width=420, readonly=True, hint="未选择文件")
        dpg.add_button(label="选择文件", callback=lambda s, a, u: dpg.show_item("file_dialog"), width=100)

    dpg.add_spacer(height=5)

    # 文件信息
    dpg.add_text("文件信息:", color=(180, 180, 180, 255))
    dpg.add_text("等待选择文件...", tag="info_text", color=(200, 200, 200, 255), wrap=500)

    dpg.add_spacer(height=5)
    dpg.add_separator()
    dpg.add_spacer(height=5)

    # 输出路径
    dpg.add_text("输出路径 (.glb)", color=(180, 180, 180, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="output_path_text", default_value="", width=420, readonly=True, hint="未设置")
        dpg.add_button(label="选择位置", callback=lambda s, a, u: dpg.show_item("output_dialog"), width=100)

    dpg.add_spacer(height=15)

    # 进度条
    dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=560, height=20)
    dpg.add_text("", tag="progress_text", color=(150, 150, 150, 255))

    dpg.add_spacer(height=10)

    # 转换按钮
    with dpg.group(horizontal=True):
        dpg.add_button(label="▶ 开始转换", tag="start_btn", callback=on_start_convert, width=140, enabled=False)
        dpg.add_button(label="✕ 取消", tag="cancel_btn", callback=None, width=100, enabled=False)

    dpg.add_spacer(height=10)

    # 状态栏
    dpg.add_separator()
    dpg.add_text("就绪", tag="status_text", color=(150, 150, 150, 255), wrap=560)


# ─── 文件对话框 ───
with dpg.file_dialog(
    tag="file_dialog",
    label="选择 STP 文件",
    directory_selector=False,
    show=True,
    modal=True,
    callback=on_select_file,
    min_size=(500, 400),
    default_path=os.path.expanduser("~/Desktop")
):
    for ext in SUPPORTED_EXTENSIONS:
        dpg.add_file_extension(ext, color=(0, 255, 0, 255))
    dpg.add_file_extension(".stp", color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))

with dpg.file_dialog(
    tag="output_dialog",
    label="保存 GLB 文件",
    directory_selector=False,
    show=False,
    modal=True,
    callback=on_select_output,
    min_size=(500, 400),
    file_name="output.glb"
):
    dpg.add_file_extension(".glb", color=(0, 255, 0, 255))
    dpg.add_file_extension(".*", color=(200, 200, 200, 255))


# ─── Blender 检测（启动时） ───
def check_blender_async():
    ok, msg = check_blender()
    state["blender_ok"] = ok
    state["blender_version"] = msg
    if ok:
        dpg.configure_item("blender_status", default_value=msg, color=(0, 255, 0, 255))
    else:
        dpg.configure_item("blender_status", default_value=msg, color=(255, 80, 80, 255))
        dpg.set_value("status_text", f"⚠ Blender 未就绪: {msg}")

blender_thread = threading.Thread(target=check_blender_async, daemon=True)
blender_thread.start()


# ─── 启动 ───
dpg.set_primary_window("main_window", True)
dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
