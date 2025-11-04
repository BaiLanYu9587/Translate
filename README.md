# 多语言互译器

AI 驱动的桌面翻译工具，支持多API提供商，通过全局快捷键（三击空格）触发翻译。

- **工作方式**: 复制文本 → 三击空格 → 自动翻译与替换
- **目标平台**: Windows 10/11 (x64)
- **最新版本**: v2.2.4

---

## ✨ 主要特性

- **多AI提供商支持**: 动态加载 Google Gemini、Anthropic Claude、OpenAI 及所有 OpenAI 兼容的 API 服务。
- **全局快捷键**: 在任何输入框中三击空格键即可触发翻译，无需切换窗口。
- **智能缓存系统**: 高性能双层缓存（内存 LRU + SQLite 持久化），大幅减少API调用和成本。
- **上下文感知翻译**: 能够根据当前窗口标题区分不同的对话上下文，提供连贯的翻译。
- **翻译质量评估**: 自动评估翻译结果的质量，在质量不佳时智能重试，确保翻译效果。
- **健壮的异步架构**: 采用 `asyncio` 和多线程模型，实现高性能的并发请求和流畅的用户体验。
- **高级配置管理**:
  - 使用 Pydantic 模型进行严格的配置验证。
  - 在程序目录不可写时，自动回退到用户主目录，保证程序正常运行。
- **安全密钥管理**: 内置 AES-GCM 加密工具，确保 API 密钥的安全存储。
- **开发者工具**: 提供功能丰富的运行时控制台，支持模式切换、配置热重载、API 健康检查和网络诊断。
- **健壮的启动程序**: 自动处理 Windows 环境下的 OpenSSL 动态库依赖、高DPI显示和临时文件清理。

---

## 🚀 核心工作流

![动画演示](动画演示.gif)

1.  **触发翻译**: 用户在任意应用程序的输入框中，通过三击空格键激活翻译功能。
2.  **获取文本**: 程序自动从系统剪贴板获取需要翻译的文本。
3.  **智能处理**:
    - **语言检测**: 自动识别源语言。
    - **缓存查询**: 首先在内存缓存中查找，然后在 SQLite 数据库中查找，如果命中则直接返回结果。
    - **API 调用**: 如果缓存未命中，则根据配置的顺序，依次调用 AI 提供商的 API 进行翻译。
    - **质量评估**: 对 API 返回的翻译结果进行质量打分，如果质量不达标，会自动尝试下一个配置的 API 提供商。
4.  **结果替换**: 最终的翻译结果会自动替换到用户当前的输入框中。

---

## 🛠️ 环境与安装

- **系统**: Windows 10/11 (x64)
- **依赖**: Python 3.12+, Poetry

**快速开始:**

```bash
# 1. 安装依赖
# 建议使用 Python 3.12 环境
pip install poetry
poetry install
poetry shell

# 2. 配置API密钥 (关键步骤)
# 程序启动前必须至少配置一个API密钥
# 运行以下命令，并按照菜单提示操作
poetry run python -m utils.api_key_tool

# 3. 启动程序
poetry run python start.py
```

**⚠️ 重要提示:**

- **API 密钥必须加密**: 在启动程序前，您**必须**使用 `api_key_tool` 来加密并设置您的 API 密钥。程序不会接受未加密的原始密钥。
- **配置文件**: 程序首次启动时，会自动在 `config/` 目录下生成 `config.yaml`, `mode_config.yaml`, `models.yaml` 三个配置文件。您可以根据需要进行修改。

---

## 📁 项目结构

