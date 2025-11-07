import os
import sys
import threading
import logging
import yaml  # type: ignore[import-untyped]
from ruamel.yaml import YAML  # type: ignore[import-untyped]
from ruamel.yaml.scalarstring import PreservedScalarString  # type: ignore[import-untyped]
from typing import Dict, Any, Union, Optional, TypeVar, overload
import io
from functools import lru_cache
from pydantic import BaseModel, Field  # type: ignore[import-untyped]
from pydantic.root_model import RootModel  # type: ignore[import-untyped]

_T = TypeVar("_T")

logger = logging.getLogger(__name__)


def _find_project_root(start_dir: str, marker: str = "pyproject.toml") -> Optional[str]:
    """向上遍历目录以查找项目根目录（由标记文件标识）"""
    path = start_dir
    while True:
        if os.path.exists(os.path.join(path, marker)):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


@lru_cache(maxsize=1)
def get_application_path() -> str:
    """获取应用程序根目录，提供一个确定的、可预测的路径。

    优先级顺序:
    1. PyInstaller 环境: 可执行文件所在目录。
    2. 脚本启动环境 (`start.py`): `start.py` 所在目录。
    3. 项目环境: 向上查找 `pyproject.toml` 所在的目录。
    4. 回退: 当前文件所在目录的上级目录。

    如果所有方法都失败，将引发 RuntimeError，而不是回退到不稳定的CWD。
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_path = os.path.dirname(sys.executable)
        logger.info(f"检测到 PyInstaller 打包环境，应用路径: {base_path}")
        return base_path

    try:
        import __main__

        if hasattr(__main__, "__file__") and __main__.__file__:
            main_file = os.path.abspath(__main__.__file__)
            if os.path.basename(main_file) == "start.py":
                base_path = os.path.dirname(main_file)
                logger.info(f"从 start.py 启动，应用路径: {base_path}")
                return base_path
    except (ImportError, AttributeError):
        pass

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = _find_project_root(current_dir)
    if project_root:
        logger.info(f"通过 pyproject.toml 找到项目根目录: {project_root}")
        return project_root

    fallback_path = os.path.dirname(current_dir)
    logger.warning(
        f"未能通过标准方法确定应用路径，回退到基于文件结构的路径: {fallback_path}"
    )
    return fallback_path


def is_path_writable(path: str) -> bool:
    """检查路径是否可写，使用唯一的临时文件名以避免并发问题。"""
    dir_path = os.path.dirname(path) or "."
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
        except (OSError, PermissionError):
            return False

    try:
        test_filename = f"_write_test_{os.getpid()}_{threading.get_ident()}.tmp"
        test_file = os.path.join(dir_path, test_filename)
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return True
    except (OSError, PermissionError):
        return False


class DirectoryManager:
    """统一的目录管理器"""

    def __init__(self) -> None:
        self.app_root = get_application_path()
        # 延迟初始化目录，只有在需要时才创建
        self._config_dir: Optional[str] = None
        self._data_dir: Optional[str] = None
        self._logs_dir: Optional[str] = None
        self._chat_contexts_dir: Optional[str] = None

    def _determine_and_prepare_path(self, dir_name: str) -> str:
        """确定、创建并返回一个目录的最终路径，处理权限和回退。"""
        primary_path = os.path.join(self.app_root, dir_name)

        # 检查主目录路径是否存在且可写
        if os.path.exists(primary_path):
            if is_path_writable(primary_path):
                logger.debug(f"主目录已存在且可写: {primary_path}")
                return primary_path
        else:
            # 主目录不存在，检查父目录是否可写
            parent_dir = os.path.dirname(primary_path)
            if parent_dir and os.access(parent_dir, os.W_OK):
                try:
                    os.makedirs(primary_path, exist_ok=True)
                    logger.debug(f"成功创建主目录: {primary_path}")
                    return primary_path
                except (OSError, PermissionError) as e:
                    logger.warning(f"无法创建主目录 {primary_path}: {e}")

        # 主目录不可用，尝试回退目录
        user_home = os.path.expanduser("~")
        fallback_base_dir = os.path.join(user_home, ".multitranslator")
        fallback_path = os.path.join(fallback_base_dir, dir_name)

        logger.warning(f"主目录 {primary_path} 不可用，尝试回退到: {fallback_path}")

        try:
            # 确保回退目录的父目录存在
            os.makedirs(os.path.dirname(fallback_path), exist_ok=True)

            if not os.path.exists(fallback_path):
                os.makedirs(fallback_path, exist_ok=True)

            if is_path_writable(fallback_path):
                logger.info(f"成功使用回退目录: {fallback_path}")
                return fallback_path
            else:
                raise OSError("回退目录不可写。")
        except Exception as e:
            logger.critical(
                f"无法创建主目录或回退目录 {fallback_path}: {e}", exc_info=True
            )
            raise RuntimeError(f"无法初始化应用目录 '{dir_name}'。请检查权限。") from e

    def get_config_dir(self) -> str:
        if self._config_dir is None:
            self._config_dir = self._determine_and_prepare_path("config")
        return self._config_dir

    def get_data_dir(self) -> str:
        if self._data_dir is None:
            self._data_dir = self._determine_and_prepare_path("data")
        return self._data_dir

    def get_logs_dir(self) -> str:
        if self._logs_dir is None:
            self._logs_dir = self._determine_and_prepare_path("logs")
        return self._logs_dir

    def get_chat_contexts_dir(self) -> str:
        if self._chat_contexts_dir is None:
            self._chat_contexts_dir = self._determine_and_prepare_path("chat_contexts")
        return self._chat_contexts_dir

    def get_config_file_path(self) -> str:
        return os.path.join(self.get_config_dir(), "config.yaml")

    def get_mode_config_file_path(self) -> str:
        return os.path.join(self.get_config_dir(), "mode_config.yaml")

    def get_models_config_file_path(self) -> str:
        return os.path.join(self.get_config_dir(), "models.yaml")

    def get_log_file_path(self) -> str:
        return os.path.join(self.get_logs_dir(), "app.log")

    def get_cache_file_path(self) -> str:
        return os.path.join(self.get_data_dir(), "translation_cache.db")


# 使用锁确保线程安全
_manager_lock = threading.Lock()
_directory_manager_instance: Optional[DirectoryManager] = None


def get_directory_manager() -> DirectoryManager:
    """获取 DirectoryManager 的单例实例，实现延迟初始化。"""
    global _directory_manager_instance
    if _directory_manager_instance is None:
        with _manager_lock:
            if _directory_manager_instance is None:
                _directory_manager_instance = DirectoryManager()
    return _directory_manager_instance


def get_data_dir() -> str:
    return get_directory_manager().get_data_dir()


def get_logs_dir() -> str:
    return get_directory_manager().get_logs_dir()


def get_chat_contexts_dir() -> str:
    return get_directory_manager().get_chat_contexts_dir()


def get_config_file_path() -> str:
    return get_directory_manager().get_config_file_path()


def get_mode_config_file_path() -> str:
    return get_directory_manager().get_mode_config_file_path()


def get_models_config_file_path() -> str:
    """获取 models.yaml 配置文件的路径。"""
    return get_directory_manager().get_models_config_file_path()


def get_cache_file_path() -> str:
    return get_directory_manager().get_cache_file_path()


# 移除模块级别的常量初始化，改为函数调用
# CONFIG_FILE = get_config_file_path()
# MODE_CONFIG_FILE = get_mode_config_file_path()
# MODELS_CONFIG_FILE = get_models_config_file_path()

DEFAULT_CONFIG_TEXT = """
# 翻译程序主配置文件

# 翻译行为配置
translation_mode: 1 # 默认翻译模式编号，对应 mode_config.yaml 中的模式
max_text_length: 500 # 最大翻译文本长度（字符数），超过此长度将拒绝翻译
context_max_count: 10 # 上下文最大数量
short_text_threshold: 10 # 短文本阈值
lang_detection_threshold: 0.9 # 语言检测置信度阈值
thread_pool_max_workers: 4 # 翻译引擎线程池最大工作线程数

# 网络和请求配置
# TCP连接设置
tcp_connector:
  limit: 15                    # 连接池最大连接数
  ttl_dns_cache: 600          # DNS缓存时间(秒)
  keepalive_timeout: 20       # 长连接保持时间(秒)
  force_close: false          # 是否强制关闭连接
  enable_cleanup_closed: true # 是否启用清理已关闭连接
  ssl_verify: true            # 是否验证SSL证书
  ssl_check_hostname: true    # 是否验证SSL证书主机名
  limit_per_host: 8           # 每个主机的最大连接数
  use_dns_cache: true         # 是否使用DNS缓存
  min_tls_version: "TLSv1_2"  # 最小TLS版本
  ciphers: "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384:DHE-RSA-CHACHA20-POLY1305" # 支持的加密套件

