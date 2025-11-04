import json
import logging
import os
import hashlib
import threading
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple, Any, Dict
import re  # 新增
import aiofiles  # 导入 aiofiles

logger = logging.getLogger(__name__)

# 创建一个模块级的锁，用于保护可能引起日志交错的代码块
# 这是一个临时的解决方案，用于解决打印大型dict时的线程安全问题
_log_lock = threading.Lock()

__all__ = ["ContextManager"]

# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _get_context_dir() -> Path:
    """返回由 DirectoryManager 管理的上下文目录路径。"""
    from .config_management import get_chat_contexts_dir

    # 完全依赖 DirectoryManager 获取路径，它会确保目录存在
    path = Path(get_chat_contexts_dir())

    # DirectoryManager 已经保证了目录的存在，但为保险起见，再次检查
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"[{threading.current_thread().name}] 上下文目录不存在，已重新创建: {path}"
            )
        except Exception as e:
            logger.error(
                f"[{threading.current_thread().name}] 创建上下文目录失败 {path}: {e}"
            )
            # 返回一个备用路径，例如用户主目录下的临时文件夹，避免程序崩溃
            fallback_path = Path(os.path.expanduser("~")) / ".translation_app_contexts"
            fallback_path.mkdir(exist_ok=True)
            logger.warning(f"将使用备用上下文目录: {fallback_path}")
            return fallback_path

    return path


def _sanitize_filename(title: str) -> str:
    """将窗口标题转换为对操作系统安全的文件名。

    该函数旨在处理包含多种语言（包括中文、日文、韩文等）的复杂窗口标题，
    确保在保留标题可读性的同时，生成一个在主流操作系统（Windows, macOS, Linux）
    上有效且唯一的文件名。

    处理流程:
    1.  **移除不可见字符**: 清理掉由 `pyautogui` 等库可能引入的零宽空格等不可见字符。
    2.  **替换非法字符**: 将在文件名中非法的字符（如 `\\`, `/`, `:`, `*`, `?`, `"`, `<`, `>`, `|`）替换为下划线 `_`。
    3.  **处理分隔符**: 对常见的 `@` 符号进行特殊处理，用 `_at_` 替换，以增强可读性和兼容性。
    4.  **压缩与整理**: 将连续的多个下划线压缩成一个，并移除首尾的下划线、点和空格。
    5.  **空标题处理**: 如果经过处理后标题变为空，则使用其 MD5 哈希值作为唯一标识。
    6.  **长度限制**: 将最终文件名截断至200个字符，以兼容不同文件系统的长度限制。
    """
    # 移除 pyautogui 可能产生的零宽空格、控制字符等不可见字符
    # 包括：零宽空格(u200B-u200D)、字节顺序标记(uFEFF)、左右显示控制符(u200E-u200F)
    sanitized = re.sub(r"[\u200b-\u200f\uFEFF]", "", title)

    # 为了更好的可读性，将@符号替换为_at_
    sanitized = sanitized.replace("@", " _at_ ")

    # 替换操作系统文件名中的非法字符
    sanitized = re.sub(r'[\\/:*?"<>|\r\n\t\0]', "_", sanitized)

    # 将多个连续的空格或下划线压缩为单个下划线
    sanitized = re.sub(r"[\s_]+", "_", sanitized)

    # 去除首尾可能存在的下划线、点或空格
    sanitized = sanitized.strip("_ .")

    # 如果处理后字符串为空 (例如，标题就是 `*?*`)，则使用哈希值
    if not sanitized:
        sanitized = hashlib.md5(
            title.encode("utf-8"), usedforsecurity=False
        ).hexdigest()

    # 截断以防止文件名过长
    return sanitized[:200]


