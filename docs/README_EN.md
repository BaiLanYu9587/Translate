# Multilingual Translator

[English](../README.md) | [中文](README_ZH.md) | [日本語](README_JA.md) | [Français](README_FR.md) | [Deutsch](README_DE.md) | [한국어](README_KO.md)

---

AI-powered desktop translation tool with multi-API provider support, triggered by global hotkey (triple-tap Space).

- **Workflow**: Copy text → Triple-tap Space → Auto-translate & replace
- **Target Platform**: Windows 10/11 (x64)

---

## ✨ Key Features

- **Multi-AI Provider Support**: Dynamic loading of Google Gemini, Anthropic Claude, OpenAI, and all OpenAI-compatible API services.
- **Global Hotkey**: Trigger translation with triple-tap Space in any input field without switching windows.
- **Intelligent Cache System**: High-performance dual-layer cache (memory LRU + SQLite persistence) to dramatically reduce API calls and costs.
- **Context-Aware Translation**: Distinguishes different conversation contexts based on current window titles for coherent translations.
- **Translation Quality Assessment**: Automatically evaluates translation quality and intelligently retries when quality is insufficient.
- **Robust Async Architecture**: Utilizes `asyncio` and multi-threading for high-performance concurrent requests and smooth user experience.
- **Advanced Configuration Management**:
  - Strict configuration validation using Pydantic models.
  - Automatic fallback to user home directory when program directory is not writable.
- **Secure Key Management**: Built-in AES-GCM encryption tool for secure API key storage.
- **Developer Tools**: Feature-rich runtime console supporting mode switching, hot config reload, API health checks, and network diagnostics.
- **Robust Startup Program**: Automatically handles OpenSSL dynamic library dependencies, high-DPI display, and temporary file cleanup in Windows environments.

---

## 🚀 Core Workflow

![Demo Animation](动画演示.gif)

1.  **Trigger Translation**: User triple-taps Space in any application's input field to activate translation.
2.  **Get Text**: Program automatically retrieves text from system clipboard.
3.  **Smart Processing**:
    - **Language Detection**: Automatically identifies source language.
    - **Cache Query**: Searches memory cache first, then SQLite database; returns immediately if hit.
    - **API Call**: If cache misses, calls AI provider APIs in configured order for translation.
    - **Quality Assessment**: Scores the API-returned translation quality; automatically tries next configured API provider if quality is insufficient.
4.  **Result Replacement**: Final translation is automatically replaced into user's current input field.

---

## 🛠️ Environment & Installation

- **System**: Windows 10/11 (x64)
- **Dependencies**: Python 3.11 or 3.12, Poetry

**Quick Start:**

```bash
# 1. Install dependencies
# Python 3.11 or 3.12 environment recommended
pip install poetry
poetry install
poetry shell

# 2. Configure API keys (critical step)
# At least one API key must be configured before starting the program
# Run the following command and follow menu prompts
poetry run python -m utils.api_key_tool

# 3. Start the program
poetry run python start.py
```

**⚠️ Important Notes:**

- **API Keys Must Be Encrypted**: You **must** use `api_key_tool` to encrypt and set your API keys before starting the program. Raw unencrypted keys are not accepted.
- **Configuration Files**: On first startup, the program automatically generates three configuration files in the `config/` directory: `config.yaml`, `mode_config.yaml`, `models.yaml`. You can modify them as needed.

---

## 📁 Project Structure

```
.
├── start.py                            # 🔑 Application entry point: handles platform compatibility (OpenSSL, DPI awareness, path resolution)
├── pyproject.toml                      # 📦 Poetry dependencies & project configuration
├── README.md                           # 📖 Project documentation
├── AGENTS.md                           # 🤖 AI assistant development guide
├── config/                             # ⚙️ Runtime-generated configuration directory
│   ├── config.yaml                     # Main config: controls app behavior, network, logging, etc.
│   ├── mode_config.yaml                # Mode config: defines translation modes, language features, and prompts
│   └── models.yaml                     # API config: manages all AI providers and models
├── core/                               # 🧠 Core logic layer (async architecture)
│   ├── main.py                         # 🎯 Application lifecycle management & global exception handling
│   ├── async_utils.py                  # 🔄 Async utilities: runs and manages event loop in dedicated thread
│   ├── translation_engine.py           # 🧠 Translation engine: integrates language detection, caching, API calls, and quality control
│   ├── prompt_builder.py               # 💬 Intelligent prompt builder
│   ├── config_management.py            # 🗂️ Advanced config management: Pydantic validation, path fallback, auto-generation
│   ├── cache_manager.py                # 💾 Hybrid cache system: memory LRU + SQLite persistence
│   ├── keyboard_listener.py            # ⌨️ Global keyboard listener
│   ├── gui_handler.py                  # 🎨 GUI handler (PyQt6)
│   ├── console_interface.py            # 💻 Runtime interactive console
│   ├── service_manager.py              # 🛠️ Service manager: unified management of network, API, cache, etc.
│   ├── context_manager.py              # 🗣️ Context manager: implements window-aware conversation history
│   ├── language_detection.py           # 🌍 Multi-algorithm language detection
│   ├── window_utils.py                 # 🪟 Cross-platform window utilities
│   ├── cleanup_utils.py                # 🧹 Background scheduled cleanup tasks (cache, context)
│   ├── logging_config.py               # 📝 Unified logging system & sensitive data sanitization
│   ├── quality_assessment.py           # 📊 Translation quality assessment engine
│   ├── response_parser.py              # 📄 API response parser (fallback)
│   ├── rules_engine.py                 # 📜 Expert rules engine: handles translation rules for specific language pairs
│   ├── text_utils.py                   # 🔤 Basic text processing utilities
│   ├── network_utils.py                # 🌐 Network utilities: SSL context, connection checks
│   ├── retry_utils.py                  # 🔄 Unified API request retry utilities
│   ├── api_manager.py                  # 🔗 API manager: dynamic loading and scheduling of multiple providers
│   ├── constants.py                    # 📋 Application constants (authoritative version source)
│   └── api_providers/                  # 🤖 AI API provider implementation layer
│       ├── base.py                     # 🔧 Provider abstract base class
│       ├── gemini.py                   # 🌐 Google Gemini API client
│       ├── openai.py                   # 🚀 OpenAI and compatible API client
│       └── anthropic.py                # 📖 Anthropic Claude API client
├── utils/                              # 🛠️ Command-line tools
│   ├── api_crypto.py                   # 🔐 AES-GCM encryption core implementation
│   └── api_key_tool.py                 # 🗝️ API key management tool
├── test/                               # 🧪 Test modules
│   └── test_core_workflow.py           # 🔧 Main workflow tests
└── openssl_dll/                        # 🔧 Windows PyInstaller OpenSSL dependencies
```

---

## 💡 Troubleshooting

- **Cannot Trigger Translation**:
  - Check if at least one encrypted API key is configured in `config/models.yaml`.
  - Ensure no other programs are occupying the global keyboard hook.
- **Translation Fails**:
  - After starting the program, select option `7` (API health check) in the console to verify API service availability.
  - Check `logs/app.log` for detailed error information.
- **Permission Issues**:
  - If the program cannot create `config`, `logs`, `data` folders in the current directory, it will automatically try to create them in the user home directory (`C:/Users/YourUsername/.multitranslator`). Ensure at least one of these locations is writable.

---

## 📄 License

MIT License