# 超时设置（秒）
timeout:
  total: 18                   # 总超时时间
  connect: 3                  # 连接超时时间
  sock_connect: 3             # Socket连接超时时间
  sock_read: 15               # Socket读取超时时间

# 网络检查设置
network_check:
  hosts:
    - 8.8.8.8                 # Google DNS
    - 1.1.1.1                 # Cloudflare DNS
    - 9.9.9.9                 # Quad9 DNS
  port: 53                    # DNS端口
  timeout: 0.5                # 网络检查超时时间(秒)
  interval: 5                 # 网络检查间隔(秒)
  https_timeout: 1.0          # HTTPS检查超时时间(秒)

# API健康检查设置
api_health_check:
  timeout_total: 10           # API健康检查总超时时间(秒)
  timeout_connect: 15          # API连接超时时间(秒)
  timeout_sock_connect: 5     # API Socket连接超时时间(秒)
  timeout_sock_read: 8        # API Socket读取超时时间(秒)
  startup_check_timeout: 20   # 启动时API健康检查总超时时间(秒)
  console_check_timeout: 60   # 控制台API健康检查总超时时间(秒)
  test_prompt: "Hello, API check" # API健康检查测试提示词
  cache_lifetime: 300.0       # API健康检查缓存有效期(秒)

# 网络配置
request_min_interval: 1.0     # API请求最小间隔时间(秒)，防止请求过频

# 重试机制配置
retry_config:
  attempts: 1                 # 每个API模型的最大尝试次数 (1表示不重试)
  min_delay: 1                # 重试之间的最小延迟(秒)
  max_delay: 10               # 重试之间的最大延迟(秒)
  backoff_factor: 2           # 退避因子，用于指数增长延迟

# 代理配置 - 用于在网络环境受限时访问API
proxy:
    enabled: false             # 是否启用代理
    url: ""                    # 代理服务器地址，例如: "http://proxy.example.com:8080"
    username: ""               # 代理用户名
    password: ""               # 代理密码

# 日志和调试配置
debug_mode: false             # 是否启用调试模式
log_max_bytes: 2097152        # 单个日志文件最大大小（字节）
log_backup_count: 3           # 保留的日志文件备份数量
cache_hit_log_interval: 10    # 缓存命中日志记录间隔（秒）
cache_key_display_length: 20  # 缓存键显示长度

# 日志配置
logging:
  info_max: 100               # INFO日志最大条目数
  other_max: 100              # 其他日志最大条目数
  cleanup_interval: 2.0       # 日志清理间隔(秒)

# GUI 配置
show_gui_progress: true       # 是否显示GUI进度条

# GUI 主题配置
gui_theme:
  background: "#ffffff"       # 背景颜色
  text: "#333333"             # 主要文字颜色
  secondary_text: "#666666"   # 次要文字颜色
  accent: "#4a86e8"          # 强调色
  success: "#2ecc71"         # 成功状态颜色
  error: "#e74c3c"           # 错误状态颜色
  border: "#dddddd"          # 边框颜色

# GUI 圆圈进度条配置
gui_progress:
  window_width: 25            # 进度条窗口宽度
  window_height: 25           # 进度条窗口高度
  circle_radius: 5            # 圆圈半径
  circle_width: 3             # 圆圈线条宽度
  animation_interval: 80      # 动画间隔时间(毫秒)

# 键盘监听配置
keyboard_listener:
  space_trigger_count: 3      # 触发翻译所需的空格键次数
  space_trigger_timeout: 1.0  # 空格键触发超时时间(秒)
  space_trigger_cooldown: 2.0 # 触发后的冷却时间(秒)
  mouse_top_exclusion_zone: 50 # 鼠标顶部排除区域(像素)

# 文本过滤配置
# 这些配置用于清理和标准化输入文本，确保翻译质量
common_symbols: '[''"`(),.!?;:<>+*/=^&@#$%~|_€£¥\\[\\]\\{\\}\\\\。，、！？；：—…·‘’“”（）【】《》〈〉「」『』～￥-]'  # 常见标点符号，用于文本清理
illegal_chars: '[\\uE000-\\uF8FF\\uFFFD\\uFEFF\\u200B-\\u200D\\u2028\\u2029\\uFFF9-\\uFFFB]'  # 非法Unicode字符，用于过滤无用字符

# 语言检测和翻译配置
# 这些配置控制语言检测、翻译缓存和重试机制
language_detection_cache_size: 300  # 语言检测缓存大小
same_language_match_threshold: 0.5  # 同语言匹配阈值，用于检测是否为相同语言

# 本地缓存配置
# 缓存系统配置，优化翻译性能和存储管理
use_local_cache: true  # 是否使用本地缓存
local_cache_path: "data/translation_cache.db"  # 缓存数据库文件路径
cache_max_entries: 2000  # 缓存最大条目数
cache_write_delay: 0.8  # 缓存写入延迟（秒）
cache_batch_size: 300  # 缓存批处理大小
cache_auto_save: true  # 是否自动保存缓存
cache_cleanup_threshold: 0.8  # 缓存清理阈值（达到此比例时触发清理）
chat_context_cleanup_days: 3  # 聊天上下文清理天数
cache_cleanup_interval_hours: 1  # 缓存清理间隔（小时）

# 语言检测和消歧配置
# 控制语言检测的敏感度和准确性参数
language_detection:
   ambiguity_factor: 1.4  # 语言歧义因子，影响检测的保守程度
   hint_bias: 0.2  # 提示偏置，语言提示对检测结果的影响程度
   prob_weight: 0.7  # 概率权重
   feature_weight: 0.3  # 特征权重
   short_text_prob_weight: 0.4  # 短文本概率权重
   short_text_feature_weight: 0.6  # 短文本特征权重
   min_char_threshold: 10  # 最小字符阈值，低于此值不进行检测
   cache_size: 300  # 语言检测缓存大小

# 翻译质量和文本分析配置
translation_quality:
  similarity_short_text_threshold: 100
  similarity_ngram_size: 3
  similarity_fallback_ngram_size: 2
  cross_lang_high_similarity_threshold: 0.7
  context_aware_similarity_threshold: 0.8
  min_translation_length_diff: 5
  effort_score_threshold: 0.5
  quality_score_thresholds:
    poor: 0.65
    average: 0.85
    good: 1.0
  quality_issue_count_thresholds:
    poor: 3
    average: 1
  word_repetition_min_words: 10
  word_repetition_ratio_threshold: 0.3
  word_repetition_min_count: 3
  non_target_char_ratio_threshold: 0.2
  source_char_ratio_threshold: 0.05
  penalties:
    length_mismatch: 0.6  # 长度严重不符时的分数乘数
    repetition: 0.5       # 内容重复时的分数乘数
    residue: 0.4          # 语言残留时的分数乘数

"""

DEFAULT_MODELS_CONFIG_TEXT = """
# -----------------------------------------------------------------------------
# API 模型配置文件 (models.yaml)
#
# 本文件用于配置翻译服务所使用的所有API提供商、模型及其参数。
#
# - 动态提供商加载: 任何以 "_provider" 结尾的顶级键都会被自动识别为一个API提供商。
#   例如: my_custom_provider, openrouter_provider, groq_provider 等。
#
# - `api_mode`: 指定提供商类型，必须是 "gemini" 或 "openai"。
# - `api_key`: 必须是使用API密钥工具加密后的密钥。如果为空，则禁用该提供商。
# - `api_base`: API的URL端点。对于OpenAI兼容模式是必需的。
# - `models`: 提供商下的模型列表，程序会按顺序尝试使用。
# -----------------------------------------------------------------------------

# --- Gemini API 配置 ---
gemini_provider:
  api_mode: "gemini"
  api_key: ""  # <-- 在此粘贴加密后的Gemini API密钥
  api_base: "https://generativelanguage.googleapis.com"
  # (可选) API版本, 默认为 v1beta
  api_version: "v1beta"
  
  models:
    - model_id: "models/gemini-2.5-flash-lite"
      params:
        temperature: 0.75
        topP: 0.92

    - model_id: "models/gemini-2.5-flash"
      params:
        temperature: 0.75
        topP: 0.92

