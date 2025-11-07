"""
文本处理工具模块
提供文本清理、n-gram 生成等通用功能
"""

import logging
import threading
from typing import Any, Optional

import regex  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# --- 性能优化：预编译常用的正则表达式 ---

RE_WHITESPACE = regex.compile(r"\s+")
RE_DEFAULT_SYMBOLS = regex.compile(r"[\p{P}\p{S}]")
RE_WORD_TOKENIZE = regex.compile(r"\b\w+\b")


def clean_text(text: str, common_symbols_pattern: Optional[str] = None) -> str:
    """清理文本，用于相似度计算

    Args:
        text: 要清理的文本
        common_symbols_pattern: 用于清理的常见符号正则表达式模式

    Returns:
        str: 清理后的文本
    """
    if not text:
        return ""

    # 统一空白字符
    text = RE_WHITESPACE.sub(" ", text).strip()
    # 去除常见标点符号
    if common_symbols_pattern:
        text = regex.sub(common_symbols_pattern, "", text)
    else:
        text = RE_DEFAULT_SYMBOLS.sub("", text)
    # 统一大小写
    text = text.lower()
    return text


def get_ngrams(text: str, n: int = 3) -> set[str]:
    """获取文本的n-gram集合

    Args:
        text: 输入文本
        n: n-gram的大小

    Returns:
        set: n-gram集合
    """
    if not text or len(text) < n:
        return set()
    return set(text[i : i + n] for i in range(len(text) - n + 1))


def clean_illegal_chars(
    text: str, config: Optional[Any] = None, illegal_pattern: Optional[str] = None
) -> str:
    """清理文本中的非法字符

    Args:
        text: 要清理的文本
        config: 配置对象，用于获取默认的非法字符模式
        illegal_pattern: (可选) 非法字符的正则表达式模式，如果提供则优先使用

    Returns:
        str: 清理后的文本
    """
    if not text:
        return ""

    if not illegal_pattern:
        if config and hasattr(config, "illegal_chars"):
            illegal_pattern = config.illegal_chars
        else:
            logger.error("无法获取 'illegal_chars' 配置，跳过非法字符清理。")
            return text

    if not illegal_pattern or not isinstance(illegal_pattern, str):
        logger.error(f"无效的 'illegal_chars' 模式: {illegal_pattern}，跳过清理。")
        return text

    try:
        return regex.sub(illegal_pattern, "", text)
    except regex.error as e:
        current_thread_name = threading.current_thread().name
        logger.error(
            f"[{current_thread_name}] 清理非法字符时正则表达式错误: {e}, pattern: '{illegal_pattern}'"
        )
        return text
