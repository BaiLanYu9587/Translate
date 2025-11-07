"""
键盘监听模块
提供键盘事件监听和处理功能
增强版本：包含跨平台兼容性和错误处理
"""

import time
import asyncio
import logging
import platform
import threading
from typing import Optional, Tuple, Any
from pynput import keyboard  # type: ignore[import-untyped]

# 导入常量

logger = logging.getLogger(__name__)


class PlatformCompatibility:
    """平台兼容性检查和处理"""

    @staticmethod
    def get_platform_info() -> dict[str, str]:
        """获取平台信息"""
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        }

    @staticmethod
    def is_windows() -> bool:
        """是否为Windows系统"""
        return platform.system().lower() == "windows"

    @staticmethod
    def is_macos() -> bool:
        """是否为macOS系统"""
        return platform.system().lower() == "darwin"

    @staticmethod
    def is_linux() -> bool:
        """是否为Linux系统"""
        return platform.system().lower() == "linux"

    @staticmethod
    def check_keyboard_support() -> Tuple[bool, str]:
        """检查键盘监听支持"""
        try:
            # 尝试创建一个测试监听器
            test_listener = keyboard.Listener(on_press=lambda key: None)
            test_listener.start()
            test_listener.stop()
            return True, "键盘监听支持正常"
        except Exception as e:
            return False, f"键盘监听不支持: {e}"

    @staticmethod
    def get_platform_specific_config() -> dict[str, float | int]:
        """获取平台特定配置"""
        if PlatformCompatibility.is_windows():
            return {
                "mouse_exclusion_zone": 50,
                "trigger_timeout": 1.5,
                "trigger_cooldown": 2.0,
            }
        elif PlatformCompatibility.is_macos():
            return {
                "mouse_exclusion_zone": 30,
                "trigger_timeout": 1.2,
                "trigger_cooldown": 1.5,
            }
        elif PlatformCompatibility.is_linux():
            return {
                "mouse_exclusion_zone": 40,
                "trigger_timeout": 1.3,
                "trigger_cooldown": 1.8,
            }
        else:
            return {
                "mouse_exclusion_zone": 50,
                "trigger_timeout": 1.5,
                "trigger_cooldown": 2.0,
            }


