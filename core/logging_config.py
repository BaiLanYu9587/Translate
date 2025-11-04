#!/usr/bin/env python3
"""
统一的日志配置模块
负责根据配置文件设置全局日志级别和处理器
"""

import logging
import logging.handlers
import sys
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from .config_management import Config, LoggingConfig

logger = logging.getLogger(__name__)


class SensitiveDataFilter(logging.Filter):
    """日志敏感信息脱敏过滤器。

    规则：
    - URL 查询中的 key= / api_key= / apikey= 的值替换为 ***
    - Authorization: Bearer <token> 的 token 替换为 ***
    - 常见 header 里的密钥（x-api-key 等）替换为 ***
    """

    _patterns = [
        # 查询参数中的 key / api_key / apikey
        (
            re.compile(r"(\b(?:key|api_key|apikey)\s*=)\s*[^&\s]+", re.IGNORECASE),
            r"\1***",
        ),
        # JSON/日志中的 "api_key": "..."
        (
            re.compile(r"(\"?api_key\"?\s*[:=]\s*\")([^\"]+)(\")", re.IGNORECASE),
            r"\1***\3",
        ),
        # Authorization: Bearer
        (
            re.compile(
                r"(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE
            ),
            r"\1***",
        ),
        # x-api-key / X-API-Key 样式
        (re.compile(r"(x-api-key\s*[:=]\s*)[^\s,]+", re.IGNORECASE), r"\1***"),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            masked = message
            for pattern, repl in self._patterns:
                masked = pattern.sub(repl, masked)
            # 替换原始内容，避免二次格式化
            record.msg = masked
            record.args = ()
        except Exception:
            # 出现异常不影响日志输出
            pass
        return True


class LimitedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """支持按日志级别和条目数量限制的异步文件处理器"""

    def __init__(
        self,
        filename: str,
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: Optional[str] = None,
        delay: bool = False,
        logging_config: Optional[LoggingConfig] = None,
    ) -> None:
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)
        self.log_info_max: int = logging_config.info_max if logging_config else 100
        self.log_other_max: int = logging_config.other_max if logging_config else 100
        self._cleanup_interval: float = (
            logging_config.cleanup_interval if logging_config else 2.0
        )
        self._cleanup_lock: threading.RLock = threading.RLock()
        self._file_lock: threading.RLock = threading.RLock()
        self._cleanup_pending: bool = False
        self._last_cleanup_time: float = 0.0
        self._new_logs_since_last_cleanup: int = 0
        self._active_cleanup_threads: int = 0
        self._async_executor: Optional[ThreadPoolExecutor] = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="log-io"
        )
        self._is_blocked: bool = False
        self._block_timeout: float = 2.0
        self._emit_depth: int = 0

    def _async_write_log(self, formatted_message: str) -> None:
        """异步写入日志消息"""
        try:
            with open(self.baseFilename, "a", encoding="utf-8") as f:
                f.write(formatted_message)
        except Exception:
            pass

    def emit(self, record: logging.LogRecord) -> None:
        """发出日志记录，并异步检查是否需要按条目数量轮转"""
        if self._is_blocked:
            return
        self._emit_depth += 1
        if self._emit_depth > 5:
            self._emit_depth -= 1
            return
        try:
            if not self._async_executor or (
                hasattr(self._async_executor, "_shutdown")
                and self._async_executor._shutdown
            ):
                return
            formatted_message = self.format(record)
            future = self._async_executor.submit(
                self._async_write_log, formatted_message
            )
            try:
                future.result(timeout=self._block_timeout)
                self._is_blocked = False
                with self._cleanup_lock:
                    self._new_logs_since_last_cleanup += 1
                self._schedule_cleanup_check()
            except TimeoutError:
                self._is_blocked = True
                future.cancel()
                sys.stderr.write(
                    f"[LOG_IO_BLOCKED] 日志写入耗时超过 {self._block_timeout}s，暂停日志写入\n"
                )
        except Exception as e:
            try:
                sys.stderr.write(f"日志写入失败: {e}\n")
                sys.stderr.flush()
            except Exception:
                pass
        finally:
            self._emit_depth = max(0, self._emit_depth - 1)

    def _schedule_cleanup_check(self) -> None:
        """调度异步清理检查"""
        current_time = time.time()
        if current_time - self._last_cleanup_time < self._cleanup_interval:
            return
        min_limit: int = int(min(self.log_info_max, self.log_other_max))
        cleanup_trigger_threshold: int = max(1, min(5, max(1, min_limit // 5)))
        if self._new_logs_since_last_cleanup < cleanup_trigger_threshold:
            return
        with self._cleanup_lock:
            if self._cleanup_pending or self._active_cleanup_threads > 0:
                return
            self._cleanup_pending = True
            self._active_cleanup_threads += 1
        cleanup_thread = threading.Thread(
            target=self._async_check_log_limits, daemon=True
        )
        cleanup_thread.start()

    def _async_check_log_limits(self) -> None:
        """异步检查日志条目数量限制并清理旧日志"""
        try:
            with self._file_lock:
                self._last_cleanup_time = time.time()
                with self._cleanup_lock:
                    self._new_logs_since_last_cleanup = 0
                if not os.path.exists(self.baseFilename):
                    return
                try:
                    with open(self.baseFilename, "r+", encoding="utf-8"):
                        pass
                except (PermissionError, OSError) as e:
                    sys.stderr.write(f"日志文件被占用，跳过清理: {e}\n")
                    return
            try:
                with open(
                    self.baseFilename, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    lines = f.readlines()
            except Exception:
                try:
                    with open(
                        self.baseFilename, "r", encoding="utf-8-sig", errors="ignore"
                    ) as f:
                        lines = f.readlines()
                except Exception:
                    with open(self.baseFilename, "w", encoding="utf-8") as f:
                        f.write("")
                    return
            if not lines:
                return
            valid_log_lines, info_lines, other_lines = [], [], []
            log_pattern = re.compile(
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} - (INFO|WARNING|ERROR|DEBUG) - "
            )
            for line in lines:
                clean_line = "".join(
                    char for char in line if ord(char) >= 32 or char in "\n\r\t"
                )
                if log_pattern.match(clean_line):
                    valid_log_lines.append(clean_line)
                    if " - INFO - " in clean_line:
                        info_lines.append(clean_line)
                    elif any(
                        level in clean_line
                        for level in [" - WARNING - ", " - ERROR - ", " - DEBUG - "]
                    ):
                        other_lines.append(clean_line)
            has_invalid_content = len(valid_log_lines) < len(lines)
            should_cleanup = (
                has_invalid_content
                or len(info_lines) > self.log_info_max
                or len(other_lines) > self.log_other_max
            )
            if not should_cleanup:
                return
            info_to_keep = min(len(info_lines), self.log_info_max)
            other_to_keep = min(len(other_lines), self.log_other_max)
            new_lines = []
            if len(info_lines) > info_to_keep:
                new_lines.extend(info_lines[-info_to_keep:])
            else:
                new_lines.extend(info_lines)
            if len(other_lines) > other_to_keep:
                new_lines.extend(other_lines[-other_to_keep:])
            else:
                new_lines.extend(other_lines)
            try:
                new_lines.sort(
                    key=lambda x: x[:19] if len(x) >= 19 else "0000-00-00 00:00:00"
                )
            except Exception:
                pass
            with open(self.baseFilename, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            info_removed = len(info_lines) - info_to_keep
            other_removed = len(other_lines) - other_to_keep
            invalid_removed = len(lines) - len(valid_log_lines)
            if info_removed > 0 or other_removed > 0 or invalid_removed > 0:
                cleanup_msg = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - INFO - logging_config - 日志清理完成，删除了 {info_removed} 条INFO日志、{other_removed} 条其他日志、{invalid_removed} 条无效内容，保留INFO: {info_to_keep}条，其他: {other_to_keep}条\n"
                with open(self.baseFilename, "a", encoding="utf-8") as f:
                    f.write(cleanup_msg)
        except Exception as e:
            try:
                error_msg = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ERROR - logging_config - 日志清理失败: {str(e)}\n"
                with open(self.baseFilename, "a", encoding="utf-8") as f:
                    f.write(error_msg)
            except Exception:
                pass
        finally:
            with self._cleanup_lock:
                self._cleanup_pending = False
                self._active_cleanup_threads = max(0, self._active_cleanup_threads - 1)


class LoggingManager:
    """日志配置管理器"""

    _initialized = False
    _root_logger = None
    _console_handler = None
    _file_handler = None
    logger = logging.getLogger(__name__)

    @classmethod
    def initialize(cls, config: Optional[Config] = None) -> None:
        """初始化日志系统"""
        current_thread_name = threading.current_thread().name
        if cls._initialized:
            cls.logger.debug(
                f"[{current_thread_name}] 日志系统已初始化，跳过重复初始化。"
            )
            return
        cls._root_logger = logging.getLogger()
        cls.logger.debug(f"[{current_thread_name}] 获取根日志记录器。")
        for handler in cls._root_logger.handlers[:]:
            cls._root_logger.removeHandler(handler)
        cls.logger.debug(f"[{current_thread_name}] 已清除所有现有日志处理器。")
        debug_mode = config.debug_mode if config else False
        log_level = logging.DEBUG if debug_mode else logging.INFO
        cls._root_logger.setLevel(log_level)
        logging.getLogger("aiosqlite").setLevel(logging.WARNING)
        cls.logger.debug(
            f"[{current_thread_name}] 设置根日志级别为: {logging.getLevelName(log_level)}"
        )
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - [%(threadName)s] - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        cls._setup_console_handler(formatter, log_level)
        cls._setup_file_handler(formatter, config)
        cls._initialized = True
        cls.logger.info(
            f"[{current_thread_name}] 日志系统已初始化，调试模式: {'开启' if debug_mode else '关闭'}"
        )

    @classmethod
    def _setup_console_handler(
        cls, formatter: logging.Formatter, log_level: int
    ) -> None:
        """设置控制台处理器"""
        cls._console_handler = logging.StreamHandler(sys.stdout)
        cls._console_handler.setLevel(log_level)
        cls._console_handler.setFormatter(formatter)
        cls._console_handler.addFilter(SensitiveDataFilter())
        if cls._root_logger is not None:
            cls._root_logger.addHandler(cls._console_handler)

    @classmethod
    def _setup_file_handler(
        cls, formatter: logging.Formatter, config: Optional[Config]
    ) -> None:
        """设置文件处理器"""
        try:
            from .config_management import get_logs_dir

            logs_dir = get_logs_dir()
            log_file = os.path.join(logs_dir, "app.log")
            max_bytes = config.log_max_bytes if config else 2 * 1024 * 1024
            backup_count = config.log_backup_count if config else 3
            logging_config = config.logging if config else None
            cls._file_handler = LimitedRotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
                logging_config=logging_config,
            )
            cls._file_handler.setLevel(logging.INFO)
            cls._file_handler.setFormatter(formatter)
            cls._file_handler.addFilter(SensitiveDataFilter())
            if cls._root_logger is not None:
                cls._root_logger.addHandler(cls._file_handler)
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"文件日志处理器初始化失败: {e}")

    @classmethod
    def update_log_level(cls, debug_mode: bool) -> None:
        """动态更新日志级别"""
        current_thread_name = threading.current_thread().name
        if not cls._initialized:
            cls.logger.warning(
                f"[{current_thread_name}] 尝试在日志系统未初始化时更新日志级别。"
            )
            return
        log_level = logging.DEBUG if debug_mode else logging.INFO
        if cls._root_logger is not None:
            cls._root_logger.setLevel(log_level)
            cls.logger.debug(
                f"[{current_thread_name}] 根日志级别已更新为: {logging.getLevelName(log_level)}"
            )
        if cls._console_handler is not None:
            cls._console_handler.setLevel(log_level)
            cls.logger.debug(
                f"[{current_thread_name}] 控制台处理器日志级别已更新为: {logging.getLevelName(log_level)}"
            )
        cls.logger.info(
            f"[{current_thread_name}] 日志级别已更新，调试模式: {'开启' if debug_mode else '关闭'}"
        )

    @classmethod
    def is_initialized(cls) -> bool:
        """检查日志系统是否已初始化"""
        return cls._initialized

    @classmethod
    def get_root_logger(cls) -> Optional[logging.Logger]:
        """获取根日志记录器实例"""
        return cls._root_logger

    @classmethod
    def shutdown(cls) -> None:
        """关闭日志系统，正确清理资源"""
        try:
            if cls._file_handler and isinstance(
                cls._file_handler, LimitedRotatingFileHandler
            ):
                if (
                    hasattr(cls._file_handler, "_async_executor")
                    and cls._file_handler._async_executor
                ):
                    executor = cls._file_handler._async_executor
                    if not executor._shutdown:
                        cls._shutdown_executor_with_timeout(executor, timeout=3.0)
                        cls._file_handler._async_executor = None
        except Exception as e:
            logger.error(f"关闭日志系统时出错: {e}")
        finally:
            cls._initialized = False
            cls._file_handler = None
            cls._console_handler = None

    @classmethod
    def _shutdown_executor_with_timeout(
        cls, executor: ThreadPoolExecutor, timeout: float = 3.0
    ) -> None:
        """带超时机制的线程池执行器关闭方法

        Args:
            executor: 要关闭的线程池执行器
            timeout: 等待超时时间（秒）
        """

        def shutdown_in_thread() -> None:
            """在线程中执行shutdown，避免阻塞主线程"""
            try:
                executor.shutdown(wait=True)
            except Exception as e:
                logger.error(f"日志线程池关闭异常: {e}")

        # 创建一个守护线程来执行shutdown
        shutdown_thread = threading.Thread(target=shutdown_in_thread, daemon=True)
        shutdown_thread.start()

        # 等待线程完成，但设置超时
        shutdown_thread.join(timeout=timeout)

        # 如果线程还在运行，说明shutdown被阻塞了
        if shutdown_thread.is_alive():
            logger.warning(
                f"日志线程池关闭超时 ({timeout}s)，可能有日志写入任务仍在执行"
            )
            # 不强制终止，让线程继续运行直到完成
        else:
            logger.debug("日志线程池已正常关闭")

    @classmethod
    def get_log_file_path(cls, script_dir: Optional[str] = None) -> str:
        """获取日志文件路径"""
        from .config_management import get_logs_dir

        logs_dir = get_logs_dir()
        return os.path.join(logs_dir, "app.log")


def setup_logging(config: Optional[Config] = None) -> None:
    """便捷函数：设置日志系统"""
    LoggingManager.initialize(config)


def update_debug_mode(debug_mode: bool) -> None:
    """便捷函数：更新调试模式"""
    LoggingManager.update_log_level(debug_mode)
