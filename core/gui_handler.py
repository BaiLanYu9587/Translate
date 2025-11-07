"""
PyQt6现代化圆形进度条处理器
使用Qt信号槽机制在主线程中更新GUI
"""

import sys
import threading
import signal
import atexit
import queue
from typing import Optional, Dict, Any
import logging
import pyautogui  # type: ignore[import-untyped]
from PyQt6.QtWidgets import QApplication, QWidget  # type: ignore[import-untyped]
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QMetaObject, Q_ARG  # type: ignore[import-untyped]
from PyQt6.QtGui import QPainter, QColor, QPen  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


class ProgressWindow(QWidget):
    """圆形进度条窗口"""

    def __init__(
        self, theme_config: Dict[str, Any], progress_config: Dict[str, Any]
    ) -> None:
        super().__init__()
        self.theme_config = theme_config
        self.progress_config = progress_config

        # 设置窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint  # 绕过窗口管理器
        )

        # 设置透明背景
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # 设置窗口不接受鼠标事件，避免干扰鼠标操作
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.progress = 0
        self.animation_step = 0
        self.rotation_angle = 0

        # 动画定时器
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animation)
        # 使用配置，提供更小的无硬编码默认值
        self.animation_timer.setInterval(
            self.progress_config.get("animation_interval", 80)
        )

        # 位置跟踪定时器
        self.position_timer = QTimer(self)
        self.position_timer.timeout.connect(self.update_position)

        # 设置尺寸，完全依赖配置（提供更小的默认值，避免硬编码）
        self.setFixedSize(
            int(self.progress_config.get("window_width", 18)),
            int(self.progress_config.get("window_height", 18)),
        )

        # 设置完全透明背景样式表
        self.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)

        self.hide()

    @pyqtSlot(int, int)
    def show_at_position(self, x: int, y: int) -> None:
        """在指定位置显示进度条"""
        self.move(x + 5, y + 5)  # 紧贴鼠标右下角显示，避免遮挡鼠标
        self.show()
        self.raise_()
        self.animation_timer.start(100)  # 10 FPS
        self.position_timer.start(100)  # 位置更新频率

    @pyqtSlot()
    def hide_window(self) -> None:
        """隐藏进度条窗口"""
        self.animation_timer.stop()
        self.position_timer.stop()
        self.hide()

    def update_animation(self) -> None:
        """更新动画"""
        self.rotation_angle = (self.rotation_angle + 15) % 360
        self.update()

    def update_position(self) -> None:
        """更新位置以跟随鼠标"""
        try:
            mouse_x, mouse_y = pyautogui.position()
            window_x = mouse_x + 5
            window_y = mouse_y + 5
            self.move(int(window_x), int(window_y))
            self.raise_()
        except Exception:
            pass

    @pyqtSlot(int)
    def set_progress(self, progress: int) -> None:
        """设置进度值"""
        self.progress = max(0, min(100, progress))
        self.update()

    @pyqtSlot(int, int)
    def schedule_progress_after(self, delay_ms: int, progress: int) -> None:
        """在主线程中延时更新进度"""
        try:
            QTimer.singleShot(int(delay_ms), lambda p=progress: self.set_progress(p))
        except Exception:
            # 回退：直接设置
            self.set_progress(progress)

    @pyqtSlot(int)
    def schedule_hide_after(self, delay_ms: int) -> None:
        """在主线程中延时隐藏窗口"""
        try:
            QTimer.singleShot(int(delay_ms), self.hide_window)
        except Exception:
            self.hide_window()

    def paintEvent(self, event: Any) -> None:
        """绘制圆形进度条"""
        _ = event  # 避免未使用变量警告
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 设置绘制区域
        rect = self.rect().adjusted(4, 4, -4, -4)

        # 绘制背景圆环
        bg_color = QColor(self.theme_config.get("border", "#dddddd"))
        circle_width = int(self.progress_config.get("circle_width", 2))
        pen = QPen(bg_color, max(1, circle_width - 1))
        painter.setPen(pen)
        painter.drawEllipse(rect)

        # 绘制进度圆弧
        if self.progress > 0:
            progress_color = QColor(self.theme_config.get("accent", "#4a86e8"))
            pen = QPen(progress_color, circle_width)
            painter.setPen(pen)

            # 计算角度
            start_angle = -90 + self.rotation_angle  # 从顶部开始
            span_angle = int((self.progress / 100) * 360)

            if span_angle < 10 and self.progress > 0:
                span_angle = 10  # 最小可见角度，增大以便更容易看到

            painter.drawArc(rect, start_angle * 16, span_angle * 16)


