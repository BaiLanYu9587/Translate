#!/usr/bin/env python3
"""
重构版翻译程序主入口
增强版本：包含基础检查、错误处理和用户友好的错误提示
适用于打包分发版本，无需依赖检查
"""

import sys
import os
import shutil
import tempfile
import time
import logging
import threading


def setup_openssl_dll_path() -> None:
    """
    动态地将打包的OpenSSL DLL目录添加到搜索路径中。
    这确保了应用程序使用我们提供的OpenSSL版本，尤其是在打包后。
    此函数应在应用程序启动的最开始被调用。
    """
    # 获取当前函数的logger实例
    logger = logging.getLogger(__name__)

    if sys.platform != "win32":
        # 此解决方案仅适用于Windows
        return

    # 尝试设置DPI感知，解决Qt警告
    try:
        import ctypes

        # 尝试多种DPI感知设置方法
        try:
            # 方法1: 使用SetProcessDpiAwarenessContext (Windows 10 1703+)
            user32 = ctypes.windll.user32
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
            result = user32.SetProcessDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
            if result:
                logger.info(
                    "已成功设置进程DPI感知为 Per-Monitor V2 (SetProcessDpiAwarenessContext)。"
                )
            else:
                raise Exception("SetProcessDpiAwarenessContext 返回失败")
        except Exception as e1:
            try:
                # 方法2: 使用SetProcessDpiAwareness (Windows 8.1+)
                ctypes.windll.shcore.SetProcessDpiAwareness(
                    2
                )  # PROCESS_PER_MONITOR_DPI_AWARE
                logger.info(
                    "已成功设置进程DPI感知为 Per-Monitor (SetProcessDpiAwareness)。"
                )
            except Exception as e2:
                try:
                    # 方法3: 使用SetProcessDPIAware (Windows Vista+)
                    ctypes.windll.user32.SetProcessDPIAware()
                    logger.info(
                        "已成功设置进程DPI感知为 System DPI Aware (SetProcessDPIAware)。"
                    )
                except Exception as e3:
                    logger.warning(
                        f"所有DPI感知设置方法都失败: {e1}, {e2}, {e3}。Qt警告可能仍然出现。"
                    )
    except Exception as e:
        logger.warning(f"设置进程DPI感知失败: {e}。Qt警告可能仍然出现。")

    base_path = ""
    # 确定基础路径
    if getattr(sys, "frozen", False):
        # 应用程序被打包 (PyInstaller)
        # 对于 --onefile 模式, 数据文件在 sys._MEIPASS 临时目录
        # 我们优先检查 _MEIPASS, 因为这是最常见的打包方式
        if hasattr(sys, "_MEIPASS"):
            base_path = getattr(sys, "_MEIPASS")
            logger.info(f"检测到PyInstaller打包环境，基础路径: {base_path}")
        else:
            # 对于 --onedir 模式, 数据文件在 sys.executable 所在目录
            base_path = os.path.dirname(sys.executable)
            logger.info(f"检测到PyInstaller --onedir 模式，基础路径: {base_path}")
    else:
        # 应用程序未被打包 (从脚本运行)
        base_path = os.path.dirname(os.path.abspath(__file__))
        logger.info(f"从脚本运行，基础路径: {base_path}")

    openssl_dir = os.path.join(base_path, "openssl_dll")

    # -------- 优化：在 PyInstaller --onefile 环境下，将 DLL 解压复制到可执行文件同级目录 --------
    # 目标：首次运行时解压，后续运行时直接使用，以优化启动性能。
    # 策略：
    # 1. 检查 .exe 同级目录是否存在 openssl_dll 文件夹。
    # 2. 如果不存在或不完整，则从 _MEIPASS 临时目录中复制。
    # 3. 如果复制成功，则优先使用此外部路径。
    # 4. 如果复制失败（如权限不足），则优雅回退，继续使用 _MEIPASS 中的路径。
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            exe_dir = os.path.dirname(sys.executable)
            extracted_dir = os.path.join(exe_dir, "openssl_dll")

            # 检查源目录是否存在
            if os.path.isdir(openssl_dir):
                # 根据进程位数选择DLL名称
                is_x64 = sys.maxsize > 2**32
                ssl_name = "libssl-3-x64.dll" if is_x64 else "libssl-3-x86.dll"
                crypto_name = "libcrypto-3-x64.dll" if is_x64 else "libcrypto-3-x86.dll"
                dll_files = [ssl_name, crypto_name]

                # 检查目标文件是否都已存在
                all_exist = all(
                    os.path.isfile(os.path.join(extracted_dir, f)) for f in dll_files
                )

                if not all_exist:
                    logger.info(
                        f"检测到 {extracted_dir} 不完整，将从程序内部解压 OpenSSL 库。"
                    )
                    os.makedirs(extracted_dir, exist_ok=True)

                    for dll_name in dll_files:
                        src_path = os.path.join(openssl_dir, dll_name)
                        dest_path = os.path.join(extracted_dir, dll_name)

                        if os.path.isfile(src_path) and not os.path.isfile(dest_path):
                            try:
                                shutil.copy2(src_path, dest_path)
                                logger.info(f"已解压 {dll_name} 到程序目录。")
                            except Exception as copy_err:
                                logger.warning(
                                    f"解压 {dll_name} 失败: {copy_err}。将使用内存中的版本。"
                                )

                # 如果最终所有文件都存在于外部目录，则优先使用它
                if all(
                    os.path.isfile(os.path.join(extracted_dir, f)) for f in dll_files
                ):
                    logger.info(f"将优先使用位于程序目录的 OpenSSL 库: {extracted_dir}")
                    openssl_dir = extracted_dir
                else:
                    logger.warning(
                        "无法在程序目录创建完整的 OpenSSL 库，将使用内存中的临时版本。"
                    )

    except Exception as extract_err:
        logger.warning(f"处理 OpenSSL DLL 解压逻辑时发生错误: {extract_err}")

    logger.info(f"正在查找OpenSSL库: {openssl_dir}")

    # 调试信息: 列出基础目录的内容，帮助诊断路径问题
    try:
        if os.path.exists(base_path):
            logger.debug(f"基础路径 '{base_path}' 的内容: {os.listdir(base_path)}")
        else:
            logger.debug(f"基础路径 '{base_path}' 不存在。")
    except Exception as e:
        logger.debug(f"无法列出基础路径内容: {e}")

    if not os.path.isdir(openssl_dir):
        logger.warning(
            f"未找到 'openssl_dll' 目录于 '{openssl_dir}'。程序将依赖系统默认的OpenSSL库。"
        )
        return

    logger.info(f"成功找到OpenSSL目录: {openssl_dir}")
    try:
        # 使用Python 3.8+的标准方法
        os.add_dll_directory(openssl_dir)
        logger.info(f"已将 {openssl_dir} 添加到DLL搜索路径")

        # 预加载库以验证（将 ctypes 的使用放入同一 try 块，避免 NameError）
        try:
            import ctypes as _ctypes
        except Exception as import_err:
            logger.error(f"导入 ctypes 失败，无法预加载 OpenSSL: {import_err}")
            return

        # 根据进程位数选择DLL名称
        is_x64 = sys.maxsize > 2**32
        ssl_name = "libssl-3-x64.dll" if is_x64 else "libssl-3-x86.dll"
        crypto_name = "libcrypto-3-x64.dll" if is_x64 else "libcrypto-3-x86.dll"

        libssl_path = os.path.join(openssl_dir, ssl_name)
        libcrypto_path = os.path.join(openssl_dir, crypto_name)

        # 存在性检查，提前给出更清晰的日志
        missing = [p for p in (libssl_path, libcrypto_path) if not os.path.isfile(p)]
        if missing:
            logger.error(f"OpenSSL 预加载失败，缺少文件: {missing}")
            return

        _ctypes.CDLL(libssl_path)
        _ctypes.CDLL(libcrypto_path)
        logger.info(f"OpenSSL库 ({libssl_path}, {libcrypto_path}) 预加载成功")
    except Exception as e:
        # 提供更具体的诊断建议（常见原因：位数不匹配、依赖缺失、权限不足）
        logger.error(f"添加或加载OpenSSL库失败: {e}", exc_info=True)
        try:
            arch = "x64" if sys.maxsize > 2**32 else "x86"
            logger.error(
                "可能原因与排查: \n"
                f"- 进程位数: {arch}；请确保 openssl_dll 下的 DLL 与进程位数一致 (x64: libssl-3-x64.dll/libcrypto-3-x64.dll; x86: libssl-3-x86.dll/libcrypto-3-x86.dll)\n"
                "- 缺少依赖: Visual C++ 运行库或系统缺失依赖，请安装并重试\n"
                f"- 路径权限: {openssl_dir} 是否可读\\写；尝试以管理员权限或移动到非受限路径\n"
                f"- 备选方案: 删除 openssl_dll，使系统 OpenSSL 接管，或将 DLL 放置于 {os.path.dirname(sys.executable)}"
            )
        except Exception:
            pass


