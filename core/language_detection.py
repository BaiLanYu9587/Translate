"""
语言检测模块
提供多种语言检测算法和决策逻辑
"""

import regex
import logging
import os
import threading
import json
from collections import OrderedDict
from typing import Dict, List, Optional, Any, TypedDict
import xxhash
import pycld2 as cld2

import yaml
from .config_management import (
    get_config_file_path,
    get_mode_config_file_path,
    generate_default_main_config,
    generate_default_mode_config,
)
import core.constants as constants_module

TranslationConstants = constants_module.TranslationConstants

logger = logging.getLogger(__name__)


# 全局预编译模式
COMPILED_PATTERNS: Dict[str, Dict[str, Any]] = {}

# 多线程安全的模式初始化锁
_patterns_lock = threading.Lock()
_patterns_initialized = False


def _initialize_patterns() -> None:
    """在模块加载时编译语言模式，具有多线程安全性"""
    global COMPILED_PATTERNS, _patterns_initialized

    if _patterns_initialized:
        return  # 已经初始化完成，直接返回

    with _patterns_lock:
        if _patterns_initialized:
            return  # 双重检查锁定模式

        try:
            # 确保配置文件存在
            main_config_path = get_config_file_path()
            mode_config_path = get_mode_config_file_path()

            if not os.path.exists(main_config_path):
                generate_default_main_config()
            if not os.path.exists(mode_config_path):
                generate_default_mode_config()

            # 加载模式配置
            with open(mode_config_path, "r", encoding="utf-8-sig") as f:
                mode_config = yaml.safe_load(f)

            language_features = mode_config.get("language_features", {})
            if language_features:
                COMPILED_PATTERNS = compile_language_patterns(language_features)
                logger.debug("全局语言特征模式已编译。")

            # 标记初始化完成
            _patterns_initialized = True
            logger.debug("语言模式初始化完成，多线程安全")

        except Exception as e:
            logger.error(f"初始化语言模式失败: {e}", exc_info=True)
            # 即使失败也要标记为已初始化，避免无限重试
            _patterns_initialized = True


# 结果类型定义，消除 Any 推断
class ResultEntry(TypedDict):
    lang: str
    prob: float


class FeatureResult(TypedDict):
    matches: bool
    excludes_violated: bool
    desc: str
    match_score: float


# 使用 OrderedDict 实现一个简单的LRU缓存
language_detection_cache: "OrderedDict[str, tuple[str, float]]" = OrderedDict()


