"""
服务管理模块
管理网络连接和API服务状态，提供缓存机制
"""

import time
import logging
from typing import Dict, Any, Optional
from .network_utils import NetworkChecker
from .api_manager import ApiManager
from .cache_manager import CacheManager
from .config_management import Config

logger = logging.getLogger(__name__)


class ServiceManager:
    """
    服务管理类，统一管理和协调应用的核心服务。
    包括：API管理器, 网络检查器, 以及重构后的缓存管理器。
    """

    def __init__(
        self,
        config: Config,
        api_manager: ApiManager,
        cache_manager: CacheManager,
        network_checker: Optional[NetworkChecker] = None,
    ):
        self.config = config
        self.api_manager = api_manager
        self.cache_manager = cache_manager
        self.network_checker = network_checker or NetworkChecker(config)

        # API健康检查的缓存现在由通用的CacheManager处理
        self.api_cache_lifetime = getattr(self.config, "api_health_check", {}).get(
            "cache_lifetime", 300.0
        )

        # 为 mypy 添加类型注解
        self._models_config_cache: Optional[Dict[str, Any]] = None
        self._models_config_last_check: float = 0.0

        logger.info("服务管理器初始化完成。")

    def start_services(self) -> None:
        """启动所有后台服务，例如缓存管理器。"""
        logger.info("正在启动所有服务...")
        self.cache_manager.start()
        logger.info("所有服务已启动。")

    def shutdown_services(self) -> None:
        """优雅地关闭所有服务。"""
        logger.info("正在关闭所有服务...")
        self.cache_manager.shutdown()
        logger.info("所有服务已关闭。")

    def _load_models_config_cached(self) -> Optional[Dict[str, Any]]:
        """带缓存的模型配置加载，避免重复加载和日志，支持智能过期"""
        current_time = time.time()

        if (
            hasattr(self, "_models_config_cache")
            and self._models_config_cache is not None
            and hasattr(self, "_models_config_last_check")
            and current_time - self._models_config_last_check < 300.0  # 5分钟过期
        ):
            return self._models_config_cache

        from .config_management import load_models_config

        try:
            self._models_config_last_check = current_time
            config = load_models_config()
            if config:
                self._models_config_cache = config
                logger.debug("ServiceManager: 模型配置已加载并更新缓存")
                return config
            else:
                logger.warning("ServiceManager: 模型配置加载失败，使用旧缓存")
                return getattr(self, "_models_config_cache", None)
        except Exception as e:
            logger.error(f"ServiceManager: 加载 models.yaml 配置文件时出错: {e}")
            return getattr(self, "_models_config_cache", None)

    def is_network_connected(self, force_check: bool = False) -> bool:
        """检查网络连接状态，利用CacheManager进行缓存"""
        # 注意：网络检查通常需要快速响应，使用简单的内存缓存或短周期的翻译缓存可能更合适。
        # 这里为了演示，我们使用翻译缓存，但实际应用中可能需要一个独立的短生命周期缓存。
        cache_key = "network_status:check"
        cached_status = self.cache_manager.get_translation(cache_key, "status")

        if not force_check and cached_status is not None:
            logger.debug(f"使用网络状态缓存: {cached_status == 'connected'}")
            return cached_status == "connected"

        logger.info("执行实际网络连接检查...")
        connected = self.network_checker.is_network_connected(force_check)

        # 将布尔值转换为字符串进行存储
        status_str = "connected" if connected else "disconnected"
        self.cache_manager.add_translation(cache_key, "status", status_str)

        logger.debug(f"网络状态缓存已更新: {connected}")
        return connected

    async def check_api_health(
        self, provider_name: str, force_check: bool = False
    ) -> Dict[str, Any]:
        """检查API健康状态，利用CacheManager进行缓存"""
        cache_key = f"api_health:{provider_name}"
        # API健康状态通常是字典，不适合直接用作翻译，我们将其序列化或只缓存关键状态
        # 这里简化为只缓存 "ok" 或 "failed" 状态
        cached_health_status = self.cache_manager.get_translation(
            cache_key, "health_status"
        )

        if not force_check and cached_health_status:
            logger.debug(
                f"API健康状态缓存命中: {provider_name} -> {cached_health_status}"
            )
            # 实际应用中需要反序列化或重构返回格式
            return {
                "status": cached_health_status,
                "provider": provider_name,
                "cached": True,
            }

        logger.info(f"执行API健康检查 (Provider: {provider_name})...")
        health_status = await self.api_manager.check_api_health(provider_name)

        # 只缓存关键状态
        status_to_cache = "ok" if health_status.get("status") == "ok" else "failed"
        self.cache_manager.add_translation(cache_key, "health_status", status_to_cache)

        logger.debug(f"API健康状态缓存已更新: {provider_name}")
        return health_status

    def clear_all_cache(self) -> None:
        """清空所有缓存"""
        self.cache_manager.clear_all_cache()
        logger.info("所有服务缓存已通过CacheManager清空")
