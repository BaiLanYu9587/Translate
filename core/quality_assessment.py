"""
翻译质量评估模块
"""

import collections
import logging
from typing import Any, Dict, List, Optional, Tuple

import regex
from rapidfuzz import fuzz  # type: ignore[import-not-found]

from .constants import TokenizationConstants, TranslationConstants
from .rules_engine import find_best_matching_rule, get_language_group
from .text_utils import clean_text, get_ngrams

logger = logging.getLogger(__name__)

# --- 性能优化：预编译常用的正则表达式 ---

# 用于 assess_translation_quality
RE_NON_TARGET_CHARS_CLEANUP = regex.compile(r"[\s\p{P}]")

# 用于 _is_valid_repetition
RE_COMMON_REPETITION = regex.compile(r"[\s\p{P}]+")


# 用于 assess_translation_quality (新增)
RE_INVALID_TAGS = regex.compile(r"</?\s*[^>]+>")


def detect_translation_effort(
    original_text: str,
    translated_text: str,
    detected_source_lang: Optional[str] = None,
    target_lang_code: Optional[str] = None,
    config: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    检测翻译工作量和质量指标
    - 分析翻译是否进行了实质性改动
    - 识别可能的简单复制或机械翻译

    Args:
        original_text: 原文
        translated_text: 译文
        detected_source_lang: 检测到的源语言
        target_lang_code: 目标语言代码

    Returns:
        Dict: 包含工作量评分、是否可能是复制等信息
    """
    if not original_text or not translated_text:
        return {"effort_score": 0.0, "is_likely_copy": True, "indicators": ["文本为空"]}

    indicators = []
    effort_score = 1.0
    char_similarity = 0.0  # Default value

    # 1. 长度变化分析
    len_ratio = len(translated_text) / len(original_text) if original_text else 0
    length_diff = abs(len(translated_text) - len(original_text))

    if length_diff < 3:  # 长度变化小于3个字符
        indicators.append("长度变化不足")
        effort_score *= 0.6

    # 2. 字符级变化检测
    if original_text == translated_text:
        indicators.append("完全一致")
        effort_score *= 0.1
    else:
        # 计算字符级别的变化
        orig_chars = set(original_text)
        trans_chars = set(translated_text)
        char_intersection = len(orig_chars.intersection(trans_chars))
        char_union = len(orig_chars.union(trans_chars))
        char_similarity = char_intersection / char_union if char_union > 0 else 0

        if char_similarity > 0.8:  # 字符集过于相似
            indicators.append("字符集高度相似")
            effort_score *= 0.7

    # 3. 语言特征变化检测
    if detected_source_lang and target_lang_code:
        language_features: Dict[str, Dict[str, Any]] = {}

        if config:
            if hasattr(config, "language_features"):
                language_features = getattr(config, "language_features", {})
            elif hasattr(config, "mode_config"):
                if isinstance(config.mode_config, dict):
                    language_features = config.mode_config.get("language_features", {})
                else:
                    language_features = getattr(
                        config.mode_config, "language_features", {}
                    )
            elif hasattr(config, "get"):
                language_features = config.get("language_features", {})

        source_pattern = ""
        target_pattern = ""

        if isinstance(language_features, dict):
            source_lang_config = language_features.get(detected_source_lang, {})
            if isinstance(source_lang_config, dict):
                source_pattern = source_lang_config.get("pattern", "")

            target_lang_config = language_features.get(target_lang_code, {})
            if isinstance(target_lang_config, dict):
                target_pattern = target_lang_config.get("pattern", "")

        has_source_indicators = False
        if source_pattern:
            try:
                has_source_indicators = bool(
                    regex.search(source_pattern, translated_text)
                )
            except regex.error as e:
                logger.warning(
                    f"源语言特征检测正则表达式错误: {e}, pattern: {source_pattern}"
                )

        has_target_indicators = False
        if target_pattern:
            try:
                has_target_indicators = bool(
                    regex.search(target_pattern, translated_text)
                )
            except regex.error as e:
                logger.warning(
                    f"目标语言特征检测正则表达式错误: {e}, pattern: {target_pattern}"
                )

        if (
            has_source_indicators
            and detected_source_lang != target_lang_code
            and source_pattern
        ):
            indicators.append("保留源语言特征，未完整翻译为目标语言")
            effort_score *= 0.5
        elif (
            detected_source_lang != target_lang_code
            and not has_target_indicators
            and target_pattern
        ):
            indicators.append("缺少目标语言特征，翻译不完整")
            effort_score *= 0.5

    # 4. 标点符号和空格变化
    orig_punct = len([c for c in original_text if c in '.,!?;:"()[]{}'])
    trans_punct = len([c for c in translated_text if c in '.,!?;:"()[]{}'])

    if abs(orig_punct - trans_punct) < 2 and length_diff > 10:
        indicators.append("标点符号变化不足")
        effort_score *= 0.8

    return {
        "effort_score": effort_score,
        "is_likely_copy": effort_score < 0.4,
        "indicators": indicators,
        "length_ratio": len_ratio,
        "char_similarity": char_similarity,
    }


def calculate_text_similarity(
    text1: str, text2: str, config: Optional[Any] = None
) -> float:
    """计算两段文本的相似度"""
    if not text1 or not text2:
        return 0.0

    common_symbols_pattern = getattr(config, "common_symbols", None)
    if common_symbols_pattern:
        logger.debug(f"使用配置中的 common_symbols: {common_symbols_pattern}")
    else:
        logger.debug("未找到 common_symbols 配置，将使用默认的标点符号清理。")

    clean_text1 = clean_text(text1, common_symbols_pattern)
    clean_text2 = clean_text(text2, common_symbols_pattern)

    if not clean_text1 or not clean_text2:
        return 0.0

    quality_config = getattr(config, "translation_quality", {}) if config else {}
    short_text_threshold = quality_config.get("similarity_short_text_threshold", 100)
    ngram_size = quality_config.get("similarity_ngram_size", 3)
    fallback_ngram_size = quality_config.get("similarity_fallback_ngram_size", 2)

    if (
        len(clean_text1) < short_text_threshold
        and len(clean_text2) < short_text_threshold
    ):
        return fuzz.ratio(clean_text1, clean_text2) / 100.0

    ngrams1 = get_ngrams(clean_text1, ngram_size)
    ngrams2 = get_ngrams(clean_text2, ngram_size)

    if not ngrams1 or not ngrams2:
        ngrams1 = get_ngrams(clean_text1, fallback_ngram_size)
        ngrams2 = get_ngrams(clean_text2, fallback_ngram_size)

    intersection = len(ngrams1.intersection(ngrams2))
    union = len(ngrams1.union(ngrams2))

    return intersection / union if union > 0 else 0.0


def _get_tokenization_strategy(lang_code: str, mode_config: Dict[str, Any]) -> str:
    """根据语言代码和模式配置获取分词策略。"""
    default_strategy: str = TokenizationConstants.DEFAULT_STRATEGY
    if not mode_config or "special_language_groups" not in mode_config:
        return default_strategy

    for group_info in mode_config["special_language_groups"].values():
        if isinstance(group_info, dict) and lang_code in group_info.get(
            "languages", []
        ):
            return str(group_info.get("tokenization_strategy", default_strategy))
    return default_strategy


def _tokenize_text_by_language(
    text: str, lang_code: str, mode_config: Dict[str, Any]
) -> List[str]:
    """根据语言特征自动确定分词策略。"""
    strategy = _get_tokenization_strategy(lang_code, mode_config)
    logger.debug(f"为语言 '{lang_code}' 自动选择的分词策略: '{strategy}'")

    if strategy == TokenizationConstants.STRATEGY_CHAR:
        return list(text)
    else:  # 默认是 "space"
        return text.split()


def _create_ngrams(items: List[str], n: int) -> List[str]:
    """创建n-gram"""
    return [" ".join(items[i : i + n]) for i in range(len(items) - n + 1)]


def _is_valid_repetition(
    ngram: str, count: int, min_count: int, text: str, quality_config: Dict[str, Any]
) -> bool:
    """检查是否为有效的重复内容"""
    if count < min_count:
        return False
    if ngram.isdigit():
        return False
    stripped_ngram = ngram.strip().replace(" ", "")
    if len(stripped_ngram) < 3:
        return False
    if RE_COMMON_REPETITION.fullmatch(ngram):
        return False
    total_repeated_length = len(stripped_ngram) * count
    ratio = total_repeated_length / len(text) if len(text) > 0 else 0
    ratio_threshold = quality_config.get("word_repetition_ratio_threshold", 0.3)
    if ratio < ratio_threshold:
        return False
    return True


def detect_text_repetition(
    text: str,
    lang_code: str,
    mode_config: Dict[str, Any],
    quality_config: Dict[str, Any],
) -> Tuple[bool, str, int]:
    """检测文本中的重复内容"""
    if not text:
        return False, "", 0
    if not lang_code:
        logger.error("必须提供语言代码用于重复检测")
        return False, "", 0

    min_len = quality_config.get("word_repetition_min_words", 20)
    min_count = quality_config.get("word_repetition_min_count", 3)
    ngram_sizes = quality_config.get("repetition_ngram_sizes", [3, 4, 5])

    if len(text) < min_len:
        return False, "", 0

    processed_text = regex.sub(r"(.)\1{2,}", r" \1 ", text)
    items = _tokenize_text_by_language(processed_text, lang_code, mode_config)

    if not items:
        return False, "", 0

    for n in ngram_sizes:
        if len(items) < n:
            continue
        ngrams = _create_ngrams(items, n)
        if not ngrams:
            continue
        ngram_counts = collections.Counter(ngrams)
        most_common = ngram_counts.most_common(1)
        if not most_common:
            continue
        ngram, count = most_common[0]
        if _is_valid_repetition(ngram, count, min_count, text, quality_config):
            return True, ngram, count
    return False, "", 0


def check_source_language_residue(
    translated_text: str, source_lang_code: str, language_features: Dict[str, Any]
) -> bool:
    """检查翻译结果中是否残留源语言内容"""
    if not translated_text or not source_lang_code or not language_features:
        return False
    if source_lang_code not in language_features:
        return False
    source_lang_config = language_features[source_lang_code]
    if not isinstance(source_lang_config, dict):
        return False
    source_pattern = source_lang_config.get("pattern", "")
    if not source_pattern:
        return False
    exclusive_patterns = source_lang_config.get("exclusive", [])
    if not isinstance(exclusive_patterns, list):
        exclusive_patterns = []
    try:
        # 检查是否匹配源语言特征
        source_match = bool(regex.search(source_pattern, translated_text))
        if not source_match:
            return False

        # 如果匹配源语言特征，检查是否也匹配排除特征（即在目标语言中正常使用）
        for excl_pattern in exclusive_patterns:
            if excl_pattern and regex.search(excl_pattern, translated_text):
                return False  # 如果匹配排除特征，不算残留

        return True  # 匹配源语言特征且未匹配排除特征，算残留
    except regex.error:
        return False


def assess_translation_quality(
    original_text: str,
    translated_text: str,
    detected_source_lang: Optional[str] = None,
    target_lang_code: Optional[str] = None,
    config: Optional[Any] = None,
    mode_config: Optional[Dict[str, Any]] = None,
    context_history: Optional[List[Tuple[str, str, str]]] = None,
) -> Tuple[str, float, List[str]]:
    """通用化翻译质量评估函数"""
    if not original_text or not translated_text:
        return "较差", 0.0, ["原文或译文为空"]
    if original_text.strip() == translated_text.strip():
        logger.info("翻译结果与原文完全相同，质量评估为“较差”。")
        return "较差", 0.0, ["翻译结果与原文完全相同"]

    quality_config = getattr(config, "translation_quality", {}) if config else {}
    penalties = quality_config.get("penalties", {})
    score = 1.0
    issues = []

    # 新增步骤：无效标签检测
    if RE_INVALID_TAGS.search(translated_text):
        issues.append("翻译结果中包含无效的XML/HTML标签")
        score *= penalties.get("invalid_tags", 0.1)

    # 1. 智能文本相似度检查
    similarity = calculate_text_similarity(original_text, translated_text, config)
    has_context = context_history and len(context_history) > 0
    min_length_diff = quality_config.get(
        "min_translation_length_diff",
        TranslationConstants.MIN_TRANSLATION_LENGTH_DIFF_DEFAULT,
    )

    # 2. 翻译工作量分析
    effort_analysis = detect_translation_effort(
        original_text, translated_text, detected_source_lang, target_lang_code, config
    )

    if has_context:
        high_similarity_threshold = quality_config.get(
            "context_aware_similarity_threshold",
            TranslationConstants.CONTEXT_AWARE_SIMILARITY_THRESHOLD_DEFAULT,
        )
    else:
        high_similarity_threshold = quality_config.get(
            "cross_lang_high_similarity_threshold",
            TranslationConstants.CROSS_LANG_HIGH_SIMILARITY_THRESHOLD_DEFAULT,
        )

    length_diff = abs(len(translated_text) - len(original_text))
    effort_threshold = quality_config.get(
        "effort_score_threshold", TranslationConstants.EFFORT_SCORE_THRESHOLD_DEFAULT
    )

    is_problematic = False
    if (
        detected_source_lang
        and target_lang_code
        and detected_source_lang != target_lang_code
    ):
        if similarity > high_similarity_threshold and (
            length_diff < min_length_diff
            or effort_analysis["effort_score"] < effort_threshold
        ):
            is_problematic = True
    else:
        if (
            similarity > high_similarity_threshold
            and effort_analysis["effort_score"] < effort_threshold
        ):
            is_problematic = True

    if is_problematic:
        threshold_desc = "上下文感知" if has_context else "跨语言"
        effort_indicators = (
            ", ".join(effort_analysis["indicators"])
            if effort_analysis["indicators"]
            else "无明显改动"
        )
        issues.append(
            f"翻译结果与原文{threshold_desc}相似度过高 ({similarity:.2f})，翻译工作量不足 ({effort_analysis['effort_score']:.2f} < {effort_threshold})，{effort_indicators}。"
        )
        score *= 0.7

    # 3. 句子长度比例检查
    len_original = len(original_text)
    len_translated = len(translated_text)
    if len_original > 0 and len_translated > 0 and config:
        ratio = len_translated / len_original
        special_rules = {}
        lang_groups = {}

        if mode_config:
            special_rules = mode_config.get("special_language_pairs", {})
            lang_groups = mode_config.get("special_language_groups", {})

        if not special_rules and config:
            if hasattr(config, "special_language_pairs"):
                special_rules = config.special_language_pairs
            elif hasattr(config, "get"):
                special_rules = config.get("special_language_pairs", {})
        if not lang_groups and config:
            if hasattr(config, "special_language_groups"):
                lang_groups = config.special_language_groups
            elif hasattr(config, "get"):
                lang_groups = config.get("special_language_groups", {})

        source_group = get_language_group(detected_source_lang, lang_groups)
        target_group = get_language_group(target_lang_code, lang_groups)

        best_rule = find_best_matching_rule(
            detected_source_lang,
            target_lang_code,
            source_group,
            target_group,
            special_rules,
        )

        min_ratio = best_rule.get("min_char_ratio")
        max_ratio = best_rule.get("max_char_ratio")

        if min_ratio is not None and max_ratio is not None:
            if not (min_ratio <= ratio <= max_ratio):
                issues.append(
                    f"译文长度与原文比例 ({ratio:.2f}) 超出专家规则范围 [{min_ratio}, {max_ratio}]，可能存在内容丢失或不自然的扩展。"
                )
                score *= penalties.get("length_mismatch", 0.85)
        else:
            lang_pair = f"{detected_source_lang}-{target_lang_code}"
            logger.warning(
                f"未在专家规则中找到适用于 {lang_pair} 的长度比例规则 (min/max_char_ratio)，跳过此项检查。"
            )

    # 4. 重复内容检测
    if mode_config and target_lang_code:
        repetition_detected, repeated_item, repeat_count = detect_text_repetition(
            translated_text, target_lang_code, mode_config, quality_config
        )
        if repetition_detected and len(repeated_item.replace(" ", "")) > 1:
            issues.append(
                f"翻译结果中短语 '{repeated_item}' 重复 {repeat_count} 次，可能不自然。"
            )
            score *= penalties.get("repetition", 0.8)

    # 5. 源语言残留检测
    if (
        config
        and detected_source_lang
        and target_lang_code
        and detected_source_lang != target_lang_code
    ):
        # 查找最匹配的规则
        special_rules = (
            mode_config.get("special_language_pairs", {}) if mode_config else {}
        )
        lang_groups = (
            mode_config.get("special_language_groups", {}) if mode_config else {}
        )
        source_group = get_language_group(detected_source_lang, lang_groups)
        target_group = get_language_group(target_lang_code, lang_groups)
        best_rule = find_best_matching_rule(
            detected_source_lang,
            target_lang_code,
            source_group,
            target_group,
            special_rules,
        )

        # 根据规则决定是否执行残留检查
        perform_residue_check = not best_rule.get("allow_source_residue", False)

        # 新增逻辑：如果源语言和目标语言在同一个组（例如cjk），则不执行残留检查
        if source_group and source_group == target_group:
            logger.debug(
                f"源语言 ({detected_source_lang}) 和目标语言 ({target_lang_code}) "
                f"同属于 '{source_group}' 组，跳过源语言残留检查。"
            )
            perform_residue_check = False

        if perform_residue_check:
            lang_features = (
                mode_config.get("language_features", {}) if mode_config else {}
            )
            if check_source_language_residue(
                translated_text, detected_source_lang, lang_features
            ):
                issue_text = "译文中检测到源语言残留"
                if not any(issue_text in s for s in issues):
                    issues.append(issue_text)
                    score *= penalties.get("residue", 0.4)
        elif not source_group or source_group != target_group:
            logger.debug(
                f"根据规则 '{best_rule.get('desc', '未命名规则')}'，跳过对 {detected_source_lang} -> {target_lang_code} 的源语言残留检查。"
            )

    # 6. 根据分数和问题数量判断最终标签
    score_thresholds = quality_config.get(
        "quality_score_thresholds", {"poor": 0.6, "average": 0.85, "good": 1.0}
    )
    issue_count_thresholds = quality_config.get(
        "quality_issue_count_thresholds", {"poor": 3, "average": 1}
    )

    final_label = "良好"
    if score < score_thresholds.get("poor", 0.6) or len(
        issues
    ) >= issue_count_thresholds.get("poor", 3):
        final_label = "较差"
    elif score < score_thresholds.get("average", 0.85) or len(
        issues
    ) >= issue_count_thresholds.get("average", 1):
        final_label = "一般"

    return final_label, score, issues