class KeyboardListener:
    """键盘监听器，负责监听键盘事件并触发翻译"""

    def __init__(self, translator: Any, config: Any):
        """初始化键盘监听器

        Args:
            translator: 翻译器实例
            config: 配置对象
        """
        self.translator = translator
        self.config = config

        # 检查平台兼容性
        self.platform_info = PlatformCompatibility.get_platform_info()
        self.platform_config = PlatformCompatibility.get_platform_specific_config()

        # 检查键盘监听支持
        is_supported, support_msg = PlatformCompatibility.check_keyboard_support()
        if not is_supported:
            logger.error(f"键盘监听初始化失败: {support_msg}")
            raise RuntimeError(f"键盘监听不支持: {support_msg}")

        logger.info(
            f"平台信息: {self.platform_info['system']} {self.platform_info['release']}"
        )
        logger.info(f"键盘监听支持: {support_msg}")

        try:
            self.listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release,
                suppress=False,  # 不抑制按键事件
            )
            self.listener.daemon = True
        except Exception as e:
            logger.error(f"创建键盘监听器失败: {e}")
            raise

        # 空格键检测相关
        self.space_count: int = 0
        self.last_space_time: float = 0.0  # 明确类型为float
        self.last_trigger_time: float = 0.0  # 明确类型为float

        # 配置参数 - 使用平台特定配置
        listener_config = self.config.get("keyboard_listener", {})
        self.space_detection_timeout = listener_config.get("space_trigger_timeout", 1.0)
        self.trigger_cooldown = listener_config.get("space_trigger_cooldown", 2.0)
        self.required_space_count = listener_config.get("space_trigger_count", 3)
        self.mouse_exclusion_zone = listener_config.get("mouse_top_exclusion_zone", 50)
        # 新增：允许通过配置禁用顶部排除区检查，便于排障
        self.disable_mouse_top_exclusion = listener_config.get(
            "disable_mouse_top_exclusion", False
        )

        logger.debug(
            f"[{threading.current_thread().name}] 键盘监听器初始化完成，平台配置: {self.platform_config}"
        )

    def get_mouse_position(self) -> Optional[Tuple[int, int]]:
        """获取鼠标位置

        Returns:
            Optional[Tuple[int, int]]: 鼠标坐标(x, y)，如果获取失败则返回None
        """
        try:
            import pyautogui  # type: ignore[import-untyped]

            pos = pyautogui.position()
            return int(pos.x), int(pos.y)
        except Exception as e:
            logger.error(f"获取鼠标位置失败: {e}")
            return None

    def is_valid_trigger_position(self, mouse_pos: Optional[Tuple[int, int]]) -> bool:
        """检查鼠标位置是否适合触发翻译

        Args:
            mouse_pos: 鼠标位置

        Returns:
            bool: 是否适合触发
        """
        # 若显式禁用顶部区域排除，直接放行
        if getattr(self, "disable_mouse_top_exclusion", False):
            return True

        # 获取不到鼠标位置时，不再否决触发，只跳过顶部区域检查
        if mouse_pos is None:
            logger.debug("无法获取鼠标位置，跳过顶部区域检查。")
            return True

        # 如果鼠标在屏幕顶部区域，忽略触发
        if mouse_pos[1] < self.mouse_exclusion_zone:
            return False

        return True

    def should_ignore_keyboard_event(self) -> bool:
        """检查是否应该忽略键盘事件

        Returns:
            bool: 是否应该忽略
        """
        # 如果翻译器不可用，忽略键盘事件
        if not self.translator or not hasattr(self.translator, "config"):
            return True

        # 如果翻译器正在进行网络请求，且配置为忽略键盘事件，则拦截
        if getattr(self.translator, "suppress_keyboard", False):
            return True

        return False

    def update_space_count(self, current_time: float) -> None:
        """更新空格键计数

        Args:
            current_time: 当前时间
        """
        space_interval = current_time - self.last_space_time

        # 如果间隔过长，重置计数
        if space_interval > self.space_detection_timeout:
            self.space_count = 1
        else:
            self.space_count += 1

        self.last_space_time = current_time

    def is_in_cooldown(self, current_time: float) -> bool:
        """检查是否在冷却时间内

        Args:
            current_time: 当前时间

        Returns:
            bool: 是否在冷却时间内
        """
        return bool((current_time - self.last_trigger_time) < self.trigger_cooldown)

    def can_trigger_translation(self) -> bool:
        """检查是否可以触发翻译

        Returns:
            bool: 是否可以触发
        """
        # 检查翻译器状态
        if self.translator.config.translation_mode == 0:
            logger.warning("请先选择翻译模式")
            return False

        if getattr(self.translator, "in_progress", False):
            logger.info("已有翻译任务进行中，请稍候...")
            return False

        return True

    def trigger_translation(self) -> None:
        """触发翻译"""
        try:
            print("─" * 35 + " 开始翻译 " + "─" * 35)
            current_thread_name = threading.current_thread().name
            logger.info(f"[{current_thread_name}] 检测到三次空格，触发翻译")

            # 检查翻译器是否有事件循环
            if hasattr(self.translator, "loop") and self.translator.loop:
                # 使用翻译器的事件循环
                logger.debug(f"[{current_thread_name}] 使用翻译器的事件循环触发翻译。")
                asyncio.run_coroutine_threadsafe(
                    self.translator.replacement_translation(), self.translator.loop
                )
            else:
                # 避免在监听线程内创建并阻塞事件循环，直接记录并跳过
                logger.warning(
                    f"[{current_thread_name}] 未检测到应用事件循环，跳过本次触发以避免阻塞。"
                )
        except Exception as e:
            logger.error(
                f"[{threading.current_thread().name}] 触发翻译时发生错误: {e}",
                exc_info=True,
            )

    def on_press(self, key: Any) -> None:
        """处理键盘按键事件

        Args:
            key: 按下的键
        """
        try:
            # 检查是否应该忽略键盘事件
            if self.should_ignore_keyboard_event():
                return

            # 只处理空格键
            if key != keyboard.Key.space:
                self.space_count = 0
                return

            # 获取鼠标坐标并检查位置
            mouse_pos = self.get_mouse_position()
            if not self.is_valid_trigger_position(mouse_pos):
                return

            # 更新空格键计数
            current_time = time.time()
            self.update_space_count(current_time)

            # 检查冷却时间
            if self.is_in_cooldown(current_time):
                return

            # 检测到足够的空格键,尝试触发翻译
            if self.space_count >= self.required_space_count:
                self.space_count = 0

                # 检查是否可以触发翻译
                if self.can_trigger_translation():
                    # 只有在真正触发翻译时才更新冷却时间
                    self.last_trigger_time = current_time
                    self.trigger_translation()

        except Exception as e:
            logger.error(
                f"[{threading.current_thread().name}] 键盘事件处理错误: {e}",
                exc_info=True,
            )

    def on_release(self, key: Any) -> None:
        """处理键盘释放事件

        Args:
            key: 释放的键
        """
        # 不需要处理键盘释放事件
        pass

    def start(self) -> None:
        """启动键盘监听"""
        try:
            current_thread_name = threading.current_thread().name
            logger.debug(f"[{current_thread_name}] 尝试启动键盘监听器...")
            if hasattr(self, "listener") and self.listener:
                self.listener.start()
                logger.info(
                    f"[{current_thread_name}] 键盘监听器已启动 (平台: {self.platform_info['system']})"
                )

                # 等待一小段时间确保监听器正常启动（使用非阻塞方式替代time.sleep）
                threading.Event().wait(0.1)

                # 检查监听器状态，使用兼容性方法
                if not self._get_listener_running_status():
                    raise RuntimeError("监听器启动后未运行")

            else:
                raise RuntimeError("监听器未初始化")

        except Exception as e:
            logger.error(
                f"[{threading.current_thread().name}] 启动键盘监听器失败: {e}",
                exc_info=True,
            )
            # 尝试提供解决方案
            if PlatformCompatibility.is_linux():
                logger.info("Linux系统可能需要运行权限，尝试使用sudo运行程序")
            elif PlatformCompatibility.is_macos():
                logger.info("macOS系统可能需要在系统偏好设置中授予辅助功能权限")
            raise

    def stop(self) -> None:
        """停止键盘监听"""
        current_thread_name = threading.current_thread().name
        try:
            logger.debug(f"[{current_thread_name}] 尝试停止键盘监听器...")
            if hasattr(self, "listener") and self.listener:
                if self._get_listener_running_status():
                    self.listener.stop()
                    logger.info(f"[{current_thread_name}] 键盘监听器已停止。")

                    # 等待监听器完全停止（使用非阻塞方式替代time.sleep）
                    timeout = 5.0
                    start_time = time.time()
                    while (
                        self._get_listener_running_status()
                        and (time.time() - start_time) < timeout
                    ):
                        # 使用短暂的CPU让步替代time.sleep，减少阻塞
                        threading.Event().wait(0.1)

                    if self._get_listener_running_status():
                        logger.warning(f"[{current_thread_name}] 键盘监听器停止超时。")
                else:
                    logger.debug(f"[{current_thread_name}] 键盘监听器已经停止。")
            else:
                logger.debug(f"[{current_thread_name}] 键盘监听器未初始化或已销毁。")

        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 停止键盘监听器失败: {e}", exc_info=True
            )

    def _get_listener_running_status(self) -> bool:
        """获取监听器的运行状态，使用兼容性检查

        Returns:
            bool: 是否正在运行
        """
        try:
            if hasattr(self, "listener") and self.listener:
                # pynput.Listener可能在某些版本中无running属性
                if hasattr(self.listener, "running"):
                    return bool(self.listener.running)
                else:
                    # 备用检查：尝试访问监听器线程状态
                    try:
                        # 检查线程是否还活着且未抛出异常，非阻塞方式
                        if (
                            hasattr(self.listener, "_thread")
                            and self.listener._thread.is_alive()
                        ):
                            return True
                        return False
                    except (AttributeError, RuntimeError) as e:
                        logger.debug(f"检查监听器线程状态失败: {e}")
                        return False
            return False
        except Exception as e:
            logger.debug(f"获取监听器状态异常: {e}")
            return False

    def is_running(self) -> bool:
        """检查键盘监听器是否正在运行

        Returns:
            bool: 是否正在运行
        """
        try:
            return self._get_listener_running_status()
        except Exception as e:
            logger.error(f"检查监听器状态失败: {e}")
            return False

    def get_status(self) -> dict[str, Any]:
        """获取键盘监听器状态

        Returns:
            dict: 状态信息
        """
        return {
            "running": self.is_running(),
            "space_count": self.space_count,
            "last_space_time": self.last_space_time,
            "last_trigger_time": self.last_trigger_time,
            "space_detection_timeout": self.space_detection_timeout,
            "trigger_cooldown": self.trigger_cooldown,
            "required_space_count": self.required_space_count,
        }

    def configure(self, **kwargs: Any) -> None:
        """配置键盘监听器参数

        Args:
            **kwargs: 配置参数
        """
        if "space_detection_timeout" in kwargs:
            self.space_detection_timeout = kwargs["space_detection_timeout"]
            logger.info(f"空格检测超时时间已设置为: {self.space_detection_timeout}")

        if "trigger_cooldown" in kwargs:
            self.trigger_cooldown = kwargs["trigger_cooldown"]
            logger.info(f"触发冷却时间已设置为: {self.trigger_cooldown}")

        if "required_space_count" in kwargs:
            self.required_space_count = kwargs["required_space_count"]
            logger.info(f"所需空格次数已设置为: {self.required_space_count}")

    def reset_counters(self) -> None:
        """重置计数器"""
        self.space_count = 0
        self.last_space_time = 0
        self.last_trigger_time = 0
        logger.debug("键盘监听器计数器已重置")