# 移除运行时 sys.path 注入，改为通过包内相对/绝对导入
# 说明：
# 1) 当前项目已为包结构（core/, utils/ 均含 __init__.py），可由 Python 包解析器解析。
# 2) start.py 作为项目入口不直接从 core/utils 进行裸相对导入；后续导入使用“from core.main import ...”等绝对包导入。
# 3) 打包场景下（PyInstaller）也能正常解析，因为运行目录为项目根或 _MEIPASS，模块打包在归档内，sys.meta_path 钩子负责加载。
# 若未来需要支持将 start.py 单独放置运行，请转为模块入口（例如 python -m package.start），而非注入 sys.path。


def check_special_paths() -> bool:
    """检查特殊路径兼容性"""
    logger = logging.getLogger(__name__)  # 获取当前函数的logger实例
    current_path = os.path.dirname(os.path.abspath(__file__))

    # 检查路径中是否包含特殊字符
    special_chars = ["&", "%", "#", "@", "!", "$", "^", "(", ")", "[", "]", "{", "}"]
    problematic_chars = [char for char in special_chars if char in current_path]

    if problematic_chars:
        logger.warning("警告：程序路径包含特殊字符，可能导致运行问题")
        logger.warning(f"当前路径：{current_path}")
        logger.warning(f"问题字符：{', '.join(problematic_chars)}")
        logger.warning("建议：将程序移动到不包含特殊字符的路径下")

        # 仅在交互式终端且非冻结环境下提示输入，否则默认继续运行以避免阻塞
        try:
            is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        except Exception:
            is_tty = False
        if is_tty and not getattr(sys, "frozen", False):
            try:
                choice = input("是否继续运行？(y/n): ").strip().lower()
                if choice not in ["y", "yes", "是"]:
                    return False
            except (KeyboardInterrupt, EOFError):
                return False

    return True


