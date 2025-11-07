#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多语言互译器打包脚本
自动化打包主程序和API加解密工具
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path
import locale

# 设置输出编码为 UTF-8（CI/Windows 环境下强制 UTF-8，避免 UnicodeEncodeError）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        # 如果 reconfigure 失败，使用 TextIOWrapper 包装并启用替代字符
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 获取脚本所在目录（项目根目录）
PROJECT_ROOT = Path(__file__).parent.absolute()
os.chdir(PROJECT_ROOT)

# 导入版本号
sys.path.insert(0, str(PROJECT_ROOT))
from core.constants import APP_VERSION  # noqa: E402

# 定义路径和名称（使用英文）
DIST_PATH = PROJECT_ROOT / "dist"
APP_NAME = f"MultiLangTranslator-v{APP_VERSION}"
API_TOOL_NAME = f"APIKeyTool-v{APP_VERSION}"
ICON_PATH = PROJECT_ROOT / "icon.ico"

print("=" * 60)
print(f"开始打包 v{APP_VERSION}")
print("=" * 60)

# 创建编译输出目录
DIST_PATH.mkdir(exist_ok=True)
print(f"输出目录: {DIST_PATH}")

# 通用的hidden-import列表
COMMON_HIDDEN_IMPORTS = [
    "pyautogui", "yaml", "keyboard", "pycld2", "cryptography", "PyQt6",
    "aiohttp", "pynput", "regex", "ruamel.yaml", "sqlite3", "_sqlite3",
    "logging.handlers", "socket", "ssl", "json", "collections", "asyncio",
    "threading", "importlib.util", "time", "os", "sys", "io", "queue",
    "signal", "atexit", "dataclasses", "typing", "re", "hashlib", "base64",
    "urllib", "urllib.parse", "http", "http.client", "utils.api_crypto",
    "pyperclip", "win32gui", "win32api", "PIL", "pygetwindow", "certifi"
]

# 通用的collect-submodules列表
COMMON_COLLECT_SUBMODULES = [
    "sqlite3", "logging", "urllib", "http", "PIL", "pywin32"
]


def run_pyinstaller(spec_name, entry_point, app_name, add_data_list, hidden_imports, collect_submodules):
    """运行PyInstaller打包命令"""
    print(f"\n{'=' * 60}")
    print(f"正在打包: {app_name}")
    print(f"{'=' * 60}")
    
    cmd = [
        "pyinstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
    ]
    
    # 添加数据文件
    for data in add_data_list:
        cmd.extend(["--add-data", data])
    
    # 添加隐藏导入
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])
    
    # 添加子模块收集
    for mod in collect_submodules:
        cmd.extend(["--collect-submodules", mod])
    
    # 添加图标（检查文件是否存在）
    icon_to_use = ICON_PATH if ICON_PATH.exists() else PROJECT_ROOT / "图标.ico"
    if icon_to_use.exists():
        cmd.extend(["--icon", str(icon_to_use)])
    
    # 添加输出名称
    cmd.extend(["--name", app_name])
    
    # 控制台模式
    cmd.append("--console")
    
    # 输出目录
    cmd.extend(["--distpath", str(DIST_PATH)])
    
    # 入口文件
    cmd.append(str(entry_point))
    
    print(f"执行命令: {' '.join(cmd[:5])} ... (完整命令已省略)")
    
    try:
        subprocess.run(cmd, check=True, capture_output=False)
        print(f"✓ {app_name} 打包成功！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {app_name} 打包失败: {e}")
        return False
    except FileNotFoundError:
        print("✗ 错误: 找不到 pyinstaller 命令")
        print("请先安装: pip install pyinstaller")
        return False


def build_main_app():
    """打包主程序"""
    # 检查图标文件，如果不存在则尝试使用原中文名
    icon_to_use = ICON_PATH if ICON_PATH.exists() else PROJECT_ROOT / "图标.ico"
    
    add_data = [
        "core/*;core/",
        "utils/*;utils/",
        f"{icon_to_use};.",
        "openssl_dll/*;openssl_dll/"
    ]
    
    return run_pyinstaller(
        spec_name=f"{APP_NAME}.spec",
        entry_point=PROJECT_ROOT / "start.py",
        app_name=APP_NAME,
        add_data_list=add_data,
        hidden_imports=COMMON_HIDDEN_IMPORTS,
        collect_submodules=COMMON_COLLECT_SUBMODULES
    )


def build_api_tool():
    """打包API加解密工具"""
    # 检查图标文件
    if not ICON_PATH.exists():
        print(f"警告: 图标文件不存在: {ICON_PATH}")
    
    add_data = [
        "utils/api_crypto.py;utils/",
        "openssl_dll/*;openssl_dll/"
    ]
    
    hidden_imports = ["yaml"]
    
    return run_pyinstaller(
        spec_name=f"{API_TOOL_NAME}.spec",
        entry_point=PROJECT_ROOT / "utils" / "api_key_tool.py",
        app_name=API_TOOL_NAME,
        add_data_list=add_data,
        hidden_imports=hidden_imports,
        collect_submodules=[]
    )


def clean_build_artifacts():
    """清理构建产物"""
    print("\n正在清理构建产物...")
    
    artifacts = ["build", "__pycache__"]
    for artifact in artifacts:
        artifact_path = PROJECT_ROOT / artifact
        if artifact_path.exists():
            try:
                shutil.rmtree(artifact_path)
                print(f"✓ 已删除: {artifact}")
            except Exception as e:
                print(f"✗ 删除失败 {artifact}: {e}")
    
    # 删除.spec文件
    for spec_file in PROJECT_ROOT.glob("*.spec"):
        try:
            spec_file.unlink()
            print(f"✓ 已删除: {spec_file.name}")
        except Exception as e:
            print(f"✗ 删除失败 {spec_file.name}: {e}")


def main():
    """主函数"""
    print(f"Python版本: {sys.version}")
    print(f"项目目录: {PROJECT_ROOT}")
    print(f"应用版本: {APP_VERSION}\n")
    
    # 检查图标文件
    if not ICON_PATH.exists():
        print(f"警告: 图标文件不存在: {ICON_PATH}")
        print("将继续打包，但不会包含图标\n")
    
    success_count = 0
    total_count = 2
    
    # 打包主程序
    if build_main_app():
        success_count += 1
    
    # 打包API工具
    if build_api_tool():
        success_count += 1
    
    # 清理构建产物
    clean_build_artifacts()
    
    # 输出结果
    print("\n" + "=" * 60)
    print("打包完成")
    print("=" * 60)
    print(f"成功: {success_count}/{total_count}")
    
    if success_count == total_count:
        print("\n✓ 所有程序打包成功！")
        print(f"输出目录: {DIST_PATH}")
        
        # 列出生成的文件
        exe_files = list(DIST_PATH.glob("*.exe"))
        if exe_files:
            print("\n生成的文件:")
            for exe_file in exe_files:
                size_mb = exe_file.stat().st_size / (1024 * 1024)
                print(f"  - {exe_file.name} ({size_mb:.2f} MB)")
    else:
        print("\n✗ 部分程序打包失败")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n打包已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 打包过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
