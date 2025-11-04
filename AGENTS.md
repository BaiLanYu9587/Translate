# AGENTS.md - Guide for AI Coding Agents

This document provides context and instructions for AI agents working on this project. Follow these guidelines to ensure consistency and prevent common errors.

---
description: "Rules that must be strictly enforced"
---
1. Basic Principles

Do not consider backward compatibility, only pursue generality and future scalability.

Reply to users only in Chinese.

Adopt Sequential Thinking MCP approach for gradual reasoning and problem-solving.

Strictly follow the rules defined in AGENTS.md, any code must be consistent with it.

2. Code Specifications

Do not write hard-coded code, placeholder code, or meaningless functions.

Code structure should be clear, avoid messy code, and maintain simplicity and maintainability.

Prohibit adding emojis or symbols unrelated to functionality in the code.

Follow first principles to identify and solve root causes of problems, rather than surface-level fixes.

3. Task Execution

Must fully understand the project and context before writing code.

Use task lists to break down and execute the development process step by step.

Prioritize finding optimal solutions, avoiding inefficient or redundant implementations.

Test code should be cleaned up after completion and not retained in the final submission.

4. Tools and Dependencies

When introducing new or unfamiliar libraries, must query the latest stable usage through Context7 MCP before implementation.

Maintain minimal dependencies to avoid bloating.

## Environment & Startup

- **Python Version**: This project requires Python 3.12 or higher.
- **Package Manager**: This project uses Poetry for dependency management.

### Installation and Startup
1.  **Install dependencies**:
    ```bash
    poetry install
    ```
2.  **Activate the virtual environment**:
    ```bash
    poetry shell
    ```
3.  **Run the application**:
    The main entry point provides a console interface for managing the application.
    ```bash
    poetry run python start.py
    ```

### Utilities
- **API Key Management**: To encrypt or decrypt API keys, use the provided tool. This is mandatory for setting up the application.
  - **Encrypt a key**: `poetry run python -m utils.api_key_tool --encrypt YOUR_RAW_API_KEY`
  - **Set a key for a provider**: `poetry run python -m utils.api_key_tool` and follow the interactive menu.

## Code Style

- **Language**: Python 3.8+ with strict type hinting.
- **Formatting**: Adhere to PEP 8 standards. Use an auto-formatter like Black if possible.
- **Architecture**: The project is modular:
    - `core/`: Contains all core business logic, including the translation engine, API providers, and service managers.
    - `utils/`: Holds helper scripts and utility classes, like the API crypography tool.
    - `config/`: All user-facing configuration is managed here. Do not hardcode values.
- **Configuration**: Use Pydantic models (defined in `core/config_management.py`) for validating and accessing configuration data.
- **Concurrency**: The application uses both `threading` for background tasks (like the console UI and keyboard listener) and `asyncio` for non-blocking I/O operations (API calls). Ensure thread-safety and proper async/await usage.

## Testing

- **Framework**: Tests are written using `pytest`.
- **Location**: All test files are located in the `test/` directory.
- **Running Tests**:
    - To run all tests:
      ```bash
      poetry run pytest
      ```
    - To run a specific test file:
      ```bash
      poetry run pytest test/test_main_workflow.py
      ```
    - To run code quality checks:
      ```bash
      poetry run ruff check . --fix && poetry run ruff format . && poetry run mypy . --config-file .mypy.ini
      ```

## Important Notes & Pitfalls

- ⚠️ **API Keys**: API keys **MUST** be encrypted using `utils.api_key_tool` (`poetry run python -m utils.api_key_tool`) before being added to `config/models.yaml`. The application will fail if it finds a raw, unencrypted key.
- **Configuration Files**: The application's behavior is heavily controlled by the YAML files in the `config/` directory. Before modifying logic, review `config.yaml` (main settings), `models.yaml` (API providers), and `mode_config.yaml` (translation rules).
- **Entry Point**: The primary entry point is `start.py`. It performs critical setup, such as configuring DLL search paths for OpenSSL on Windows, before importing the main application logic from `core/main.py`. Any changes to the startup sequence should be made there.
- **Stateful Directories**: The application automatically creates and manages `logs/`, `data/` (for the cache database), and `chat_contexts/` directories. These directories are essential for its operation and should not be deleted manually.