def _normalize_window_title(title: str) -> str:
    """规范化窗口标题，消除可能导致文件名变化的动态部分。

    此函数旨在通过移除窗口标题中常见的动态变化部分（如未读消息数、
    程序后缀、输入状态等），为同一个聊天或工作窗口生成一个稳定、一致的标识符。

    处理步骤:
    1.  **移除常见应用后缀**: 清理如 `- Telegram`, `- WeChat` 等程序名称后缀。
    2.  **移除未读消息计数**: 去除如 `(3)` 或 `[12]` 形式的未读消息数。
    3.  **移除多语言"正在输入"提示**: 删除中英文等多种语言的"正在输入..."状态提示。
    4.  **通用清理**: 去除首尾的空白字符。

    这样做可以确保，即使用户在会话中收到新消息，程序依然能将上下文
    正确地关联到同一个文件中。
    """
    cleaned = title.strip()

    # 1️ 移除常见应用后缀
    common_suffixes = [
        # Telegram
        " - Telegram",
        "— Telegram",
        " – Telegram",
        "- Telegram",
        "Telegram",
        # WeChat / 微信
        " - WeChat",
        "— WeChat",
        " – WeChat",
        "- WeChat",
        "WeChat",
        " - 微信",
        "— 微信",
        " – 微信",
        "- 微信",
        "微信",
        # QQ
        " - QQ",
        "— QQ",
        " – QQ",
        "- QQ",
        "QQ",
        # Discord
        " - Discord",
        "— Discord",
        " – Discord",
        "- Discord",
        "Discord",
        # WhatsApp
        " - WhatsApp",
        "— WhatsApp",
        " – WhatsApp",
        "- WhatsApp",
        "WhatsApp",
        # Signal
        " - Signal",
        "— Signal",
        " – Signal",
        "- Signal",
        "Signal",
        # Slack
        " - Slack",
        "— Slack",
        " – Slack",
        "- Slack",
        "Slack",
        # LINE
        " - LINE",
        "— LINE",
        " – LINE",
        "- LINE",
        "LINE",
        # KakaoTalk
        " - KakaoTalk",
        "— KakaoTalk",
        " – KakaoTalk",
        "- KakaoTalk",
        "KakaoTalk",
        # Skype
        " - Skype",
        "— Skype",
        " – Skype",
        "- Skype",
        "Skype",
        # Microsoft Teams
        " - Microsoft Teams",
        "— Microsoft Teams",
        " – Microsoft Teams",
        "- Microsoft Teams",
        "Microsoft Teams",
        # Facebook / FB Messenger
        " - Messenger",
        "— Messenger",
        " – Messenger",
        "- Messenger",
        "Messenger",
        " - Facebook Messenger",
        "— Facebook Messenger",
        " – Facebook Messenger",
        "- Facebook Messenger",
        "Facebook Messenger",
    ]
    for suffix in common_suffixes:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break

    # 2️ 移除尾部未读数，支持 () 和 []
    cleaned = re.sub(r"\s*[\(\[]\d+[\)\]]$", "", cleaned).strip()

    # 3️ 移除多种语言的"正在输入..."提示
    typing_indicators = [
        # Latin-based languages
        r"is typing.*$",  # English
        r"are typing.*$",  # English (group)
        r"est en train d'écrire.*$",  # French
        r"está escribiendo.*$",  # Spanish
        r"està escrivint.*$",  # Catalan
        r"está a escrever.*$",  # Portuguese
        r"sta scrivendo.*$",  # Italian
        r"schreibt.*$",  # German
        r"typt.*$",  # Dutch
        r"skriver.*$",  # Danish, Norwegian, Swedish
        # CJK languages
        r"正在输入.*$",  # Chinese
        r"が入力中です.*$",  # Japanese
        r"入力中.*$",  # Japanese (alternative)
        r"입력 중.*$",  # Korean
        # Cyrillic-based languages
        r"печатает.*$",  # Russian
        r"друкує.*$",  # Ukrainian
        # Other languages
        r"กำลังพิมพ์.*$",  # Thai
        r"đang gõ.*$",  # Vietnamese
        r"sedang mengetik.*$",  # Indonesian/Malay
        r"yazıyor.*$",  # Turkish
        r"พิมพ์.*$",  # Thai (alternative)
    ]
    for indicator in typing_indicators:
        cleaned = re.sub(indicator, "", cleaned, flags=re.IGNORECASE).strip()

    # 如果清理后变为空，则返回原始标题以避免完全丢失信息
    return cleaned or title


@lru_cache(maxsize=128)
def _get_file_path(title: str) -> Path:
    """根据窗口标题生成对应的 JSON 文件路径。"""
    #  先进行标题规范化，保证稳定性
    normalized_title = _normalize_window_title(title)

    context_dir = _get_context_dir()
    filename = _sanitize_filename(normalized_title) + ".json"
    return context_dir / filename


