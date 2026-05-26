"""
STP → GLB 转换工具
主程序：tkinter 界面 + Blender subprocess 封装
"""
import os
import sys
import subprocess
import threading
import re
import time
from pathlib import Path
from tkinter import *
from tkinter import ttk  # noqa: F401
from tkinter import ttk as ttk_
from tkinter import filedialog, messagebox, ttk

# ─── 全局崩溃捕获 + 日志 ───
LOG_FILE = os.path.join(os.path.dirname(sys.argv[0] if getattr(sys, 'frozen', False) else __file__), "startup.log")

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except:
        pass

def except_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log("UNCAUGHT %s: %s\n%s" % (exc_type.__name__, str(exc_value), tb))
    try:
        messagebox.showerror("STP->GLB 转换工具 错误",
            "%s: %s\n\n详细信息已写入 startup.log" % (exc_type.__name__, str(exc_value)))
    except:
        pass
    sys.exit(1)

sys.excepthook = except_hook

log("=" * 40)
log("Startup: " + sys.argv[0])
log("Python: " + sys.version)

# ─── 全局配置 ───
VERSION = "1.0.0"
SUPPORTED_EXTENSIONS = [("STP/STEP 文件", "*.stp *.step *.STP *.STEP"), ("所有文件", "*.*")]

# ─── Blender 检测 ───
def find_blender():
    """从多个可能位置找 blender.exe"""
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

    pf = os.environ.get("ProgramFiles", "")
    if pf:
        candidates.append(Path(pf) / "Blender" / "blender.exe")

    for p in candidates:
        if p.exists():
            log("Blender found: " + str(p))
            return str(p)
    log("No blender.exe found")
    return ""


def check_blender(path):
    if not path:
        return False, "未指定"
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return True, r.stdout.strip().split('\n')[0]
        return False, "exit code " + str(r.returncode)
    except FileNotFoundError:
        return False, "文件不存在"
    except Exception as e:
        return False, str(e)


