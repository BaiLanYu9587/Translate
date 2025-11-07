from __future__ import annotations  # 解决前向引用问题

import asyncio
import gc
import logging
import os
import signal
import sys
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional, Union

# 关键修复：在导入任何 PyQt6 模块之前，设置环境变量
# 这是解决 Windows 上 "SetProcessDpiAwarenessContext() failed" 警告的
# 官方推荐且最稳妥的方法。
if sys.platform == "win32":
    # 移除此处对DPI的设置，因为已在start.py中提前设置
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_HIGHDPI_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"
    # 添加更多DPI相关设置以避免权限问题
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    os.environ["QT_SCALE_FACTOR"] = "1"

import pyautogui  # type: ignore[import-untyped]
import pyperclip  # type: ignore[import-untyped]
from PyQt6.QtWidgets import QApplication  # type: ignore[import-untyped]
from ruamel.yaml import YAML  # type: ignore[import-untyped]

from .async_utils import AsyncLoopThread

from .cleanup_utils import ScheduledCleanupManager
from .cache_manager import CacheManager
from .config_management import (
    Config,
    complete_language_features_and_tones_in_dict,
    generate_default_main_config,
    generate_default_mode_config,
    get_application_path,
    get_config_file_path,
    get_default_config_dict,
    get_default_mode_config_dict,
    get_mode_config_file_path,
    load_models_config,
    prompt_and_update_api_key,
    save_main_config,
)
from .console_interface import (
    enter_cache_menu,
    enter_settings_menu,
    network_diagnosis,
    quick_clear_all_cache,
    show_current_config,
    show_logs,
)
from .constants import ConsoleMenus, LogMessages
from .context_manager import ContextManager
from .gui_handler import GUIHandler
from .keyboard_listener import KeyboardListener
from .logging_config import setup_logging, LoggingManager
from .service_manager import ServiceManager
from .translation_engine import TranslationEngine
from .window_utils import get_active_window_title

"""
语言互译程序 - 重构版主程序
整合所有模块化组件，提供简洁的程序入口
"""

# 设置日志 - 将在load_configuration后初始化
logger = logging.getLogger(__name__)

# 配置文件路径
CONFIG_FILE = get_config_file_path()
MODE_CONFIG_FILE = get_mode_config_file_path()

# 全局应用实例引用（用于异常处理器回调）
APP_INSTANCE: Optional[Any] = None

# 全局关闭锁和状态标志
_shutdown_lock = threading.Lock()
_is_shutting_down = False


class GlobalExceptionHandler:
    """全局异常处理器"""

    def __init__(self) -> None:
        self.original_excepthook = sys.excepthook
        self.exception_count = 0
        self.max_exceptions = 10  # 最大异常数量，防止异常循环
        # 用于在异常发生时回调到应用实例
        self.app: Optional[Any] = None

    def setup(self) -> None:
        """设置全局异常处理器"""
        sys.excepthook = self.handle_exception
        threading.excepthook = self.handle_thread_exception
        logger.info("全局异常处理器已设置")

    def handle_exception(
        self, exc_type: Any, exc_value: Any, exc_traceback: Any
    ) -> None:
        """处理主线程异常"""
        self.exception_count += 1

        # 防止异常处理器本身出现异常导致的无限循环
        if self.exception_count > self.max_exceptions:
            print(f"异常处理器达到最大处理次数({self.max_exceptions})，程序将退出")
            logger.critical(
                f"[异常监控] 异常处理器达到最大处理次数({self.max_exceptions})，检测到可能的递归异常，程序将强制退出"
            )
            os._exit(1)

        logger.warning(
            f"[异常监控] 异常计数器: {self.exception_count}/{self.max_exceptions}, 异常类型: {exc_type.__name__}"
        )

        # 忽略KeyboardInterrupt，让程序正常处理
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("用户中断程序执行")
            if self.app:
                self.app.graceful_shutdown()
            return

        # 记录异常信息
        error_msg = f"未捕获的异常: {exc_type.__name__}: {exc_value}"
        logger.error(error_msg, exc_info=(exc_type, exc_value, exc_traceback))

        # 尝试保存错误报告
        try:
            self.save_error_report(exc_type, exc_value, exc_traceback)
        except Exception as e:
            logger.error(f"保存错误报告失败: {e}")

        # 显示用户友好的错误信息
        print(f"\n程序遇到意外错误：{exc_type.__name__}")
        print(f"错误详情：{exc_value}")
        print("\n错误信息已记录到日志文件中。")
        print("如果问题持续存在，请联系技术支持。")

        # 尝试优雅关闭
        if self.app:
            self.app.graceful_shutdown()

        # 最后调用原始异常处理器
        self.original_excepthook(exc_type, exc_value, exc_traceback)

    def handle_thread_exception(self, args: Any) -> None:
        """处理线程异常"""
        exc_type = args.exc_type
        exc_value = args.exc_value
        exc_traceback = args.exc_traceback
        thread = args.thread

        # 记录线程异常
        error_msg = (
            f"线程 {thread.name} 中的未捕获异常: {exc_type.__name__}: {exc_value}"
        )
        logger.error(error_msg, exc_info=(exc_type, exc_value, exc_traceback))

        # 对于关键线程的异常，可能需要重启或退出程序
        critical_threads = ["keyboard_listener", "console_interface", "asyncloopthread"]
        if any(name in thread.name.lower() for name in critical_threads):
            logger.critical(f"关键线程 {thread.name} 异常，程序将执行关闭")
            if self.app:
                self.app.graceful_shutdown()

    def save_error_report(
        self, exc_type: Any, exc_value: Any, exc_traceback: Any
    ) -> None:
        """保存错误报告到文件"""
        try:
            error_file = os.path.join(get_application_path(), "error_report.txt")
            with open(error_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 50}\n")
                f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"类型: {exc_type.__name__}\n")
                f.write(f"信息: {exc_value}\n")
                f.write("堆栈:\n")
                traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
                f.write(f"{'=' * 50}\n")
            logger.info(f"错误报告已保存到: {error_file}")
        except Exception as e:
            logger.error(f"保存错误报告失败: {e}")

    def restore(self) -> None:
        """恢复原始异常处理器"""
        sys.excepthook = self.original_excepthook
        logger.info("已恢复原始异常处理器")


