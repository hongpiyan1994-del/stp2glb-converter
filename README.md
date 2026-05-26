# STP → GLB 本地转换工具

## 用途
将 STP/STEP CAD 文件转换为 GLB 格式，供 Web 实时渲染使用。

## 构建说明

### 依赖
- Python 3.10+
- DearPyGUI
- Blender CLI (Windows portable)
- PyInstaller

### 构建 EXE
```bash
pip install -r requirements.txt
pyinstaller converter.spec --noconfirm
```

### 转换测试（Linux 服务器验证用）
```bash
cd tests
bash test_convert.sh
```

## 文件说明
- `converter_gui.py` - 主程序（DearPyGUI 界面 + Blender 封装）
- `blender_converter.py` - Blender CLI 调用封装
- `requirements.txt` - Python 依赖
- `converter.spec` - PyInstaller 打包配置
- `.github/workflows/build.yml` - Windows EXE 构建流水线
