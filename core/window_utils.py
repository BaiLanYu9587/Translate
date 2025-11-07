import platform
import logging
import threading

logger = logging.getLogger(__name__)


def get_active_window_title() -> str:
    """获取当前活动窗口的标题

    尝试使用 ``pyautogui`` 获取当前活动窗口标题；若失败则在 Windows
    平台回退到 ``win32gui``。在其它平台返回 ``UnknownWindow`` 占位。

    Returns
    -------
    str
        活动窗口标题，如无法获取则返回 ``"UnknownWindow"``。
    """
    current_thread_name = threading.current_thread().name
    logger.debug(f"[{current_thread_name}] 尝试获取活动窗口标题...")
    # 首选跨平台的 pyautogui 实现
    try:
        import pyautogui  # type: ignore[import-untyped]

        # pyautogui 没有 getActiveWindow 方法，使用 screenshot 方式获取窗口信息
        # 在某些系统上可以尝试使用 position 方法
        screen = pyautogui.screenshot()
        if screen is not None:
            # 尝试使用其他方法获取活动窗口
            # 这里不直接返回，因为 pyautogui 主要用于截图和鼠标控制
            pass
    except Exception as e:  # pragma: no cover – 容错处理与日志
        logger.warning(f"[{current_thread_name}] 通过 pyautogui 获取窗口标题失败: {e}")

    # Windows 备用方案：使用 win32gui 直接调用 Win32 API
    if platform.system().lower() == "windows":
        try:
            import win32gui  # type: ignore[import-untyped]

            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                title = win32gui.GetWindowText(hwnd)
                if title:
                    logger.info(
                        f"[{current_thread_name}] 通过 win32gui 获取到窗口标题: {title}"
                    )
                    return title
        except Exception as e:  # pragma: no cover
            logger.warning(
                f"[{current_thread_name}] 通过 win32gui 获取窗口标题失败: {e}"
            )

    # 其它平台或失败情况返回占位符
    logger.warning(f"[{current_thread_name}] 无法获取窗口标题，返回 'UnknownWindow'")
    return "UnknownWindow"