# --- Groq API 配置 (作为另一个OpenAI兼容提供商) ---
groq_provider:
  api_mode: "openai"
  api_key: ""
  api_base: "https://api.groq.com/openai/v1/chat/completions"
  models:
    - model_id: "moonshotai/kimi-k2-instruct-0905"
      params:
        temperature: 0.75
        topP: 0.92


# --- 自定义OpenAI兼容提供商示例 (OpenRouter) ---
# 您可以复制此块并修改提供商名称 (如 `another_provider`) 来添加更多提供商。
openrouter_provider:
  # API模式，对于OpenRouter, Groq, DeepSeek等应设置为 "openai"
  api_mode: "openai"
  # 加密后的API密钥。
  api_key: ""  # <-- 在此粘贴加密后的API密钥
  # API基础URL (必需)
  api_base: "https://openrouter.ai/api/v1/chat/completions"
  
  # 模型列表 (按顺序尝试)
  models:
    - model_id: "openrouter/sonoma-sky-alpha"
      params:
        temperature: 0.75
        topP: 0.92



# --- Anthropic API 配置 ---
anthropic_provider:
  api_mode: "anthropic"
  api_key: ""  # <-- 在此粘贴加密后的Anthropic API密钥
  # 对于Anthropic，api_base通常是固定的，但如果需要可以覆盖
  # api_base: "https://api.anthropic.com/v1/messages"
  models:
    - model_id: "claude-sonnet-4-20250514"
      params:
        temperature: 0.75
        topP: 0.92
"""
DEFAULT_MODE_CONFIG_TEXT = """
# 语言模式配置文件

# 语气助词配置
tone_particles:
  zh:
    joy: ["哈", "哈哈", "嘻嘻", "嘿嘿", "好耶", "太棒了", "开心", "真好", "绝了", "芜湖", "起飞"]
    anger: ["哼", "切", "怒", "可恶", "气死我了", "草", "我靠", "妈的", "滚"]
    sadness: ["呜", "呜呜呜", "泪目", "难过", "伤心", "唉", "嗐", "麻了"]
    surprise: ["哇", "呀", "哟", "哇塞", "咦", "欸", "哎呀", "哎哟", "我趣"]
    neutral: ["嗯", "哦", "嘛", "吧", "呢", "啦", "呵", "呸", "哎", "啧", "啧啧", "呃", "额", "啊对对对"]
  en:
    joy: ["lol", "lmao", "rofl", "haha", "hehe", "yay", "awesome", "cool", "great", "lit", "dope", "sick"]
    anger: ["grr", "ugh", "furious", "annoyed", "damn", "hell", "pissed", "screw you"]
    sadness: ["sigh", "sad", "crying", "alas", "bummer"]
    surprise: ["omg", "wow", "oops", "gee", "holy cow", "no way"]
    neutral: ["yeah", "duh", "meh", "smh", "tsk", "ew", "nah", "whatever", "bruh", "welp"]
  ja:
    joy: ["w", "ww", "www", "笑", "草", "（笑）", "やったー", "最高", "うれしい", "神", "マジ卍"]
    anger: ["ちっ", "むかつく", "うざい", "おこ", "キレそう", "くそ", "ふざけんな"]
    sadness: ["はぁ", "ふぅ", "悲しい", "泣ける", "ぴえん"]
    surprise: ["えっ", "あっ", "まじ", "えー", "は?", "嘘"]
    neutral: ["乙", "うぽつ", "うーん", "ふーん", "まあ", "なるほど"]
  ko:
    joy: ["ㅋ", "ㅋㅋ", "ㅎ", "ㅎㅎ", "헤", "아싸", "대박", "짱", "오예", "개꿀"]
    anger: ["ㅡㅡ", "화나", "빡쳐", "짜증나", "미쳤어", "아오", "씨발", "개빡치네"]
    sadness: ["ㅜ", "ㅠㅠ", "슬퍼", "슬프다", "아쉽다"]
    surprise: ["헐", "헉", "대박", "진짜?"]
    neutral: ["아", "네", "음", "글쎄", "흠", "에휴", "으", "쯧", "쯧쯧", "하", "허"]
  de:
    joy: ["haha", "hehe", "toll", "super", "geil", "spitze"]
    anger: ["grr", "wütend", "sauer", "genervt", "verdammt", "scheiße"]
    sadness: ["seufz", "traurig", "schnief", "ach je"]
    surprise: ["oha", "ach", "wow", "echt?", "krass"]
    neutral: ["ne", "ja", "doch", "mal", "naja", "schon", "halt", "tja", "pff", "hm", "achso"]
  fr:
    joy: ["lol", "mdr", "ptdr", "haha", "génial", "super", "cool", "nickel"]
    anger: ["pff", "fâché", "énervé", "merde", "putain", "ça suffit"]
    sadness: ["soupir", "triste", "mince", "zut"]
    surprise: ["oh", "ah", "ouah", "la vache", "c'est pas vrai"]
    neutral: ["hein", "quoi", "eh bien", "ben", "ouais", "bah", "bof", "tss", "oups"]
  es:
    joy: ["jaja", "jeje", "genial", "guay", "chévere", "qué bueno"]
    anger: ["grr", "enfadado", "enojado", "molesto", "joder", "mierda", "coño"]
    sadness: ["suspiro", "triste", "qué pena"]
    surprise: ["dios", "guau", "ay", "ostia", "no me digas"]
    neutral: ["eh", "pues", "vale", "no", "bueno", "venga", "uff", "pff", "bah", "ajá", "oye", "hmm"]
  it:
    joy: ["haha", "hehe", "grande", "figo", "bello", "che figata"]
    anger: ["grr", "arrabbiato", "infastidito", "cazzo", "merda"]
    sadness: ["sospiro", "triste", "peccato", "uffa"]
    surprise: ["oddio", "wow", "ops", "caspita", "davvero?"]
    neutral: ["eh", "beh", "dai", "cioè", "uff", "mah", "bah", "tsk", "eh già", "boh", "vabbè"]
  pt:
    joy: ["haha", "hehe", "rsrs", "kkk", "legal", "massa", "daora", "show"]
    anger: ["grr", "bravo", "irritado", "nervoso", "porra", "merda", "caralho"]
    sadness: ["suspiro", "triste", "que pena"]
    surprise: ["mds", "nossa", "opa", "eita", "caraca"]
    neutral: ["né", "pois", "então", "ué", "aff", "pff", "tsc", "bah"]
  ru:
    joy: ["хаха", "хехе", "круто", "супер", "класс", "отлично"]
    anger: ["злой", "бесит", "раздражает", "блин", "черт", "сука"]
    sadness: ["эх", "эхх", "грустно", "жаль"]
    surprise: ["ого", "ой", "ай", "ничего себе"]
    neutral: ["ну", "да", "же", "ага", "угу", "фу", "хм", "тьфу"]
  vi:
    joy: ["hihi", "hehe", "tuyệt", "sướng", "vui", "đã"]
    anger: ["hừ", "tức", "giận", "điên", "chết tiệt", "đm"]
    sadness: ["huhu", "hic", "buồn", "khóc", "chán"]
    surprise: ["á", "chời", "trời", "ôi", "ặc", "thật á?"]
    neutral: ["ạ", "nhé", "nha", "ấy", "ơi", "haiz", "haizz", "ờ", "ớ"]
  th:
    joy: ["ฮ่าฮ่า", "ฮิฮิ", "555", "สุดยอด", "เจ๋ง", "ดีใจ", "เริ่ด"]
    anger: ["โกรธ", "โมโห", "หงุดหงิด", "ชิ", "แม่ง", "ให้ตายสิ"]
    sadness: ["เศร้า", "ร้องไห้", "เฮ้อ", "เสียใจ"]
    surprise: ["โห", "โอ้", "เห้ย", "จริงดิ"]
    neutral: ["นะ", "ค่ะ", "ครับ", "จ้า", "ล่ะ", "จ้ะ", "จ๊ะ", "เหอะ", "เซ็ง"]
  ar:
    joy: ["هههه", "رائع", "حلو", "جميل", "عظيم"]
    anger: ["غاضب", "منزعج", "تبا", "اللعنة"]
    sadness: ["آه", "حزين", "يا للحسرة"]
    surprise: ["أوه", "يا إلهي", "يا ساتر", "عجبا"]
    neutral: ["والله", "يعني", "طيب", "حسناً", "تمام", "أف", "هه", "بس", "عادي"]
  km:
    joy: ["ហាហា", "ហិហិ", "ល្អណាស់", "សប្បាយ", "สุดยอด"]
    anger: ["ខឹង", "โมโห"]
    sadness: ["តូចចិត្ត", "เสียใจ"]
    surprise: ["អូ", "អ្ហា៎", "ពិតមែនឬ?"]
    neutral: ["ណា", "ទេ", "ហើយ", "ចា៎", "បាទ", "ហ្នឹងហើយ"]


