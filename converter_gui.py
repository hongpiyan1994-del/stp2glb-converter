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
from tkinter import ttk, filedialog, messagebox


# ─── 全局崩溃捕获 + 日志 ───
LOG_FILE = os.path.join(
    os.path.dirname(sys.argv[0] if getattr(sys, "frozen", False) else __file__),
    "startup.log",
)

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass

def except_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    err = "%s: %s" % (exc_type.__name__, str(exc_value))
    log("UNCAUGHT " + err + "\n" + tb)
    try:
        messagebox.showerror("错误", err + "\n\n详细信息已写入 startup.log")
    except Exception:
        pass
    sys.exit(1)

sys.excepthook = except_hook

log("=" * 40)
log("Startup: " + sys.argv[0])
log("Python: " + sys.version)

# ─── 颜色常量 ───
BG = "#1e1e1e"
FG = "#d4d4d4"
ACCENT = "#007acc"
GREEN = "#4ec9b0"
RED = "#f14c4c"
ORANGE = "#cca700"
DARK_ENTRY = "#2d2d2d"
BTN_BLUE = "#0e639c"
BTN_BLUE_HOVER = "#1177bb"
BTN_GREY = "#3c3c3c"

TITLE_FONT = ("Segoe UI", 15, "bold")
LABEL_FONT = ("Segoe UI", 10)
MONO_FONT = ("Consolas", 9)
SMALL_FONT = ("Segoe UI", 8)

VERSION = "1.0.0"
SUPPORTED = [("STP/STEP 文件", "*.stp *.step *.STP *.STEP"), ("所有文件", "*.*")]


# ─── Blender 检测 ───
def find_blender():
    candidates = []
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
        exe_dir = Path(sys.argv[0]).parent
        for d in [base, exe_dir]:
            candidates.append(d / "blender" / "blender.exe")
            candidates.append(d / "blender.exe")
            # Also check Blender's own folder structure
            candidates.append(d / "blender-4.2.0-windows-x64" / "blender.exe")
    else:
        candidates.append(Path(__file__).parent / "blender" / "blender.exe")
        candidates.append(Path(__file__).parent / "blender.exe")

    pf = os.environ.get("ProgramFiles", "")
    if pf:
        candidates.append(Path(pf) / "Blender" / "blender.exe")
        candidates.append(Path(pf) / "Blender Foundation" / "Blender 4.2" / "blender.exe")

    for p in candidates:
        if p.exists():
            log("Blender found: " + str(p))
            return str(p)
    log("No blender.exe found in: " + str(candidates))
    return ""


def check_blender(path):
    if not path:
        return False, "未指定"
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return True, r.stdout.strip().split("\n")[0]
        return False, "exit code " + str(r.returncode)
    except FileNotFoundError:
        return False, "文件不存在"
    except Exception as e:
        return False, str(e)


