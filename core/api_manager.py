import logging
import time
import asyncio
import aiohttp
from typing import Dict, Optional, Any, List

from .network_utils import create_ssl_context

from .config_management import load_models_config
from .api_providers.base import ApiProvider
from .api_providers.gemini import GeminiProvider
from .api_providers.openai import OpenAIProvider
from .api_providers.anthropic import AnthropicProvider
from .quality_assessment import assess_translation_quality
from utils.api_crypto import ApiCrypto

logger = logging.getLogger(__name__)


class ApiManager:
    def __init__(self, config: Any):
        self.config = config
        self.api_crypto = self._load_api_crypto()
        self._models_config_cache: Optional[Dict[str, Any]] = None
        self._models_config_loaded = False
        self._models_config_last_check = 0.0
        self.providers: Dict[str, List[ApiProvider]] = self._create_providers()
        self._session_cache: dict[str, aiohttp.ClientSession] = {}
        self._session_lock = asyncio.Lock()

    def _load_api_crypto(self) -> Optional[ApiCrypto]:
        """Loads the API crypto module."""
        try:
            return ApiCrypto()
        except Exception as e:
            logger.error(f"加载ApiCrypto模块失败: {e}")
            return None

    def _decrypt_key(self, encrypted_key: str) -> Optional[str]:
        """Decrypts a single API key."""
        if not self.api_crypto or not encrypted_key:
            return None
        if not self.api_crypto.is_encrypted(encrypted_key):
            return encrypted_key
        try:
            decrypted_key = self.api_crypto.decrypt(encrypted_key)
            return str(decrypted_key) if decrypted_key else None
        except Exception as e:
            logger.error(f"解密API密钥失败: {e}")
            return None

    def _load_models_config_cached(self) -> Optional[Dict[str, Any]]:
        """Loads model configuration with caching."""
        current_time = time.time()
        if (
            self._models_config_cache
            and current_time - self._models_config_last_check < 300
        ):
            return self._models_config_cache

        self._models_config_last_check = current_time
        try:
            config = load_models_config()
            if config:
                self._models_config_cache = config
                logger.debug("模型配置已加载并缓存。")
            return config
        except Exception as e:
            logger.error(f"加载models.yaml失败: {e}")
            return self._models_config_cache

    def _create_providers(self) -> Dict[str, List[ApiProvider]]:
        """Creates a dictionary of API provider instances, grouped by provider name."""
        providers: Dict[str, List[ApiProvider]] = {}
        models_config = self._load_models_config_cached()
        if not models_config:
            logger.error("无法加载模型配置，不会创建任何提供商。")
            return {}

        for provider_name, provider_config in models_config.items():
            if not provider_name.endswith("_provider"):
                continue

            if not isinstance(provider_config, dict):
                logger.warning(f"提供商 '{provider_name}' 的配置不是字典，跳过。")
                continue

            provider_instances: List[ApiProvider] = []
            api_key_encrypted = provider_config.get("api_key", "")
            api_key = (
                (self._decrypt_key(api_key_encrypted) or "")
                if api_key_encrypted
                else ""
            )

            if not api_key:
                logger.warning(
                    f"提供商 '{provider_name}' 的API密钥缺失或无效。跳过此提供商。"
                )
                continue

            api_mode = provider_config.get("api_mode", "").lower()
            api_base = provider_config.get("api_base")

            models = provider_config.get("models", [])
            logger.debug(f"为提供商 '{provider_name}' 处理 {len(models)} 个模型")

            for model_info in models:
                try:
                    model_id = model_info.get("model_id", "unknown")
                    logger.debug(f"尝试为 {model_id} 创建模型实例")

                    instance: Optional[ApiProvider] = None
                    if api_mode == "gemini":
                        instance = GeminiProvider(
                            self,
                            self.config,
                            model_info,
                            api_key,
                            api_base,
                            provider_name,
                        )
                    elif api_mode == "openai":
                        # Fallback for openrouter custom field
                        if not api_base:
                            api_base = provider_config.get("openrouter")

                        if not api_base:
                            logger.error(
                                f"OpenAI兼容提供商 '{provider_name}' 需要 api_base，跳过模型 {model_id}。"
                            )
                            continue
                        instance = OpenAIProvider(
                            self,
                            self.config,
                            model_info,
                            api_key,
                            api_base,
                            provider_name,
                        )
                    elif api_mode == "anthropic":
                        instance = AnthropicProvider(
                            self,
                            self.config,
                            model_info,
                            api_key,
                            api_base,
                            provider_name,
                        )
                    else:
                        logger.warning(
                            f"不支持的 api_mode '{api_mode}' 对于提供商 '{provider_name}'，跳过模型 {model_id}。"
                        )
                        continue

                    if instance:
                        provider_instances.append(instance)
                        logger.debug(f"为 {model_id} 成功创建模型实例")

                except Exception as e:
                    model_id = model_info.get("model_id", "unknown")
                    logger.error(
                        f"为提供商 '{provider_name}' 中的 {model_id} 创建模型实例失败: {e}",
                        exc_info=True,
                    )
                    # Continue with next model instead of failing entirely
                    continue

            if provider_instances:
                providers[provider_name] = provider_instances
                logger.info(
                    f"为提供商 '{provider_name}' 创建了 {len(provider_instances)} 个模型实例。"
                )

        return providers

    async def translate(
        self, prompt: str, gui_handler: Optional[Any] = None
    ) -> Optional[str]:
        """Iterates through providers to get a translation."""
        if not self.providers:
            logger.error("没有配置或可用的API提供商。")
            return "翻译失败: 没有配置API提供商"

        for provider_name, provider_models in self.providers.items():
            logger.info(f"正在尝试使用提供商 '{provider_name}' 进行翻译...")
            for i, model_provider in enumerate(provider_models):
                try:
                    logger.info(
                        f"  模型 {i + 1}/{len(provider_models)}: 正在尝试使用 {type(model_provider).__name__} ({model_provider.model_info.get('model_id')}) 进行翻译"
                    )
                    translation_result = await model_provider.translate(
                        prompt, gui_handler
                    )

                    if translation_result:
                        if isinstance(translation_result, dict):
                            # 从字典中提取内容，使用 raw 或 processed
                            if "processed" in translation_result:
                                logger.info(
                                    f"使用 {type(model_provider).__name__} ({model_provider.model_info.get('model_id')}) 成功翻译，返回处理后的内容"
                                )
                                return translation_result["processed"]
                            else:
                                # 处理降级情况
                                logger.warning(
                                    f"来自 {type(model_provider).__name__} 的意外响应格式: {translation_result}"
                                )
                                return None
                        elif isinstance(translation_result, str):
                            # 处理错误消息
                            if isinstance(
                                translation_result, str
                            ) and translation_result.startswith("翻译失败"):
                                logger.warning(
                                    f"  模型 {type(model_provider).__name__} 失败: {translation_result}"
                                )
                            else:
                                logger.info(
                                    f"使用 {type(model_provider).__name__} ({model_provider.model_info.get('model_id')}) 成功翻译"
                                )
                                return translation_result
                    else:
                        logger.warning(
                            f"  模型 {type(model_provider).__name__} 失败: {translation_result}"
                        )
                except Exception as e:
                    logger.error(
                        f"  模型 {type(model_provider).__name__} 异常: {e}",
                        exc_info=True,
                    )
            logger.warning(f"提供商 '{provider_name}' 的所有模型都失败了。")

        logger.error("所有API提供商及其模型都无法翻译文本。")
        return "翻译失败: 所有API提供商均失败"

    async def translate_with_quality_check(
        self,
        prompt: str,
        gui_handler: Optional[Any] = None,
        original_text: Optional[str] = None,
        detected_lang: Optional[str] = None,
        target_lang_code: Optional[str] = None,
        config: Optional[Any] = None,
        mode_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        使用质量评估的翻译方法，在质量不合格时自动尝试下一个API提供商

        Args:
            prompt: 翻译提示词
            gui_handler: GUI处理器
            original_text: 原文(用于质量评估)
            detected_lang: 检测到的源语言
            target_lang_code: 目标语言代码
            config: 配置对象

        Returns:
            Optional[str]: 翻译结果
        """
        if not self.providers:
            logger.error("没有配置或可用的API提供商。")
            return "翻译失败: 没有配置API提供商"

        for provider_name, provider_models in self.providers.items():
            logger.info(f"正在尝试使用提供商 '{provider_name}' 进行翻译...")
            for i, model_provider in enumerate(provider_models):
                try:
                    logger.info(
                        f"  模型 {i + 1}/{len(provider_models)}: 正在尝试使用 {type(model_provider).__name__} ({model_provider.model_info.get('model_id')}) 进行质量检查"
                    )
                    translation_result = await model_provider.translate(
                        prompt, gui_handler, original_text=original_text
                    )

                    if translation_result:
                        logger.info(f"使用 {type(model_provider).__name__} 成功翻译")

                        if translation_result and not isinstance(
                            translation_result, dict
                        ):
                            # 处理非字典错误返回
                            logger.warning(
                                f"  模型 {type(model_provider).__name__} 失败: {translation_result}"
                            )
                            continue  # 尝试下一个模型
                        elif translation_result and isinstance(
                            translation_result, dict
                        ):
                            # 获取原始内容和处理后的内容
                            raw_content = translation_result.get("raw")
                            processed_content = translation_result.get("processed")

                            if raw_content and processed_content:
                                logger.info(
                                    f"使用 {type(model_provider).__name__} ({model_provider.model_info.get('model_id')}) 成功翻译"
                                )

                                # 确保 raw_content 和 processed_content 为字符串类型
                                raw_content_str = (
                                    raw_content
                                    if isinstance(raw_content, str)
                                    else str(raw_content or "")
                                )
                                processed_content_str = (
                                    processed_content
                                    if isinstance(processed_content, str)
                                    else str(processed_content or "")
                                )

                                # 检查 raw_content 是否为错误消息
                                if raw_content_str.startswith("翻译失败"):
                                    logger.warning(
                                        f"原始内容是错误消息: {raw_content_str}，跳过质量评估并尝试下一个模型..."
                                    )
                                    continue

                                # 检查是否应执行质量评估
                                if (
                                    original_text is not None
                                    and detected_lang
                                    and target_lang_code
                                    and config
                                    and detected_lang != target_lang_code
                                ):
                                    quality_label, quality_score, quality_issues = (
                                        assess_translation_quality(
                                            original_text,
                                            processed_content_str,
                                            detected_lang,
                                            target_lang_code,
                                            config,
                                            mode_config,
                                            None,
                                        )
                                    )
                                    logger.info(
                                        f"质量评估: {quality_label} (得分: {quality_score:.2f})，"
                                        f"问题: {quality_issues if quality_issues else '无'}"
                                    )
                                    if quality_label == "良好":
                                        logger.info(
                                            f"为 {type(model_provider).__name__} 通过质量检查，返回原始内容"
                                        )
                                        logger.debug(
                                            f"[DEBUG_TYPE] raw_content 类型: {type(raw_content_str)}, 值: {raw_content_str[:100]}"
                                        )
                                        return raw_content_str
                                    else:
                                        logger.warning(
                                            f"为 {type(model_provider).__name__} 质量检查失败。尝试下一个模型..."
                                        )
                                        continue
                                else:
                                    # 不执行质量评估，直接返回处理后的内容
                                    logger.info(
                                        f"未执行质量检查，为 {type(model_provider).__name__} 返回处理后的内容"
                                    )
                                    logger.debug(
                                        f"[DEBUG_TYPE] processed_content 类型: {type(processed_content_str)}, 值: {processed_content_str[:100]}"
                                    )
                                    return processed_content_str
                            else:
                                logger.warning(
                                    f"  模型 {type(model_provider).__name__} 返回无效响应格式: {translation_result}"
                                )
                                return "翻译失败: 返回格式无效"
                        else:
                            logger.warning(
                                f"  模型 {type(model_provider).__name__} 返回空响应失败"
                            )
                    else:
                        logger.warning(
                            f"  模型 {type(model_provider).__name__} 失败: {translation_result}"
                        )
                except Exception as e:
                    logger.error(
                        f"  模型 {type(model_provider).__name__} 异常: {e}",
                        exc_info=True,
                    )
            logger.warning(f"提供商 '{provider_name}' 的所有模型都失败了。")

        # 如果所有质量检查失败，回退到无质量检查的标准翻译

        logger.error("所有API提供商及其模型的质量检查或翻译都失败了。")
        return "翻译失败: 所有API提供商均失败或质量不合格"

    async def check_api_health(self, provider_name: str) -> Dict[str, Any]:
        """使用精确名称匹配检查特定API提供商的健康状态。"""
        provider_models = self.providers.get(provider_name)

        if not provider_models:
            return {
                "healthy": False,
                "message": f"提供商 '{provider_name}' 未找到或未配置。",
            }

        # Check the first model of the provider for simplicity
        first_model = provider_models[0]
        provider_instance_name = f"{type(first_model).__name__} ({first_model.model_info.get('model_id')}) for provider '{provider_name}'"
        logger.info(f"正在检查健康状态: {provider_instance_name}...")
        start_time = time.time()
        try:
            test_prompt = "你好"
            response_dict = await first_model.translate(test_prompt)
            response_time = time.time() - start_time

            # 从返回的字典中提取处理后的结果
            processed_result = (
                response_dict.get("processed", "")
                if isinstance(response_dict, dict)
                else ""
            )
            # 确保返回值始终为字符串类型
            if processed_result is None:
                processed_result = ""
            elif not isinstance(processed_result, str):
                processed_result = str(processed_result)

            if (
                processed_result
                and isinstance(processed_result, str)
                and not processed_result.startswith("翻译失败")
            ):
                # 添加类型验证日志
                logger.debug(
                    f"[DEBUG_TYPE] processed_result 类型: {type(processed_result)}, 值: {processed_result[:100] if isinstance(processed_result, str) else processed_result}"
                )
                return {
                    "healthy": True,
                    "message": f"成功 (响应时间: {response_time:.2f}s)",
                }
            else:
                failure_message = (
                    processed_result if processed_result else "收到无效或空响应"
                )
                return {"healthy": False, "message": f"失败: {failure_message}"}
        except Exception as e:
            return {"healthy": False, "message": f"异常: {e}"}

    async def create_session(
        self, config: Optional[Any] = None
    ) -> aiohttp.ClientSession:
        """
        创建并返回一个 aiohttp.ClientSession，包含自定义的SSL上下文和连接器设置。
        """
        # 优化连接器配置
        if config:
            tcp_connector_config = getattr(config, "tcp_connector", {})
            dns_cache = tcp_connector_config.get("dns_cache", True)
            dns_cache_ttl = tcp_connector_config.get("dns_cache_ttl", 300)
            limit_per_host = tcp_connector_config.get("limit_per_host", 20)
        else:
            dns_cache, dns_cache_ttl, limit_per_host = True, 300, 20

        # 创建SSL上下文
        ssl_context = create_ssl_context(config)

        # 使用 aiohttp.TCPConnector
        connector = aiohttp.TCPConnector(
            ssl=ssl_context,
            limit_per_host=limit_per_host,
            use_dns_cache=dns_cache,
            ttl_dns_cache=dns_cache_ttl,
            force_close=True,
            enable_cleanup_closed=True,
        )

        # 创建会话
        session = aiohttp.ClientSession(connector=connector)
        logger.debug(f"创建了新的 aiohttp.ClientSession (ID: {id(session)})")
        return session

    async def get_or_create_session(self, session_key: str) -> aiohttp.ClientSession:
        """获取或创建优化的HTTP会话，实现连接池复用"""
        async with self._session_lock:
            if session_key not in self._session_cache:
                session = await self.create_session(self.config)
                self._session_cache[session_key] = session
                logger.debug(f"为 {session_key} 创建了新的 aiohttp 会话。")
            return self._session_cache[session_key]

    async def close_all_sessions(self) -> None:
        """关闭所有缓存的 aiohttp 会话。"""
        async with self._session_lock:
            for session in self._session_cache.values():
                if not session.closed:
                    await session.close()
            self._session_cache.clear()
            logger.info("所有 aiohttp 会话已关闭。")

    def get_proxy_config(self) -> tuple[Optional[str], Optional[aiohttp.BasicAuth]]:
        """从主配置中获取代理设置"""
        if not self.config or not getattr(self.config, "proxy", None):
            return None, None

        proxy_config = getattr(self.config, "proxy", {})
        if not proxy_config.get("enable", False):
            return None, None

        proxy_url = proxy_config.get("url")
        proxy_user = proxy_config.get("username")
        proxy_pass = proxy_config.get("password")

        proxy_auth = (
            aiohttp.BasicAuth(proxy_user, proxy_pass)
            if proxy_user and proxy_pass
            else None
        )
        return proxy_url, proxy_auth