def _load_config_generic(
    filename: str,
    default_generator: Callable[..., Any],
    default_getter: Callable[..., Dict[str, Any]],
    post_processor: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """通用配置加载函数"""
    try:
        if not os.path.exists(filename):
            logger.warning(f"配置文件 {filename} 不存在，正在生成默认配置...")
            if default_generator(force_overwrite=False):
                logger.info(f"默认配置文件已生成: {filename}")
                if os.path.exists(filename):
                    return _load_config_generic(
                        filename, default_generator, default_getter, post_processor
                    )
            logger.error("生成默认配置文件失败，使用内存中的默认配置")
            return default_getter()

        yaml = YAML()
        with open(filename, "r", encoding="utf-8") as f:
            config_data = yaml.load(f)

        if not config_data:
            logger.warning(f"配置文件 {filename} 为空，重新生成默认配置")
            if default_generator(force_overwrite=True):
                return _load_config_generic(
                    filename, default_generator, default_getter, post_processor
                )
            else:
                return default_getter()

        config_dict = dict(config_data)
        if post_processor:
            config_dict = post_processor(config_dict)

        logger.info(f"配置文件 {filename} 加载成功")
        return config_dict

    except Exception as e:
        logger.error(f"加载配置文件 {filename} 失败: {e}")
        logger.warning("将使用默认配置")
        return default_getter()


def load_config(filename: str = CONFIG_FILE) -> Dict[str, Any]:
    """加载主配置文件"""
    return _load_config_generic(
        filename, generate_default_main_config, get_default_config_dict
    )


def save_config(
    config: Union[Dict[str, Any], Config], filename: str = CONFIG_FILE
) -> bool:
    """保存配置到文件"""
    try:
        if isinstance(config, Config):
            config_dict = config.model_dump()
        else:
            config_dict = config
        return save_main_config(config_dict, filename)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False


def load_mode_config(filename: str = MODE_CONFIG_FILE) -> Dict[str, Any]:
    """加载模式配置文件"""
    return _load_config_generic(
        filename,
        generate_default_mode_config,
        get_default_mode_config_dict,
        post_processor=complete_language_features_and_tones_in_dict,
    )


class TranslationApp:
    """翻译应用程序主类"""

    def __init__(self) -> None:
        """初始化翻译应用程序"""
        self.config: Optional[Config] = None
        # DearPyGui不需要root窗口
        self.translation_engine: Optional[TranslationEngine] = None
        self.service_manager: Optional[ServiceManager] = None
        self.cache_manager: Optional[CacheManager] = None
        self.gui_handler: Optional[GUIHandler] = None
        self.keyboard_listener: Optional[KeyboardListener] = None
        self.cleanup_manager: Optional[ScheduledCleanupManager] = None

        # 控制标志
        self.exiting = False  # 旧的标志，将被 _is_shutting_down 替代
        self.console_thread: Optional[threading.Thread] = None
        self.async_loop_thread: Optional[AsyncLoopThread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # 全局异常处理器
        self.exception_handler = GlobalExceptionHandler()

        # 将当前应用实例交给异常处理器，便于异常时回调
        self.exception_handler.app = self

        # 注册到全局变量，作为兜底方案
        global APP_INSTANCE
        APP_INSTANCE = self

        logger.info("翻译应用程序初始化开始")

    def setup_async_loop(self) -> None:
        """设置并启动在专用线程中运行的异步事件循环。"""
        from .async_utils import AsyncLoopThread

        self.async_loop_thread = AsyncLoopThread()
        self.async_loop_thread.start()
        # 等待循环成功启动并获取循环对象的引用
        self.loop = self.async_loop_thread.get_loop()
        logger.info(
            f"异步事件循环已在线程 '{self.async_loop_thread.name}' (ID: {self.async_loop_thread.ident}) 中启动。"
        )

    def _start_scheduled_cleanup(self) -> None:
        """启动定时清理管理器"""
        current_thread_name = threading.current_thread().name
        try:
            if not self.config or not self.loop:
                logger.warning(
                    f"[{current_thread_name}] 配置或事件循环未初始化，无法启动定时清理管理器"
                )
                return

            # 获取缓存管理器
            cache_manager = None
            if self.translation_engine and hasattr(
                self.translation_engine, "cache_manager"
            ):
                cache_manager = self.translation_engine.cache_manager

            # 只有在缓存管理器可用时才创建 ScheduledCleanupManager
            if cache_manager:
                # 创建定时清理管理器
                cleanup_interval_hours = getattr(
                    self.config, "cache_cleanup_interval_hours", 1
                )
                self.cleanup_manager = ScheduledCleanupManager(
                    config=self.config,
                    cache_manager=cache_manager,
                    loop=self.loop,
                    cleanup_interval_hours=cleanup_interval_hours,
                )

                # 启动定时清理
                self.cleanup_manager.start()
                logger.info(f"[{current_thread_name}] 定时清理管理器已启动")
            else:
                logger.warning(
                    f"[{current_thread_name}] 缓存管理器未初始化，跳过定时清理管理器的创建和启动"
                )

        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 启动定时清理管理器失败: {e}", exc_info=True
            )

    def load_configuration(self) -> None:
        """加载配置"""
        try:
            # 1. 确保所有默认配置文件都已生成
            logger.info("开始检查并生成默认配置文件...")
            generate_default_main_config()
            generate_default_mode_config()
            from .config_management import generate_default_models_config

            generate_default_models_config()
            logger.info("默认配置文件检查与生成完成。")

            # 2. 检查是否需要提示输入API密钥
            models_config = load_models_config()
            api_key_found = False
            if models_config:
                for provider_config in models_config.values():
                    if provider_config.get("api_key", "").strip():
                        api_key_found = True
                        break

            if not api_key_found:
                logger.info("未在 models.yaml 中发现任何API密钥，开始提示用户输入。")
                prompt_and_update_api_key()
            else:
                logger.info("在 models.yaml 中已找到API密钥，跳过输入提示。")

            # 3. 加载主配置文件
            config_data = load_config()

            # 4. 使用增强的 pydantic 验证和创建 Config 实例
            try:
                self.config = Config.validate_config(config_data)
                logger.debug("配置验证通过")
            except Exception as validation_err:
                logger.error(f"配置验证失败: {validation_err}")
                logger.warning("将使用默认配置")
                default_config_data = get_default_config_dict()
                try:
                    self.config = Config.validate_config(default_config_data)
                    logger.info("默认配置验证通过")
                except Exception as default_validation_err:
                    logger.critical(f"默认配置验证也失败: {default_validation_err}")
                    logger.critical("程序无法继续运行，将退出")
                    raise RuntimeError("配置系统初始化失败") from default_validation_err

            # 5. 初始化日志系统
            assert self.config is not None, "配置对象未初始化"
            setup_logging(self.config)

            logger.info(LogMessages.CONFIG_LOADED)
            logger.info(f"调试模式: {'开启' if self.config.debug_mode else '关闭'}")
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            raise

    def setup_gui(self) -> None:
        """设置PyQt6组件（仅主线程）。若在非主线程或初始化失败，则禁用 GUI 进度并继续运行。"""
        thread_name = threading.current_thread().name
        logger.debug(f"[{thread_name}] 开始设置PyQt6组件...")
        try:
            if threading.current_thread() is not threading.main_thread():
                raise RuntimeError(
                    "GUI 初始化必须在主线程执行；已自动禁用 GUI 进度指示器"
                )
            # 创建PyQt6处理器，无需root窗口
            self.gui_handler = GUIHandler(None, self.config)
            logger.info(f"[{thread_name}] PyQt6组件设置完成。")
        except Exception as e:
            logger.warning(
                f"[{thread_name}] GUI 初始化失败或非主线程：{e}，将禁用 GUI 进度。"
            )
            # 降级：禁用 GUI 进度，允许无 GUI 模式运行
            if self.config is not None and hasattr(self.config, "show_gui_progress"):
                try:
                    setattr(self.config, "show_gui_progress", False)
                except Exception:
                    pass
            self.gui_handler = None

    def setup_services(self) -> None:
        """设置服务组件"""
        if self.config is None:
            raise RuntimeError("配置未加载，无法设置服务组件")

        # 1. 创建缓存管理器
        self.cache_manager = CacheManager(self.config)

        # 2. 创建翻译引擎，并传入缓存管理器
        self.translation_engine = TranslationEngine(
            self.config, self.get_mode_config(), self.cache_manager, self.loop
        )

        # 3. 创建服务管理器，并传入API管理器和缓存管理器
        self.service_manager = ServiceManager(
            config=self.config,
            api_manager=self.translation_engine.api_manager,
            cache_manager=self.cache_manager,
        )

        # 4. 更新翻译引擎中的服务管理器引用
        self.translation_engine.service_manager = self.service_manager

        logger.debug("服务组件设置完成")

    def setup_keyboard_listener(self) -> None:
        """设置键盘监听器

        放宽对 GUI 的强制依赖，允许在无 GUI 环境下运行键盘监听。
        仅强校验配置、翻译引擎与事件循环。"""
        logger.debug(f"[{threading.current_thread().name}] 开始设置键盘监听器...")
        if self.config is None:
            raise RuntimeError("配置未加载，无法设置键盘监听器")
        if self.translation_engine is None:
            raise RuntimeError("翻译引擎未初始化，无法设置键盘监听器")
        if self.loop is None:
            raise RuntimeError("异步事件循环未初始化，无法设置键盘监听器")

        # 创建一个简化的翻译器接口供键盘监听器使用
        translator_interface = TranslatorInterface(
            self.config, self.translation_engine, self.gui_handler, self.loop
        )

        # 创建键盘监听器
        self.keyboard_listener = KeyboardListener(translator_interface, self.config)
        if self.keyboard_listener:  # 添加None检查
            self.keyboard_listener.start()
            logger.info(f"[{threading.current_thread().name}] 键盘监听器已启动。")

        logger.info(f"[{threading.current_thread().name}] 键盘监听器设置完成。")

    def get_mode_config(self) -> Dict[str, Any]:
        """获取模式配置"""
        try:
            return load_mode_config()
        except Exception as e:
            logger.error(f"获取模式配置失败: {e}")
            # 返回默认配置
            return {
                "translation_modes": {
                    1: {
                        "source_lang": "中文",
                        "target_lang": "英语",
                        "source_code": "zh",
                        "target_code": "en",
                        "default_lang": "English",
                        "style": "",
                    }
                },
                "supported_langs": {"zh": "Chinese", "en": "English"},
                "language_features": {},
                "tone_particles": {},
            }

    def setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        try:

            def signal_handler(sig: int, frame: Any) -> None:
                logger.info(f"接收到信号 {sig}，准备优雅退出")
                self.graceful_shutdown()

            # 仅在主线程设置信号处理器，避免 ValueError
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGINT, signal_handler)
                signal.signal(signal.SIGTERM, signal_handler)
                logger.debug("信号处理器设置完成（主线程）")
            else:
                logger.warning(
                    f"当前线程 {threading.current_thread().name} 非主线程，跳过信号处理器设置"
                )
        except (ImportError, AttributeError) as e:
            logger.warning(f"无法设置信号处理器: {e}")
        except Exception as e:
            logger.warning(f"设置信号处理器时出现未知错误: {e}")

    def start_console_interface(self) -> None:
        """启动控制台界面"""
        logger.debug(f"[{threading.current_thread().name}] 开始启动控制台界面...")

        def run_console() -> None:
            """运行控制台界面"""
            try:
                logger.info(f"[{threading.current_thread().name}] 控制台线程已启动。")
                # PyInstaller打包环境下的控制台输入处理
                # 在打包环境中，isatty()可能返回False，但我们仍需处理用户输入

                while not _is_shutting_down:
                    # 直接显示翻译模式选择菜单
                    self.show_translation_mode_menu()
                    try:
                        # 在PyInstaller环境中，使用更健壮的输入处理
                        choice = input().strip()
                        self.handle_translation_mode_choice(choice)
                    except (EOFError, OSError):
                        # PyInstaller环境下可能出现的输入错误
                        if not _is_shutting_down:
                            print("输入流已关闭，继续运行...")
                            break
                    except KeyboardInterrupt:
                        logger.info(
                            f"[{threading.current_thread().name}] 用户请求退出程序"
                        )
                        self.graceful_shutdown()
                        break
                    except Exception as e:
                        # 捕获其他可能的异常
                        logger.warning(f"控制台输入处理异常: {e}")
                        if not _is_shutting_down:
                            print("输入处理出错，请重试")

                    # 使用非阻塞方式替代time.sleep，减少CPU占用
                    threading.Event().wait(0.1)
                    gc.collect()
            except Exception as e:
                logger.error(f"[{threading.current_thread().name}] 控制台线程异常: {e}")
                self.graceful_shutdown()

        # 启动控制台线程
        self.console_thread = threading.Thread(
            target=run_console, daemon=True, name="ConsoleInterfaceThread"
        )
        self.console_thread.start()
        logger.info(
            f"[{threading.current_thread().name}] 控制台界面已在线程 '{self.console_thread.name}' (ID: {self.console_thread.ident}) 中启动。"
        )

    def show_main_menu(self) -> None:
        """显示主菜单"""
        if self.config is None:
            print("配置未加载")
            return

        current_mode = getattr(self.config, "translation_mode", 1)
        mode_config = self.get_mode_config()
        mode_desc = "未知模式"

        if current_mode in mode_config.get("translation_modes", {}):
            mode_data = mode_config["translation_modes"][current_mode]
            mode_desc = f"{mode_data.get('source_lang', '未知')}-{mode_data.get('target_lang', '未知')}"
            if mode_data.get("style"):
                mode_desc += f"-{mode_data['style']}"

        print(f"\n当前翻译模式: {current_mode} ({mode_desc})")
        print(ConsoleMenus.MAIN_MENU)

    def show_translation_mode_menu(self) -> None:
        """显示翻译模式选择菜单"""
        if self.config is None:
            print("配置未加载")
            return

        current_mode = getattr(self.config, "translation_mode", 1)
        mode_config = self.get_mode_config()
        available_modes = mode_config.get("translation_modes", {})

        # 构建模式描述
        mode_desc = "未知模式"
        if current_mode in available_modes:
            mode_data = available_modes[current_mode]
            mode_desc = f"{mode_data.get('source_lang', '未知')}-{mode_data.get('target_lang', '未知')}"
            if mode_data.get("style"):
                mode_desc += f"-{mode_data['style']}"

        # 构建可用模式列表
        available_modes_text = []
        for mode_id, mode_data in available_modes.items():
            desc = f"{mode_data.get('source_lang', '未知')}-{mode_data.get('target_lang', '未知')}"
            if mode_data.get("style"):
                desc += f"-{mode_data['style']}"
            available_modes_text.append(f"{mode_id}. {desc}")

        print(
            ConsoleMenus.TRANSLATION_MODE_MENU.format(
                current_mode=current_mode,
                mode_desc=mode_desc,
                available_modes="\n".join(available_modes_text),
            )
        )

    def handle_console_choice(self, choice: str) -> None:
        """处理控制台选择"""
        if choice == "1":
            self.switch_translation_mode()
        elif choice == "2":
            if self.config:
                show_current_config(self.config)
            else:
                print("配置未加载")
        elif choice == "3":
            enter_settings_menu(self)
        elif choice == "4":
            enter_cache_menu(self)
        elif choice == "5":
            show_logs()
        elif choice == "6":
            if self.service_manager:
                network_diagnosis(self.service_manager)
            else:
                print("服务管理器未初始化，无法进行网络诊断。")
        elif choice == "7":
            if self.loop:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self.check_api_health(), self.loop
                    )
                    console_timeout = (
                        self.config.api_health_check.get("console_check_timeout", 60)
                        if self.config and self.config.api_health_check
                        else 60
                    )
                    future.result(timeout=console_timeout)
                except Exception as e:
                    print(f"API健康检查时发生错误: {e}")
            else:
                print("异步事件循环未初始化，无法进行API健康检查。")
        elif choice == "8" or choice.lower() in ["q", "quit", "exit"]:
            logger.info("用户请求退出程序")
            self.graceful_shutdown()
        else:
            print("无效选项，请重新选择")

    def handle_translation_mode_choice(self, choice: str) -> None:
        """处理翻译模式选择"""
        if choice.lower() in ["q", "quit", "exit"]:
            logger.info("用户从控制台请求退出程序")
            self.graceful_shutdown()
        elif choice == "0":
            # 进入设置菜单
            self.enter_settings_from_mode_menu()
        elif choice == "00":
            # 快速清除所有缓存
            quick_clear_all_cache(self)
        else:
            # 尝试切换翻译模式
            if self.config is None:
                print("配置未加载，无法切换翻译模式")
                return

            try:
                mode_id = int(choice)
                mode_config = self.get_mode_config()
                available_modes = mode_config.get("translation_modes", {})

                if mode_id in available_modes:
                    old_mode = getattr(self.config, "translation_mode", 1)
                    setattr(self.config, "translation_mode", mode_id)

                    # 保存配置
                    save_main_config(self.config.model_dump())

                    mode_data = available_modes[mode_id]
                    mode_desc = f"{mode_data.get('source_lang', '未知')}-{mode_data.get('target_lang', '未知')}"
                    if mode_data.get("style"):
                        mode_desc += f"-{mode_data['style']}"

                    print(f"翻译模式已切换: {old_mode} → {mode_id} ({mode_desc})")
                    logger.info(f"翻译模式已切换: {old_mode} → {mode_id}")
                else:
                    print(f"无效的模式编号: {mode_id}")
            except ValueError:
                print("请输入有效的数字或命令")

    def enter_settings_from_mode_menu(self) -> None:
        """从翻译模式菜单进入设置菜单"""
        print("\n=== 进入设置菜单 ===")
        enter_settings_menu(self)

    def switch_translation_mode(self) -> None:
        """切换翻译模式"""
        if self.config is None:
            print("配置未加载，无法切换翻译模式")
            return

        mode_config = self.get_mode_config()
        available_modes = mode_config.get("translation_modes", {})

        print("\n=== 翻译模式选择 ===")
        print(f"当前模式: {getattr(self.config, 'translation_mode', 1)}")
        print("可用模式:")

        for mode_id, mode_data in available_modes.items():
            desc = f"{mode_data.get('source_lang', '未知')}-{mode_data.get('target_lang', '未知')}"
            if mode_data.get("style"):
                desc += f"-{mode_data['style']}"
            print(f"{mode_id}. {desc}")

        try:
            choice = int(input("请输入模式编号: ").strip())
            if choice in available_modes:
                setattr(self.config, "translation_mode", choice)
                save_config(self.config)
                logger.info(f"已切换到翻译模式 {choice}")
                print(f"已切换到模式 {choice}")
            else:
                print("无效的模式编号")
        except ValueError:
            print("请输入有效的数字")

    async def check_api_health(self) -> None:
        """检查API健康状态，通过实际调用进行测试"""
        if not (
            self.translation_engine
            and self.translation_engine.api_manager
            and self.loop
        ):
            print("服务未完全初始化，无法检查API健康状态。")
            return

        api_manager = self.translation_engine.api_manager
        if not api_manager.providers:
            print("未找到任何配置了API密钥的提供商。")
            return

        # 统计总模型数（所有提供商下的模型实例总数）
        try:
            total_models = sum(len(models) for models in api_manager.providers.values())
        except Exception:
            total_models = len(api_manager.providers)

        print(f"发现 {total_models} 个已配置的API模型，将逐一检查...")

        async def check_single_model(
            provider_group: str, model_provider: Any
        ) -> tuple[str, bool, str]:
            model_id = (getattr(model_provider, "model_info", {}) or {}).get("model_id")
            provider_name = (
                f"{type(model_provider).__name__} ({model_id}) [组: {provider_group}]"
            )
            print(f"正在检查: {provider_name}...")

            if not getattr(model_provider, "api_key", None):
                return (provider_name, False, "跳过: API密钥未配置")

            start_time = time.time()
            try:
                # 使用一个简单、低成本的prompt进行测试
                test_prompt = "Hi"
                result = await model_provider.translate(test_prompt)
                response_time = time.time() - start_time

                # 处理不同的返回类型，使用防御性编程
                success = False
                failure_reason = ""

                if result is None:
                    success = False
                    failure_reason = "返回结果为空"
                    logger.debug(f"[健康检查调试] 结果为空: {result}")
                elif isinstance(result, dict):
                    # 如果结果是字典，检查processed字段
                    processed_value = result.get("processed")
                    logger.debug(f"[健康检查调试] 字典result内容: {result}")
                    logger.debug(
                        f"[健康检查调试] processed字段类型: {type(processed_value)}, 值: {processed_value[:200] + '...' if isinstance(processed_value, str) and len(processed_value) > 200 else processed_value}"
                    )

                    # 检查processed字段的有效性 - 根据实际API返回格式调整
                    if processed_value is not None and isinstance(processed_value, str):
                        # 如果processed是字符串，检查是否成功（不以"翻译失败"开头且不为空）
                        if processed_value.strip() and not processed_value.startswith(
                            "翻译失败"
                        ):
                            success = True
                        else:
                            success = False
                            failure_reason = (
                                f"翻译结果无效: '{processed_value[:100]}...'"
                            )
                            logger.debug(
                                f"[健康检查调试] 翻译失败，原因: '{processed_value}'"
                            )
                    elif isinstance(processed_value, bool):
                        # 保持向后兼容，如果确实是bool值
                        success = processed_value
                        if not success:
                            failure_reason = result.get(
                                "message", f"处理失败: {result}"
                            )
                    else:
                        success = False
                        failure_reason = f"字典结果processed字段类型无效: 类型={type(processed_value)}, 值={processed_value}"
                        logger.debug(
                            f"[健康检查调试] processed字段类型检查失败: {failure_reason}"
                        )
                elif isinstance(result, str):
                    # 字符串结果：检查是否成功
                    if not result.startswith("翻译失败"):
                        success = True
                    else:
                        success = False
                        failure_reason = result
                else:
                    # 其他类型都视为失败
                    success = False
                    failure_reason = (
                        f"不支持的结果类型 {type(result).__name__}: {result}"
                    )

                if success:
                    return (
                        provider_name,
                        True,
                        f"成功 (响应时间: {response_time:.2f}s)",
                    )
                else:
                    if not failure_reason:
                        failure_reason = f"失败: {result}"
                    return (provider_name, False, failure_reason)

            except Exception as e:
                return (provider_name, False, f"异常: {e}")

        # 为每个提供商下的每个模型创建检查任务
        check_tasks = []
        for provider_group, model_list in api_manager.providers.items():
            for model_provider in model_list:
                check_tasks.append(check_single_model(provider_group, model_provider))

        if not check_tasks:
            print("没有可供检查的API模型。")
            return

        check_results = await asyncio.gather(*check_tasks, return_exceptions=True)

        for result in check_results:
            if isinstance(result, Exception):
                logger.error(f"健康检查任务中发生未捕获的异常: {result}")
                print("\n--- 结果: 检查任务异常 ---")
                print("状态: 异常")
                print(f"详情: {result}")
                continue

            if not isinstance(result, tuple) or len(result) != 3:
                logger.error(f"健康检查返回格式错误: {result}")
                continue

            provider_name, is_healthy, message = result
            status = "正常" if is_healthy else "异常"
            print(f"\n--- 结果: {provider_name} ---")
            print(f"状态: {status}")
            print(f"详情: {message}")

    def graceful_shutdown(
        self, signum: Optional[int] = None, frame: Optional[Any] = None
    ) -> None:
        """
        实现有序、同步的关闭流程，解决线程竞态问题。
        """
        global _is_shutting_down
        with _shutdown_lock:
            if _is_shutting_down:
                return
            _is_shutting_down = True

        # 使用 print 是因为 logger 自身也可能在关闭过程中被终止
        print("程序正在关闭，请稍候...")
        logger.info(f"[{threading.current_thread().name}] {LogMessages.SHUTDOWN}")

        # 1. 停止所有事件源，防止新任务产生
        print("  - 停止事件监听...")
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            logger.info("键盘监听器已停止。")
        if self.console_thread and self.console_thread.is_alive():
            # 控制台线程通过 _is_shutting_down 标志退出，这里仅记录
            logger.info("控制台界面将退出。")

        # 2. 停止所有服务（例如缓存的写入和API健康检查）
        print("  - 停止核心服务...")
        if self.service_manager:
            self.service_manager.shutdown_services()  # 这个方法应该是同步阻塞的
            logger.info("服务管理器已停止所有服务。")

        # 3. 安全地请求GUI退出
        print("  - 关闭图形界面...")
        if self.gui_handler:
            self.gui_handler.safe_quit()
            time.sleep(0.5)  # 给Qt事件循环一点时间来处理退出请求
            logger.info("已发送GUI退出请求。")

        # 4. 最后关闭异步核心（确保所有日志和网络请求都已处理）
        print("  - 关闭异步处理核心...")
        if self.async_loop_thread:
            self.async_loop_thread.stop()
            logger.info("异步核心已停止。")

        # 5. 等待关键子线程完全结束
        print("  - 等待所有线程结束...")
        current_thread = threading.current_thread()
        threads_to_join = [self.console_thread, self.async_loop_thread]
        for thread in threads_to_join:
            if thread and thread.is_alive() and thread is not current_thread:
                try:
                    logger.debug(f"等待线程 {thread.name} 结束...")
                    thread.join(timeout=5.0)
                    if thread.is_alive():
                        logger.warning(f"线程 {thread.name} 在超时后仍未结束。")
                    else:
                        logger.info(f"线程 {thread.name} 已成功结束。")
                except Exception as e:
                    logger.error(f"等待线程 {thread.name} 时发生错误: {e}")

        print("所有组件已成功关闭。")
        logger.info("所有资源释放完毕，程序即将退出。")

    def run(self) -> None:
        """运行应用程序 - 优化启动性能"""
        try:
            # 设置全局异常处理器
            self.exception_handler.setup()

            # 优化启动：分阶段初始化组件
            logger.info("开始快速启动流程...")

            # 第一阶段：核心组件初始化
            self.load_configuration()  # 先加载配置
            self.setup_async_loop()  # 设置异步循环

            # 第二阶段：延迟初始化非关键组件
            self._delayed_initialization()

            # 显示启动消息
            logger.info("程序已启动，等待用户操作...")

            # 启动PyQt6事件循环以支持GUI显示
            try:
                app = QApplication.instance()
                if app is None:
                    # 如果没有实例，可以创建一个，但这通常不应该发生
                    # 在我们的场景下，我们只是检查是否存在
                    logger.info("未检测到PyQt6应用，使用传统循环保持程序运行")
                    while not _is_shutting_down:
                        time.sleep(1)
                else:
                    logger.info("检测到PyQt6应用，进入事件循环以支持GUI显示")
                    app.exec()
            except KeyboardInterrupt:
                logger.info("接收到键盘中断，准备退出")
                self.graceful_shutdown()

        except Exception as e:
            logger.error(f"应用程序运行异常: {e}")
            raise
        finally:
            self.graceful_shutdown()
            # 确保所有线程结束后再关闭日志系统
            LoggingManager.shutdown()

    def _delayed_initialization(self) -> None:
        """延迟初始化非关键组件，提高启动速度"""
        try:
            logger.debug("开始延迟初始化组件...")

            # 在主线程中初始化GUI组件（必须在主线程中）
            self.setup_gui()

            # 设置信号处理器（必须在主线程中）
            self.setup_signal_handlers()

            # 在后台线程中初始化其他组件
            def init_background_components() -> None:
                try:
                    # 初始化服务组件
                    self.setup_services()

                    # 启动服务管理器（这会启动缓存的后台线程）
                    if self.service_manager:
                        self.service_manager.start_services()

                    # 异步初始化翻译引擎组件
                    if self.translation_engine and self.loop:
                        try:
                            logger.debug("开始异步初始化翻译引擎...")
                            future = asyncio.run_coroutine_threadsafe(
                                self.translation_engine.async_init(), self.loop
                            )
                            future.result(timeout=10)  # 等待初始化完成
                            logger.info("翻译引擎异步初始化完成。")

                            # 在翻译引擎初始化后启动定时清理
                            self._start_scheduled_cleanup()

                        except Exception as init_err:
                            logger.error(f"翻译引擎异步初始化失败: {init_err}")

                    # 初始化键盘监听器
                    self.setup_keyboard_listener()

                    # 先执行初始检查，再启动控制台界面，确保检查日志先于菜单输出
                    if self.loop:
                        try:
                            logger.debug(
                                "等待初始网络与API健康检查完成后再启动控制台界面..."
                            )
                            future = asyncio.run_coroutine_threadsafe(
                                self._async_check_initial_status(), self.loop
                            )
                            # 设置上限等待时间，避免极端情况下卡住启动流程
                            startup_timeout = (
                                self.config.api_health_check.get(
                                    "startup_check_timeout", 15
                                )
                                if self.config and self.config.api_health_check
                                else 15
                            )
                            future.result(timeout=startup_timeout)
                            logger.debug("初始检查完成，准备启动控制台界面。")
                        except Exception as wait_err:
                            logger.warning(
                                f"初始检查等待超时或失败({type(wait_err).__name__})，将继续启动控制台界面"
                            )
                    else:
                        logger.debug("事件循环未就绪，跳过初始检查等待。")

                    # 启动控制台界面（放在初始检查之后）
                    self.start_console_interface()

                    logger.debug("后台组件初始化完成")

                except Exception as e:
                    logger.error(f"后台组件初始化失败: {e}")

            # 在后台线程中执行非GUI组件初始化
            init_thread = threading.Thread(
                target=init_background_components, daemon=True
            )
            init_thread.start()

            logger.debug("延迟初始化完成")

        except Exception as e:
            logger.error(f"延迟初始化失败: {e}")

    async def _async_check_initial_status(self) -> None:
        """异步检查初始状态"""
        print("\n" + "=" * 60)
        print(" 开始初始化检查 - 系统状态检测")
        print("=" * 60)

        try:
            if not self.service_manager or not self.config:
                print(" 服务管理器或配置未初始化")
                logger.error("服务管理器或配置未初始化")
                return

            print(" 正在检查网络连接...")
            is_network_ok = self.service_manager.is_network_connected()

            if is_network_ok:
                print(" 网络连接正常")
                logger.info("网络连接正常")

                # 调用新的API健康检查方法，该方法会从models.yaml读取并遍历所有有效提供商
                await self.check_api_health()
            else:
                print(" 网络连接不可用")
                print("  警告: 无法连接到互联网，这可能会影响翻译功能")
                logger.warning("网络连接不可用，可能会影响翻译功能")

        except Exception as e:
            print(f" 初始状态检查失败: {e}")
            logger.error(f"检查初始状态失败: {e}", exc_info=True)

        finally:
            print("=" * 60)
            print(" 初始化检查完成，程序正在启动...")
            print("=" * 60 + "\n")