# ---------------------- 新增：临时目录清理工具 ----------------------
def cleanup_old_temp_dirs(
    prefixes: tuple[str, ...] = ("_MEI",), max_age_hours: int = 24
) -> None:
    """在程序启动时清理由 PyInstaller 等生成、残留在系统临时目录中的旧目录。

    参数:
        prefixes: 需要匹配的目录名前缀元组。
        max_age_hours: 仅删除修改时间早于该值 (小时) 的条目。
    """
    logger = logging.getLogger(__name__)  # 获取当前函数的logger实例
    try:
        temp_root = tempfile.gettempdir()
        now = time.time()
        current_meipass = (
            os.path.abspath(getattr(sys, "_MEIPASS", ""))
            if hasattr(sys, "_MEIPASS")
            else None
        )

        for entry in os.listdir(temp_root):
            # 仅匹配指定前缀的目录
            if not any(entry.startswith(p) for p in prefixes):
                continue

            path = os.path.join(temp_root, entry)
            if not os.path.isdir(path):
                continue

            # 跳过当前运行实例所在目录
            if current_meipass and os.path.abspath(path) == current_meipass:
                continue

            # 仅删除超过阈值时间的目录
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue

            if now - mtime < max_age_hours * 3600:
                continue

            try:
                shutil.rmtree(path, ignore_errors=True)
                logger.info(f"已清理旧临时目录: {path}")
            except Exception as rm_err:
                logger.warning(f"删除临时目录失败 {path}: {rm_err}")
    except Exception as e:
        logger.warning(f"清理临时目录过程中出现异常: {e}")


