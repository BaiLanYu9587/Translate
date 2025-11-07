import asyncio
import logging
from typing import Any, Callable

import aiohttp  # type: ignore[import-untyped]
from tenacity import (  # type: ignore[import-untyped]
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .config_management import Config, RetryConfig

logger = logging.getLogger(__name__)


def create_retry_decorator(config: Config) -> Callable[..., Any]:
    """
    根据应用配置动态创建并返回一个 tenacity 重试装饰器。

    Args:
        config: 包含 retry_config 的应用配置对象。

    Returns:
        一个配置好的 tenacity 重试装饰器。
    """
    # 从配置中获取重试参数，如果未定义则使用默认值
    retry_config: RetryConfig = getattr(config, "retry_config", None) or RetryConfig(
        attempts=1, min_delay=1, max_delay=10, backoff_factor=2
    )

    return retry(
        stop=stop_after_attempt(retry_config.attempts),
        wait=wait_exponential(
            multiplier=retry_config.backoff_factor,
            min=retry_config.min_delay,
            max=retry_config.max_delay,
        ),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
