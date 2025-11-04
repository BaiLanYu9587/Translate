"""
API 响应解析器模块 - 简化的fallback函数
此模块仅作为最后的fallback，当API provider无法直接解析响应时使用。
现代模型应在各自的provider中实现结构化解析，不依赖正则表达式。
"""

import json
import logging
from typing import Any, Optional, Tuple

from .text_utils import clean_illegal_chars

logger = logging.getLogger(__name__)


def _safe_extract_and_convert_to_string(data: Any) -> str:
    """安全地将数据转换为字符串。如果数据是字典或列表，则使用JSON序列化。"""
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False)
    return str(data).strip()


def extract_reasoning_and_content(
    api_response: str, config: Optional[Any] = None
) -> Tuple[str, str]:
    """
    简化的fallback函数，仅在API provider无法解析响应时使用。
    现代模型应在各自的provider中实现结构化解析，不依赖此函数。

    :param api_response: API返回的原始字符串
    :param config: 配置对象
    :return: (空字符串, 清理后的内容) - 此函数不提取thinking过程
    """
    logger.warning(
        "[response_parser] 此函数仅作为最后的fallback，不应被正常使用。API provider应实现自己的解析逻辑。"
    )

    final_content = str(api_response).strip()

    # 尝试解析JSON响应中的content字段（最后的保底方案）
    try:
        data = json.loads(api_response)
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            msg = choice.get("message", {})
            if "content" in msg:
                final_content = _safe_extract_and_convert_to_string(msg["content"])
        elif "content" in data:
            final_content = _safe_extract_and_convert_to_string(data["content"])
    except (json.JSONDecodeError, KeyError, IndexError):
        pass

    final_content = clean_illegal_chars(final_content, config=config)
    return "", final_content  # 不提取thinking过程，直接返回内容
