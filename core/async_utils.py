import asyncio
import logging
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class AsyncLoopThread(threading.Thread):
    """
    一个专门用于在后台运行 asyncio 事件循环的线程类。
    它提供了启动、停止和安全获取循环引用的方法。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Avoid name parameter conflict by checking if name is already provided
        if "name" not in kwargs:
            kwargs["name"] = "AsyncLoopThread"
        super().__init__(*args, daemon=True, **kwargs)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_started = threading.Event()
        self._exception_handler: Optional[
            Callable[[asyncio.AbstractEventLoop, Dict[str, Any]], None]
        ] = None

    def _exception_handler_wrapper(
        self, loop: asyncio.AbstractEventLoop, context: Dict[str, Any]
    ) -> None:
        """asyncio 异常处理的包装器"""
        exception = context.get("exception")
        if isinstance(exception, asyncio.CancelledError):
            logger.debug(f"[{self.name}] 捕获到已取消的任务（正常操作）")
        else:
            logger.error(
                f"[{self.name}] 异步循环中出现未捕获的异常: {context.get('message')}",
                exc_info=exception,
            )

        if self._exception_handler:
            self._exception_handler(loop, context)

    def run(self) -> None:
        """线程主执行函数"""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.set_exception_handler(self._exception_handler_wrapper)

            # 标记循环已创建并设置好
            self._loop_started.set()
            logger.info(f"[{self.name}] 异步事件循环已启动并正在运行。")
            self._loop.run_forever()
        except Exception as e:
            logger.critical(
                f"[{self.name}] 异步事件循环线程遇到致命错误并退出: {e}", exc_info=True
            )
        finally:
            if self._loop and not self._loop.is_closed():
                # 清理所有剩余任务
                tasks = asyncio.all_tasks(loop=self._loop)
                for task in tasks:
                    task.cancel()

                # 集合所有任务以确保它们都已取消
                async def gather_tasks() -> None:
                    await asyncio.gather(*tasks, return_exceptions=True)

                # 同步运行最后的清理
                self._loop.run_until_complete(gather_tasks())
                self._loop.close()
            logger.info(f"[{self.name}] 异步事件循环已完全关闭。")

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """
        安全地获取事件循环实例。如果循环尚未启动，将阻塞等待。
        """
        if not self.is_alive():
            raise RuntimeError("无法在未启动的线程中获取事件循环。")

        self._loop_started.wait()  # 等待 run 方法中的 _loop_started.set()
        if not self._loop:
            raise RuntimeError("事件循环未能成功初始化。")
        return self._loop

    def stop(self) -> None:
        """
        请求事件循环停止。这是一个线程安全的操作。
        """
        if not self._loop or not self.is_alive():
            logger.debug(f"[{self.name}] 异步循环未运行，无需停止。")
            return

        logger.info(f"[{self.name}] 正在请求异步事件循环停止...")
        # run_coroutine_threadsafe 是线程安全的，但 stop() 不是协程
        # call_soon_threadsafe 可以安全地在循环中安排一个普通函数的调用
        self._loop.call_soon_threadsafe(self._loop.stop)