# ─── STP 信息读取 ───
def get_stp_info(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            header = f.read(50000)
        products = re.findall(r"#\d+=PRODUCT\('([^']+)'", header)
        return {
            "filename": Path(path).name,
            "size_mb": round(Path(path).stat().st_size / 1024 / 1024, 2),
            "parts": len(products),
            "samples": products[:8]
        }
    except Exception as e:
        return {"error": str(e)}


def parse_glb_stats(path):
    try:
        size_mb = round(Path(path).stat().st_size / 1024 / 1024, 2)
        with open(path, 'rb') as f:
            if f.read(4) != b'glTF':
                return {"error": "无效 GLB"}
        return {"size_mb": size_mb, "valid": True}
    except Exception as e:
        return {"error": str(e)}


# ─── Blender 转换核心 ───
def convert_stp_to_glb(stp_path, output_glb_path, blender_exe, progress_var, status_var):
    if not blender_exe or not Path(blender_exe).exists():
        return False, "blender.exe 未找到"

    _sp = "__STP__"
    _op = "__OUT__"
    _tpl = """
import bpy, sys

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

out = r"%s"
try:
    bpy.ops.export_scene.gltf(filepath=out, export_format='GLB',
        export_draco=1, export_materials='EXPORT',
        export_colors=True, use_selection=False)
    print("CONVERT_SUCCESS")
except Exception as e:
    print("EXPORT_ERROR:" + str(e))
    sys.exit(1)
""" % (_sp, _op)

    script = _tpl.replace(_sp, stp_path).replace(_op, output_glb_path)
    script_path = output_glb_path + ".pyconvert"
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script)

    log("Blender: " + blender_exe)
    log("STP: " + stp_path)

    try:
        p = subprocess.Popen(
            [blender_exe, "--background", "--python", script_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        out_lines = []
        while True:
            line = p.stdout.readline()
            if not line and p.poll() is not None:
                break
            if line:
                out_lines.append(line.strip())
                root.after(10, lambda l=line.strip(): status_var.set(l[:80]))

        stderr = p.stderr.read()
        rc = p.wait()
        try:
            os.remove(script_path)
        except:
            pass

        if rc != 0:
            msg = "\n".join(out_lines + [stderr])
            for pat in [r"IMPORT_ERROR:(.+)", r"EXPORT_ERROR:(.+)", r"Error: (.+)"]:
                m = re.search(pat, msg)
                if m:
                    return False, m.group(1).strip()
            return False, "Blender exit code: " + str(rc)

        if not os.path.exists(output_glb_path):
            return False, "GLB 未生成"

        log("SUCCESS: " + output_glb_path)
        return True, output_glb_path

    except Exception as e:
        log("convert error: " + str(e))
        return False, str(e)


# ─── 转换线程 ───
def do_convert(stp_var, out_var, blender_var, progress_var, status_var, start_btn, cancel_btn):
    stp = stp_var.get()
    out = out_var.get()
    blender = blender_var.get()
    if not all([stp, out, blender]):
        status_var.set("请填写所有步骤")
        return

    start_btn.config(state=DISABLED)
    cancel_btn.config(state=NORMAL)
    progress_var.set(0)
    status_var.set("正在转换，请稍候...")

    def worker():
        ok, result = convert_stp_to_glb(stp, out, blender, progress_var, status_var)
        if ok:
            info = parse_glb_stats(result)
            root.after(0, lambda: progress_var.set(100))
            root.after(0, lambda: status_var.set(
                "转换成功！%.1f MB\n%s" % (info.get('size_mb', 0), result)))
        else:
            root.after(0, lambda: status_var.set("失败: " + result))
        root.after(0, lambda: start_btn.config(state=NORMAL))
        root.after(0, lambda: cancel_btn.config(state=DISABLED))

    threading.Thread(target=worker, daemon=True).start()


# ─── UI 布局 ───
root = Tk()
root.title("STP -> GLB 转换工具 v" + VERSION)
root.geometry("680x520")
root.resizable(False, False)
root.configure(bg="#1e1e1e")

# 字体
TITLE_FONT = ("Segoe UI", 16, "bold")
LABEL_FONT = ("Segoe UI", 10)
MONO_FONT = ("Consolas", 9)

# 颜色
BG = "#1e1e1e"
FG = "#d4d4d4"
ACCENT = "#007acc"
GREEN = "#4ec9b0"
RED = "#f14c4c"
ORANGE = "#cca700"

# 上边框
frame_top = Frame(root, bg=BG)
frame_top.pack(fill=X, padx=20, pady=(20, 5))
Label(frame_top, text="STP -> GLB 转换工具", font=TITLE_FONT, fg=ACCENT, bg=BG).pack(anchor=W)
Label(frame_top, text="Powered by Blender + Python tkinter | 崩溃日志: startup.log", font=("Segoe UI", 8), fg="#808080", bg=BG).pack(anchor=W)

ttk.Separator(root, orient=HORIZONTAL).pack(fill=X, padx=20, pady=5)

# Blender
frame_blender = Frame(root, bg=BG)
frame_blender.pack(fill=X, padx=20, pady=5)
Label(frame_blender, text="第一步: 选择 blender.exe (必填)", font=LABEL_FONT, fg=FG, bg=BG).pack(anchor=W)
frame_blender_row = Frame(frame_blender, bg=BG)
frame_blender_row.pack(fill=X, pady=3)
blender_var = StringVar()
Entry(frame_blender_row, textvariable=blender_var, font=MONO_FONT, bg="#2d2d2d", fg=FG,
      insertbackground=FG, disabledbackground="#2d2d2d", disabledforeground="#808080",
      width=52, state=DISABLED).pack(side=LEFT, fill=X, expand=True)
Button(frame_blender_row, text="浏览...", command=lambda: browse_blender(blender_var),
       bg="#0e639c", fg=FG, activebackground="#1177bb", relief=FLAT, width=8).pack(side=LEFT, padx=(5, 0))

blender_status_var = StringVar(value="未选择")
Label(frame_blender, text="状态:", font=("Segoe UI", 9), fg="#808080", bg=BG).pack(anchor=W)
Label(frame_blender, textvariable=blender_status_var, font=("Segoe UI", 9), fg=ORANGE, bg=BG, anchor=W).pack(anchor=W)

ttk.Separator(root, orient=HORIZONTAL).pack(fill=X, padx=20, pady=5)

# STP
frame_stp = Frame(root, bg=BG)
frame_stp.pack(fill=X, padx=20, pady=5)
Label(frame_stp, text="第二步: 选择 STP/STEP 文件", font=LABEL_FONT, fg=FG, bg=BG).pack(anchor=W)
frame_stp_row = Frame(frame_stp, bg=BG)
frame_stp_row.pack(fill=X, pady=3)
stp_var = StringVar()
Entry(frame_stp_row, textvariable=stp_var, font=MONO_FONT, bg="#2d2d2d", fg=FG,
      insertbackground=FG, width=52, state=DISABLED).pack(side=LEFT, fill=X, expand=True)
Button(frame_stp_row, text="浏览...", command=lambda: browse_file(stp_var),
       bg="#0e639c", fg=FG, activebackground="#1177bb", relief=FLAT, width=8).pack(side=LEFT, padx=(5, 0))

info_var = StringVar(value="等待选择文件...")
Label(frame_stp, textvariable=info_var, font=("Segoe UI", 9), fg="#808080", bg=BG, anchor=W, wraplength=620).pack(anchor=W)

ttk.Separator(root, orient=HORIZONTAL).pack(fill=X, padx=20, pady=5)

# 输出路径
frame_out = Frame(root, bg=BG)
frame_out.pack(fill=X, padx=20, pady=5)
Label(frame_out, text="第三步: 保存 GLB 位置", font=LABEL_FONT, fg=FG, bg=BG).pack(anchor=W)
frame_out_row = Frame(frame_out, bg=BG)
frame_out_row.pack(fill=X, pady=3)
out_var = StringVar()
Entry(frame_out_row, textvariable=out_var, font=MONO_FONT, bg="#2d2d2d", fg=FG,
      insertbackground=FG, width=52, state=DISABLED).pack(side=LEFT, fill=X, expand=True)
Button(frame_out_row, text="浏览...", command=lambda: save_file(out_var, stp_var),
       bg="#0e639c", fg=FG, activebackground="#1177bb", relief=FLAT, width=8).pack(side=LEFT, padx=(5, 0))

# 进度条
progress_var = DoubleVar(value=0)
frame_progress = Frame(root, bg=BG)
frame_progress.pack(fill=X, padx=20, pady=(10, 0))
Progressbar(frame_progress, variable=progress_var, mode=determinate,
           length=640, height=18, bg="#2d2d2d", fg=ACCENT,
           troughcolor="#2d2d2d", borderwidth=0).pack()
progress_label_var = StringVar(value="")
Label(frame_progress, textvariable=progress_label_var, font=("Segoe UI", 8), fg="#808080", bg=BG).pack()

# 按钮
frame_buttons = Frame(root, bg=BG)
frame_buttons.pack(fill=X, padx=20, pady=10)
start_btn = Button(frame_buttons, text="开始转换", font=("Segoe UI", 10, "bold"),
                  command=lambda: do_convert(stp_var, out_var, blender_var, progress_var, status_var, start_btn, cancel_btn),
                  bg="#0e639c", fg="white", activebackground="#1177bb", relief=FLAT, width=12, state=DISABLED)
start_btn.pack(side=LEFT)
cancel_btn = Button(frame_buttons, text="取消", font=("Segoe UI", 10),
                   state=DISABLED, bg="#3c3c3c", fg=FG, relief=FLAT, width=8)
cancel_btn.pack(side=LEFT, padx=(5, 0))

# 状态栏
ttk.Separator(root, orient=HORIZONTAL).pack(fill=X, padx=20)
frame_status = Frame(root, bg=BG)
frame_status.pack(fill=X, padx=20, pady=8)
status_var = StringVar(value="就绪 - 请先选择 blender.exe")
Label(frame_status, textvariable=status_var, font=("Segoe UI", 9), fg="#808080", bg=BG, anchor=W, wraplength=640).pack(fill=X)


# ─── 回调函数 ───
def browse_blender(var):
    path = filedialog.askopenfilename(
        title="选择 blender.exe",
        filetypes=[("blender.exe", "blender.exe"), ("所有文件", "*.*")],
        initialdir=os.environ.get("ProgramFiles", "C:\\")
    )
    if path:
        var.set(path)
        ok, msg = check_blender(path)
        blender_status_var.set(msg)
        Label(frame_blender, textvariable=blender_status_var,
              font=("Segoe UI", 9), fg=GREEN if ok else RED, bg=BG, anchor=W).pack(anchor=W)
        start_btn.config(state=NORMAL if ok else DISABLED)


def browse_file(var):
    path = filedialog.askopenfilename(
        title="选择 STP/STEP 文件",
        filetypes=SUPPORTED_EXTENSIONS,
        initialdir=os.path.expanduser("~/Desktop")
    )
    if path:
        var.set(path)
        info = get_stp_info(path)
        if "error" not in info:
            samples = ", ".join(info.get("samples", [])[:5])
            info_var.set("零件数: %d 个 | 大小: %.1f MB | 示例: %s" % (
                info['parts'], info['size_mb'], samples))
            info_var._root_label.config(fg=GREEN)
            # 自动设置输出路径
            out_path = str(Path(path).with_suffix(".glb"))
            out_var.set(out_path)
        else:
            info_var.set("读取失败: " + info['error'])
            info_var._root_label.config(fg=RED)


def save_file(var, stp_var_ref):
    path = filedialog.asksaveasfilename(
        title="保存 GLB 文件",
        defaultextension=".glb",
        filetypes=[("GLB 文件", "*.glb"), ("所有文件", "*.*")],
        initialdir=os.path.dirname(stp_var_ref.get()) if stp_var_ref.get() else None
    )
    if path:
        var.set(path)


# ─── Blender 自动检测 ───
log("Starting Blender auto-detect...")
auto_blender = find_blender()
if auto_blender:
    blender_var.set(auto_blender)
    ok, msg = check_blender(auto_blender)
    blender_status_var.set(msg)
    Label(frame_blender, textvariable=blender_status_var,
          font=("Segoe UI", 9), fg=GREEN if ok else ORANGE, bg=BG, anchor=W).pack(anchor=W)
    if ok:
        start_btn.config(state=NORMAL)
        log("Blender auto-detected OK")
        status_var.set("Blender 自动检测成功: " + msg[:60])
else:
    log("No Blender auto-detected, user must select manually")


# ─── 启动 ───
log("Starting mainloop...")
# hack: 给 info_var 添加 _root_label 引用用于后续配置颜色
for w in frame_stp.winfo_children():
    if isinstance(w, Label) and w.cget("textvariable") == info_var:
        info_var._root_label = w
        break

root.mainloop()
log("Mainloop ended")