# 翻译模式配置
translation_modes:
  1: # 模式1：Chinese-English
    source_lang: 中文
    target_lang: 英文
    source_lang_en: Chinese
    target_lang_en: English
    style: Natural Internationalization
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: en
  2: # 模式2：Chinese-Japanese Plain
    source_lang: 中文
    target_lang: 日文
    source_lang_en: Chinese
    target_lang_en: Japanese
    style: Plain Language
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: ja
  3: # 模式3：Chinese-Japanese Honorific
    source_lang: 中文
    target_lang: 日文
    source_lang_en: Chinese
    target_lang_en: Japanese
    style: Honorific Language
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: ja
  4: # 模式4：Chinese-German
    source_lang: 中文
    target_lang: 德文
    source_lang_en: Chinese
    target_lang_en: German
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: de
  5: # 模式5：Chinese-French
    source_lang: 中文
    target_lang: 法文
    source_lang_en: Chinese
    target_lang_en: French
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: fr
  6: # 模式6：Chinese-Italian
    source_lang: 中文
    target_lang: 意大利文
    source_lang_en: Chinese
    target_lang_en: Italian
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: it
  7: # 模式7：Chinese-Spanish
    source_lang: 中文
    target_lang: 西班牙文
    source_lang_en: Chinese
    target_lang_en: Spanish
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: es
  8: # 模式8：Chinese-Korean Plain
    source_lang: 中文
    target_lang: 韩文
    source_lang_en: Chinese
    target_lang_en: Korean
    style: Natural Plain Language
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: ko
  9: # 模式9：Chinese-Korean Honorific
    source_lang: 中文
    target_lang: 韩文
    source_lang_en: Chinese
    target_lang_en: Korean
    style: Natural Honorific Language
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: ko
  10: # 模式10：Chinese-Russian
    source_lang: 中文
    target_lang: 俄文
    source_lang_en: Chinese
    target_lang_en: Russian
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: ru
  11: # 模式11：Chinese-Portuguese
    source_lang: 中文
    target_lang: 葡萄牙文
    source_lang_en: Chinese
    target_lang_en: Portuguese
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: pt
  12: # 模式12：Chinese-Arabic
    source_lang: 中文
    target_lang: 阿拉伯文
    source_lang_en: Chinese
    target_lang_en: Arabic
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: ar
  13: # 模式13：Chinese-Vietnamese
    source_lang: 中文
    target_lang: 越南文
    source_lang_en: Chinese
    target_lang_en: Vietnamese
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: vi
  14: # 模式14：Chinese-Thai
    source_lang: 中文
    target_lang: 泰文
    source_lang_en: Chinese
    target_lang_en: Thai
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: th
  15: # 模式15：Chinese-Cambodian
    source_lang: 中文
    target_lang: 高棉文
    source_lang_en: Chinese
    target_lang_en: Cambodian
    style: "Natural"
    default_lang: 中文
    default_lang_en: Chinese
    source_code: zh
    target_code: km


# 语言特征配置
language_features:
  zh: # 中文特征
    pattern: "[\\u4E00-\\u9FFF]" # 汉字Unicode范围
    exclusive: # 排除特征
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 汉字 # 描述
    question_pattern: "[?？]"
    exclamation_pattern: "[!！]"
  ko: # 韩文特征
    pattern: "[\\uAC00-\\uD7AF]" # 韩文谚文Unicode范围
    exclusive:
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 韩文谚文 # 描述
    question_pattern: "[?？]"
    exclamation_pattern: "[!！]"
  ja: # 日文特征
    pattern: "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 日文假名Unicode范围
    exclusive:
      - "[\\uAC00-\\uD7AF]" # 排除韩文
    desc: 日文假名 # 描述
    question_pattern: "[?？]"
    exclamation_pattern: "[!！]"
  en: # 英文特征
    pattern: "[A-Za-z]" # 英文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 英文拉丁字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  vi: # 越南文特征
    pattern: "[A-Za-zÀ-ỹ]" # 越南文字母范围（包括带音调符号的拉丁字母）
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 越南文拉丁字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  fr: # 法文特征
    pattern: "[A-Za-zÀ-ÿ]" # 法文字母范围（包括带音调符号的拉丁字母）
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 法文拉丁字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  de: # 德文特征
    pattern: "[A-Za-zÄäÖöÜüß]" # 德文字母范围（包括变音符号）
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 德文拉丁字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  es: # 西班牙文特征
    pattern: "[A-Za-zÁáÉéÍíÓóÚúÜüÑñ]" # 西班牙文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 西班牙文拉丁字母 # 描述
    question_pattern: "[?¿]"
    exclamation_pattern: "[!¡]"
  ru: # 俄文特征
    pattern: "[А-Яа-я]" # 俄文西里尔字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 俄文西里尔字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  pt: # 葡萄牙文特征
    pattern: "[A-Za-zÁáÂâÃãÀàÇçÉéÊêÍíÓóÔôÕõÚú]" # 葡萄牙文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 葡萄牙文拉丁字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  ar: # 阿拉伯文特征
    pattern: "[\\u0600-\\u06FF]" # 阿拉伯文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 阿拉伯文字母 # 描述
    question_pattern: "[؟]"
    exclamation_pattern: "[!]"
  it: # 意大利文特征
    pattern: "[A-Za-zÀàÈèÉéÌìÍíÒòÓóÙùÚú]" # 意大利文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 意大利文拉丁字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  th: # 泰文特征
    pattern: "[\\u0E00-\\u0E7F]" # 泰文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 泰文字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"
  km: # 柬埔寨文特征
    pattern: "[\\u1780-\\u17FF]" # 柬埔寨文字母范围
    exclusive: # 排除特征
      - "[\\u4E00-\\u9FFF]" # 排除中文
      - "[\\uAC00-\\uD7AF]" # 排除韩文
      - "[\\u3040-\\u309F\\u30A0-\\u30FF]" # 排除日文
    desc: 柬埔寨文字母 # 描述
    question_pattern: "[?]"
    exclamation_pattern: "[!]"

supported_langs:
  zh: ["zh"]
  ko: ["ko"]
  ja: ["ja"]
  en: ["en"]
  vi: ["vi"]
  fr: ["fr"]
  de: ["de"]
  es: ["es"]
  ru: ["ru"]
  pt: ["pt"]
  ar: ["ar"]
  it: ["it"]
  th: ["th"]
  km: ["km"]

# 特殊语言组配置
special_language_groups:
  cjk:
    languages:
      - ja
      - zh
      - ko
    strict_detection: false
    tokenization_strategy: char
    desc: 中日韩语言组
  latin:
    languages:
      - en
      - es
      - fi
      - sv
      - de
      - nl
      - da
      - pt
      - no
      - vi
      - it
      - fr
    strict_detection: false
    tokenization_strategy: space
    desc: 拉丁语系
  indic:
    languages:
      - ml
      - mr
      - ta
      - te
      - bn
      - gu
      - kn
      - hi
      - pa
    strict_detection: false
    tokenization_strategy: space
    desc: 印度语系
  semitic:
    languages:
      - he
      - am
      - ti
      - mt
      - ar
    strict_detection: false
    tokenization_strategy: char
    desc: 闪米特语系
  southeast_asian:
    languages:
      - vi
      - th
      - lo
      - km
      - my
      - id
      - ms
      - tl
    strict_detection: false
    tokenization_strategy: char # 混合，但char更安全
    desc: 东南亚语系

