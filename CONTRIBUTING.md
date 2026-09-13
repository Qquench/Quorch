# Contributing to Quench Dev-Orchestrator (`quorch`)

[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING_zh.md)

Thank you for your interest in contributing to **Quench Dev-Orchestrator**! We welcome bug fixes, feature enhancements, documentation improvements, and architectural suggestions.

> [!TIP]
> **Author's Transparency Note on Cross-Tool & Cross-Platform Integrations**:  
> This project originated from real-world development needs on **Windows using Google Antigravity IDE**, and the core codebase has been thoroughly tested and verified. However, extending compatibility to other developer tools (such as **Cursor**) and non-Windows operating systems (macOS/Linux) was generated entirely by AI models based on architectural abstractions, as the author lacks practical development experience with those environments. Real-world edge cases or quirks may still surface. We warmly welcome community feedback, bug reports, and Pull Requests to test and harden these integrations!

---

## 🏗️ Development Environment Setup

### Prerequisites
- **Python**: Version 3.11 or higher.
- **Git**: Installed and available in your system path.
- **FastMCP**: `>=2.0` (installed automatically via `install.py` or `requirements.txt`).

### Local Bootstrap Steps
1. Fork and clone the repository:
   ```bash
   git clone https://github.com/your-username/quorch.git
   cd quorch
   ```
2. Create and activate a virtual environment:
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Run the installer to generate local configuration files:
   ```bash
   python scripts/install.py
   ```
4. Verify your setup with the test suite:
   ```bash
   # Windows (PowerShell)
   $env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests -v

   # macOS / Linux (bash)
   PYTHONPATH="plugins/quench-dev-tasks/server" python -m pytest plugins/quench-dev-tasks/server/tests -v
   ```

---

## 📐 Engineering Guidelines

### 1. The Six-Core-Field DevTask Standard
All non-trivial changes should be planned using standard DevTasks containing the six core fields:
- **Affected Files** (`【涉及文件】`): Explicit whitelist with `[MODIFY]`, `[NEW]`, `[DELETE]`, `[RENAME]` prefixes.
- **Root Cause & Target** (`【缺陷根因与修改目标】`): Clear problem statement and objective.
- **Type Contracts** (`【目标签名与类型契约】`): Interface signatures and return types.
- **Step-by-Step Instructions** (`【分步改造指引】`): Sequential numbered steps.
- **Defensive & Edge Checks** (`【防御与边缘校验】`): Defensive bounds, concurrency handling, and fallback behavior.
- **DoD Verification Commands** (`【DoD 验证命令】`): Concrete test commands that must be executed and pass.

### 2. Test-Driven Development (TDD)
- **Zero Regression**: All existing 105+ tests must continue to pass 100%.
- **Assertion Coverage**: Any bug fix or new feature must include accompanying unit test assertions in `plugins/quench-dev-tasks/server/tests/`.
- **Zero Local Hardcoded Paths**: Never commit personal absolute file paths (such as `C:\Users\...` or `D:\Work\...`). Always resolve paths dynamically using `os.path.dirname(os.path.abspath(__file__))`.

### 3. Cross-Platform Compatibility
- Ensure all terminal operations and scripts cleanly handle Windows, macOS, and Linux.
- Always configure standard I/O streams with UTF-8 encoding (`sys.stdout.reconfigure(encoding="utf-8")`) to prevent Windows CP936/GBK decode errors.
- Wrap file paths in double quotes in commands to support directories with spaces.

---

## 🚀 Pull Request Workflow

1. Create a descriptive feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Implement your changes following the coding standards and add unit tests.
3. Run pre-commit checks and the full test suite:
   ```bash
   python scripts/install.py --preflight
   $env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests -v
   ```
4. Commit your changes using conventional commit messages (e.g., `feat(engine): add ...`, `fix(guard): handle ...`, `docs: update ...`).
5. Push to your fork and submit a Pull Request to the `master` branch.
