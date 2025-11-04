import logging
import re
from typing import Dict, Any, List, Tuple
from .constants import UNIVERSAL_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class PromptBuilder:
    def __init__(self, config: Any, mode_config: Dict[str, Any]):
        self.config = config
        self.mode_config = mode_config

    def build_translation_prompt(
        self,
        original_text: str,
        detected_lang: str,
        target_lang_code: str,
        context_history: List[Tuple[str, str, str]],
    ) -> Tuple[str, str]:
        """构建翻译提示词

        Args:
            original_text: 原文
            detected_lang: 检测到的源语言
            target_lang_code: 目标语言代码
            context_history: 上下文历史

        Returns:
            Tuple[str, str]: 构建的提示词和翻译方向
        """
        # 获取当前翻译模式的配置信息
        mode_id = getattr(self.config, "translation_mode", 1)
        translation_modes = self.mode_config.get("translation_modes", {})
        mode_info = translation_modes.get(mode_id, {})

        # 提前从模式配置中读取所有需要的语言信息
        mode_source_code = mode_info.get("source_code", "zh")
        mode_target_code = mode_info.get("target_code", "en")
        mode_source_lang_en = mode_info.get("source_lang_en", "Chinese")
        mode_target_lang_en = mode_info.get("target_lang_en", "English")
        default_lang_code = mode_info.get("default_lang", mode_target_code)
        default_lang_en = mode_info.get("default_lang_en", mode_target_lang_en)

        # 根据检测到的语言，场景化地确定实际的翻译方向和语言名称
        if detected_lang == mode_source_code:
            # 场景一：正向翻译 (例如，检测到中文，模式是中->英)
            actual_source_code = mode_source_code
            actual_target_code = mode_target_code
            source_lang_name_en = mode_source_lang_en
            target_lang_name_en = mode_target_lang_en
        elif detected_lang == mode_target_code:
            # 场景二：反向翻译 (例如，检测到英文，模式是中->英)
            actual_source_code = mode_target_code
            actual_target_code = mode_source_code
            source_lang_name_en = mode_target_lang_en
            target_lang_name_en = mode_source_lang_en
        else:
            # 场景三：未知语言翻译 (例如，检测到法文，模式是中->英)
            actual_source_code = detected_lang
            actual_target_code = default_lang_code
            source_lang_name_en = detected_lang  # 未知语言，直接使用其代码
            target_lang_name_en = default_lang_en

        # 记录实际的翻译方向，便于调试
        logger.debug(
            f"实际翻译方向: {source_lang_name_en} -> {target_lang_name_en} (检测到: {detected_lang}, 目标: {target_lang_code})"
        )

        # 获取风格指令
        style_instruction = mode_info.get("style", "")
        if style_instruction:
            style_instruction = f", Use {style_instruction} Language Style"

        # 获取语气词信息
        tone_particles_config = self.mode_config.get("tone_particles", {})

        def get_all_tones_as_regex(lang_code: str) -> str:
            """从配置中获取指定语言的所有语气词，并合并成一个正则表达式字符串。"""
            lang_tones = tone_particles_config.get(lang_code, {})
            all_tones = []
            if isinstance(lang_tones, dict):
                for category, words in lang_tones.items():
                    if isinstance(words, list):
                        all_tones.extend(words)

            if not all_tones:
                return ""

            # 使用 re.escape 确保特殊字符被正确处理，然后用 | 连接
            return "|".join(re.escape(word) for word in all_tones)

        actual_source_tone = get_all_tones_as_regex(actual_source_code)
        actual_target_tone = get_all_tones_as_regex(actual_target_code)

        # 构建上下文部分
        history_part = ""
        if context_history:
            history_lines = []
            max_context = getattr(self.config, "context_max_count", 6)
            for i, (orig, trans, direction) in enumerate(
                context_history[-max_context:], 1
            ):
                if direction == "ME→Counterpart":
                    orig_lang = mode_source_code
                    trans_lang = mode_target_code
                else:  # Assumes "Counterpart→ME"
                    orig_lang = mode_target_code
                    trans_lang = mode_source_code

                history_lines.append(
                    f'  <dialogue index="{i}" direction="{direction}">\n'
                    f'    <original language="{orig_lang}">{orig}</original>\n'
                    f'    <translation language="{trans_lang}">{trans}</translation>\n'
                    "  </dialogue>"
                )
            history_part = "\n".join(history_lines)

        # 根据翻译方向确定对话角色
        if detected_lang == mode_source_code:
            # 用户输入的是源语言，说明是“我”在发送消息
            direction_role = "ME→Counterpart"
        elif detected_lang == mode_target_code:
            # 用户输入的是目标语言，说明是收到了“对方”的消息
            direction_role = "Counterpart→ME"
        else:
            # 对于未知语言
            direction_role = "Unknown"

        # 构建主要指令部分（使用英语）
        dialogue_direction = (
            f"{source_lang_name_en} to {target_lang_name_en} conversation"
        )

        # 使用通用提示词模板，并填充所有占位符
        prompt = UNIVERSAL_PROMPT_TEMPLATE.format(
            input_lang=source_lang_name_en,
            output_lang=target_lang_name_en,
            dialogue_direction=dialogue_direction,
            style_instruction=style_instruction,
            default_lang=target_lang_name_en,
            actual_source_tone=actual_source_tone,
            actual_target_tone=actual_target_tone,
            dialogue_history=history_part,
            direction_role=direction_role.replace("→", " to "),
            original_text=original_text,
        )

        # 记录完整的提示词到日志，方便排查错误
        logger.debug(f"构建的完整提示词:{prompt}")

        return prompt, direction_role