# -------------------------------------------------------------------


def main() -> None:
    """启动重构版翻译程序 - 优化启动性能"""
    # 在任何其他日志记录发生之前，设置一个基本的日志配置
    # 这将捕获 PyInstaller 和早期启动阶段的日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(threadName)s] - %(name)s - %(message)s",
        stream=sys.stdout,
    )

    # 获取一个logger实例用于start.py自身的日志
    logger = logging.getLogger(__name__)
    current_thread_name = threading.current_thread().name

    logger.info(f"[{current_thread_name}] === 多语言互译器 ===")
    logger.info(
        f"[{current_thread_name}] 程序启动于: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    logger.info(f"[{current_thread_name}] Python 版本: {sys.version}")
    logger.info(f"[{current_thread_name}] 操作系统: {sys.platform}")

    # 优化启动：延迟清理操作，只在必要时执行
    logger.info(f"[{current_thread_name}] 正在进行快速启动检查...")

    # 检查特殊路径（快速检查）
    if not check_special_paths():
        # 非交互环境/冻结环境避免阻塞或抛 EOF
        try:
            is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        except Exception:
            is_tty = False
        if is_tty and not getattr(sys, "frozen", False):
            try:
                input("按回车键退出...")
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)

    logger.info(f"[{current_thread_name}] 启动检查完成，正在初始化程序...")

    try:
        # 先执行关键的OpenSSL设置（同步执行，确保在主程序启动前完成）
        setup_openssl_dll_path()

        # 延迟导入主模块，减少启动时间
        logger.debug(f"[{current_thread_name}] 准备延迟导入主模块...")
        from core.main import main as run_main

        logger.debug(f"[{current_thread_name}] 主模块导入成功。")

        # 在程序启动后异步执行清理操作
        def delayed_cleanup() -> None:
            cleanup_thread_name = threading.current_thread().name
            logger.info(f"[{cleanup_thread_name}] 后台清理线程开始执行。")
            try:
                cleanup_old_temp_dirs()
            except Exception as e:
                logger.warning(
                    f"[{cleanup_thread_name}] 后台清理操作失败: {e}", exc_info=True
                )
            logger.info(f"[{cleanup_thread_name}] 后台清理线程执行完毕。")

        # 启动后台清理线程
        cleanup_thread = threading.Thread(
            target=delayed_cleanup, daemon=True, name="CleanupThread"
        )
        cleanup_thread.start()
        logger.info(
            f"[{current_thread_name}] 后台清理线程 '{cleanup_thread.name}' (ID: {cleanup_thread.ident}) 已启动。"
        )

        # 启动主程序
        logger.info(f"[{current_thread_name}] 准备启动主程序逻辑...")
        run_main()

    except KeyboardInterrupt:
        logger.info(f"[{current_thread_name}] \n程序已通过键盘中断退出。")
    except ImportError as e:
        logger.error(f"[{current_thread_name}] 模块导入失败：{e}", exc_info=True)
        logger.error("请检查程序文件是否完整")
        # 仅在交互式且非冻结环境下才提示按回车，避免阻塞/EOF
        try:
            is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        except Exception:
            is_tty = False
        if is_tty and not getattr(sys, "frozen", False):
            try:
                input("按回车键退出...")
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)
    except Exception as e:
        logger.error(f"[{current_thread_name}] 程序运行失败: {e}", exc_info=True)
        logger.error("\n详细错误信息：")
        import traceback

        logger.error(traceback.format_exc())  # 使用logger记录堆栈信息
        logger.error("\n如果问题持续存在，请联系技术支持")
        # 仅在交互式且非冻结环境下才提示按回车，避免阻塞/EOF
        try:
            is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        except Exception:
            is_tty = False
        if is_tty and not getattr(sys, "frozen", False):
            try:
                input("按回车键退出...")
            except (EOFError, KeyboardInterrupt):
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
