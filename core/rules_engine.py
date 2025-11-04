"""
规则引擎模块
用于处理语言规则、匹配最佳规则等
"""

import logging
from typing import Any, Dict, Optional, cast

logger = logging.getLogger(__name__)


def get_language_group(
    lang_code: Optional[str], groups: Dict[str, Any]
) -> Optional[str]:
    """根据语言代码查找其所属的语言组"""
    if not lang_code or not groups:
        return None
    for group_name, group_data in groups.items():
        if isinstance(group_data, dict) and lang_code in group_data.get(
            "languages", []
        ):
            return group_name
    return None


def find_best_matching_rule(
    source_lang: Optional[str],
    target_lang: Optional[str],
    source_group: Optional[str],
    target_group: Optional[str],
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    """
    根据语言和语言组查找最匹配的特殊语言对规则。
    通过合并通用规则和特定规则，确保返回的规则集是完整的。
    """
    base_rule = rules.get("*-*", {}).copy()
    logger.debug(f"加载基础规则 '*-*': {base_rule}")

    if not source_lang or not target_lang:
        logger.debug("源语言或目标语言为空，直接返回基础规则。")
        return cast(Dict[str, Any], base_rule)

    potential_keys = []
    # 级别1: 精确语言对
    potential_keys.append(f"{source_lang}-{target_lang}")
    potential_keys.append(f"{target_lang}-{source_lang}")

    # 级别2: 语言组对
    if source_group and target_group:
        potential_keys.append(f"{source_group}-{target_group}")
        potential_keys.append(f"{target_group}-{source_group}")

    # 级别3: 单边语言通配符
    potential_keys.append(f"{source_lang}-*")
    potential_keys.append(f"*-{target_lang}")

    # 级别4: 组-通配符
    if source_group:
        potential_keys.append(f"{source_group}-*")
    if target_group:
        potential_keys.append(f"*-{target_group}")

    logger.debug(f"规则查找顺序: {potential_keys}")

    specific_rule = {}
    found_key = None
    for key in potential_keys:
        if key in rules:
            specific_rule = rules[key]
            found_key = key
            logger.debug(f"找到匹配的特定规则: '{key}' -> {specific_rule}")
            break

    if not found_key:
        logger.debug("未找到特定语言对规则，将仅使用基础规则。")

    base_rule.update(specific_rule)
    logger.debug(f"最终合并后的规则: {base_rule}")
    return cast(Dict[str, Any], base_rule)
