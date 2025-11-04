import os
import glob
import time
import asyncio
import logging
import threading
from typing import Any, Optional, TYPE_CHECKING
from concurrent.futures import Future

from .config_management import get_chat_contexts_dir

if TYPE_CHECKING:
    from .cache_manager import CacheManager

logger = logging.getLogger(__name__)

# 使用统一的目录管理器获取聊天上下文目录
CHAT_CONTEXTS_DIR = get_chat_contexts_dir()


async def cleanup_old_contexts_async(config: Any) -> None:
    """
    异步删除 chat_contexts 目录下超过指定天数未更新的 .json 上下文文件。
    """
    current_thread_name = threading.current_thread().name
    logger.info(f"[{current_thread_name}] 开始执行异步上下文清理任务...")
    try:
        cleanup_days = getattr(config, "chat_context_cleanup_days", 3)
        if cleanup_days == 0:
            logger.info(
                f"[{current_thread_name}] 上下文清理天数设置为0，跳过旧上下文文件的清理。"
            )
            return

        if not os.path.exists(CHAT_CONTEXTS_DIR):
            logger.warning(
                f"[{current_thread_name}] 目录 '{CHAT_CONTEXTS_DIR}' 不存在，无需清理旧上下文文件。"
            )
            return

        logger.info(
            f"[{current_thread_name}] 开始异步清理 '{CHAT_CONTEXTS_DIR}' 目录下超过 {cleanup_days} 天未更新的 .json 文件..."
        )
        now = time.time()
        cutoff_time = now - (cleanup_days * 24 * 60 * 60)

        json_files = glob.glob(os.path.join(CHAT_CONTEXTS_DIR, "*.json"))
        if not json_files:
            logger.info(
                f"[{current_thread_name}] 在 '{CHAT_CONTEXTS_DIR}' 目录中未找到 .json 文件。"
            )
            return

        cleaned_count = 0
        for json_file in json_files:
            try:
                if not os.path.exists(json_file):
                    continue

                file_mod_time = os.path.getmtime(json_file)
                if file_mod_time < cutoff_time:
                    if os.path.exists(json_file):
                        os.remove(json_file)
                        cleaned_count += 1
                        logger.debug(
                            f"[{current_thread_name}] 已删除旧上下文文件: {json_file}"
                        )

                await asyncio.sleep(0.01)  # 避免长时间阻塞事件循环
            except FileNotFoundError:
                logger.debug(
                    f"[{current_thread_name}] 文件已不存在（可能被其他进程删除）: {json_file}"
                )
            except OSError as e:
                logger.error(
                    f"[{current_thread_name}] 删除旧上下文文件失败 '{json_file}': {e}"
                )
            except Exception as e_inner:
                logger.error(
                    f"[{current_thread_name}] 处理文件 '{json_file}' 时发生错误: {e_inner}"
                )

        if cleaned_count > 0:
            logger.info(
                f"[{current_thread_name}] 成功异步清理了 {cleaned_count} 个旧的 .json 上下文文件。"
            )
        else:
            logger.info(
                f"[{current_thread_name}] 没有找到需要清理的旧 .json 上下文文件。"
            )

    except Exception as e:
        logger.error(
            f"[{current_thread_name}] 异步清理旧上下文文件时发生意外错误: {e}",
            exc_info=True,
        )


def cleanup_old_database_records(
    cache_manager: "CacheManager", cleanup_days: int
) -> None:
    """
    同步调用 CacheManager 清理数据库中超过指定天数的翻译记录。

    Args:
        cache_manager: 缓存管理器实例
        cleanup_days: 清理天数
    """
    current_thread_name = threading.current_thread().name
    logger.info(f"[{current_thread_name}] 准备执行数据库记录清理...")

    if not cache_manager:
        logger.warning(f"[{current_thread_name}] CacheManager 未提供，跳过数据库清理。")
        return

    try:
        # 直接调用 CacheManager 的同步清理方法
        cache_manager.clear_expired_records(cleanup_days)
    except Exception as e:
        logger.error(
            f"[{current_thread_name}] 执行数据库清理时发生错误: {e}", exc_info=True
        )


class ScheduledCleanupManager:
    """定时清理管理器 - 负责定期执行文件和数据库清理任务"""

    def __init__(
        self,
        config: Any,
        cache_manager: "CacheManager",
        loop: asyncio.AbstractEventLoop,
        cleanup_interval_hours: int = 1,
    ) -> None:
        """
        初始化定时清理管理器

        Args:
            config: 配置对象
            cache_manager: 缓存管理器实例
            loop: 异步事件循环
            cleanup_interval_hours: 清理间隔（小时），默认1小时
        """
        self.config = config
        self.cache_manager = cache_manager
        self.loop = loop
        self.cleanup_interval_hours = cleanup_interval_hours
        self.cleanup_interval_seconds = cleanup_interval_hours * 3600
        self._cleanup_task: Optional[Future[Any]] = None
        self._is_running = False
        self._stop_event = threading.Event()

        logger.info(f"定时清理管理器已初始化，清理间隔: {cleanup_interval_hours} 小时")

    def start(self) -> None:
        """启动定时清理任务"""
        if self._is_running:
            logger.warning("定时清理任务已在运行，跳过启动")
            return

        self._is_running = True
        self._stop_event.clear()

        # 在单独的守护线程中运行定时器
        cleanup_thread = threading.Thread(
            target=self._run_scheduler, daemon=True, name="ScheduledCleanupThread"
        )
        cleanup_thread.start()

        logger.info(f"定时清理任务已启动，线程: {cleanup_thread.name}")

    def stop(self) -> None:
        """停止定时清理任务"""
        if not self._is_running:
            return

        self._is_running = False
        self._stop_event.set()

        # 取消异步任务
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

        logger.info("定时清理任务已停止")

    def _run_scheduler(self) -> None:
        """运行定时调度器（在单独线程中执行）"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 定时清理调度器开始运行")

        while self._is_running and not self._stop_event.is_set():
            try:
                # 执行清理任务
                self._cleanup_task = asyncio.run_coroutine_threadsafe(
                    self._execute_cleanup(), self.loop
                )

                # 等待清理任务完成（带超时）
                try:
                    self._cleanup_task.result(timeout=300)  # 5分钟超时
                except asyncio.TimeoutError:
                    logger.warning(f"[{current_thread_name}] 清理任务执行超时")
                    self._cleanup_task.cancel()
                except Exception as e:
                    logger.error(f"[{current_thread_name}] 清理任务执行失败: {e}")

                # 等待下次执行
                if self._stop_event.wait(timeout=self.cleanup_interval_seconds):
                    break  # 收到停止信号

            except Exception as e:
                logger.error(
                    f"[{current_thread_name}] 定时清理调度器异常: {e}", exc_info=True
                )
                # 发生异常时等待较短时间后重试
                if self._stop_event.wait(timeout=60):  # 1分钟后重试
                    break

        logger.info(f"[{current_thread_name}] 定时清理调度器已退出")

    async def _execute_cleanup(self) -> None:
        """执行清理任务（异步）"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始执行定时清理任务...")

        try:
            # 获取清理天数配置
            cleanup_days = getattr(self.config, "chat_context_cleanup_days", 3)

            # 执行文件清理
            await cleanup_old_contexts_async(self.config)

            # 执行数据库清理
            # 在事件循环的线程池中运行同步的数据库清理，避免阻塞
            await self.loop.run_in_executor(
                None, cleanup_old_database_records, self.cache_manager, cleanup_days
            )

            logger.info(f"[{current_thread_name}] 定时清理任务执行完成")

        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 定时清理任务执行失败: {e}", exc_info=True
            )