```
.
├── start.py                            # 🔑 应用主入口：处理平台兼容性（OpenSSL, DPI感知, 路径解析）
├── pyproject.toml                      # 📦 Poetry依赖与项目配置
├── README.md                           # 📖 项目说明文档
├── AGENTS.md                           # 🤖 AI助手开发指南
├── config/                             # ⚙️ 运行时生成的配置文件目录
│   ├── config.yaml                     # 主配置文件：控制应用行为、网络、日志等
│   ├── mode_config.yaml                # 模式配置文件：定义翻译模式、语言特征和提示词
│   └── models.yaml                     # API配置文件：管理所有AI提供商和模型
├── core/                               # 🧠 项目核心逻辑层（异步架构）
│   ├── main.py                         # 🎯 应用生命周期管理与全局异常处理
│   ├── async_utils.py                  # 🔄 异步工具：在独立线程中运行和管理事件循环
│   ├── translation_engine.py           # 🧠 翻译引擎：集成语言检测、缓存、API调用和质量控制
│   ├── prompt_builder.py               # 💬 智能提示词构建器
│   ├── config_management.py            # 🗂️ 高级配置管理：Pydantic验证、路径回退、自动生成
│   ├── cache_manager.py                # 💾 混合缓存系统：内存LRU + SQLite持久化
│   ├── keyboard_listener.py            # ⌨️ 全局键盘监听器
│   ├── gui_handler.py                  # 🎨 GUI处理器（PyQt6）
│   ├── console_interface.py            # 💻 运行时交互控制台
│   ├── service_manager.py              # 🛠️ 服务管理器：统一管理网络、API、缓存等服务
│   ├── context_manager.py              # 🗣️ 上下文管理器：实现窗口感知的对话历史
│   ├── language_detection.py           # 🌍 多算法语言检测
│   ├── window_utils.py                 # 🪟 跨平台窗口工具
│   ├── cleanup_utils.py                # 🧹 后台定时清理任务（缓存、上下文）
│   ├── logging_config.py               # 📝 统一日志系统与敏感信息脱敏
│   ├── quality_assessment.py           # 📊 翻译质量评估引擎
│   ├── response_parser.py              # 📄 API响应解析器（Fallback）
│   ├── rules_engine.py                 # 📜 专家规则引擎：处理特定语言对的翻译规则
│   ├── text_utils.py                   # 🔤 基础文本处理工具
│   ├── network_utils.py                # 🌐 网络工具：SSL上下文、连接检查
│   ├── retry_utils.py                  # 🔄 统一的API请求重试工具
│   ├── api_manager.py                  # 🔗 API管理器：动态加载和调度多提供商
│   ├── constants.py                    # 📋 应用常量（版本号权威来源）
│   └── api_providers/                  # 🤖 AI API提供商实现层
│       ├── base.py                     # 🔧 提供商抽象基类
│       ├── gemini.py                   # 🌐 Google Gemini API客户端
│       ├── openai.py                   # 🚀 OpenAI及兼容API客户端
│       └── anthropic.py                # 📖 Anthropic Claude API客户端
├── utils/                              # 🛠️ 命令行工具
│   ├── api_crypto.py                   # 🔐 AES-GCM加密核心实现
│   └── api_key_tool.py                 # 🗝️ API密钥管理工具
├── test/                               # 🧪 测试模块
│   └── test_core_workflow.py           # 🔧 主工作流程测试
└── openssl_dll/                        # 🔧 Windows PyInstaller OpenSSL依赖
```

---

## 💡 故障排查

- **无法触发翻译**:
  - 检查 `config/models.yaml` 中是否已配置并加密了至少一个 API 密钥。
  - 确保没有其他程序占用了全局键盘钩子。
- **翻译失败**:
  - 启动程序后，在控制台中选择选项 `7` (API健康检查)，检查您的 API 服务是否可用。
  - 查看 `logs/app.log` 文件，获取详细的错误信息。
- **权限问题**:
  - 如果程序无法在当前目录创建 `config`, `logs`, `data` 等文件夹，它会自动尝试在用户主目录 (`C:/Users/YourUsername/.multitranslator`) 中创建。请确保这两个位置之一是可写的。

---

## 📄 许可

MIT License