def get_stp_info(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            header = f.read(50000)
        products = re.findall(r"#\d+=PRODUCT\('([^']+)'", header)
        return {
            "filename": Path(path).name,
            "size_mb": round(Path(path).stat().st_size / 1024 / 1024, 2),
            "parts": len(products),
            "samples": products[:8],
        }
    except Exception as e:
        return {"error": str(e)}


def parse_glb_stats(path):
    try:
        size_mb = round(Path(path).stat().st_size / 1024 / 1024, 2)
        with open(path, "rb") as f:
            if f.read(4) != b"glTF":
                return {"error": "无效 GLB"}
        return {"size_mb": size_mb, "valid": True}
    except Exception as e:
        return {"error": str(e)}


def convert_stp_to_glb(stp_path, output_glb_path, blender_exe, status_callback):
    if not blender_exe or not Path(blender_exe).exists():
        return False, "blender.exe 未找到: " + str(blender_exe)

    stp_esc = stp_path.replace("\\", "\\\\")
    out_esc = output_glb_path.replace("\\", "\\\\")

    script = (
        "import bpy, sys, addon_utils\n"
        "# Find and enable STEP/IO_mesh_step addon\n"
        "step_addon = None\n"
        "for mod in addon_utils.module_keys():\n"
        "    if 'step' in mod.lower() or 'io_mesh_step' in mod:\n"
        "        step_addon = mod\n"
        "        break\n"
        "if step_addon:\n"
        "    try:\n"
        "        bpy.ops.preferences.addon_enable(module=step_addon)\n"
        "        print('STEP addon enabled: ' + step_addon)\n"
        "    except Exception as e:\n"
        "        print('addon_enable error: ' + str(e))\n"
        "else:\n"
        "    print('STEP addon not found in available addons')\n"
        "bpy.ops.object.select_all(action='SELECT')\n"
        "bpy.ops.object.delete(use_global=False)\n"
        "stp_path = r'%s'\n"
        "try:\n"
        "    bpy.ops.import_mesh.step(filepath=stp_path)\n"
        "except Exception as e:\n"
        "    print('IMPORT_ERROR:' + str(e))\n"
        "    sys.exit(1)\n"
        "for obj in bpy.data.objects:\n"
        "    if obj.type == 'MESH':\n"
        "        obj.select_set(True)\n"
        "        bpy.context.view_layer.objects.active = obj\n"
        "        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)\n"
        "        bpy.ops.object.origin_set(type='ORIGIN_CENTER_OF_VOLUME')\n"
        "out_path = r'%s'\n"
        "try:\n"
        "    bpy.ops.export_scene.gltf(filepath=out_path, export_format='GLB',\n"
        "        export_draco=1, export_materials='EXPORT',\n"
        "        export_colors=True, use_selection=False)\n"
        "    print('CONVERT_SUCCESS')\n"
        "except Exception as e:\n"
        "    print('EXPORT_ERROR:' + str(e))\n"
        "    sys.exit(1)\n"
        % (stp_esc, out_esc)
    )
    script_path = output_glb_path + ".pyconvert"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    log("Blender: " + blender_exe + " STP: " + stp_path)

    try:
        p = subprocess.Popen(
            [blender_exe, "--background", "--python", script_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        out_lines = []
        while True:
            line = p.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line:
                out_lines.append(line)
                if status_callback:
                    status_callback(line)
            if p.poll() is not None:
                break

        stderr = p.stderr.read()
        rc = p.wait()
        try:
            os.remove(script_path)
        except Exception:
            pass

        log("Blender rc=" + str(rc) + " stdout_lines=" + str(out_lines))

        if rc != 0:
            msg = "\n".join(out_lines + [stderr])
            for pat in [r"IMPORT_ERROR:(.+)", r"EXPORT_ERROR:(.+)", r"Error: (.+)"]:
                m = re.search(pat, msg)
                if m:
                    return False, m.group(1).strip()
            return False, "Blender exit code: " + str(rc) + " msg: " + msg[:200]

        if not os.path.exists(output_glb_path):
            return False, "GLB 未生成"

        log("SUCCESS: " + output_glb_path)
        return True, output_glb_path

    except Exception as e:
        log("convert exception: " + str(e))
        return False, str(e)


# ─── UI 布局 ───
root = Tk()
root.title("STP -> GLB 转换工具 v" + VERSION)
root.geometry("680x520")
root.resizable(False, False)
root.configure(bg=BG)

def sep():
    Frame(root, bg=BG, height=1).pack(fill=X, padx=20)


# ─── Header ───
fr_top = Frame(root, bg=BG)
fr_top.pack(fill=X, padx=20, pady=(20, 5))
Label(fr_top, text="STP -> GLB 转换工具", font=TITLE_FONT, fg=ACCENT, bg=BG, anchor=W).pack(anchor=W)
Label(fr_top, text="Powered by Blender + Python tkinter | 崩溃日志: startup.log",
      font=SMALL_FONT, fg="#808080", bg=BG, anchor=W).pack(anchor=W)
sep()

# ─── Blender 选择 ───
fr_blender = Frame(root, bg=BG)
fr_blender.pack(fill=X, padx=20, pady=5)
Label(fr_blender, text="第一步: 选择 blender.exe (必填)",
      font=LABEL_FONT, fg=FG, bg=BG, anchor=W).pack(anchor=W)
blender_var = StringVar()
fr_br = Frame(fr_blender, bg=BG)
fr_br.pack(fill=X, pady=3)
# Use Label instead of Entry for read-only path display (Entry DISABLED can't be updated)
blender_path_lbl = Label(fr_br, text="(未选择)", font=MONO_FONT, bg=DARK_ENTRY, fg=FG,
                         anchor=W, width=52)
blender_path_lbl.pack(side=LEFT, fill=X, expand=True)
Button(fr_br, text="浏览...", bg=BTN_BLUE, fg=FG,
       activebackground=BTN_BLUE_HOVER, relief=FLAT, width=8).pack(side=LEFT, padx=(5, 0))
blender_status_var = StringVar(value="状态: 未选择")
Label(fr_blender, textvariable=blender_status_var, font=SMALL_FONT,
      fg=ORANGE, bg=BG, anchor=W).pack(anchor=W)
sep()

# ─── STP 文件选择 ───
fr_stp = Frame(root, bg=BG)
fr_stp.pack(fill=X, padx=20, pady=5)
Label(fr_stp, text="第二步: 选择 STP/STEP 文件",
      font=LABEL_FONT, fg=FG, bg=BG, anchor=W).pack(anchor=W)
stp_var = StringVar()
fr_sr = Frame(fr_stp, bg=BG)
fr_sr.pack(fill=X, pady=3)
stp_path_lbl = Label(fr_sr, text="(未选择文件)", font=MONO_FONT, bg=DARK_ENTRY, fg=FG,
                      anchor=W, width=52)
stp_path_lbl.pack(side=LEFT, fill=X, expand=True)
Button(fr_sr, text="浏览...", bg=BTN_BLUE, fg=FG,
       activebackground=BTN_BLUE_HOVER, relief=FLAT, width=8).pack(side=LEFT, padx=(5, 0))
info_var = StringVar(value="等待选择文件...")
info_lbl = Label(fr_stp, textvariable=info_var, font=SMALL_FONT, fg="#808080", bg=BG, anchor=W, wraplength=640)
info_lbl.pack(anchor=W)
sep()

# ─── 输出路径 ───
fr_out = Frame(root, bg=BG)
fr_out.pack(fill=X, padx=20, pady=5)
Label(fr_out, text="第三步: 保存 GLB 位置",
      font=LABEL_FONT, fg=FG, bg=BG, anchor=W).pack(anchor=W)
out_var = StringVar()
fr_or = Frame(fr_out, bg=BG)
fr_or.pack(fill=X, pady=3)
out_path_lbl = Label(fr_or, text="(未设置)", font=MONO_FONT, bg=DARK_ENTRY, fg=FG,
                     anchor=W, width=52)
out_path_lbl.pack(side=LEFT, fill=X, expand=True)
Button(fr_or, text="浏览...", bg=BTN_BLUE, fg=FG,
       activebackground=BTN_BLUE_HOVER, relief=FLAT, width=8).pack(side=LEFT, padx=(5, 0))
sep()

# ─── 进度条 ───
fr_prog = Frame(root, bg=BG)
fr_prog.pack(fill=X, padx=20, pady=(10, 0))
progress_var = DoubleVar(value=0)
ttk.Progressbar(fr_prog, variable=progress_var, mode="determinate",
                 length=640).pack()
progress_label_var = StringVar(value="")
Label(fr_prog, textvariable=progress_label_var, font=SMALL_FONT,
      fg="#808080", bg=BG).pack()
sep()

# ─── 按钮 ───
fr_btn = Frame(root, bg=BG)
fr_btn.pack(fill=X, padx=20, pady=10)
start_btn = Button(fr_btn, text="开始转换", font=("Segoe UI", 10, "bold"),
                   bg=BTN_BLUE, fg="white", activebackground=BTN_BLUE_HOVER,
                   relief=FLAT, width=12, state=DISABLED)
start_btn.pack(side=LEFT)
cancel_btn = Button(fr_btn, text="取消", font=("Segoe UI", 10),
                     state=DISABLED, bg=BTN_GREY, fg=FG, relief=FLAT, width=8)
cancel_btn.pack(side=LEFT, padx=(5, 0))

# ─── 状态栏 ───
sep()
fr_stat = Frame(root, bg=BG)
fr_stat.pack(fill=X, padx=20, pady=8)
status_var = StringVar(value="就绪 - 请先选择 blender.exe")
Label(fr_stat, textvariable=status_var, font=SMALL_FONT, fg="#808080",
      bg=BG, anchor=W, wraplength=640).pack(fill=X)


# ─── 回调函数 ───
def on_blender_browse():
    path = filedialog.askopenfilename(
        title="选择 blender.exe",
        filetypes=[("blender.exe", "blender.exe"), ("所有文件", "*.*")],
        initialdir=os.environ.get("ProgramFiles", "C:\\"),
    )
    if not path:
        return
    blender_var.set(path)
    blender_path_lbl.config(text=path)
    ok, msg = check_blender(path)
    blender_status_var.set(msg)
    Label(fr_blender, textvariable=blender_status_var, font=SMALL_FONT,
          fg=GREEN if ok else RED, bg=BG, anchor=W).pack(anchor=W)
    start_btn.config(state=NORMAL if ok else DISABLED)
    if ok:
        status_var.set("Blender 就绪: " + msg[:60])


def on_stp_browse():
    path = filedialog.askopenfilename(
        title="选择 STP/STEP 文件",
        filetypes=SUPPORTED,
        initialdir=os.path.expanduser("~/Desktop"),
    )
    if not path:
        return
    stp_var.set(path)
    stp_path_lbl.config(text=path)
    info = get_stp_info(path)
    if "error" not in info:
        samples = ", ".join(info.get("samples", [])[:5])
        info_var.set("零件数: %d 个 | 大小: %.1f MB | 示例: %s" % (
            info["parts"], info["size_mb"], samples))
        info_lbl.config(fg=GREEN)
        out_path = str(Path(path).with_suffix(".glb"))
        out_var.set(out_path)
        out_path_lbl.config(text=out_path)
    else:
        info_var.set("读取失败: " + info["error"])
        info_lbl.config(fg=RED)


def on_output_browse():
    init_dir = os.path.dirname(stp_var.get()) if stp_var.get() else None
    path = filedialog.asksaveasfilename(
        title="保存 GLB 文件",
        defaultextension=".glb",
        filetypes=[("GLB 文件", "*.glb"), ("所有文件", "*.*")],
        initialdir=init_dir,
    )
    if path:
        out_var.set(path)
        out_path_lbl.config(text=path)


def do_convert():
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
    info_lbl.config(fg="#808080")

    def worker():
        def cb(line):
            root.after(0, lambda: status_var.set(str(line)[:80] if line else "处理中..."))

        ok, result = convert_stp_to_glb(stp, out, blender, cb)

        if ok:
            info = parse_glb_stats(result)
            root.after(0, lambda: progress_var.set(100))
            root.after(0, lambda: status_var.set(
                "转换成功！%.1f MB\n%s" % (info.get("size_mb", 0), result)))
        else:
            root.after(0, lambda: progress_var.set(0))
            root.after(0, lambda: status_var.set("转换失败: " + result))
            info_lbl.config(fg=RED)

        root.after(0, lambda: start_btn.config(state=NORMAL))
        root.after(0, lambda: cancel_btn.config(state=DISABLED))

    threading.Thread(target=worker, daemon=True).start()


# Bind button callbacks
fr_br.winfo_children()[1].config(command=on_blender_browse)
fr_sr.winfo_children()[1].config(command=on_stp_browse)
fr_or.winfo_children()[1].config(command=on_output_browse)
start_btn.config(command=do_convert)


# ─── Blender 自动检测 ───
log("Starting Blender auto-detect...")
auto_blender = find_blender()
if auto_blender:
    blender_var.set(auto_blender)
    blender_path_lbl.config(text=auto_blender)
    ok, msg = check_blender(auto_blender)
    blender_status_var.set(msg)
    Label(fr_blender, textvariable=blender_status_var, font=SMALL_FONT,
          fg=GREEN if ok else ORANGE, bg=BG, anchor=W).pack(anchor=W)
    if ok:
        start_btn.config(state=NORMAL)
        status_var.set("Blender 自动检测成功: " + msg[:60])
    else:
        status_var.set("Blender 自动检测失败，请手动选择")
else:
    status_var.set("未检测到 blender.exe，请手动选择")


# ─── 启动 ───
log("Starting mainloop...")
root.mainloop()
log("Mainloop ended")