# 特殊语言对配置
special_language_pairs:
  "*-*":
    desc: 通用语言对配置
    skip_source_detection: false
    min_char_ratio: 0.2
    max_char_ratio: 5.0
  zh-ko:
    desc: zh-ko互译配置
    skip_source_detection: true
    min_char_ratio: 0.3
    max_char_ratio: 3.0
    allow_source_residue: true
  zh-ja:
    desc: zh-ja互译配置
    skip_source_detection: true
    min_char_ratio: 0.3
    max_char_ratio: 3.0
    allow_source_residue: true
  zh-en:
    desc: zh-en互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-vi:
    desc: zh-vi互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-fr:
    desc: zh-fr互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-de:
    desc: zh-de互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-es:
    desc: zh-es互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-ru:
    desc: zh-ru互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-pt:
    desc: zh-pt互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-ar:
    desc: zh-ar互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-it:
    desc: zh-it互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-th:
    desc: zh-th互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  zh-km:
    desc: zh-km互译配置
    skip_source_detection: false
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  cjk-latin:
    desc: cjk与latin语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  cjk-slavic:
    desc: cjk与slavic语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  cjk-indic:
    desc: cjk与indic语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  cjk-semitic:
    desc: cjk与semitic语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  latin-cjk:
    desc: latin与cjk语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  latin-slavic:
    desc: latin与slavic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  latin-indic:
    desc: latin与indic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  latin-semitic:
    desc: latin与semitic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  slavic-cjk:
    desc: slavic与cjk语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  slavic-latin:
    desc: slavic与latin语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  slavic-indic:
    desc: slavic与indic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  slavic-semitic:
    desc: slavic与semitic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  indic-cjk:
    desc: indic与cjk语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  indic-latin:
    desc: indic与latin语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  indic-slavic:
    desc: indic与slavic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  indic-semitic:
    desc: indic与semitic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  semitic-cjk:
    desc: semitic与cjk语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  semitic-latin:
    desc: semitic与latin语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  semitic-slavic:
    desc: semitic与slavic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  semitic-indic:
    desc: semitic与indic语言组互译配置
    min_char_ratio: 0.1
    max_char_ratio: 5.0
  cjk-*:
    desc: cjk语言组对外互译
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  "*-cjk":
    desc: 外部语言翻译到cjk语言组
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  latin-*:
    desc: latin语言组对外互译
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  "*-latin":
    desc: 外部语言翻译到latin语言组
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  slavic-*:
    desc: slavic语言组对外互译
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  "*-slavic":
    desc: 外部语言翻译到slavic语言组
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  indic-*:
    desc: indic语言组对外互译
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  "*-indic":
    desc: 外部语言翻译到indic语言组
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  semitic-*:
    desc: semitic语言组对外互译
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  "*-semitic":
    desc: 外部语言翻译到semitic语言组
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  cjk-southeast_asian:
    desc: cjk与东南亚语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  southeast_asian-cjk:
    desc: 东南亚语言组与cjk互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  latin-southeast_asian:
    desc: latin与东南亚语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  southeast_asian-latin:
    desc: 东南亚语言组与latin互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  slavic-southeast_asian:
    desc: slavic与东南亚语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  southeast_asian-slavic:
    desc: 东南亚语言组与slavic互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  indic-southeast_asian:
    desc: indic与东南亚语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  southeast_asian-indic:
    desc: 东南亚语言组与indic互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  semitic-southeast_asian:
    desc: semitic与东南亚语言组互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  southeast_asian-semitic:
    desc: 东南亚语言组与semitic互译配置
    min_char_ratio: 0.15
    max_char_ratio: 5.0
    allow_short_text_mismatch: true
  southeast_asian-*:
    desc: 东南亚语言组对外互译
    min_char_ratio: 0.15
    max_char_ratio: 5.0
  "*-southeast_asian":
    desc: 外部语言翻译到东南亚语言组
    min_char_ratio: 0.15
    max_char_ratio: 5.0

