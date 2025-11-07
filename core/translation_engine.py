"""
翻译引擎核心模块
提供翻译业务逻辑、API调用、缓存管理等核心功能
"""

import asyncio
import aiohttp
import time
import logging
import collections
import concurrent.futures
from typing import Dict, Optional, Any


# 引入 tenacity 用于重试
from tenacity import (  # type: ignore[import-not-found]
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

# 导入其他模块
from .cache_manager import CacheManager
from .language_detection import LanguageDetector, detect_language_with_cache
from .context_manager import ContextManager
from .prompt_builder import PromptBuilder
from .api_manager import ApiManager

import threading

logger = logging.getLogger(__name__)

# 全局重试装饰器配置
retry_decorator = retry(
    stop=stop_after_attempt(3),  # 最多重试3次
    wait=wait_exponential(multiplier=1, min=1, max=10),  # 指数退避：1s, 2s, 4s...
    retry=retry_if_exception_type(
        (aiohttp.ClientError, asyncio.TimeoutError)
    ),  # 重试条件
    before_sleep=before_sleep_log(logger, logging.WARNING),  # 重试前记录日志
    reraise=True,  # 重新抛出最后一个异常
)


class LRUCache:
    """简单的LRU缓存实现"""

    def __init__(self, capacity: int):
        """初始化LRU缓存

        Args:
            capacity: 缓存容量上限
        """
        self.cache: collections.OrderedDict[str, Optional[str]] = (
            collections.OrderedDict()
        )
        self.capacity = capacity
        self._lock = asyncio.Lock()  # 使用异步锁
        # 添加统计信息
        self.hits = 0
        self.misses = 0
        logger.debug(f"创建LRU缓存，容量: {capacity}")

    async def get(self, key: str) -> Optional[str]:
        """获取缓存值"""
        async with self._lock:
            if key in self.cache:
                # 移动到末尾（最近使用）
                value = self.cache.pop(key)
                self.cache[key] = value
                self.hits += 1
                return value
            else:
                self.misses += 1
                return None

    async def put(self, key: str, value: Optional[str]) -> None:
        """存储缓存值"""
        async with self._lock:
            if key in self.cache:
                # 更新现有值
                self.cache.pop(key)
            elif len(self.cache) >= self.capacity:
                # 移除最旧的项
                self.cache.popitem(last=False)

            self.cache[key] = value

    async def clear(self) -> None:
        """清空缓存"""
        async with self._lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
            "size": len(self.cache),
            "capacity": self.capacity,
        }


