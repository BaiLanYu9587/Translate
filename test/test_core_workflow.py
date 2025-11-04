import pytest
import yaml
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Any, cast
import logging

from core.config_management import Config
from core.main import TranslatorInterface
from core.logging_config import LoggingManager


@pytest.fixture
def default_config_dict() -> dict[str, Any]:
    """提供一个基础的、有效的默认配置字典"""
    return cast(
        dict[str, Any],
        yaml.safe_load("""
translation_mode: 1
max_text_length: 500
context_max_count: 10
short_text_threshold: 10
lang_detection_threshold: 0.9
thread_pool_max_workers: 4
tcp_connector:
  limit: 15
timeout:
  total: 18
network_check:
  hosts:
    - 8.8.8.8
api_health_check:
  timeout_total: 10
request_min_interval: 1.0
retry_config:
  attempts: 1
  min_delay: 1
  max_delay: 10
  backoff_factor: 2
proxy:
  enabled: false
debug_mode: false
logging:
  info_max: 100
  other_max: 100
  cleanup_interval: 2.0
log_max_bytes: 2097152
log_backup_count: 3
cache_hit_log_interval: 10
cache_key_display_length: 20
show_gui_progress: true
gui_theme:
  background: "#ffffff"
gui_progress:
  window_width: 25
keyboard_listener:
  space_trigger_count: 3
common_symbols: "[]"
illegal_chars: "[]"
language_detection_cache_size: 300
same_language_match_threshold: 0.5
use_local_cache: true
local_cache_path: "data/translation_cache.db"
cache_max_entries: 2000
cache_write_delay: 0.8
cache_batch_size: 300
cache_auto_save: true
cache_cleanup_threshold: 0.8
chat_context_cleanup_days: 3
cache_cleanup_interval_hours: 1
language_detection:
  ambiguity_factor: 1.4
translation_quality:
  similarity_short_text_threshold: 100
"""),
    )


@pytest.fixture
def mock_config(default_config_dict: dict[str, Any]) -> Config:
    """创建一个有效的、经过验证的 Config 对象"""
    return Config.model_validate(default_config_dict)


def test_config_loading_and_validation(mock_config: Config) -> None:
    """测试配置是否能被成功加载和验证"""
    assert mock_config is not None
    assert isinstance(mock_config, Config)
    assert mock_config.translation_mode == 1
    assert mock_config.logging.info_max == 100
    assert mock_config.debug_mode is False


def test_logging_initialization(mock_config: Config) -> None:
    """测试日志系统是否能用新的Config模型成功初始化"""
    with patch("core.config_management.get_logs_dir", return_value="logs"):
        LoggingManager.initialize(mock_config)
        root_logger = LoggingManager.get_root_logger()
        assert root_logger is not None
        expected_level = "DEBUG" if mock_config.debug_mode else "INFO"
        assert logging.getLevelName(root_logger.level) == expected_level
        # 重置以避免影响其他测试
        LoggingManager._initialized = False


@pytest.mark.asyncio
async def test_simplified_translation_flow(mock_config: Config) -> None:
    """测试一个简化的端到端翻译流程"""
    mock_translation_engine = MagicMock()
    mock_translation_engine.translate_text_async = AsyncMock(
        return_value=("Translated Text", "api", {})
    )

    with (
        patch("core.main.pyperclip.paste", return_value="Hello World"),
        patch("core.main.pyperclip.copy") as mock_copy,
        patch("core.main.get_active_window_title", return_value="Test Window"),
        patch("core.main.ContextManager") as mock_context_manager_class,
        patch("core.main.pyautogui.hotkey"),
    ):
        mock_context_instance = mock_context_manager_class.return_value
        mock_context_instance.load_context_with_direction = AsyncMock(return_value=[])

        translator_interface = TranslatorInterface(
            config=mock_config,
            translation_engine=mock_translation_engine,
            gui_handler=MagicMock(),
            loop=MagicMock(),
        )

        await translator_interface.replacement_translation()

        mock_translation_engine.translate_text_async.assert_awaited_once_with(
            "Hello World", translator_interface.gui_handler
        )
        mock_copy.assert_called_once_with("Translated Text")


@pytest.mark.asyncio
async def test_window_title_failure_fallback(mock_config: Config) -> None:
    """测试当获取窗口标题失败时，系统能否优雅地回退"""
    mock_translation_engine = MagicMock()
    mock_translation_engine.translate_text_async = AsyncMock(
        return_value=("Translated Text", "api", {})
    )

    with (
        patch("core.main.pyperclip.paste", return_value="Some Text"),
        patch("core.main.pyperclip.copy"),
        patch(
            "core.main.get_active_window_title",
            side_effect=Exception("Window access error"),
        ),
        patch("core.main.ContextManager") as mock_context_manager_class,
        patch("core.main.pyautogui.hotkey"),
    ):
        mock_context_instance = mock_context_manager_class.return_value
        mock_context_instance.load_context_with_direction = AsyncMock(return_value=[])

        translator_interface = TranslatorInterface(
            config=mock_config,
            translation_engine=mock_translation_engine,
            gui_handler=MagicMock(),
            loop=MagicMock(),
        )

        await translator_interface.replacement_translation()

        mock_context_instance.load_context_with_direction.assert_awaited_once_with(
            "unknown_window"
        )