# ---------------------------------------------------------------------------
# 对外接口类
# ---------------------------------------------------------------------------


class ContextManager:
    """上下文管理器，封装上下文读写操作。"""

    async def load_context_with_direction(
        self, title: str
    ) -> List[Tuple[str, str, str]]:
        """加载指定窗口的上下文 (original, translated, direction)。

        Args:
            title: 窗口标题

        Returns:
            List of tuples (original, translated, direction).
            如果文件不存在或格式错误，则返回空列表。
            对于旧格式或未指定方向的条目，方向默认为 "ME→Counterpart"。
        """
        current_thread_name = threading.current_thread().name
        file_path = _get_file_path(title)
        logger.debug(
            f"[{current_thread_name}] 尝试从文件加载带方向的上下文: {file_path}"
        )
        if not file_path.exists():
            logger.debug(f"[{current_thread_name}] 上下文文件不存在，返回空列表。")
            return []

        try:
            async with aiofiles.open(file_path, "r", encoding="utf-8") as fp:
                content = await fp.read()
                data = json.loads(content)

            # 如果是字典格式（新格式），提取上下文对
            if isinstance(data, dict):
                context_data = data.get("context", [])
            else:
                # 兼容旧格式（纯列表）
                context_data = data

            if not isinstance(context_data, list):
                raise ValueError("上下文文件格式错误，上下文应为列表")

            triplets: List[Tuple[str, str, str]] = []
            for item in context_data:
                if isinstance(item, dict):
                    original = item.get("original", "")
                    translated = item.get("translated", "")
                    direction = item.get("direction", "ME→Counterpart")  # 默认方向
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    original, translated = item[0], item[1]
                    # 对于旧的列表格式，没有方向信息，使用默认方向
                    direction = "ME→Counterpart"
                else:
                    continue
                triplets.append((str(original), str(translated), str(direction)))
            logger.debug(
                f"[{current_thread_name}] 成功从 {file_path} 加载 {len(triplets)} 条带方向的上下文。"
            )
            return triplets
        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 读取带方向的上下文文件失败 {file_path}: {e}",
                exc_info=True,
            )
            return []

    async def save_translation_pair(
        self,
        config: Any,
        title: str,
        original: str,
        translated: str,
        direction: str,
    ) -> None:
        """保存一对翻译 (原文, 译文, 方向) 到对应窗口的上下文文件。

        会根据 ``config.context_max_count`` 控制保留的最大条目数。

        Args:
            config: 配置对象
            title: 窗口标题
            original: 原文
            translated: 译文
            direction: 翻译方向
        """
        current_thread_name = threading.current_thread().name
        logger.debug(f"[{current_thread_name}] 尝试保存翻译对到上下文文件。")
        logger.debug(
            f"[{current_thread_name}] 参数: title={title}, original={original}, translated={translated}, direction={direction}"
        )
        max_count: int = getattr(
            config, "context_max_count", 10
        )  # 从配置读取，默认为10

        # 先加载现有数据（包括默认翻译模式）
        file_path = _get_file_path(title)
        logger.debug(f"[{current_thread_name}] 上下文文件路径: {file_path}")
        existing_data: Dict[str, Any] = {}
        if file_path.exists():
            try:
                logger.debug(
                    f"[{current_thread_name}] 尝试读取现有上下文文件: {file_path}"
                )
                async with aiofiles.open(file_path, "r", encoding="utf-8") as fp:
                    content = await fp.read()

                # 增强类型安全：处理json.loads可能因类型或格式问题导致的异常
                if isinstance(content, str) and content.strip():
                    try:
                        existing_data = json.loads(content)
                        logger.debug(
                            f"[{current_thread_name}] JSON解析成功，使用标准格式。"
                        )
                    except (json.JSONDecodeError, TypeError, ValueError) as e:
                        logger.warning(
                            f"[{current_thread_name}] JSON解析失败，尝试兼容模式: {e}"
                        )
                        # 尝试手动解析可能损坏的JSON
                        try:
                            # 移除可能存在的Unicode控制字符（AGENTS.md原则）
                            import re

                            content = re.sub(
                                r"[\u0000-\u007F\u0080-\u00FF]{0,}[\u007F-\u009F]",
                                "",
                                content,
                            )
                            existing_data = json.loads(content)
                            logger.info(
                                f"[{current_thread_name}] 通过Unicode清理成功解析。"
                            )
                        except (json.JSONDecodeError, TypeError) as fallback_e:
                            logger.error(
                                f"[{current_thread_name}] 兼容模式解析失败，创建新文件: {fallback_e}"
                            )
                            existing_data = {}
                else:
                    logger.warning(
                        f"[{current_thread_name}] 读取到空或非字符串内容，使用新字典。"
                    )
                    existing_data = {}

                logger.debug(f"[{current_thread_name}] 成功读取现有上下文文件。")
            except Exception as e:
                logger.warning(
                    f"[{current_thread_name}] 读取现有上下文文件失败 {file_path}: {e}，将创建新文件。"
                )
        else:
            logger.debug(f"[{current_thread_name}] 上下文文件不存在，将创建新文件。")

        # 增强格式兼容性：处理所有历史格式（AGENTS.md配置深合并原则）
        if isinstance(existing_data, list):
            logger.debug(
                f"[{current_thread_name}] 检测到历史格式（列表），转换为新格式。"
            )
            existing_data = {"context": existing_data}

        # 类型安全检查：确保existing_data是字典
        if not isinstance(existing_data, dict):
            logger.warning(
                f"[{current_thread_name}] 现有数据类型无效 (类型: {type(existing_data).__name__})，创建新空上下文。"
            )
            existing_data = {"context": []}
        else:
            logger.debug(f"[{current_thread_name}] 数据格式验证通过。")

        # 深合并兼容性：确保context键存在并是列表
        if "context" not in existing_data or not isinstance(
            existing_data["context"], (list, type(None))
        ):
            logger.warning(
                f"[{current_thread_name}] 上下文键缺失或类型错误，重置为空列表。"
            )
            existing_data["context"] = []
        elif existing_data["context"] is None:
            logger.debug(f"[{current_thread_name}] 上下文为空，初始化为空列表。")
            existing_data["context"] = []

        # 增强类型安全：更新上下文对，强制类型转换确保兼容性
        logger.debug(f"[{current_thread_name}] 开始更新上下文对。")
        triplets: List[Tuple[str, str, str]] = []
        context_data = existing_data.get("context", [])

        # 类型检查确保context_data是可迭代的
        if not isinstance(context_data, (list, tuple)):
            logger.warning(
                f"[{current_thread_name}] 上下文数据不是列表类型，重置为空。"
            )
            context_data = []

        logger.debug(
            f"[{current_thread_name}] 现有上下文数据条目数: {len(context_data)}"
        )

        for i, item in enumerate(context_data):
            try:
                if isinstance(item, dict):
                    o = str(item.get("original", ""))  # 强制类型转换
                    t = str(item.get("translated", ""))
                    d = str(item.get("direction", "ME→Counterpart"))
                    triplets.append((o, t, d))
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    # 历史格式兼容：旧列表条目（AGENTS.md深合并原则）
                    o = str(item[0]) if item[0] is not None else ""
                    t = str(item[1]) if item[1] is not None else ""
                    d = "ME→Counterpart"  # 为旧格式提供默认方向
                    triplets.append((o, t, d))
                elif isinstance(item, str) and item.strip():
                    # 尝试解析可能的简单字符串格式
                    try:
                        parsed_item = json.loads(item)
                        if (
                            isinstance(parsed_item, (list, tuple))
                            and len(parsed_item) >= 2
                        ):
                            triplets.append(
                                (
                                    str(parsed_item[0]),
                                    str(parsed_item[1]),
                                    "ME→Counterpart",
                                )
                            )
                        else:
                            logger.debug(
                                f"[{current_thread_name}] 无法解析字符串项: {item}"
                            )
                    except (json.JSONDecodeError, TypeError):
                        logger.debug(
                            f"[{current_thread_name}] 跳过无法解析的字符串: {item}"
                        )
                else:
                    logger.debug(
                        f"[{current_thread_name}] 跳过无效条目 (索引{i}): {type(item).__name__}"
                    )
            except Exception as e:
                logger.warning(
                    f"[{current_thread_name}] 处理上下文条目{i}时出现错误: {e}，跳过此条目。"
                )

        # 增强类型安全：检查重复，确保完全的字符串比较
        is_duplicate = False
        try:
            for existing_original, existing_translated, existing_direction in triplets:
                # 强制转换为字符串进行比较（修复TypeError兼容性）
                orig_cmp = (
                    str(existing_original) if existing_original is not None else ""
                )
                trans_cmp = (
                    str(existing_translated) if existing_translated is not None else ""
                )
                if (
                    orig_cmp.strip() == str(original).strip()
                    and trans_cmp.strip() == str(translated).strip()
                ):
                    logger.debug(
                        f"[{current_thread_name}] 发现重复翻译对，跳过写入: '{orig_cmp}' -> '{trans_cmp}'"
                    )
                    is_duplicate = True
                    break
        except Exception as e:
            logger.warning(
                f"[{current_thread_name}] 检查重复时出现错误: {e}，继续写入。"
            )
            is_duplicate = False

        if not is_duplicate:
            logger.debug(
                f"[{current_thread_name}] 添加新条目: original={original}, translated={translated}, direction={direction}"
            )
            triplets.append((original, translated, direction))
            if len(triplets) > max_count:
                logger.debug(
                    f"[{current_thread_name}] 上下文条目数超过最大限制 {max_count}，进行截断。"
                )
                triplets = triplets[-max_count:]  # 仅保留最新 max_count 条
        else:
            logger.debug(f"[{current_thread_name}] 跳过重复条目，保持现有上下文不变")

        # 增强类型安全：更新上下文数据，确保所有值都是字符串
        logger.debug(f"[{current_thread_name}] 准备更新上下文数据，包含方向信息。")
        try:
            updated_context = []
            for o, t, d in triplets:
                # 强制类型转换确保类型安全
                safe_original = str(o) if o is not None else ""
                safe_translated = str(t) if t is not None else ""
                safe_direction = str(d) if d is not None else "ME→Counterpart"
                updated_context.append(
                    {
                        "original": safe_original,
                        "translated": safe_translated,
                        "direction": safe_direction,
                    }
                )

            existing_data["context"] = updated_context
            with _log_lock:
                logger.debug(
                    f"[{current_thread_name}] 更新后的上下文数据: {existing_data}"
                )
        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 更新上下文数据时出现错误: {e}，不执行更新。"
            )
            return

        try:
            # 确保目录存在
            logger.debug(f"[{current_thread_name}] 确保目录存在: {file_path.parent}")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(f"[{current_thread_name}] 开始写入上下文文件: {file_path}")
            async with aiofiles.open(file_path, "w", encoding="utf-8") as fp:
                await fp.write(
                    json.dumps(
                        existing_data,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            logger.info(
                f"[{current_thread_name}] 已更新上下文文件: {file_path} (共 {len(triplets)} 条)"
            )
        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 写入上下文文件失败 {file_path}: {e}",
                exc_info=True,
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取上下文文件的统计信息。

        Returns:
            Dict[str, Any]: 包含文件总数和总大小的字典。
        """
        context_dir = _get_context_dir()
        total_files = 0
        total_size = 0
        try:
            for item in context_dir.iterdir():
                if item.is_file() and item.suffix == ".json":
                    total_files += 1
                    total_size += item.stat().st_size
            return {"total_files": total_files, "total_size_bytes": total_size}
        except Exception as e:
            logger.error(f"获取上下文统计信息失败: {e}")
            return {"total_files": 0, "total_size_bytes": 0, "error": str(e)}

    def clear_all_context(self) -> int:
        """清空所有上下文文件。

        Returns:
            int: 已删除的文件数量。
        """
        context_dir = _get_context_dir()
        deleted_count = 0
        try:
            for item in context_dir.iterdir():
                if item.is_file() and item.suffix == ".json":
                    item.unlink()
                    deleted_count += 1
            logger.info(f"成功清空 {deleted_count} 个上下文文件。")
            return deleted_count
        except Exception as e:
            logger.error(f"清空上下文文件失败: {e}")
            return 0