def compile_language_patterns(
    language_features: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """编译语言特征的正则表达式模式

    Args:
        language_features: 语言特征配置字典

    Returns:
        Dict[str, Dict[str, Any]]: 编译后的模式字典
    """
    import regex

    compiled_patterns: Dict[str, Dict[str, Any]] = {}

    for lang_code, features in language_features.items():
        if lang_code not in compiled_patterns:
            compiled_patterns[lang_code] = {}

        # 编译主模式 - 使用 "pattern" 键
        if "pattern" in features and features["pattern"]:
            try:
                pattern_str = features["pattern"].strip()
                if pattern_str:
                    compiled_patterns[lang_code]["main"] = regex.compile(
                        pattern_str, regex.IGNORECASE
                    )
                else:
                    compiled_patterns[lang_code]["main"] = regex.compile(
                        r"(?!)"
                    )  # 永不匹配的模式
            except regex.error as e:
                logger.warning(f"编译语言 {lang_code} 的主模式失败: {e}")
                compiled_patterns[lang_code]["main"] = regex.compile(
                    r"(?!)"
                )  # 永不匹配的模式

        # 编译排他模式 - 使用 "exclusive" 键
        if "exclusive" in features and features["exclusive"]:
            exclusive_patterns = []
            for pattern_str in features["exclusive"]:
                if pattern_str.strip():
                    try:
                        exclusive_patterns.append(
                            regex.compile(pattern_str.strip(), regex.IGNORECASE)
                        )
                    except regex.error as e:
                        logger.warning(f"编译语言 {lang_code} 的排他模式失败: {e}")
                        exclusive_patterns.append(
                            regex.compile(r"(?!)")
                        )  # 永不匹配的模式
            compiled_patterns[lang_code]["exclusive"] = exclusive_patterns
        else:
            compiled_patterns[lang_code]["exclusive"] = []

    return compiled_patterns


def detect_language_features(
    text: str,
    language_features: Dict[str, Dict[str, List[str]]],
    compiled_patterns: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, FeatureResult]:
    """使用语言特征检测文本语言

    Args:
        text: 要检测的文本
        language_features: 语言特征配置
        compiled_patterns: 预编译的模式（可选）

    Returns:
        Dict[str, Dict]: 特征检测结果
    """
    if not text or not language_features:
        return {}

    if compiled_patterns is None:
        compiled_patterns = compile_language_patterns(language_features)

    feature_results: Dict[str, FeatureResult] = {}

    for lang_code in language_features:
        if lang_code not in compiled_patterns:
            continue

        # 修复：确保 'main' 键存在，如果不存在则跳过该语言
        if "main" not in compiled_patterns[lang_code]:
            logger.warning(f"语言 {lang_code} 缺少主模式，跳过该语言的特征检测")
            continue

        # 添加类型检查，确保 compiled_patterns[lang_code] 是字典
        lang_patterns = compiled_patterns[lang_code]
        if not isinstance(lang_patterns, dict):
            logger.warning(
                f"语言 {lang_code} 的模式配置不是字典类型，跳过该语言的特征检测"
            )
            continue

        pattern = lang_patterns["main"]
        exclusive_patterns = lang_patterns.get("exclusive", [])

        matches = bool(pattern.search(text))
        excludes_violated = any(excl.search(text) for excl in exclusive_patterns)

        match_score: float = 0.0
        if matches and not excludes_violated and len(text) > 0:
            try:
                matched_content = regex.findall(pattern, text)
                match_len = sum(
                    len(m)
                    if isinstance(m, str)
                    else sum(len(part) if isinstance(part, str) else 1 for part in m)
                    if isinstance(m, list)
                    else 1
                    for m in matched_content
                )
                match_score = min(match_len / len(text), 1.0)
            except regex.error as e:
                logger.error(f"计算语言 {lang_code} 的 match_score 时正则错误: {e}")

        feature_results[lang_code] = {
            "matches": matches,
            "excludes_violated": excludes_violated,
            "desc": str(language_features[lang_code].get("desc", f"{lang_code} 语言")),
            "match_score": match_score,
        }

    return feature_results


def detect_with_pycld2(
    text: str, supported_langs: Dict[str, List[str]]
) -> List[ResultEntry]:
    """使用pycld2进行语言检测

    Args:
        text: 要检测的文本
        supported_langs: 支持的语言字典

    Returns:
        List[Dict]: 检测结果列表
    """
    if not text or not supported_langs:
        return []

    cld2_results: List[ResultEntry] = []
    try:
        is_reliable, _, detected_details = cld2.detect(text)
        logger.debug(
            f"pycld2 检测结果: is_reliable={is_reliable}, details={detected_details}"
        )

        for _, code, percent, _ in detected_details:
            if code != "un" and code in supported_langs:
                cld2_results.append({"lang": code, "prob": percent / 100.0})
    except Exception as e:
        logger.error(f"pycld2 语言检测失败: {e}")

    return cld2_results


def apply_hint_bias(
    results: List[ResultEntry], hint_lang: str, bias_value: float
) -> List[ResultEntry]:
    """应用语言提示偏置

    Args:
        results: 检测结果列表
        hint_lang: 提示语言代码
        bias_value: 偏置值

    Returns:
        List[Dict]: 应用偏置后的结果
    """
    if not results or not hint_lang or bias_value <= 0:
        return results

    # 为提示语言增加偏置
    for result in results:
        if result["lang"] == hint_lang:
            result["prob"] = min(result["prob"] + bias_value, 1.0)
            break
    else:
        # 如果提示语言不在结果中，添加它
        results.append({"lang": hint_lang, "prob": bias_value})

    # 重新排序
    results.sort(key=lambda x: x["prob"], reverse=True)
    return results


def check_language_ambiguity(
    results: List[ResultEntry], ambiguity_factor: float
) -> bool:
    """检查语言检测是否存在歧义

    Args:
        results: 检测结果列表
        ambiguity_factor: 歧义判断系数

    Returns:
        bool: 是否存在歧义
    """
    if len(results) < 2:
        return False

    first_prob = results[0]["prob"]
    second_prob = results[1]["prob"]

    # 如果第一名的概率不够高，或者与第二名差距不够大，则认为存在歧义
    return (
        first_prob < 0.7
        or (first_prob / second_prob if second_prob > 0 else float("inf"))
        < ambiguity_factor
    )


def combine_detection_results(
    main_results: List[ResultEntry],
    feature_results: Dict[str, FeatureResult],
    prob_weight: float,
    feature_weight: float,
) -> List[ResultEntry]:
    """结合主检测器和特征检测的结果

    Args:
        main_results: 主检测器结果
        feature_results: 特征检测结果
        prob_weight: 主检测器权重
        feature_weight: 特征检测权重

    Returns:
        List[Dict]: 结合后的结果
    """
    combined_scores = {}

    # 处理主检测器结果
    for result in main_results:
        lang = result["lang"]
        combined_scores[lang] = result["prob"] * prob_weight

    # 处理特征检测结果
    for lang, feature_data in feature_results.items():
        if feature_data["matches"] and not feature_data["excludes_violated"]:
            score = feature_data["match_score"] * feature_weight
            combined_scores[lang] = combined_scores.get(lang, 0) + score

    # 转换为列表并排序
    combined_results: List[ResultEntry] = [
        {"lang": lang, "prob": float(score)} for lang, score in combined_scores.items()
    ]
    combined_results.sort(key=lambda x: x["prob"], reverse=True)

    return combined_results


def detect_language_with_cache(
    text: str,
    hint_lang: Optional[str] = None,
    supported_langs: Optional[Dict[str, List[str]]] = None,
    language_features: Optional[Dict[str, Dict[str, List[str]]]] = None,
    config: Optional[Any] = None,
    compiled_patterns: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """带缓存的语言检测

    Args:
        text: 要检测的文本
        hint_lang: 提示语言代码
        supported_langs: 支持的语言字典
        language_features: 语言特征配置
        config: 配置对象

    Returns:
        str: 检测到的语言代码
    """
    global language_detection_cache
    current_thread_name = threading.current_thread().name

    logger.debug(
        f"[{current_thread_name}] 开始语言检测，文本长度: {len(text)}, 提示语言: {hint_lang}"
    )

    if not text:
        logger.warning(f"[{current_thread_name}] 语言检测失败：文本为空")
        return "unknown"

    # 使用辅助函数为配置生成一个稳定的哈希值
    def get_stable_config_hash(config_obj: Any) -> str:
        if not (config_obj and hasattr(config_obj, "language_detection")):
            return "no_config"
        try:
            # 使用json.dumps并排序键来创建稳定的字符串表示
            config_dict = config_obj.language_detection
            # 对于复杂对象，优先使用其可序列化属性而不是整个对象
            if hasattr(config_obj, "__dict__"):
                # 提取配置对象的具体参数作为额外哈希因子
                extra_params = {}
                if hasattr(config_obj, "thread_pool_max_workers"):
                    extra_params["thread_pool_max_workers"] = (
                        config_obj.thread_pool_max_workers
                    )
                if hasattr(config_obj, "short_text_threshold"):
                    extra_params["short_text_threshold"] = (
                        config_obj.short_text_threshold
                    )
                if hasattr(config_obj, "cache_max_entries"):
                    extra_params["cache_max_entries"] = config_obj.cache_max_entries

                if extra_params:
                    config_dict = dict(config_dict)
                    config_dict["_extra_params"] = extra_params

            config_str = json.dumps(config_dict, sort_keys=True)
            return xxhash.xxh64(config_str.encode("utf-8")).hexdigest()
        except (TypeError, AttributeError, Exception) as e:
            logger.warning(
                f"无法为语言检测配置生成稳定哈希: {e}，使用配置类名和关键参数"
            )
            # 多线程安全的最终防线：使用配置对象的类名和关键参数
            stable_fallback = f"{config_obj.__class__.__name__}"
            try:
                if hasattr(config_obj, "thread_pool_max_workers"):
                    stable_fallback += f"_{config_obj.thread_pool_max_workers}"
                if hasattr(config_obj, "short_text_threshold"):
                    stable_fallback += f"_{config_obj.short_text_threshold}"
                if hasattr(config_obj, "cache_max_entries"):
                    stable_fallback += f"_{config_obj.cache_max_entries}"
            except Exception:
                pass  # 如果访问失败，保持基础fallback
            return xxhash.xxh64(stable_fallback.encode("utf-8")).hexdigest()

    text_hash = xxhash.xxh64(text.encode("utf-8")).hexdigest()
    config_hash = get_stable_config_hash(config)
    cache_key = f"{text_hash}|{hint_lang or 'none'}|{config_hash}"

    # 缓存键生成后，可以移除对 hashlib 的导入

    # 检查缓存
    cached_result = _get_from_language_cache(cache_key)
    if cached_result:
        logger.debug(f"[{current_thread_name}] 语言检测缓存命中，结果: {cached_result}")
        return cached_result

    # 执行检测
    logger.debug(f"[{current_thread_name}] 执行实际语言检测")
    detected_lang = detect_language_internal(
        text, hint_lang, supported_langs, language_features, config, compiled_patterns
    )
    logger.info(f"[{current_thread_name}] 语言检测完成，结果: {detected_lang}")

    # 更新缓存
    detection_config = getattr(config, "language_detection", {}) if config else {}
    cache_size = detection_config.get(
        "cache_size", TranslationConstants.LANGUAGE_DETECTION_CACHE_SIZE_DEFAULT
    )
    import time as _t

    _add_to_language_cache(cache_key, (detected_lang, _t.time()), cache_size)

    return detected_lang


def detect_language_internal(
    text: str,
    hint_lang: Optional[str] = None,
    supported_langs: Optional[Dict[str, List[str]]] = None,
    language_features: Optional[Dict[str, Dict[str, List[str]]]] = None,
    config: Optional[Any] = None,
    compiled_patterns: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """内部语言检测实现

    Args:
        text: 要检测的文本
        hint_lang: 提示语言代码
        supported_langs: 支持的语言字典
        language_features: 语言特征配置
        config: 配置对象

    Returns:
        str: 检测到的语言代码
    """
    current_thread_name = threading.current_thread().name
    if not text or not supported_langs:
        logger.warning(f"[{current_thread_name}] 语言检测失败：文本或支持语言列表为空")
        return "unknown"

    # 获取配置参数
    detection_config = getattr(config, "language_detection", {}) if config else {}
    logger.debug(f"[{current_thread_name}] 原始配置对象类型: {type(config)}")

    ambiguity_factor = detection_config.get("ambiguity_factor", 1.4)
    hint_bias = detection_config.get("hint_bias", 0.2)
    prob_weight = detection_config.get("prob_weight", 0.7)
    feature_weight = detection_config.get("feature_weight", 0.3)

    logger.debug(
        f"[{current_thread_name}] 检测配置: ambiguity_factor={ambiguity_factor}, hint_bias={hint_bias}, "
        f"prob_weight={prob_weight}, feature_weight={feature_weight}"
    )

    # 验证配置是否正确加载（仅在debug模式下输出详细信息）
    if logger.isEnabledFor(logging.DEBUG):
        if not (config and hasattr(config, "language_detection")):
            logger.debug(
                f"[{current_thread_name}] config对象没有language_detection属性"
            )

    # 判断是否为短文本
    short_threshold = getattr(
        config,
        "short_text_threshold",
        TranslationConstants.SHORT_TEXT_THRESHOLD_DEFAULT,
    )
    is_short_text = len(text) <= short_threshold

    if is_short_text:
        prob_weight = detection_config.get("short_text_prob_weight", 0.4)
        feature_weight = detection_config.get("short_text_feature_weight", 0.6)
        # 添加保护措施，防止特征权重过高导致误判
        feature_weight = min(feature_weight, 0.7)  # 限制特征权重最大值
        logger.debug(
            f"[{current_thread_name}] 短文本检测，调整权重: prob_weight={prob_weight}, feature_weight={feature_weight}"
        )

    # 使用pycld2进行主检测
    logger.debug(f"[{current_thread_name}] 开始pycld2主检测")
    main_results = detect_with_pycld2(text, supported_langs)
    logger.debug(f"[{current_thread_name}] pycld2检测结果: {main_results}")

    # 使用特征检测
    feature_results = {}
    if language_features:
        logger.debug(f"[{current_thread_name}] 开始特征检测")
        # 传递预编译的模式
        feature_results = detect_language_features(
            text, language_features, compiled_patterns
        )
        logger.debug(
            f"[{current_thread_name}] 特征检测结果: {list(feature_results.keys())}"
        )

    # 结合检测结果
    logger.debug(f"[{current_thread_name}] 结合检测结果")

    # 通用误判校正：当pycld2的结果与特征检测冲突时，惩罚pycld2的结果
    if main_results and feature_results:
        pycld2_top_lang = main_results[0]["lang"]
        
        # 检查pycld2的首选语言是否通过了自身的特征检测
        pycld2_lang_has_features = feature_results.get(pycld2_top_lang, {}).get("matches", False)

        # 寻找其他通过了特征检测的语言
        other_feature_matches = [
            lang for lang, res in feature_results.items()
            if res.get("matches") and not res.get("excludes_violated") and lang != pycld2_top_lang
        ]

        # 如果pycld2的结果没有通过特征检测，而其他语言通过了，则判定为冲突
        if not pycld2_lang_has_features and other_feature_matches:
            logger.warning(
                f"[{current_thread_name}] 检测到pycld2结果 ('{pycld2_top_lang}') 与特征检测结果 "
                f"({other_feature_matches}) 冲突。将惩罚pycld2的置信度。"
            )
            # 大幅降低pycld2首选结果的置信度
            main_results[0]["prob"] *= 0.05  # 惩罚因子
            # 重新排序
            main_results.sort(key=lambda x: x["prob"], reverse=True)
            logger.debug(f"[{current_thread_name}] 惩罚后pycld2结果: {main_results}")


    combined_results = combine_detection_results(
        main_results, feature_results, prob_weight, feature_weight
    )
    logger.debug(f"[{current_thread_name}] 结合后结果: {combined_results}")

    # 应用提示偏置
    if hint_lang and hint_bias > 0:
        logger.debug(
            f"[{current_thread_name}] 应用提示偏置: {hint_lang}, 偏置值: {hint_bias}"
        )
        combined_results = apply_hint_bias(combined_results, hint_lang, hint_bias)
        logger.debug(f"[{current_thread_name}] 应用偏置后结果: {combined_results}")

    # 检查歧义并返回结果
    if not combined_results:
        logger.warning(f"[{current_thread_name}] 语言检测失败：没有检测结果")
        return "unknown"

    # 如果存在歧义，使用通用决策逻辑
    if check_language_ambiguity(combined_results, ambiguity_factor):
        logger.warning(
            f"[{current_thread_name}] 检测到语言歧义，前两名: {combined_results[:2]}"
        )

    final_result = combined_results[0]["lang"]
    logger.debug(
        f"[{current_thread_name}] 最终检测结果: {final_result}, 置信度: {combined_results[0]['prob']:.3f}"
    )
    return final_result


class LanguageDetector:
    """包装 detect_language_with_cache 的轻量级类，保持旧接口兼容。"""

    def __init__(
        self, mode_config: Optional[Dict[str, Any]] = None, config: Optional[Any] = None
    ):
        self.mode_config = mode_config or {}
        self.config = config
        self.supported_langs: Dict[str, List[str]] = self.mode_config.get(
            "supported_langs", {}
        )
        self.language_features: Dict[str, Dict[str, List[str]]] = self.mode_config.get(
            "language_features", {}
        )
        # 使用全局预编译的模式
        self._compiled_patterns = COMPILED_PATTERNS

    def detect(self, text: str, hint_lang: Optional[str] = None) -> str:
        return detect_language_with_cache(
            text,
            hint_lang,
            self.supported_langs,
            self.language_features,
            self.config,
            self._compiled_patterns,  # 传递编译后的模式
        )

    def __call__(self, text: str, hint_lang: Optional[str] = None) -> str:  # noqa: D401
        return self.detect(text, hint_lang)


# ---------------------------------------------------------------------------
# 缓存管理
# ---------------------------------------------------------------------------

_language_detection_cache_lock = threading.Lock()  # 为全局缓存添加锁


def _add_to_language_cache(key: str, value: tuple[str, float], cache_size: int) -> None:
    """线程安全地添加语言检测结果到缓存"""
    with _language_detection_cache_lock:
        if len(language_detection_cache) >= cache_size:
            # OrderedDict.popitem(last=False) 移除最先插入的（最旧的）项
            language_detection_cache.popitem(last=False)
            logger.debug(
                f"语言检测缓存已满，移除最旧项，当前大小: {len(language_detection_cache)}"
            )
        language_detection_cache[key] = value
        logger.debug(f"语言检测结果已缓存，缓存大小: {len(language_detection_cache)}")


def _get_from_language_cache(key: str) -> Optional[str]:
    """线程安全地从语言检测缓存获取结果"""
    with _language_detection_cache_lock:
        entry = language_detection_cache.get(key)
        if entry:
            # 实现LRU的关键：将访问的条目移到末尾，标记为“最近使用”
            language_detection_cache.move_to_end(key)
            return entry[0]
        return None


# ---------------------------------------------------------------------------
# 语言检测核心逻辑
# ---------------------------------------------------------------------------
_initialize_patterns()