class GUIHandler:
    """使用Qt信号槽机制的GUI处理器"""

    def __init__(
        self, root: Optional[Any] = None, config: Optional[Any] = None
    ) -> None:
        """初始化GUI处理器"""
        _ = root  # 避免未使用变量警告
        self.config = config
        self.app: Optional[QApplication] = None
        self.progress_window: Optional[ProgressWindow] = None
        self.is_running = False
        self.thread = None
        self.command_queue: queue.Queue[Dict[str, Any]] = queue.Queue()

        # 线程安全
        self.lock = threading.Lock()
        self.is_showing = False

        # 设置配置
        self._setup_config()

        # 注册清理函数
        atexit.register(self.cleanup)

        # 设置信号处理
        self._setup_signal_handlers()

        # 启动GUI（必须在主线程中完成）
        self._start_gui_thread()

        logger.debug(f"[{threading.current_thread().name}] GUIHandler初始化完成")

    def _setup_config(self) -> None:
        """设置配置参数"""
        # 设置进度条配置
        if self.config:
            self.progress_config = getattr(self.config, "gui_progress", {})
            self.theme_config = getattr(self.config, "gui_theme", {})
        else:
            self.progress_config = {}
            self.theme_config = {}

    def _setup_signal_handlers(self) -> None:
        """设置信号处理器，确保程序中断时能正确清理"""
        try:
            # 检查是否在主线程中
            if threading.current_thread() is not threading.main_thread():
                logger.warning("GUI处理器不在主线程中，跳过信号处理器设置")
                return

            # 设置SIGINT处理器（Ctrl+C）
            signal.signal(signal.SIGINT, self._signal_handler)
            # 设置SIGTERM处理器
            signal.signal(signal.SIGTERM, self._signal_handler)
            logger.debug("信号处理器设置成功")
        except Exception as e:
            logger.warning(f"设置信号处理器失败: {e}")

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """信号处理器"""
        _ = frame  # 避免未使用变量警告
        logger.info(f"接收到信号 {signum}，开始清理资源...")
        self.cleanup()
        sys.exit(0)

    def _start_gui_thread(self) -> None:
        """启动GUI组件（确保在主线程中执行）"""
        current_thread_name = threading.current_thread().name
        logger.debug(f"[{current_thread_name}] 尝试启动GUI组件...")
        # 检查是否在主线程中
        if threading.current_thread() is not threading.main_thread():
            logger.error(f"[{current_thread_name}] GUI组件必须在主线程中初始化")
            raise RuntimeError("GUI组件必须在主线程中初始化")

        # 检查是否已经有QApplication实例
        if QApplication.instance() is None:
            # 在主线程中创建QApplication
            self.app = QApplication([])
            if self.app:
                self.app.setQuitOnLastWindowClosed(False)
            logger.debug(
                f"[{current_thread_name}] 已创建新的QApplication实例 (id={id(self.app)})"
            )
        else:
            # 使用现有的QApplication实例
            self.app = QApplication.instance()  # type: ignore
            logger.debug(
                f"[{current_thread_name}] 使用现有的QApplication实例 (id={id(self.app)})"
            )

        # 在主线程中创建进度窗口
        self.progress_window = ProgressWindow(self.theme_config, self.progress_config)
        self.is_running = True

        # 启动命令处理循环
        self._start_command_processing()

        # 启动一个定时器以保证Qt事件泵活跃（在未显式exec的情况下也能处理排队事件）
        keepalive_timer = QTimer(self.progress_window)
        keepalive_timer.setInterval(100)
        keepalive_timer.timeout.connect(lambda: None)
        keepalive_timer.start()
        logger.info(f"[{current_thread_name}] GUI组件已初始化，KeepAlive计时器已启动。")

    def _start_command_processing(self) -> None:
        """启动命令处理循环"""

        def process_commands() -> None:
            while self.is_running:
                try:
                    command = self.command_queue.get(timeout=0.1)
                    self._handle_command(command)
                    self.command_queue.task_done()
                except queue.Empty:
                    pass

        command_thread = threading.Thread(target=process_commands)
        command_thread.daemon = True
        command_thread.start()

    def _handle_command(self, command: Dict[str, Any]) -> None:
        """处理命令"""
        cmd_type = command.get("type")
        data = command.get("data", {})

        if cmd_type == "show_progress":
            x, y = data.get("position", (0, 0))
            # 使用Qt的信号槽机制在主线程中更新GUI
            QMetaObject.invokeMethod(
                self.progress_window,
                "show_at_position",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, x),
                Q_ARG(int, y),
            )

        elif cmd_type == "hide_progress":
            # 使用Qt的信号槽机制在主线程中更新GUI
            QMetaObject.invokeMethod(
                self.progress_window, "hide_window", Qt.ConnectionType.QueuedConnection
            )

        elif cmd_type == "update_progress":
            # 更新进度值
            progress = data.get("progress", 0)
            # 使用Qt的信号槽机制在主线程中更新进度
            if self.progress_window:
                QMetaObject.invokeMethod(
                    self.progress_window,
                    "set_progress",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(int, progress),
                )
            # 优化：减少进度更新日志频率，仅记录关键节点
            if progress in [25, 50, 75, 100]:
                logger.debug(f"进度更新: {progress}%")

        elif cmd_type == "delayed_update":
            # 主线程中安排延时进度更新
            progress = data.get("progress", 0)
            delay = int(data.get("delay", 0))
            if self.progress_window:
                QMetaObject.invokeMethod(
                    self.progress_window,
                    "schedule_progress_after",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(int, delay),
                    Q_ARG(int, progress),
                )
                if progress in [25, 50, 75, 100]:
                    logger.debug(f"延时进度更新: +{delay}ms -> {progress}%")

        elif cmd_type == "delayed_hide":
            # 主线程中安排延时隐藏
            delay = int(data.get("delay", 0))
            if self.progress_window:
                QMetaObject.invokeMethod(
                    self.progress_window,
                    "schedule_hide_after",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(int, delay),
                )

    def show_progress_indicator(self) -> None:
        """显示圆形进度条"""
        current_thread_name = threading.current_thread().name
        logger.debug(f"[{current_thread_name}] 调用 show_progress_indicator。")
        with self.lock:
            if self.is_showing:
                logger.debug(f"[{current_thread_name}] 进度条已在显示，忽略本次调用。")
                return

            try:
                # 获取鼠标位置
                mouse_x, mouse_y = pyautogui.position()

                # 发送显示命令
                self.command_queue.put(
                    {"type": "show_progress", "data": {"position": (mouse_x, mouse_y)}}
                )

                self.is_showing = True
                logger.info(f"[{current_thread_name}] 进度条显示命令已发送。")

            except Exception as e:
                logger.error(
                    f"[{current_thread_name}] 显示进度条失败: {e}", exc_info=True
                )

    def update_progress_indicator(
        self,
        status_key: str,
        progress: Optional[int] = None,
        custom_message: Optional[str] = None,
    ) -> None:
        """更新进度"""
        _ = status_key, custom_message  # 避免未使用变量警告

        if progress is not None:
            try:
                if self.is_showing:
                    # 检查进度是否有变化
                    if (
                        self.progress_window
                        and hasattr(self.progress_window, "progress")
                        and self.progress_window.progress == progress
                    ):
                        return

                    # 发送更新命令
                    self.command_queue.put(
                        {"type": "update_progress", "data": {"progress": progress}}
                    )
                    # 优化：减少命令发送日志频率
                    if progress in [25, 50, 75, 100]:
                        logger.debug(f"进度更新命令已发送: {progress}%")
                else:
                    # 优化：减少忽略命令的日志频率
                    if progress in [25, 50, 75, 100]:
                        logger.debug(f"进度条未显示，忽略更新命令: {progress}%")
            except Exception as e:
                logger.error(f"更新进度失败: {e}")

    def smooth_update_progress(
        self, target_progress: int, duration_ms: int = 200
    ) -> None:
        """平滑更新进度到目标值

        Args:
            target_progress: 目标进度值 (0-100)
            duration_ms: 动画持续时间（毫秒）
        """
        if not self.is_showing:
            return

        try:
            # 获取当前进度值
            current_progress = (
                getattr(self.progress_window, "progress", 0)
                if self.progress_window
                else 0
            )

            # 如果目标进度和当前进度相同，直接返回
            if current_progress == target_progress:
                return

            # 计算步数和每步的进度增量
            steps = max(
                5, min(20, abs(target_progress - current_progress))
            )  # 5-20步之间
            step_size = (target_progress - current_progress) / steps
            step_interval = duration_ms / steps

            # 逐步更新进度（通过命令队列在主线程安排 QTimer）
            for i in range(1, steps + 1):
                intermediate_progress = int(current_progress + step_size * i)
                intermediate_progress = max(
                    0, min(100, intermediate_progress)
                )  # 确保在0-100范围内

                self.command_queue.put(
                    {
                        "type": "delayed_update",
                        "data": {
                            "progress": intermediate_progress,
                            "delay": int(step_interval * i),
                        },
                    }
                )

            logger.debug(
                f"平滑进度更新: {current_progress}% -> {target_progress}%, {steps}步, {step_interval:.1f}ms/步"
            )

        except Exception as e:
            logger.error(f"平滑进度更新失败: {e}")
            # 失败时直接更新到目标进度
            self.update_progress_indicator("fallback", target_progress)

    def complete_progress_and_hide(self) -> None:
        """完成进度并隐藏"""
        try:
            # 先更新到100%
            if self.is_showing:
                self.command_queue.put(
                    {"type": "update_progress", "data": {"progress": 100}}
                )

            # 延迟隐藏 - 通过主线程安排 QTimer
            self.command_queue.put({"type": "delayed_hide", "data": {"delay": 100}})
        except Exception as e:
            logger.error(f"完成进度失败: {e}")

    def hide_progress_indicator(self) -> None:
        """隐藏进度条"""
        current_thread_name = threading.current_thread().name
        logger.debug(f"[{current_thread_name}] 调用 hide_progress_indicator。")
        with self.lock:
            if not self.is_showing:
                logger.debug(f"[{current_thread_name}] 进度条未显示，忽略本次调用。")
                return

            try:
                # 发送隐藏命令
                self.command_queue.put({"type": "hide_progress", "data": {}})
                self.is_showing = False
                logger.info(f"[{current_thread_name}] 进度条隐藏命令已发送。")
            except Exception as e:
                logger.error(
                    f"[{current_thread_name}] 隐藏进度条失败: {e}", exc_info=True
                )

    def is_progress_showing(self) -> bool:
        """检查进度条是否正在显示"""
        return self.is_showing

    def cleanup(self) -> None:
        """清理资源"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始清理GUI资源...")
        try:
            # 停止命令处理
            if self.is_running:
                self.is_running = False
                logger.debug(f"[{current_thread_name}] 命令处理循环已停止。")

            # 隐藏进度窗口
            if self.progress_window:
                # 使用主线程调用隐藏窗口
                QMetaObject.invokeMethod(
                    self.progress_window,
                    "hide_window",
                    Qt.ConnectionType.QueuedConnection,
                )
                logger.debug(f"[{current_thread_name}] 进度窗口已隐藏。")

            logger.info(f"[{current_thread_name}] GUI资源已清理。")

        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 清理资源时发生错误: {e}", exc_info=True
            )

        self.is_showing = False

    def safe_quit(self) -> None:
        """线程安全地请求退出Qt应用（在Qt主线程排队执行）"""
        try:
            current_thread_name = threading.current_thread().name
            logger.debug(
                f"[{current_thread_name}] 请求 Qt 安全退出 (QMetaObject.invokeMethod)..."
            )
            if QApplication.instance() is None:
                logger.debug(
                    f"[{current_thread_name}] 无QApplication实例，跳过safe_quit。"
                )
                return
            # 使用队列连接在Qt主线程执行 quit
            from PyQt6.QtCore import QCoreApplication

            QMetaObject.invokeMethod(
                QCoreApplication.instance(), "quit", Qt.ConnectionType.QueuedConnection
            )
            logger.info(f"[{current_thread_name}] 已发送 Qt 退出请求。")
        except Exception as e:
            logger.error(
                f"[{threading.current_thread().name}] 发送 Qt 退出请求失败: {e}",
                exc_info=True,
            )
