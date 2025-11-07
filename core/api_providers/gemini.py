import asyncio
import json
import logging
import time
import re
from typing import Dict, Any, Optional

import aiohttp
from .base import ApiProvider
from ..text_utils import clean_illegal_chars
from ..constants import HTTP_STATUS_CODE_MESSAGES, format_error_message
from ..retry_utils import create_retry_decorator

logger = logging.getLogger(__name__)


class GeminiProvider(ApiProvider):
    def __init__(
        self,
        api_manager: Any,
        config: Any,
        model_info: Dict[str, Any],
        api_key: Optional[str],
        api_base: Optional[str] = None,
        provider_name: Optional[str] = None,
    ):
        super().__init__(
            api_manager,
            config,
            model_info,
            api_key,
            api_base or "https://generativelanguage.googleapis.com",
            provider_name=provider_name,
        )

    async def translate(
        self,
        prompt: str,
        gui_handler: Optional[Any] = None,
        is_retry: bool = False,
        original_text: Optional[str] = None,
    ) -> Dict[str, str]:
        model_id = self.model_info.get("model_id", "gemini-pro")
        params = self.model_info.get("params", {})
        api_mode = self.model_info.get("api_mode", "gemini")

        # 提前定义api_name以便在错误处理中使用
        api_name = (api_mode or "gemini").upper()

        if not self.api_key:
            error_msg = format_error_message(
                "API_KEY_NOT_CONFIGURED", provider=api_name
            )
            return {
                "raw": error_msg,
                "processed": error_msg,
            }

        # 使用新的重试装饰器
        retry_decorator = create_retry_decorator(self.config)
        logger.debug(
            f"开始调用 {api_name} 兼容 API，模型: {model_id}, 重试: {is_retry}"
        )

        # 初始化response变量以避免未绑定错误
        response = None

        try:
            # Correctly construct the URL using the api_base from config
            # and the standard Gemini API path structure.
            api_version = self.model_info.get("api_version", "v1beta")
            url = f"{self.api_base}/{api_version}/{model_id}:generateContent?key={self.api_key}"

            safe_url = url.split("?")[0]
            logger.debug(f"API请求URL: {safe_url} [敏感参数已隐藏]")

            headers = {"Content-Type": "application/json"}

            # 通用参数处理，直接传递嵌套结构（这里已经做到了无硬编码适配所有模型的参数传递，需要在yaml合理配置嵌套关系，如无要求不要修改此处）
            def to_camel_case(snake_str: str) -> str:
                if "_" not in snake_str:
                    return snake_str
                components = snake_str.split("_")
                return components[0] + "".join(x.title() for x in components[1:])

            def process_gemini_params(params_dict: Dict[str, Any]) -> Dict[str, Any]:
                # 基础参数映射
                key_mappings = {
                    "temperature": "temperature",
                    "topP": "top_p",
                    "max_tokens": "maxOutputTokens",
                    "max_completion_tokens": "maxOutputTokens",
                }

                config = {}
                for key, value in params_dict.items():
                    # 直接传递嵌套字典结构
                    if isinstance(value, dict):
                        # 递归处理嵌套字典
                        config[key] = process_gemini_params(value)
                    else:
                        # 普通参数使用映射或驼峰转换
                        mapped_key = key_mappings.get(key, to_camel_case(key))
                        config[mapped_key] = value

                return config

            generation_config = process_gemini_params(params)

            request_data: Dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
            }
            if generation_config:
                request_data["generationConfig"] = generation_config

            logger.debug(
                f"[{api_name} API] 发送数据: {json.dumps(request_data, ensure_ascii=False, indent=2)}"
            )

            logger.debug(
                f"最终生成配置: {request_data.get('generationConfig', '未设置')}"
            )

            session = await self.api_manager.get_or_create_session(
                f"gemini_{self.model_info.get('model_id')}"
            )
            proxy_url, proxy_auth = self.api_manager.get_proxy_config()
            logger.debug(f"使用会话, 代理: {proxy_url is not None}")

            start_time = time.time()

            # 获取超时代码，直接使用API健康检查的timeout_connect设置
            api_timeout = getattr(self.config, "api_health_check", {}).get(
                "timeout_connect", 5
            )
            logger.debug(f"使用API超时设置: {api_timeout}秒")

            @retry_decorator
            async def _gemini_api_request() -> Any:
                logger.info(f"发送 {api_name} API请求，模型: {model_id}")
                return await session.post(
                    url,
                    headers=headers,
                    json=request_data,
                    proxy=proxy_url,
                    proxy_auth=proxy_auth,
                    # 添加超时控制
                    timeout=aiohttp.ClientTimeout(total=float(api_timeout)),
                )

            try:
                response = await _gemini_api_request()
                if gui_handler and hasattr(gui_handler, "update_progress_indicator"):
                    gui_handler.update_progress_indicator("processing_response", 75)

                if response is None:
                    error_msg = format_error_message(
                        "API_RESPONSE_EMPTY", provider=api_name
                    )
                    return {
                        "raw": error_msg,
                        "processed": error_msg,
                    }
                response_text = await response.text()
                logger.debug(
                    f"收到API响应，状态码: {response.status}, 响应长度: {len(response_text)}"
                )
                try:
                    # 尝试将响应文本格式化为JSON以便阅读
                    response_json_data = json.loads(response_text)
                    formatted_response = json.dumps(
                        response_json_data, indent=2, ensure_ascii=False
                    )
                    logger.debug(f"[{api_name} API] 返回数据:\n{formatted_response}")
                except json.JSONDecodeError:
                    # 如果不是有效的JSON，则按原样记录
                    logger.debug(f"[{api_name} API] 返回数据 (非JSON): {response_text}")

                if response.status == 200:
                    try:
                        response_json = json.loads(response_text)
                        reasoning_text = ""
                        processed_content = ""
                        raw_content = ""

                        if (
                            "candidates" in response_json
                            and response_json["candidates"]
                        ):
                            candidate = response_json["candidates"][0]

                            # 优先尝试从结构化字段获取思考过程
                            if "thoughts" in candidate and candidate["thoughts"]:
                                reasoning_text = json.dumps(
                                    candidate["thoughts"], ensure_ascii=False
                                )
                                content = candidate.get("content", {})
                                if "parts" in content:
                                    raw_content = "".join(
                                        part.get("text", "")
                                        for part in content["parts"]
                                    ).strip()
                                processed_content = clean_illegal_chars(
                                    raw_content, self.config
                                )
                            else:
                                # 处理Gemini thinking模式的parts结构
                                content = candidate.get("content", {})
                                if "parts" in content:
                                    reasoning_parts = []
                                    final_parts = []

                                    # 分离thinking和final内容
                                    for part in content.get("parts", []):
                                        part_text = part.get("text", "").strip()
                                        if part.get("thought", False):
                                            reasoning_parts.append(part_text)
                                        else:
                                            final_parts.append(part_text)

                                    if reasoning_parts:
                                        reasoning_text = "\n".join(reasoning_parts)
                                    else:
                                        reasoning_text = ""

                                    if final_parts:
                                        raw_content = "\n".join(final_parts)
                                    else:
                                        # 如果没有非thinking部分，整个响应作为content
                                        raw_content = "".join(
                                            part.get("text", "")
                                            for part in content.get("parts", [])
                                        ).strip()

                                    # 移除所有XML/HTML标签
                                    raw_content = re.sub(
                                        r"<.*?>", "", raw_content, flags=re.DOTALL
                                    ).strip()
                                    processed_content = clean_illegal_chars(
                                        raw_content, self.config
                                    )
                                else:
                                    # 后备方案：直接使用所有parts的内容
                                    raw_content = "".join(
                                        part.get("text", "")
                                        for part in content.get("parts", [])
                                    ).strip()
                                processed_content = clean_illegal_chars(
                                    raw_content, self.config
                                )
                                reasoning_text = ""  # 未使用，但保留以保持一致性
                                logger.debug(
                                    f"Gemini后备方案解析，thinking内容: {reasoning_text[:100]}..."
                                )
                        else:
                            # 如果没有 'candidates'，作为最后的防线，直接使用响应文本
                            raw_content = response_text.strip()
                            reasoning_text = ""
                            processed_content = clean_illegal_chars(
                                raw_content, self.config
                            )

                        if processed_content:
                            response_time = time.time() - start_time
                            logger.info(
                                f"[{api_name} API成功] 模型: {model_id}, 结果长度: {len(processed_content)}, 响应时间: {response_time:.2f}s"
                            )
                            # self.api_manager.set_last_reasoning(reasoning_text)
                            return {
                                "raw": processed_content,
                                "processed": processed_content,
                            }
                        else:
                            # 检查是否存在已知的API错误原因
                            if "promptFeedback" in response_json:
                                if "blockReason" in response_json["promptFeedback"]:
                                    block_reason = response_json["promptFeedback"][
                                        "blockReason"
                                    ]
                                    logger.error(
                                        f"Prompt被安全策略阻止: {block_reason}"
                                    )
                                    error_msg = format_error_message(
                                        "GEMINI_SAFETY_BLOCKED",
                                        provider=api_name,
                                        details=block_reason,
                                    )
                                    return {
                                        "raw": error_msg,
                                        "processed": error_msg,
                                    }

                            # 如果从响应中无法提取任何有效内容，则记录通用错误
                            logger.error(
                                "API返回格式异常或内容为空，无法提取有效翻译。"
                            )
                            error_msg = format_error_message(
                                "API_RESPONSE_FORMAT_ERROR", provider=api_name
                            )
                            return {
                                "raw": error_msg,
                                "processed": error_msg,
                            }

                    except json.JSONDecodeError as e:
                        logger.error(f"解析API响应JSON失败: {e}", exc_info=True)
                        error_msg = format_error_message(
                            "API_RESPONSE_FORMAT_ERROR",
                            provider=api_name,
                            details=str(e),
                        )
                        return {
                            "raw": error_msg,
                            "processed": error_msg,
                        }
                else:
                    error_message = HTTP_STATUS_CODE_MESSAGES.get(
                        response.status, f"未知错误码 {response.status}"
                    )
                    # 原始响应已在DEBUG级别记录，这里只记录错误本身
                    logger.error(
                        f"API请求失败，状态码: {response.status} ({error_message})"
                    )
                    error_msg = format_error_message(
                        "API_HTTP_ERROR", provider=api_name, status_code=response.status
                    )
                    return {
                        "raw": error_msg,
                        "processed": error_msg,
                    }
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

        except aiohttp.ClientResponseError as e:
            logger.error(
                f"调用 {api_name} API时发生HTTP响应错误: 状态码={e.status}, 消息={e.message}",
                exc_info=True,
            )
            error_msg = format_error_message(
                "API_HTTP_ERROR", provider=api_name, status_code=e.status
            )
            return {
                "raw": error_msg,
                "processed": error_msg,
            }
        except aiohttp.ClientConnectorSSLError as e:
            logger.error(f"调用 {api_name} API时发生SSL异常: {e}", exc_info=True)
            error_msg = format_error_message("API_SSL_ERROR", provider=api_name)
            return {
                "raw": error_msg,
                "processed": error_msg,
            }
        except aiohttp.ClientConnectorError as e:
            logger.error(f"调用 {api_name} API时发生连接异常: {e}")
            error_msg = format_error_message(
                "API_CONNECTION_ERROR",
                provider=api_name,
                exception_type=type(e).__name__,
            )
            return {
                "raw": error_msg,
                "processed": error_msg,
            }
        except aiohttp.ClientError as e:
            logger.error(f"调用 {api_name} API时发生客户端异常: {e}")
            error_msg = format_error_message(
                "API_CLIENT_ERROR", provider=api_name, exception_type=type(e).__name__
            )
            return {
                "raw": error_msg,
                "processed": error_msg,
            }
        except asyncio.TimeoutError:
            error_details = ""
            # 检查 response 对象是否已创建且包含状态信息
            if response and hasattr(response, "status"):
                error_details = f"状态码: {response.status}, 响应头: {response.headers}"
                logger.error(
                    f"调用 {api_name} API时发生超时。可能是在读取响应体时。{error_details}"
                )
                # 尝试安全地读取部分响应文本以供调试
                try:
                    # 使用 response.content 而不是 response.text()，并设置一个小的读取限制
                    partial_content = await response.content.read(1024)
                    decoded_partial = partial_content.decode("utf-8", errors="ignore")
                    logger.error(f"API返回的部分内容 (前1KB): {decoded_partial}")
                    error_details += f", 部分响应: {decoded_partial}"
                except Exception as read_exc:
                    logger.error(f"在超时后尝试读取响应内容时发生错误: {read_exc}")
            else:
                logger.error(
                    f"调用 {api_name} API时发生超时。可能是在建立连接或发送请求时。"
                )

            error_msg = format_error_message(
                "API_TIMEOUT", provider=api_name, details=error_details
            )
            return {
                "raw": error_msg,
                "processed": error_msg,
            }
        except Exception as e:
            logger.error(f"调用 {api_name} API时发生异常: {e}", exc_info=True)
            error_msg = format_error_message(
                "API_UNKNOWN_ERROR", provider=api_name, exception_type=type(e).__name__
            )
            return {
                "raw": error_msg,
                "processed": error_msg,
            }