"""


class ModelParams(BaseModel):
    class Config:
        extra = "allow"


class ModelProfile(BaseModel):
    model_id: str
    params: ModelParams = Field(default_factory=ModelParams)


class ProviderProfile(BaseModel):
    api_key: str = ""
    api_base: Union[str, None] = None
    api_mode: str
    models: list[ModelProfile]


class ModelsConfig(RootModel[Dict[str, ProviderProfile]]):
    def __getitem__(self, item: str) -> ProviderProfile:
        return self.root[item]

    @overload
    def get(self, key: str) -> Optional[ProviderProfile]: ...
    @overload
    def get(self, key: str, default: _T) -> Union[ProviderProfile, _T]: ...
    def get(self, key: str, default: Any = None) -> Any:
        return self.root.get(key, default)


class RetryConfig(BaseModel):
    attempts: int
    min_delay: int
    max_delay: int
    backoff_factor: int


class LoggingConfig(BaseModel):
    info_max: int = 100
    other_max: int = 100
    cleanup_interval: float = 2.0


class Config(BaseModel):
    translation_mode: int
    max_text_length: int
    context_max_count: int
    short_text_threshold: int
    lang_detection_threshold: float
    thread_pool_max_workers: int
    tcp_connector: Dict[str, Any]
    timeout: Dict[str, Any]
    network_check: Dict[str, Any]
    api_health_check: Dict[str, Any]
    request_min_interval: float
    retry_config: RetryConfig
    proxy: Dict[str, Any]
    debug_mode: bool
    logging: LoggingConfig
    log_max_bytes: int
    log_backup_count: int
    cache_hit_log_interval: int
    cache_key_display_length: int
    show_gui_progress: bool
    gui_theme: Dict[str, Any]
    gui_progress: Dict[str, Any]
    keyboard_listener: Dict[str, Any]
    common_symbols: str
    illegal_chars: str
    language_detection_cache_size: int
    same_language_match_threshold: float
    use_local_cache: bool
    local_cache_path: str
    cache_max_entries: int
    cache_write_delay: float
    cache_batch_size: int
    cache_auto_save: bool
    cache_cleanup_threshold: float
    chat_context_cleanup_days: int
    cache_cleanup_interval_hours: int = Field(
        default=1, description="缓存清理间隔（小时）"
    )
    language_detection: Dict[str, Any]
    translation_quality: Dict[str, Any]

    model_config = {"arbitrary_types_allowed": True}

    def get(self, key: str, default: Any = None) -> Any:
        try:
            if hasattr(self, key):
                return getattr(self, key)
            else:
                return default
        except Exception as e:
            logger.error(f"获取配置项 {key} 时出错: {e}")
            return default

    @classmethod
    def validate_config(cls, config_data: Dict[str, Any]) -> "Config":
        """增强的配置验证方法，在Pydantic验证基础上进行额外检查"""
        # 首先进行基础的Pydantic验证
        try:
            config = cls.model_validate(config_data)
        except Exception as e:
            raise ValueError(f"配置验证失败: {e}")

        # 执行额外验证
        cls._validate_config_logic(config_data)
        return config

    @staticmethod
    def _validate_config_logic(config: Dict[str, Any]) -> None:
        """验证配置逻辑的正确性"""
        errors = []

        # 验证翻译模式
        if (
            not isinstance(config["translation_mode"], int)
            or config["translation_mode"] < 1
        ):
            errors.append(
                f"翻译模式必须是大于0的整数，当前值: {config['translation_mode']}"
            )

        # 验证文本长度限制
        if config["max_text_length"] <= 0:
            errors.append(f"最大文本长度必须大于0，当前值: {config['max_text_length']}")

        # 验证线程池大小
        if config["thread_pool_max_workers"] <= 0:
            errors.append(
                f"线程池最大工作线程数必须大于0，当前值: {config['thread_pool_max_workers']}"
            )

        # 验证TCP连接器配置
        if not isinstance(config["tcp_connector"], dict):
            errors.append("tcp_connector配置必须是字典类型")
        else:
            required_tcp_keys = [
                "limit",
                "ttl_dns_cache",
                "keepalive_timeout",
                "force_close",
            ]
            for key in required_tcp_keys:
                if key not in config["tcp_connector"]:
                    errors.append(f"tcp_connector配置缺少必需的键: {key}")

        # 验证超时配置
        if not isinstance(config["timeout"], dict):
            errors.append("timeout配置必须是字典类型")
        else:
            required_timeout_keys = ["total", "connect", "sock_connect", "sock_read"]
            for key in required_timeout_keys:
                if key not in config["timeout"]:
                    errors.append(f"timeout配置缺少必需的键: {key}")

        # 验证网络检查配置
        if not isinstance(config["network_check"], dict):
            errors.append("network_check配置必须是字典类型")
        else:
            required_network_keys = [
                "hosts",
                "port",
                "timeout",
                "interval",
                "https_timeout",
            ]
            for key in required_network_keys:
                if key not in config["network_check"]:
                    errors.append(f"network_check配置缺少必需的键: {key}")

        # 验证API健康检查配置
        if not isinstance(config["api_health_check"], dict):
            errors.append("api_health_check配置必须是字典类型")
        else:
            required_api_keys = [
                "timeout_total",
                "timeout_connect",
                "timeout_sock_connect",
                "timeout_sock_read",
                "startup_check_timeout",
                "console_check_timeout",
                "test_prompt",
                "cache_lifetime",
            ]
            for key in required_api_keys:
                if key not in config["api_health_check"]:
                    errors.append(f"api_health_check配置缺少必需的键: {key}")

        # 验证重试配置
        if config["retry_config"]["attempts"] < 1:
            errors.append(
                f"重试次数必须大于等于1，当前值: {config['retry_config']['attempts']}"
            )

        # 验证代理配置
        if not isinstance(config["proxy"], dict):
            errors.append("proxy配置必须是字典类型")
        else:
            if config["proxy"].get("enabled", False) and not config["proxy"].get("url"):
                errors.append("代理已启用但未设置代理URL")

        # 验证本地缓存配置
        if config["use_local_cache"] and not config["local_cache_path"].strip():
            errors.append("本地缓存已启用但缓存路径为空")

        # 验证缓存配置
        if config["cache_max_entries"] <= 0:
            errors.append(
                f"缓存最大条目数必须大于0，当前值: {config['cache_max_entries']}"
            )

        if (
            config["cache_cleanup_threshold"] <= 0
            or config["cache_cleanup_threshold"] > 1
        ):
            errors.append(
                f"缓存清理阈值必须在0-1之间，当前值: {config['cache_cleanup_threshold']}"
            )

        # 验证语言检测阈值
        if (
            config["lang_detection_threshold"] <= 0
            or config["lang_detection_threshold"] > 1
        ):
            errors.append(
                f"语言检测阈值必须在0-1之间，当前值: {config['lang_detection_threshold']}"
            )

        if (
            config["same_language_match_threshold"] < 0
            or config["same_language_match_threshold"] > 1
        ):
            errors.append(
                f"同语言匹配阈值必须在0-1之间，当前值: {config['same_language_match_threshold']}"
            )

        # 验证日志配置
        if config["log_max_bytes"] <= 0:
            errors.append(
                f"日志文件最大大小必须大于0，当前值: {config['log_max_bytes']}"
            )

        if config["log_backup_count"] <= 0:
            errors.append(
                f"日志文件备份数量必须大于0，当前值: {config['log_backup_count']}"
            )

        # 验证GUI配置
        if not isinstance(config["gui_theme"], dict):
            errors.append("gui_theme配置必须是字典类型")

        if not isinstance(config["gui_progress"], dict):
            errors.append("gui_progress配置必须是字典类型")

        if not isinstance(config["keyboard_listener"], dict):
            errors.append("keyboard_listener配置必须是字典类型")

        # 验证语言检测配置
        if not isinstance(config["language_detection"], dict):
            errors.append("language_detection配置必须是字典类型")

        if not isinstance(config["translation_quality"], dict):
            errors.append("translation_quality配置必须是字典类型")

        if errors:
            error_msg = "配置验证失败，以下是具体的错误:\n" + "\n".join(
                f"  - {error}" for error in errors
            )
            raise ValueError(error_msg)


def get_default_config_dict() -> Dict[str, Any]:
    """从 DEFAULT_CONFIG_TEXT 解析并返回默认配置字典"""
    yaml_loader = YAML()
    try:
        config_dict = yaml_loader.load(DEFAULT_CONFIG_TEXT)
        if not isinstance(config_dict, dict):
            logger.error("DEFAULT_CONFIG_TEXT 解析失败，返回空字典。")
            return {}
        return config_dict
    except Exception as e:
        logger.error(f"解析 DEFAULT_CONFIG_TEXT 失败: {e}，返回空字典。")
        return {}


def _to_yaml_compatible(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _to_yaml_compatible(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_to_yaml_compatible(item) for item in data]
    elif isinstance(data, str) and "\n" in data:
        return PreservedScalarString(data)
    return data


def _merge_ruamel_data(target: Any, source: Any) -> Any:
    """深度合并两个数据结构，特殊处理列表和字典配置。"""
    # 需要深度合并（不覆盖）的顶级配置键
    dict_merge_keys = {
        "tcp_connector",
        "timeout",
        "network_check",
        "api_health_check",
        "proxy",
        "gui_theme",
        "gui_progress",
        "keyboard_listener",
        "logging",
        "language_detection",
        "translation_quality",
        "translation_modes",
        "tone_particles",
        "language_features",
        "supported_langs",
        "special_language_groups",
        "special_language_pairs",
    }

    # 需要列表合并（添加新元素而不覆盖）的键
    list_merge_keys = {
        "hosts",
        "models",
        "exclusive",
    }

    if isinstance(source, dict):
        if not isinstance(target, dict):
            return _to_yaml_compatible(source)
        for key, value in source.items():
            if key not in target:
                # 新键直接添加
                target[key] = _to_yaml_compatible(value)
            elif (
                key in dict_merge_keys
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                # 深度合并字典配置
                _merge_ruamel_data(target[key], value)
            elif (
                key in list_merge_keys
                and isinstance(target[key], list)
                and isinstance(value, list)
            ):
                # 列表合并：添加新元素而不覆盖现有元素
                merged_list = list(target[key])
                for item in value:
                    if item not in merged_list:
                        merged_list.append(item)
                target[key] = _to_yaml_compatible(merged_list)
            else:
                # 其他情况：配置值通常应该整体替换而不是合并
                target[key] = _to_yaml_compatible(value)
        return target
    elif isinstance(source, list):
        return _to_yaml_compatible(source)
    else:
        return _to_yaml_compatible(source)


def save_main_config(
    config_data: Union[Dict[str, Any], Config], filename: Optional[str] = None
) -> bool:
    if filename is None:
        filename = get_config_file_path()
    config_dict = (
        config_data if isinstance(config_data, dict) else config_data.model_dump()
    )

    if not is_path_writable(filename):
        user_home = os.path.expanduser("~")
        app_data_dir = os.path.join(user_home, ".multitranslator")
        try:
            if not os.path.exists(app_data_dir):
                os.makedirs(app_data_dir)
            backup_filename = os.path.join(app_data_dir, os.path.basename(filename))
            logger.warning(f"无法写入 {filename}，将使用备用路径: {backup_filename}")
            filename = backup_filename
        except Exception as e:
            logger.error(f"创建备用配置目录失败: {e}")
            return False

    yaml_loader = YAML()
    yaml_loader.preserve_quotes = True
    yaml_loader.indent(mapping=2, sequence=4, offset=2)

    try:
        data_to_save = None
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            try:
                with open(filename, "r", encoding="utf-8-sig") as f:
                    data_to_save = yaml_loader.load(f)
                if not isinstance(data_to_save, dict):
                    logger.warning(
                        f"配置文件 {filename} 内容格式不正确，将使用新配置覆盖。"
                    )
                    data_to_save = None
            except Exception as e:
                logger.error(f"读取配置文件 {filename} 失败: {e}。将尝试使用新配置。")
                data_to_save = None

        if data_to_save is None:
            logger.info(f"将从 DEFAULT_CONFIG_TEXT 创建或覆盖配置: {filename}")
            try:
                default_config_stream = io.StringIO(DEFAULT_CONFIG_TEXT)
                data_to_save = yaml_loader.load(default_config_stream)
                if not isinstance(data_to_save, dict):
                    logger.error(
                        "DEFAULT_CONFIG_TEXT 解析失败，无法创建带注释的默认配置。将使用Pydantic模型创建。"
                    )
                    data_to_save = Config(**get_default_config_dict()).model_dump()
            except Exception as e_load_default:
                logger.error(
                    f"从 DEFAULT_CONFIG_TEXT 加载默认配置失败: {e_load_default}。将使用Pydantic模型创建。"
                )
                data_to_save = Config(**get_default_config_dict()).model_dump()

        if isinstance(data_to_save, dict):
            _merge_ruamel_data(data_to_save, config_dict)
        else:
            data_to_save = config_dict

        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w", encoding="utf-8-sig") as f:
            yaml_loader.dump(data_to_save, f)

        logger.info(f"主配置文件已保存: {filename}")
        return True
    except Exception as e:
        logger.error(f"保存主配置文件 {filename} 失败: {e}", exc_info=True)
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)

            with open(filename, "w", encoding="utf-8-sig") as file:
                yaml.dump(
                    config_dict,
                    file,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                    indent=2,
                )
            logger.info(f"主配置已通过备用方法 (PyYAML) 保存到 {filename}")
            return True
        except Exception as e2:
            logger.error(f"主配置备用保存方式 (PyYAML) 也失败: {e2}")
            return False


def generate_default_main_config(force_overwrite: bool = False) -> bool:
    current_thread_name = threading.current_thread().name
    logger.debug(
        f"[{current_thread_name}] 调用 generate_default_main_config (force_overwrite={force_overwrite})"
    )

    config_file = get_config_file_path()
    if not is_path_writable(config_file):
        user_home = os.path.expanduser("~")
        app_data_dir = os.path.join(user_home, ".multitranslator")
        try:
            os.makedirs(app_data_dir, exist_ok=True)
            backup_config_file = os.path.join(
                app_data_dir, os.path.basename(get_config_file_path())
            )
            logger.warning(
                f"[{current_thread_name}] 无法写入 {get_config_file_path()}，将使用备用路径: {backup_config_file}"
            )

            if not force_overwrite and os.path.exists(backup_config_file):
                logger.info(
                    f"[{current_thread_name}] 备用配置文件 {backup_config_file} 已存在。"
                )
                return True

            if _write_default_config_text(backup_config_file):
                logger.info(
                    f"[{current_thread_name}] 默认主配置文件已成功生成到备用位置: {backup_config_file}"
                )
                return True
            else:
                logger.error(
                    f"[{current_thread_name}] 无法在备用位置生成默认主配置文件"
                )
                return False
        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 创建备用配置失败: {e}", exc_info=True
            )
            return False

    config_file_path = get_config_file_path()
    if not force_overwrite and os.path.exists(config_file_path):
        logger.info(
            f"[{current_thread_name}] {config_file_path} 已存在，且未强制覆盖。"
        )
        return True

    logger.info(f"[{current_thread_name}] 正在生成默认主配置文件: {config_file_path}")

    if _write_default_config_text(config_file_path):
        logger.info(
            f"[{current_thread_name}] 默认主配置文件已成功生成: {config_file_path}"
        )
        return True
    else:
        logger.error(
            f"[{current_thread_name}] 生成默认主配置文件失败: {config_file_path}"
        )
        return False


def _write_default_config_text(filename: str) -> bool:
    """直接写入默认配置文本到文件"""
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w", encoding="utf-8-sig") as f:
            f.write(DEFAULT_CONFIG_TEXT.strip())

        logger.debug(f"默认配置文本已写入: {filename}")
        return True

    except Exception as e:
        logger.error(f"写入默认配置文本失败: {e}")
        return False


def _update_api_key_in_models_config(filename: str, api_key: str) -> bool:
    """更新 models.yaml 配置文件中第一个提供商的API密钥"""
    try:
        yaml_loader = YAML()
        yaml_loader.preserve_quotes = True
        yaml_loader.indent(mapping=2, sequence=4, offset=2)

        with open(filename, "r", encoding="utf-8-sig") as f:
            models_data = yaml_loader.load(f)

        if not isinstance(models_data, dict):
            logger.error("模型配置文件格式不正确")
            return False

        provider_updated = False
        for provider_name, provider_config in models_data.items():
            if isinstance(provider_config, dict) and "api_key" in provider_config:
                logger.info(
                    f"准备更新API密钥到 models.yaml 的 '{provider_name}' 提供商"
                )
                provider_config["api_key"] = api_key
                provider_updated = True
                break

        if not provider_updated:
            logger.warning("在 models.yaml 中未找到可更新API密钥的提供商")
            return False

        with open(filename, "w", encoding="utf-8-sig") as f:
            yaml_loader.dump(models_data, f)

        logger.info("API密钥已更新到 models.yaml 的第一个提供商")
        return True

    except Exception as e:
        logger.error(f"更新 models.yaml 中的API密钥失败: {e}")
        return False


def prompt_for_api_key() -> str:
    """提示用户输入加密后的API密钥"""
    try:
        print("\n=== API密钥设置 ===")
        print("请输入您的加密后的API密钥：")
        print("注意：您必须输入已经加密的API密钥，程序不接受原始API密钥")
        print("提示：如果暂时跳过，可以稍后在设置菜单中配置")
        print("直接按回车跳过...")

        api_key = input("加密后的API密钥: ").strip()

        if not api_key:
            logger.info("用户跳过API密钥设置")
            return ""

        try:
            try:
                from utils.api_crypto import ApiCrypto
            except ImportError:
                import sys
                import os

                utils_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)), "utils"
                )
                if utils_path not in sys.path:
                    sys.path.insert(0, utils_path)
                from utils.api_crypto import ApiCrypto

            crypto = ApiCrypto()

            if crypto.is_encrypted(api_key):
                decrypted_key = crypto.decrypt(api_key)
                if decrypted_key:
                    logger.info("加密API密钥验证成功")
                    return api_key
                else:
                    print("错误：加密API密钥无效或无法解密，请重新输入")
                    logger.error("加密API密钥无效或无法解密")
                    return ""
            else:
                print("错误：输入的不是有效的加密API密钥")
                print("请使用api_crypto.py工具加密您的API密钥后再输入")
                logger.error("输入的不是有效的加密API密钥")
                return ""

        except ImportError:
            logger.warning("无法导入加密模块，无法验证API密钥格式")
            print("警告：无法验证API密钥格式，将直接保存")
            return api_key
        except Exception as e:
            logger.error(f"验证API密钥时出错: {e}")
            print(f"验证API密钥时出错: {e}")
            return ""

    except (KeyboardInterrupt, EOFError):
        logger.info("用户取消API密钥设置")
        return ""
    except Exception as e:
        logger.error(f"API密钥设置过程出错: {e}")
        return ""


def get_default_mode_config_dict() -> Dict[str, Any]:
    yaml_loader = YAML()
    try:
        config_dict = yaml_loader.load(DEFAULT_MODE_CONFIG_TEXT)
        if not isinstance(config_dict, dict):
            logger.error("DEFAULT_MODE_CONFIG_TEXT 解析失败，返回空字典。")
            return {}
        return config_dict
    except Exception as e:
        logger.error(f"解析 DEFAULT_MODE_CONFIG_TEXT 失败: {e}，返回空字典。")
        return {}


def save_mode_config_file(
    mode_config_data: Dict[str, Any], filename: Optional[str] = None
) -> bool:
    if filename is None:
        filename = get_mode_config_file_path()
    if not is_path_writable(filename):
        user_home = os.path.expanduser("~")
        app_data_dir = os.path.join(user_home, ".multitranslator")
        try:
            if not os.path.exists(app_data_dir):
                os.makedirs(app_data_dir)
            backup_filename = os.path.join(app_data_dir, os.path.basename(filename))
            logger.warning(f"无法写入 {filename}，将使用备用路径: {backup_filename}")
            filename = backup_filename
        except Exception as e:
            logger.error(f"创建备用配置目录失败: {e}")
            return False

    yaml_loader = YAML()
    yaml_loader.preserve_quotes = True
    yaml_loader.indent(mapping=2, sequence=4, offset=2)

    try:
        data_to_save = None
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            try:
                with open(filename, "r", encoding="utf-8-sig") as f:
                    data_to_save = yaml_loader.load(f)
                if not isinstance(data_to_save, dict):
                    logger.warning(
                        f"模式配置文件 {filename} 内容格式不正确，将使用新配置覆盖。"
                    )
                    data_to_save = None
            except Exception as e:
                logger.error(
                    f"读取模式配置文件 {filename} 失败: {e}。将尝试使用新配置。"
                )
                data_to_save = None

        if data_to_save is None:
            logger.info(f"将从 DEFAULT_MODE_CONFIG_TEXT 创建或覆盖模式配置: {filename}")
            try:
                default_mode_config_stream = io.StringIO(DEFAULT_MODE_CONFIG_TEXT)
                data_to_save = yaml_loader.load(default_mode_config_stream)
                if not isinstance(data_to_save, dict):
                    logger.error("DEFAULT_MODE_CONFIG_TEXT 解析失败。")
                    data_to_save = get_default_mode_config_dict()
            except Exception as e_load_default:
                logger.error(
                    f"从 DEFAULT_MODE_CONFIG_TEXT 加载默认模式配置失败: {e_load_default}。"
                )
                data_to_save = get_default_mode_config_dict()

        if isinstance(data_to_save, dict):
            _merge_ruamel_data(data_to_save, mode_config_data)
        else:
            data_to_save = mode_config_data

        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w", encoding="utf-8-sig") as f:
            yaml_loader.dump(data_to_save, f)

        logger.info(f"模式配置文件已保存: {filename}")
        return True
    except Exception as e:
        logger.error(f"保存模式配置文件 {filename} 失败: {e}", exc_info=True)
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)

            with open(filename, "w", encoding="utf-8-sig") as file:
                yaml.dump(
                    mode_config_data,
                    file,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                    indent=2,
                )
            logger.info(f"模式配置已通过备用方法 (PyYAML) 保存到 {filename}")
            return True
        except Exception as e2:
            logger.error(f"模式配置备用保存方式 (PyYAML) 也失败: {e2}")
            return False


def get_default_models_config_dict() -> Dict[str, Any]:
    yaml_loader = YAML()
    try:
        config_dict = yaml_loader.load(DEFAULT_MODELS_CONFIG_TEXT)
        if not isinstance(config_dict, dict):
            logger.error("DEFAULT_MODELS_CONFIG_TEXT 解析失败，返回空字典。")
            return {}
        return config_dict
    except Exception as e:
        logger.error(f"解析 DEFAULT_MODELS_CONFIG_TEXT 失败: {e}，返回空字典。")
        return {}


def generate_default_models_config(force_overwrite: bool = False) -> bool:
    """生成默认模型配置文件，增加对目录和权限的检查。"""
    models_config_file = get_models_config_file_path()
    if not force_overwrite and os.path.exists(models_config_file):
        return True

    try:
        config_dir = os.path.dirname(models_config_file)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)

        if not os.access(config_dir, os.W_OK):
            error_message = f"错误：没有权限写入目录 {config_dir}。请检查文件夹权限。"
            print(error_message, file=sys.stderr)
            logger.error(error_message)
            return False

        with open(models_config_file, "w", encoding="utf-8-sig") as f:
            f.write(DEFAULT_MODELS_CONFIG_TEXT.strip())

        logger.info(f"默认模型配置文件已成功生成: {models_config_file}")
        return True

    except (IOError, OSError) as e:
        error_message = f"错误：生成默认模型配置文件失败: {e}。请检查路径 {models_config_file} 是否有效和可写。"
        print(error_message, file=sys.stderr)
        logger.error(error_message)
        return False


def load_models_config(filename: Optional[str] = None) -> Dict[str, Any]:
    if filename is None:
        filename = get_models_config_file_path()
    """加载模型配置文件"""
    try:
        if not os.path.exists(filename):
            logger.warning(
                f"模型配置文件 {filename} 不存在，正在生成默认模型配置文件。"
            )
            if generate_default_models_config(force_overwrite=False):
                logger.info(f"默认模型配置文件已生成: {filename}")
                if os.path.exists(filename):
                    return load_models_config(filename)

            logger.error("生成默认模型配置文件失败，使用内存中的默认配置。")
            return get_default_models_config_dict()

        yaml = YAML()
        with open(filename, "r", encoding="utf-8-sig") as f:
            models_config = yaml.load(f)

        if not models_config:
            logger.warning("模型配置文件为空，将使用默认配置。")
            return get_default_models_config_dict()

        logger.debug("模型配置加载成功")
        return dict(models_config)
    except Exception as e:
        logger.error(f"加载模型配置文件失败: {e}")
        logger.warning("将使用默认模型配置")
        return get_default_models_config_dict()


def complete_language_features_and_tones_in_dict(
    mode_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    通过从DEFAULT_MODE_CONFIG_TEXT加载的默认值来补全传入的模式配置字典。
    这确保了即使配置文件不完整，程序也能获得必要的配置项。
    """
    default_language_features = {}
    default_tone_particles = {}
    try:
        yaml_loader = YAML()
        config_stream = io.StringIO(DEFAULT_MODE_CONFIG_TEXT)
        default_mode_config = yaml_loader.load(config_stream)
        if isinstance(default_mode_config, dict):
            if "language_features" in default_mode_config:
                default_language_features = default_mode_config["language_features"]
                logger.debug("从默认配置中成功加载language_features")
            if "tone_particles" in default_mode_config:
                default_tone_particles = default_mode_config["tone_particles"]
                logger.debug("从默认配置中成功加载tone_particles")

    except Exception as e:
        logger.error(f"从默认配置文本加载language_features或tone_particles失败: {e}")
        default_language_features = {}
        default_tone_particles = {}

    required_keys = [
        "tone_particles",
        "language_features",
        "special_language_groups",
        "special_language_pairs",
    ]
    for key in required_keys:
        mode_config.setdefault(key, {})

    required_langs = set()
    if "translation_modes" in mode_config and isinstance(
        mode_config["translation_modes"], dict
    ):
        for mode in mode_config["translation_modes"].values():
            if isinstance(mode, dict):
                if source_code := mode.get("source_code"):
                    required_langs.add(source_code)
                if target_code := mode.get("target_code"):
                    required_langs.add(target_code)

    logger.debug(f"需要支持的语言代码: {required_langs}")

    lang_features_map = mode_config["language_features"]
    tone_particles_map = mode_config["tone_particles"]

    # 然后补全缺失的语言特征和语气词
    for lang in required_langs:
        if lang not in lang_features_map:
            if lang in default_language_features:
                lang_features_map[lang] = default_language_features[lang].copy()
                logger.debug(f"为语言 {lang} 添加默认语言特征配置")
        else:
            if lang in default_language_features:
                for key, value in default_language_features[lang].items():
                    lang_features_map[lang].setdefault(key, value)

        if lang not in tone_particles_map:
            if lang in default_tone_particles:
                tone_particles_map[lang] = default_tone_particles[lang].copy()
                logger.debug(f"为语言 {lang} 添加默认语气词配置")

    return mode_config