class TranslatorInterface:
    """翻译器接口，为键盘监听器提供简化的翻译器接口"""

    def __init__(
        self,
        config: Config,
        translation_engine: TranslationEngine,
        gui_handler: Optional[GUIHandler],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """初始化翻译器接口

        Args:
            config: 配置对象
            translation_engine: 翻译引擎
            gui_handler: GUI处理器
            loop: 异步事件循环
        """
        self.config = config
        # 明确类型注解，确保Pylance正确解析为核心实现类
        from core.translation_engine import (
            TranslationEngine as TEType,
        )  # 延迟导入避免循环

        self.translation_engine: TEType = translation_engine
        self.gui_handler = gui_handler
        self.loop = loop
        self.in_progress = False
        self.suppress_keyboard = False
        # 用于管理后台异步任务，防止任务泄露
        self.background_tasks: set[asyncio.Task[Any]] = set()

    async def _post_translation_tasks(
        self,
        original_text: str,
        result: str,
        translation_source: str,
        window_title: str,
        translation_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """翻译完成后的后续任务（缓存保存、历史记录等）

        Args:
            original_text: 原始文本
            result: 翻译结果
            translation_source: 翻译来源 ('api', 'cache', 'error')
            window_title: 窗口标题
            translation_info: 翻译信息，包含语言检测结果等
        """
        try:
            # 这些操作在后台异步执行，不影响用户界面响应
            logger.debug(f"开始执行翻译后续任务，翻译来源: {translation_source}")

            # 注意：缓存保存已在翻译引擎的相似度检测逻辑中完成
            # 这里不再重复保存缓存，避免重复写入
            if translation_source == "api":
                logger.debug("[API翻译结果] 缓存保存已在翻译引擎中完成")
            else:
                logger.debug(f"翻译来源为 {translation_source}，无需保存缓存")

            # 添加到历史记录（所有成功的翻译都添加到历史记录）
            if translation_source == "api":
                # 确定当前翻译的方向
                direction = "ME→Counterpart"  # 默认方向
                if translation_info:
                    direction = translation_info.get("direction", direction)

                # 保存翻译结果到上下文文件
                try:
                    context_manager = ContextManager()
                    # 传递方向信息到 ContextManager
                    await context_manager.save_translation_pair(
                        self.config, window_title, original_text, result, direction
                    )
                    logger.debug("翻译对已保存到上下文文件。")
                except Exception as ctx_err:
                    logger.error(f"保存上下文文件失败: {ctx_err}")

            logger.debug("翻译后续任务完成")

        except Exception as e:
            logger.error(f"执行翻译后续任务时发生错误: {e}")

    async def replacement_translation(self) -> None:
        """执行替换翻译"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始执行替换翻译流程。")
        original_text = None
        window_title = "unknown_window"
        try:
            # ------------------------------------------------------------------
            # 1. 检测当前活动窗口标题，用于多窗口上下文区分
            # ------------------------------------------------------------------
            try:
                window_title_raw = get_active_window_title()
                if window_title_raw:
                    window_title = window_title_raw
                logger.debug(
                    f"[{current_thread_name}] 当前活动窗口标题: {window_title}"
                )
            except Exception as e:
                logger.error(
                    f"[{current_thread_name}] 获取窗口标题时发生异常: {e}，将使用默认上下文 'unknown_window'。"
                )
                # window_title 已经默认为 "unknown_window"

            # 预加载该窗口的历史上下文并注入到翻译引擎
            mode_id = self.translation_engine.config.translation_mode
            # 先清空旧上下文，确保不同聊天窗口上下文独立
            self.translation_engine.clear_context_for_mode(mode_id)

            context_manager = ContextManager()
            self.context_pairs = await context_manager.load_context_with_direction(
                window_title
            )
            logger.debug(
                f"[{current_thread_name}] 从上下文文件加载 {len(self.context_pairs)} 对历史翻译（含方向）。"
            )
            if self.translation_engine:
                self.translation_engine.add_to_history_batch(
                    mode_id, self.context_pairs
                )

            self.in_progress = True

            # 显示进度指示器
            if self.gui_handler and getattr(self.config, "show_gui_progress", False):
                logger.debug(f"[{current_thread_name}] 显示GUI进度指示器。")
                self.gui_handler.show_progress_indicator()
                self.gui_handler.update_progress_indicator("preparing", 10)

            # 获取剪贴板文本并保存原始内容
            original_text = pyperclip.paste()
            logger.debug(
                f"[{current_thread_name}] 从剪贴板获取文本，长度: {len(original_text) if original_text else 0}。"
            )

            if not original_text or not original_text.strip():
                logger.warning(f"[{current_thread_name}] 剪贴板为空或无有效文本。")
                if self.gui_handler and getattr(
                    self.config, "show_gui_progress", False
                ):
                    self.gui_handler.update_progress_indicator(
                        "error", 100, "剪贴板为空"
                    )
                    await asyncio.sleep(1)
                    self.gui_handler.hide_progress_indicator()
                return

            # 执行翻译
            logger.info(f"[{current_thread_name}] 调用翻译引擎进行翻译...")
            (
                result,
                translation_source,
                translation_info,
            ) = await self.translation_engine.translate_text_async(
                original_text, self.gui_handler
            )

            # 处理翻译结果：仅当来源明确为 API 或缓存，且未被中止时，才视为成功
            if (
                translation_source in ("api", "cache")
                and result is not None
                and result != ""
                and result != "翻译已中止"
            ):
                # 翻译成功：先全选当前内容，再粘贴翻译结果
                logger.info(
                    f"[{current_thread_name}] 翻译引擎返回结果，来源: {translation_source}。"
                )
                logger.info(f"[{current_thread_name}] 翻译成功，准备替换文本。")

                # 复制翻译结果到剪贴板
                pyperclip.copy(result)
                logger.debug(f"[{current_thread_name}] 翻译结果已复制到剪贴板。")

                # 先全选当前输入框内容，再粘贴新内容
                pyautogui.hotkey("ctrl", "a")  # 全选当前内容
                await asyncio.sleep(0.1)  # 短暂延迟确保全选完成
                pyautogui.hotkey("ctrl", "v")  # 粘贴翻译结果

                logger.info(f"[{current_thread_name}] 翻译完成并已替换。")

                # 完成进度并隐藏进度条
                if self.gui_handler and getattr(
                    self.config, "show_gui_progress", False
                ):
                    self.gui_handler.complete_progress_and_hide()
                    logger.debug(f"[{current_thread_name}] GUI进度指示器已完成并隐藏。")

                # 异步执行后续的历史记录操作，不阻塞主流程
                # 统一通过loop.create_task创建，确保在正确的循环中执行
                task = self.loop.create_task(
                    self._post_translation_tasks(
                        original_text,
                        result,
                        translation_source,
                        window_title,
                        translation_info,
                    )
                )
                self.background_tasks.add(task)
                task.add_done_callback(self.background_tasks.discard)
                logger.debug(f"[{current_thread_name}] 后续任务已异步启动。")
            else:
                # 翻译失败：恢复原始文本到输入框
                logger.error(f"[{current_thread_name}] 翻译失败: {result}")

                # 更新进度为错误状态并立即隐藏
                if self.gui_handler and getattr(
                    self.config, "show_gui_progress", False
                ):
                    self.gui_handler.update_progress_indicator("error", 100, "翻译失败")
                    logger.debug(f"[{current_thread_name}] GUI进度指示器显示错误状态。")
                    # 立即隐藏进度条，而不是等待
                    self.gui_handler.hide_progress_indicator()
                    logger.debug(f"[{current_thread_name}] GUI进度指示器已隐藏。")

                # 恢复原始文本到剪贴板
                pyperclip.copy(original_text)
                logger.debug(f"[{current_thread_name}] 原始文本已恢复到剪贴板。")

                # 先全选当前内容，再粘贴原始文本
                pyautogui.hotkey("ctrl", "a")  # 全选当前内容
                await asyncio.sleep(0.1)  # 短暂延迟确保全选完成
                pyautogui.hotkey("ctrl", "v")  # 粘贴原始文本

                logger.info(f"[{current_thread_name}] 已恢复原始文本到输入框。")

        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 替换翻译过程中发生异常: {e}", exc_info=True
            )

            # 异常情况下也尝试恢复原始文本
            if original_text:
                try:
                    pyperclip.copy(original_text)
                    pyautogui.hotkey("ctrl", "a")
                    await asyncio.sleep(0.1)
                    pyautogui.hotkey("ctrl", "v")
                    logger.info(f"[{current_thread_name}] 异常情况下已恢复原始文本。")
                except Exception as restore_error:
                    logger.error(
                        f"[{current_thread_name}] 恢复原始文本时发生错误: {restore_error}"
                    )

            # 显示错误状态
            if self.gui_handler and getattr(self.config, "show_gui_progress", False):
                self.gui_handler.update_progress_indicator("error", 100, "操作异常")
                await asyncio.sleep(1.5)
                self.gui_handler.hide_progress_indicator()
                logger.debug(f"[{current_thread_name}] 异常情况下GUI进度指示器已隐藏。")
        finally:
            self.in_progress = False
            # 确保在任何情况下（成功、失败、异常）都隐藏进度条
            if self.gui_handler and getattr(self.config, "show_gui_progress", False):
                if self.gui_handler.is_progress_showing():
                    logger.debug(
                        f"[{current_thread_name}] 翻译流程结束，确保隐藏进度条。"
                    )
                    self.gui_handler.hide_progress_indicator()

            print(
                "─────────────────────────────────── 翻译流程结束 ───────────────────────────────────"
            )
            logger.info(f"[{current_thread_name}] 替换翻译流程结束。")


def main() -> None:
    """主函数"""
    app = None
    try:
        app = TranslationApp()
        app.run()
    except KeyboardInterrupt:
        logger.info("捕获到 KeyboardInterrupt，程序将关闭。")
    except Exception as e:
        logger.critical(f"程序顶层出现未捕获的严重异常: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if app:
            # 确保在任何情况下都尝试进行一次最终的关闭
            app.graceful_shutdown()

        # 这是程序退出的绝对最后一步
        print("正在关闭日志系统...")
        LoggingManager.shutdown()
        print("程序已完全关闭。")


if __name__ == "__main__":
    main()
