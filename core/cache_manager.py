"""
简化的缓存模块 - 添加同步SQLite持久化支持

基于纯内存LRU版本，添加同步SQLite持久化以避免重启丢失缓存，
保持代码简洁，无异步复杂性。
"""

import time
import logging
import sqlite3
import threading
from typing import Optional, Tuple
from collections import OrderedDict
import pathlib
import xxhash  # type: ignore[import-untyped]

from core.config_management import Config, get_cache_file_path

logger = logging.getLogger(__name__)


class SimpleLRUCache:
    """简化的LRU缓存实现"""

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3 * 24 * 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, Tuple[str, float]] = OrderedDict()

    def get(self, key: str) -> Optional[str]:
        """获取缓存项"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp <= self.ttl_seconds:
                self.cache.move_to_end(key)  # 更新LRU顺序
                return value
            else:
                del self.cache[key]
        return None

    def put(self, key: str, value: str) -> None:
        """设置缓存项"""
        current_time = time.time()
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, current_time)

        # LRU清理：超过最大容量时移除最旧的
        if len(self.cache) > self.max_size:
            _, _ = self.cache.popitem(last=False)

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()


class CacheManager:
    """
    简化的缓存管理器。
    核心功能：
    - 纯内存LRU缓存，无异步开销
    - 直接内存保存，无延迟
    - 双向缓存支持（A->B 和 B->A）
    """

    def __init__(self, config: Config) -> None:
        logger.info("初始化简化的 CacheManager (同步SQLite持久化版本)")
        self.config = config
        max_entries = getattr(config, "cache_max_entries", 1000)
        ttl_seconds = getattr(config, "cache_ttl_seconds", 3 * 24 * 3600)
        self.memory_cache = SimpleLRUCache(
            max_size=max_entries, ttl_seconds=ttl_seconds
        )

        # 初始化数据库
        self.db_path = pathlib.Path(get_cache_file_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # 线程锁确保并发安全
        self._lock = threading.Lock()

        # 创建表
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS cache
                          (key TEXT PRIMARY KEY, value TEXT, timestamp REAL)""")
            logger.info("数据库表创建/验证成功")

        # 从数据库加载到内存，只加载未过期的数据
        self._load_from_database()
        logger.info(
            f"CacheManager 初始化完成，容量: {max_entries}，TTL: {ttl_seconds}秒"
        )

    def start(self) -> None:
        """启动缓存管理器（简化版本无操作）"""
        logger.info("CacheManager (简化版) 已启动")

    def generate_key(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> str:
        """生成基于内容的缓存键，包含翻译模式以防止跨模式缓存冲突"""
        parts = [text, target_lang]
        if source_lang:
            parts.append(source_lang)
        if mode:
            parts.append(mode)
        combined_string = "_".join(str(p) for p in parts if p is not None)
        return xxhash.xxh64(combined_string.encode("utf-8")).hexdigest()

    def get_translation(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Optional[str]:
        """获取缓存的翻译结果"""
        if not text or not target_lang:
            return None

        key = self.generate_key(text, target_lang, source_lang, mode)

        with self._lock:
            result = self.memory_cache.get(key)

        if result:
            logger.info("[缓存命中] 直接内存访问")
        else:
            logger.debug("[缓存未命中] 无缓存记录")

        return result

    def _load_from_database(self) -> None:
        """从数据库加载缓存到内存，只加载未过期数据"""
        with self._lock:
            try:
                current_time = time.time()
                ttl = self.memory_cache.ttl_seconds
                cutoff_time = current_time - ttl

                with sqlite3.connect(str(self.db_path)) as conn:
                    cursor = conn.execute(
                        "SELECT key, value, timestamp FROM cache WHERE timestamp > ?",
                        (cutoff_time,),
                    )
                    loaded_count = 0
                    for key, value, timestamp in cursor:
                        # 数据库查询已经过滤了过期数据，这里只需要存储
                        self.memory_cache.put(key, value)
                        loaded_count += 1

                    logger.info(f"从数据库加载 {loaded_count} 条未过期缓存")

            except Exception as e:
                logger.warning(f"从数据库加载缓存失败: {e}")

    def _save_to_database(self, key: str, value: str, timestamp: float) -> None:
        """同步保存缓存项到数据库"""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache (key, value, timestamp) VALUES (?, ?, ?)",
                    (key, value, timestamp),
                )
                logger.debug(f"[数据库写入] 保存缓存项: {key[:20]}...")
        except Exception as e:
            logger.warning(f"保存缓存到数据库失败: {e}")

    def add_translation(
        self,
        text: str,
        target_lang: str,
        translation: str,
        source_lang: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> None:
        """添加翻译结果到缓存（支持双向存储）"""
        if not text or not target_lang or not translation or text == translation:
            return

        # 获取当前时间
        current_time = time.time()

        # 准备存储的数据
        forward_key = self.generate_key(text, target_lang, source_lang, mode)

        reverse_data = None
        reverse_key = None  # type: ignore[assignment]
        if source_lang:
            reverse_key = self.generate_key(translation, source_lang, target_lang, mode)
            reverse_data = (reverse_key, text, current_time)

        # 原子性存储：要么全部成功，要么全部失败
        try:
            # 1. 先存储到内存
            self.memory_cache.put(forward_key, translation)
            if reverse_data and reverse_key:
                self.memory_cache.put(reverse_key, text)

            # 2. 再存储到数据库
            self._save_to_database(forward_key, translation, current_time)
            if reverse_data and reverse_key:
                self._save_to_database(reverse_key, text, current_time)

            logger.debug("[缓存存储] 正向+反向双向存储完成，包含磁盘持久化")

        except Exception as e:
            # 如果数据库存储失败，回滚内存中的更改
            try:
                if forward_key in self.memory_cache.cache:
                    del self.memory_cache.cache[forward_key]
                    self.memory_cache.cache.move_to_end(forward_key)
                if reverse_data and reverse_key in self.memory_cache.cache:
                    del self.memory_cache.cache[reverse_key]
                    self.memory_cache.cache.move_to_end(reverse_key)
            except Exception as rollback_error:
                logger.error(f"回滚内存缓存失败: {rollback_error}")

            logger.error(f"缓存存储失败，已回滚更改: {e}")
            raise  # 重新抛出异常，让调用方知道存储失败

    def clear_all_cache(self) -> None:
        """清除所有缓存，包括内存和数据库"""
        with self._lock:
            self.memory_cache.clear()
            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    conn.execute("DELETE FROM cache")
                    logger.info("已清除所有数据库缓存")
            except Exception as e:
                logger.warning(f"清除数据库缓存失败: {e}")
            logger.info("已清除所有内存和数据库缓存")

    def clear_expired_records(self, cleanup_days: int) -> None:
        """同步清理数据库中过期的记录"""
        current_thread_name = threading.current_thread().name
        logger.info(f"[{current_thread_name}] 开始执行同步数据库记录清理...")

        if cleanup_days == 0:
            logger.info(f"[{current_thread_name}] 数据库清理天数设置为0，跳过。")
            return

        try:
            cutoff_time = time.time() - (cleanup_days * 24 * 60 * 60)
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "DELETE FROM cache WHERE timestamp < ?", (cutoff_time,)
                )
                deleted_count = cursor.rowcount
                conn.commit()

                if deleted_count > 0:
                    logger.info(
                        f"[{current_thread_name}] 成功清理了 {deleted_count} 条过期的数据库缓存记录。"
                    )
                else:
                    logger.info(
                        f"[{current_thread_name}] 没有找到需要清理的旧数据库记录。"
                    )

        except Exception as e:
            logger.error(f"[{current_thread_name}] 同步清理数据库记录时出错: {e}")

    def cleanup_expired_cache(self) -> int:
        """清理过期缓存，防止内存泄漏"""
        with self._lock:
            try:
                # 清理内存缓存中的过期项
                memory_cleaned = 0
                current_time = time.time()

                # 手动清理过期项（因为 SimpleLRUCache 的 get 方法会自动清理）
                # 这里主要是为了确保在高并发情况下也能正确清理
                keys_to_remove = []
                for key, (value, timestamp) in list(self.memory_cache.cache.items()):
                    if current_time - timestamp > self.memory_cache.ttl_seconds:
                        keys_to_remove.append(key)

                for key in keys_to_remove:
                    del self.memory_cache.cache[key]
                    memory_cleaned += 1

                # 清理数据库中的过期项
                db_cleaned = 0
                cutoff_time = current_time - self.memory_cache.ttl_seconds
                with sqlite3.connect(str(self.db_path)) as conn:
                    cursor = conn.execute(
                        "DELETE FROM cache WHERE timestamp < ?", (cutoff_time,)
                    )
                    db_cleaned = cursor.rowcount
                    conn.commit()

                if memory_cleaned > 0 or db_cleaned > 0:
                    logger.info(
                        f"清理过期缓存完成：内存清理 {memory_cleaned} 项，"
                        f"数据库清理 {db_cleaned} 项"
                    )

                return memory_cleaned + db_cleaned

            except Exception as e:
                logger.error(f"清理过期缓存时出错: {e}")
                return 0

    def shutdown(self) -> None:
        """优雅关闭缓存管理器"""
        logger.info("CacheManager 正在关闭...")
        try:
            # 关闭前最后一次清理过期缓存
            cleaned_count = self.cleanup_expired_cache()
            if cleaned_count > 0:
                logger.info(f"关闭前清理了 {cleaned_count} 项过期缓存")
        except Exception as e:
            logger.error(f"关闭前清理缓存失败: {e}")
        logger.info("CacheManager 已关闭")