class TranslationEngine:
    """翻译引擎核心类"""

    def __init__(
        self,
        config: Any,
        mode_config: Dict[str, Any],
        cache_manager: Optional[CacheManager],
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        """初始化翻译引擎

        Args:
            config: 配置对象
            mode_config: 模式配置字典
            cache_manager: 缓存管理器
            loop: 异步事件循环
        """
        # 确保config是Config类型或至少有必要的方法
        if hasattr(config, "get") and callable(getattr(config, "get", None)):
            self.config = config
        else:
            # 如果config不是预期类型，记录警告但继续执行
            logger.warning(
                f"Config对象类型异常: {type(config)}, 期望包含'get'方法的对象"
            )
            self.config = config
        self.mode_config = mode_config
        self.service_manager: Optional[Any] = None  # Will be set later
        self.cache_manager = cache_manager
        self.api_manager = ApiManager(self.config)
        self.context_manager = ContextManager()
        self.language_detector = LanguageDetector(self.mode_config, self.config)
        self.prompt_builder = PromptBuilder(self.config, self.mode_config)
        logger.debug(
            f"创建LRU缓存，容量: {self.config.get('translation_cache_size', 200)}"
        )
        self.loop = loop or asyncio.get_event_loop()

        # 初始化本地缓存管理器 (改为异步初始化)
        if getattr(config, "use_local_cache", True):
            self._cache_config = config  # 保存配置用于后续异步初始化
        else:
            self._cache_config = None

        # 翻译状态
        self.in_progress = False
        self.last_request_time: float = 0.0
        self.original_text = ""

        # API健康状态
        self.api_health_status = {"healthy": None, "message": "", "last_check": 0}

        # 上下文历史 (存储格式: [(original, translation, direction), ...])
        # direction: "ME→Counterpart" 或 "Counterpart→ME"
        self.history: dict[int, list[tuple[str, str, str]]] = {}
        for mode_id in self.mode_config.get("translation_modes", {}):
            if isinstance(mode_id, int):
                self.history[mode_id] = []

        # HTTP 400错误修复：初始化时强制重置会话
        # 这将确保所有会话都使用正确的配置（无AsyncResolver）
        logger.info("[初始化] 启动HTTP 400错误修复程序...")
        # 检查是否有运行中的事件循环，如果有则创建任务
        # 通过重新获取事件循环的引用来确保有运行中的事件循环
        current_loop = None
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[初始化] 当前线程没有运行中的事件循环，跳过自动会话重置")
            current_loop = None

        if current_loop is not None:
            try:
                # 只有在真正有运行中的事件循环时才创建任务
                asyncio.create_task(self._initialize_with_session_reset())
                logger.debug("[初始化] 已创建会话重置任务")
            except Exception as task_err:
                logger.error(f"[初始化] 创建会话重置任务失败: {task_err}")
        else:
            logger.warning("[初始化] 无法创建会话重置任务，因为没有运行中的事件循环")

        # 性能优化：连接池复用

        # 性能优化：线程池管理
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=getattr(
                config, "thread_pool_max_workers", 4
            ),  # 从配置读取，默认为4
            thread_name_prefix="TranslatorThreadPool",
        )

        # 性能统计
        self.performance_stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "api_calls": 0,
            "average_response_time": 0.0,
            "total_response_time": 0.0,
            "network_errors": 0,
            "api_errors": 0,
        }

        # 用于管理后台异步任务，防止任务泄露
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self._task_counter = 0  # 任务计数器，用于监控
        self._last_task_cleanup = 0.0  # 上次清理时间
        self._task_cleanup_interval = 300.0  # 清理间隔(秒) - 5分钟

        # 初始化关闭标志
        self._is_shutting_down = False

        logger.info(f"[{threading.current_thread().name}] 翻译引擎初始化完成。")

    def _shutdown_thread_pool_with_timeout(self, timeout: float = 5.0) -> None:
        """带超时机制的线程池关闭方法

        Args:
            timeout: 等待超时时间（秒）
        """
        import threading

        def shutdown_in_thread() -> None:
            """在线程中执行shutdown，避免阻塞主线程"""
            try:
                self._thread_pool.shutdown(wait=True)
            except Exception as e:
                logger.error(f"线程池关闭异常: {e}")

        # 创建一个守护线程来执行shutdown
        shutdown_thread = threading.Thread(target=shutdown_in_thread, daemon=True)
        shutdown_thread.start()

        # 等待线程完成，但设置超时
        shutdown_thread.join(timeout=timeout)

        # 如果线程还在运行，说明shutdown被阻塞了
        if shutdown_thread.is_alive():
            logger.warning(f"线程池关闭超时 ({timeout}s)，可能有任务仍在执行")
            # 不强制终止，让线程继续运行直到完成
        else:
            logger.debug("线程池已正常关闭")

    def add_background_task(self, coro: Any) -> None:
        """添加后台异步任务，包含自动清理机制"""
        if self._is_shutting_down:
            logger.debug("引擎正在关闭，跳过新任务创建")
            return

        try:
            task = asyncio.create_task(coro)
            self.background_tasks.add(task)
            self._task_counter += 1

            # 设置任务完成时的回调，用于自动清理
            task.add_done_callback(self.background_tasks.discard)

            # 定期清理已完成的任务
            current_time = time.time()
            if current_time - self._last_task_cleanup > self._task_cleanup_interval:
                # 异步清理任务
                asyncio.create_task(self._async_cleanup_tasks())

            logger.debug(
                f"已添加后台任务，总计数: {self._task_counter}, "
                f"当前活跃任务: {len(self.background_tasks)}"
            )
        except Exception as e:
            logger.error(f"添加后台任务时出错: {e}", exc_info=True)

    def _cleanup_background_tasks(self) -> None:
        """清理已完成的任务"""
        if self._is_shutting_down:
            # 关闭时清理所有任务
            task_count = len(self.background_tasks)
            for task in list(self.background_tasks):
                if not task.done():
                    task.cancel()
            self.background_tasks.clear()
            logger.debug(f"关闭时清理了 {task_count} 个后台任务")
        else:
            # 定期清理：移除已完成的或取消的任务
            current_tasks = list(self.background_tasks)
            completed_tasks = [
                task for task in current_tasks if task.done() or task.cancelled()
            ]

            for task in completed_tasks:
                self.background_tasks.discard(task)

            if completed_tasks:
                logger.debug(f"清理了 {len(completed_tasks)} 个已完成的任务")

            self._last_task_cleanup = time.time()

    async def _async_cleanup_tasks(self) -> None:
        """异步清理已完成的任务"""
        current_tasks = list(self.background_tasks)
        completed_count = 0

        for task in current_tasks:
            if task.done():
                await task  # 等待任务完成以释放资源，但不关心结果
                completed_count += 1
            elif task.cancelled():
                completed_count += 1
            else:
                continue

        # 清理已完成的任务
        completed_tasks = [
            task for task in self.background_tasks if task.done() or task.cancelled()
        ]

        for task in completed_tasks:
            self.background_tasks.discard(task)

        if completed_count > 0 or completed_tasks:
            logger.debug(
                f"异步清理完成，处理了 {completed_count} 个任务，"
                f"剩余活跃任务: {len(self.background_tasks)}"
            )

    async def async_init(self) -> None:
        """异步初始化翻译引擎组件"""
        # The new CacheManager is initialized and started by the ServiceManager.
        # This method is now primarily for any other async setup the engine might need.
        logger.debug(f"[{threading.current_thread().name}] 翻译引擎异步初始化完成。")

    async def _initialize_with_session_reset(self) -> None:
        """初始化时执行会话重置以修复HTTP 400错误"""
        try:
            # 从配置中获取初始化等待时间
            network_connector_config = (
                getattr(self.config, "network_connector", {}) if self.config else {}
            )
            init_wait_time = network_connector_config.get("init_wait_time", 2.0)

            logger.info(f"[HTTP 400修复] 等待{init_wait_time}秒后执行会话重置...")
            await asyncio.sleep(init_wait_time)  # 等待引擎完全初始化

            # 检查配置中是否启用了会话重置
            force_reset = getattr(self.config, "force_session_reset_on_init", True)
            if force_reset:
                logger.info(
                    "[HTTP 400修复] 检测到force_session_reset_on_init=True，开始强制重置会话"
                )
                await self.force_reset_all_sessions()
            else:
                logger.info(
                    "[HTTP 400修复] force_session_reset_on_init=False，跳过会话重置"
                )

        except Exception as e:
            logger.error(f"[HTTP 400修复] 初始化会话重置失败: {e}")
            # 不抛出异常，避免影响主程序启动

    async def close_all_sessions(self) -> None:
        """关闭所有通过ApiManager管理的HTTP会话。"""
        logger.info("请求ApiManager关闭所有HTTP会话...")
        await self.api_manager.close_all_sessions()

    async def force_reset_all_sessions(self) -> None:
        """请求ApiManager强制重置所有HTTP会话。"""
        logger.info("请求ApiManager强制重置所有HTTP会话...")
        await (
            self.api_manager.close_all_sessions()
        )  # ApiManager的close会清空缓存，效果等同于重置

    def update_performance_stats(
        self, operation: str, response_time: float = 0.0, success: bool = True
    ) -> None:
        """更新性能统计

        Args:
            operation: 操作类型 ('cache_hit', 'api_call', 'network_error', 'api_error')
            response_time: 响应时间（秒）
            success: 是否成功
        """
        if operation == "total_request":
            self.performance_stats["total_requests"] += 1
        elif operation == "cache_hit":
            self.performance_stats["cache_hits"] += 1
        elif operation == "api_call":
            self.performance_stats["api_calls"] += 1
            if response_time > 0:
                self.performance_stats["total_response_time"] += response_time
                self.performance_stats["average_response_time"] = (
                    self.performance_stats["total_response_time"]
                    / self.performance_stats["api_calls"]
                )
        elif operation == "network_error":
            self.performance_stats["network_errors"] += 1
        elif operation == "api_error":
            self.performance_stats["api_errors"] += 1

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息

        Returns:
            dict: 性能统计数据
        """
        stats = self.performance_stats.copy()

        # 计算缓存命中率
        if stats["total_requests"] > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["total_requests"]
        else:
            stats["cache_hit_rate"] = 0.0

        # 计算错误率
        total_errors = stats["network_errors"] + stats["api_errors"]
        if stats["total_requests"] > 0:
            stats["error_rate"] = total_errors / stats["total_requests"]
        else:
            stats["error_rate"] = 0.0

        return stats

    def close(self) -> None:
        """关闭翻译引擎，释放资源"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始关闭翻译引擎...")

        # 关闭所有HTTP会话
        # 会话关闭由ApiManager处理

        # 关闭线程池（带超时机制）
        if self._thread_pool:
            logger.debug(f"[{current_thread_name}] 关闭线程池...")
            try:
                # 使用超时机制避免无限等待
                self._shutdown_thread_pool_with_timeout(timeout=5.0)
                logger.info(f"[{current_thread_name}] 线程池已关闭。")
            except Exception as e:
                logger.warning(
                    f"[{current_thread_name}] 关闭线程池时出错: {e}，尝试强制关闭..."
                )
                try:
                    self._thread_pool.shutdown(wait=False)
                    logger.info(f"[{current_thread_name}] 线程池已强制关闭。")
                except Exception as force_e:
                    logger.error(
                        f"[{current_thread_name}] 强制关闭线程池失败: {force_e}"
                    )

        # 关闭缓存管理器
        if self.cache_manager:
            logger.debug(f"[{current_thread_name}] 关闭缓存管理器...")
            try:
                if self.loop and self.loop.is_running():
                    # Shutdown is now handled by ServiceManager
                    pass
                else:
                    # Shutdown is now handled by ServiceManager
                    pass
                logger.info(f"[{current_thread_name}] 缓存管理器已关闭。")
            except Exception as e:
                logger.error(f"[{current_thread_name}] 关闭缓存管理器时出错: {e}")

        logger.info(f"[{current_thread_name}] 翻译引擎已关闭。")

    async def async_close(self) -> None:
        """异步关闭翻译引擎，等待所有后台任务完成"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始异步关闭翻译引擎...")

        # 等待后台异步任务完成
        if self.background_tasks:
            logger.debug(
                f"[{current_thread_name}] 翻译引擎有 {len(self.background_tasks)} 个后台任务正在运行，等待其完成..."
            )
            logger.debug(f"[任务监控] 总共创建过 {self._task_counter} 个异步任务")
            try:
                # 取消所有未完成的任务
                pending_tasks = [
                    task for task in self.background_tasks if not task.done()
                ]
                for task in pending_tasks:
                    task.cancel()

                # 等待任务取消完成
                if pending_tasks:
                    try:
                        await asyncio.gather(*pending_tasks, return_exceptions=True)
                    except Exception:
                        pass  # 忽略取消过程中的异常

                logger.info(f"[{current_thread_name}] 所有后台异步任务已完成。")
            except Exception as e:
                logger.error(f"[{current_thread_name}] 等待后台异步任务时出错: {e}")
            finally:
                # 清空任务集合
                self.background_tasks.clear()
                logger.debug(
                    f"[任务监控] 清理后剩余后台任务: {len(self.background_tasks)}"
                )

        # 关闭所有HTTP会话
        # 会话关闭由ApiManager处理
        await self.api_manager.close_all_sessions()

        # 关闭线程池（带超时机制）
        if self._thread_pool:
            logger.debug(f"[{current_thread_name}] 关闭线程池...")
            try:
                # 使用超时机制避免无限等待
                self._shutdown_thread_pool_with_timeout(timeout=5.0)
                logger.info(f"[{current_thread_name}] 线程池已关闭。")
            except Exception as e:
                logger.warning(
                    f"[{current_thread_name}] 关闭线程池时出错: {e}，尝试强制关闭..."
                )
                try:
                    self._thread_pool.shutdown(wait=False)
                    logger.info(f"[{current_thread_name}] 线程池已强制关闭。")
                except Exception as force_e:
                    logger.error(
                        f"[{current_thread_name}] 强制关闭线程池失败: {force_e}"
                    )

        # 关闭缓存管理器
        if self.cache_manager:
            logger.debug(f"[{current_thread_name}] 关闭缓存管理器...")
            try:
                # Shutdown is now handled by ServiceManager
                pass
                logger.info(f"[{current_thread_name}] 缓存管理器已关闭。")
            except Exception as e:
                logger.error(f"[{current_thread_name}] 关闭缓存管理器时出错: {e}")

        logger.info(f"[{current_thread_name}] 翻译引擎已关闭。")

    def clear_context_for_mode(self, mode_id: int) -> None:
        """清空指定模式的上下文历史

        Args:
            mode_id: 模式ID
        """
        if mode_id in self.history:
            self.history[mode_id].clear()
            logger.debug(f"已清空模式 {mode_id} 的上下文历史")

    def clear_all_context(self) -> None:
        """清空所有模式的内存上下文历史和磁盘上的上下文文件。"""
        # 清空内存中的历史记录
        for mode_id in self.history:
            self.history[mode_id].clear()
        logger.info("已清空所有模式的内存上下文历史。")

        # 清空磁盘上的上下文文件
        deleted_count = self.context_manager.clear_all_context()
        logger.info(f"已从磁盘删除 {deleted_count} 个上下文文件。")

    def get_context_stats(self) -> Dict[str, Any]:
        """获取上下文统计信息。"""
        # 从 ContextManager 获取磁盘文件统计
        disk_stats = self.context_manager.get_stats()

        # 获取内存中的上下文统计
        total_in_memory_records = sum(len(hist) for hist in self.history.values())

        return {
            "total_files": disk_stats.get("total_files", 0),
            "total_size_bytes": disk_stats.get("total_size_bytes", 0),
            "in_memory_records": total_in_memory_records,
            "total": disk_stats.get("total_files", 0),  # 为了向后兼容
        }

    def determine_translation_direction(
        self, detected_lang: str, mode_id: int
    ) -> tuple[str, str, str]:
        """根据检测到的语言和当前模式，确定翻译的源、目标和方向标签。

        Args:
            detected_lang: 检测到的源语言代码。
            mode_id: 当前的翻译模式ID。

        Returns:
            一个元组，包含 (源语言代码, 目标语言代码, 方向标签)。
            方向标签格式为 "ME→Counterpart" 或 "Counterpart→ME"。
        """
        translation_modes = self.mode_config.get("translation_modes", {})
        mode_info = translation_modes.get(mode_id, {})
        mode_source_code = mode_info.get("source_code", "zh")
        mode_target_code = mode_info.get("target_code", "en")

        if detected_lang == mode_source_code:
            source_lang = mode_source_code
            target_lang = mode_target_code
            direction = "ME→Counterpart"
        elif detected_lang == mode_target_code:
            source_lang = mode_target_code
            target_lang = mode_source_code
            direction = "Counterpart→ME"
        else:
            source_lang = detected_lang
            target_lang = mode_info.get("default_lang", mode_target_code)
            direction = "ME→Counterpart"  # 未知语言默认为用户发出

        return source_lang, target_lang, direction

    def add_to_history(
        self, mode_id: int, original: str, translation: str, direction: str
    ) -> None:
        """将翻译对和方向添加到指定模式的上下文历史中

        Args:
            mode_id: 模式ID
            original: 原文
            translation: 译文
            direction: 翻译方向 ("ME→Counterpart" 或 "Counterpart→ME")
        """
        if mode_id not in self.history:
            self.history[mode_id] = []

        self.history[mode_id].append((original, translation, direction))

        # 限制历史记录长度
        max_history_length = getattr(self.config, "max_history_length", 10)
        if len(self.history[mode_id]) > max_history_length:
            self.history[mode_id] = self.history[mode_id][-max_history_length:]

        logger.debug(
            f"已将翻译对和方向添加到模式 {mode_id} 的上下文历史，当前历史长度: {len(self.history[mode_id])}"
        )

    def add_to_history_batch(
        self, mode_id: int, history_items: list[tuple[str, str, str]]
    ) -> None:
        """批量添加翻译对和方向到指定模式的上下文历史中

        Args:
            mode_id: 模式ID
            history_items: 包含 (original, translation, direction) 的元组列表
        """
        if not history_items:
            return

        if mode_id not in self.history:
            self.history[mode_id] = []

        self.history[mode_id].extend(history_items)

        # 限制历史记录长度
        max_history_length = getattr(self.config, "max_history_length", 10)
        if len(self.history[mode_id]) > max_history_length:
            self.history[mode_id] = self.history[mode_id][-max_history_length:]

        logger.debug(
            f"已批量添加 {len(history_items)} 条记录到模式 {mode_id} 的上下文历史，当前历史长度: {len(self.history[mode_id])}"
        )

    async def save_to_cache(
        self,
        original_text: str,
        target_lang: str,
        source_lang: str,
        translation: str,
        timestamp: Optional[float] = None,
    ) -> None:
        """保存翻译结果到缓存 (简化版)

        Args:
            original_text: 原文
            target_lang: 目标语言代码
            source_lang: 源语言代码
            translation: 翻译结果
            timestamp: 翻译完成的时间戳
        """
        if self.cache_manager:
            # 获取当前翻译模式，确保不同模式的缓存独立
            mode_id = getattr(self.config, "translation_mode", None)
            # 调用简化后的 add_translation 方法
            self.cache_manager.add_translation(
                original_text,
                target_lang,
                translation,
                source_lang,
                mode=str(mode_id) if mode_id else None,
            )
            logger.debug(
                f"翻译结果已保存到缓存: {original_text[:50]}... -> {translation[:50]}..."
            )
        else:
            logger.warning("缓存管理器未初始化，无法保存到缓存")

    async def translate_text_async(
        self, original_text: str, gui_handler: Any
    ) -> tuple[Optional[str], str, Dict[str, Any]]:
        """异步翻译文本

        Args:
            original_text: 原文
            gui_handler: GUI处理器

        Returns:
            tuple: (翻译结果, 翻译来源, 翻译信息)
        """
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始翻译文本，长度: {len(original_text)}")
        self.update_performance_stats("total_request")

        # 1. 语言检测
        logger.debug(f"[{current_thread_name}] 开始语言检测")

        # 获取语言检测相关配置
        supported_langs = self.mode_config.get("supported_langs", {})
        language_features = self.mode_config.get("language_features", {})

        detected_lang = detect_language_with_cache(
            original_text,
            hint_lang=None,
            supported_langs=supported_langs,
            language_features=language_features,
            config=self.config,
            compiled_patterns=self.language_detector._compiled_patterns,
        )
        logger.info(f"[{current_thread_name}] 语言检测完成: {detected_lang}")

        # 2. 获取目标语言
        mode_id = getattr(self.config, "translation_mode", 1)
        translation_modes = self.mode_config.get("translation_modes", {})
        mode_info = translation_modes.get(mode_id, {})
        # 应用双向翻译逻辑：根据检测到的语言动态确定目标语言
        # 确定翻译方向
        source_lang, target_lang_code, direction = self.determine_translation_direction(
            detected_lang, mode_id
        )
        logger.debug(
            f"[{current_thread_name}] 模式配置: 源语言={mode_info.get('source_code', 'zh')}, 目标语言={mode_info.get('target_code', 'en')}"
        )
        logger.debug(
            f"[{current_thread_name}] 检测到语言: {detected_lang}, 实际目标语言: {target_lang_code}"
        )

        # 3. 检查缓存
        logger.debug(f"[{current_thread_name}] 检查缓存")
        cached_translation = None

        # 缓存查询前，需要确定api_mode和model_id，这里先用None，因为还没有选择API
        # 这是一个循环依赖，先尝试从缓存获取，如果获取不到才选择API和模型
        # 因此，在首次缓存查询时，api_mode和model_id应为None。
        # 只有在API调用成功后，才能将实际使用的api_mode和model_id传给缓存。
        if self.cache_manager:
            cached_translation = self.cache_manager.get_translation(
                original_text, target_lang_code, detected_lang
            )

        if cached_translation:
            logger.info(f"[{current_thread_name}] 缓存命中")
            self.update_performance_stats("cache_hit")
            translation_info = {
                "detected_lang": detected_lang,
                "target_lang": target_lang_code,
                "source": "cache",
                "cached": True,
                "direction": direction,
            }
            return cached_translation, "cache", translation_info

        # 4. 如果缓存未命中，调用API进行翻译
        logger.info(f"[{current_thread_name}] 缓存未命中，调用API进行翻译")

        # 构建上下文历史
        mode_id = getattr(self.config, "translation_mode", 1)
        context_history = self.history.get(mode_id, [])

        # 构建提示词
        prompt, direction_role = self.prompt_builder.build_translation_prompt(
            original_text, detected_lang, target_lang_code, context_history
        )

        # 使用带质量评估的翻译方法
        translation_result = await self.api_manager.translate_with_quality_check(
            prompt=prompt,
            gui_handler=gui_handler,
            original_text=original_text,
            detected_lang=detected_lang,
            target_lang_code=target_lang_code,
            config=self.config,
            mode_config=self.mode_config,
        )

        # 安全的类型验证日志
        if translation_result is not None:
            result_preview = (
                translation_result[:100]
                if isinstance(translation_result, str)
                else str(translation_result)
            )
            logger.debug(
                f"[DEBUG_TYPE] translation_result type: {type(translation_result)}, value: {result_preview}"
            )
        else:
            logger.debug("[DEBUG_TYPE] translation_result is None")

        # 验证翻译结果
        def _validate_translation_result(result: Any) -> bool:
            """验证翻译结果是否有效"""
            if result is None:
                return False
            if not isinstance(result, str):
                return False
            if result.startswith("翻译失败"):
                return False
            if not result.strip():
                return False
            return True

        # 处理翻译结果
        if _validate_translation_result(translation_result):
            translation_source = "api"
            # _validate_translation_result 已确保 translation_result 是有效的字符串
            # _validate_translation_result 也确保 detected_lang 不是 None
            # 保存到缓存（包含mode参数以区分不同翻译模式）
            await self.save_to_cache(
                original_text,
                target_lang_code,
                detected_lang,
                translation_result,  # type: ignore[arg-type]  # validated above
            )

            # 确定翻译方向并添加到上下文历史
            # 使用从 determine_translation_direction 获取的权威方向
            # 使用从 determine_translation_direction 获取的权威方向
            self.add_to_history(
                mode_id,
                original_text,
                translation_result,  # type: ignore[arg-type]  # validated above by _validate_translation_result
                direction,  # validated above by _validate_translation_result
            )
            logger.info(f"翻译结果已添加到模式 {mode_id} 的上下文历史")
        else:
            translation_source = "error"

        translation_info = {
            "detected_lang": detected_lang,
            "target_lang": target_lang_code,
            "source": translation_source,
            "cached": False,
            "direction": direction_role,
        }

        logger.info(f"[{current_thread_name}] 翻译完成，来源: {translation_source}")
        return translation_result, translation_source, translation_info