def generate_default_mode_config(force_overwrite: bool = False) -> bool:
    """生成默认模式配置文件"""
    current_thread_name = threading.current_thread().name
    logger.debug(
        f"[{current_thread_name}] 调用 generate_default_mode_config (force_overwrite={force_overwrite})"
    )

    mode_config_file = get_mode_config_file_path()
    if not is_path_writable(mode_config_file):
        user_home = os.path.expanduser("~")
        app_data_dir = os.path.join(user_home, ".multitranslator")
        try:
            os.makedirs(app_data_dir, exist_ok=True)
            backup_mode_config_file = os.path.join(
                app_data_dir, os.path.basename(mode_config_file)
            )
            logger.warning(
                f"[{current_thread_name}] 无法写入 {mode_config_file}，将使用备用路径: {backup_mode_config_file}"
            )

            if not force_overwrite and os.path.exists(backup_mode_config_file):
                logger.info(
                    f"[{current_thread_name}] 备用模式配置文件 {backup_mode_config_file} 已存在。"
                )
                return True

            if _write_default_mode_config_text(backup_mode_config_file):
                logger.info(
                    f"[{current_thread_name}] 默认模式配置文件已成功生成到备用位置: {backup_mode_config_file}"
                )
                return True
            else:
                logger.error(
                    f"[{current_thread_name}] 无法在备用位置生成默认模式配置文件"
                )
                return False
        except Exception as e:
            logger.error(
                f"[{current_thread_name}] 创建备用模式配置失败: {e}", exc_info=True
            )
            return False

    if not force_overwrite and os.path.exists(mode_config_file):
        logger.info(
            f"[{current_thread_name}] {mode_config_file} 已存在，且未强制覆盖。"
        )
        return True

    logger.info(f"[{current_thread_name}] 正在生成默认模式配置文件: {mode_config_file}")

    if _write_default_mode_config_text(mode_config_file):
        logger.info(
            f"[{current_thread_name}] 默认模式配置文件已成功生成: {mode_config_file}"
        )
        return True
    else:
        logger.error(
            f"[{current_thread_name}] 生成默认模式配置文件失败: {mode_config_file}"
        )
        return False


def _write_default_mode_config_text(filename: str) -> bool:
    """直接写入默认模式配置文本到文件"""
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w", encoding="utf-8-sig") as f:
            f.write(DEFAULT_MODE_CONFIG_TEXT.strip())

        logger.debug(f"默认模式配置文本已写入: {filename}")
        return True

    except Exception as e:
        logger.error(f"写入默认模式配置文本失败: {e}")
        return False


def prompt_and_update_api_key() -> None:
    """提示用户输入API密钥并更新到 models.yaml"""
    current_thread_name = threading.current_thread().name
    logger.info(f"[{current_thread_name}] 开始提示用户输入API密钥...")
    try:
        api_key = prompt_for_api_key()
        if api_key:
            if _update_api_key_in_models_config(get_models_config_file_path(), api_key):
                logger.info(
                    f"[{current_thread_name}] 已将加密的API密钥保存到 models.yaml"
                )
            else:
                logger.error(f"[{current_thread_name}] 保存API密钥到 models.yaml 失败")
    except Exception as e:
        logger.error(
            f"[{current_thread_name}] API密钥设置过程中出现错误: {e}", exc_info=True
        )
