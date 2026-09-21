# Frequently Asked Questions (FAQ)

[English](FAQ.md) | [简体中文](FAQ_zh.md)

This document collects common issues, troubleshooting tips, and technical questions encountered during the installation, configuration, and daily use of **Quench Dev-Orchestrator (`quorch`)**.

---

## Table of Contents
1. [MCP Interpreter & Runtime Environment](#1-mcp-interpreter--runtime-environment)
2. [Windows Console & Character Encoding (GBK / UTF-8)](#2-windows-console--character-encoding-gbk--utf-8)
3. [PreToolUse Interception Dialog & Hook Timeout](#3-pretooluse-interception-dialog--hook-timeout)
4. [Directory Renaming & File Handle Locks (PermissionError)](#4-directory-renaming--file-handle-locks-permissionerror)
5. [Windows MAX_PATH Path Length Warning](#5-windows-max_path-path-length-warning)
6. [Dual-Model Logical Roles & LLM Selection](#6-dual-model-logical-roles--llm-selection)
7. [Reviewer Engine API Setup, Proxy & Diagnostics](#7-reviewer-engine-api-setup-proxy--diagnostics)
8. [Draft Task State & Physical Feasibility Lint Gate](#8-draft-task-state--physical-feasibility-lint-gate)

---

### 1. MCP Interpreter & Runtime Environment

#### Q: IDE reports FastMCP not found or MCP Server fails to start?
- **Root Cause**: The IDE (Antigravity or Cursor) may be launching the MCP Server using the global system Python rather than the virtual environment where `fastmcp>=2.0` is installed.
- **Solution**:
  1. In the `quorch` root directory, execute the installer:
     ```bash
     python scripts/install.py
     ```
     The script automatically detects your active virtual environment or root `.venv` and populates the exact interpreter path into the IDE configurations.
  2. Run the environment diagnostic command:
     ```bash
     quench check
     # or
     python scripts/install.py --check
     ```

---

### 2. Windows Console & Character Encoding (GBK / UTF-8)

#### Q: PowerShell / CMD displays garbled characters or throws `UnicodeDecodeError`?
- **Root Cause**: The default Windows console code page is often CP936 (GBK) or CP437. When Python scripts output UTF-8 emojis or non-ASCII characters, console buffer encoding conflicts may occur.
- **Solution**:
  1. All internal Quench scripts preconfigure `sys.stdout.reconfigure(encoding="utf-8")` for fault tolerance.
  2. In PowerShell, you can temporarily switch the console to UTF-8:
     ```powershell
     chcp 65001
     $OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
     ```

---

### 3. PreToolUse Interception Dialog & Hook Timeout

#### Q: When an agent edits a file, the IDE suddenly pops up an authorization dialog?
- **This is the intended security mechanism**: The file the model is attempting to modify **does not belong to the `【涉及文件】` (Affected Files) whitelist** of the currently active DevTask.
- **Recommended Actions**:
  - If the edit is legitimate and necessary: Click **[Allow]** for a one-time exemption, or have the agent invoke `dev_tasks_set_bypass` for a temporary session bypass.
  - If the edit is an agent hallucination or unintentional scope creep: Click **[Deny]**. The guard will block the edit and prompt the model to refocus on the task scope.

#### Q: Hook reports timeout (Timeout > 5s)?
- **Root Cause**: Hook execution is blocked by external antivirus software or high system load.
- **Solution**: Quench Hooks are engineered to be lightweight, with normal execution latency under 20ms. If blocked by security suites, add the Python virtual environment to your antivirus exclusion list.

---

### 4. Directory Renaming & File Handle Locks (PermissionError)

#### Q: Renaming or installing fails with `[Directory Handle Locked] PermissionError`?
- **Root Cause**: A terminal window, IDE editor instance, or lingering background Python process holds an open file handle inside the directory.
- **Solution**:
  1. Run the pre-flight check to verify lock status:
     ```bash
     python scripts/install.py --preflight
     ```
  2. Close any terminal or IDE windows open inside the directory.
  3. Ensure no stray `python.exe` processes remain before retrying.

---

### 5. Windows MAX_PATH Path Length Warning

#### Q: Pre-flight check displays `[MAX_PATH Warning] Installation path length is ... characters`?
- **Root Cause**: The legacy Windows file API enforces a 260-character `MAX_PATH` limit. When the repository is cloned into deep directory trees, deeply nested test files may exceed this limit.
- **Solution**:
  - Clone the repository to a shallower path (e.g., `D:\Work\quorch`).
  - Or enable long path support in the Windows Registry:
    `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`.

---

### 6. Dual-Model Logical Roles & Universal Decoupling Design

#### Q: How does the decoupled architecture between Reviewer and Executor Agent (Runner) work? Are specific models required?
- **No specific models are required**: Quench is engineered around a **model-decoupled logical role architecture**:
  - **Reviewer (Architectural Review)**: Any model with strong reasoning, system architecture capabilities, and big-picture context (supports external reasoning APIs, local offline Ollama models, or IDE-native subagents);
  - **Executor Agent (Agile Runner)**: Any fast, cost-effective, high-instruction-following model for day-to-day coding.
- The two roles communicate via the MCP state machine and the six-core-field task contract, allowing developers to configure any combination tailored to their codebase and budget.

---

### 7. Reviewer Engine API Setup, Proxy & Diagnostics

#### Q: How do I configure external API reasoning models (DeepSeek, OpenAI, Ollama) for Reviewer?
- **Configuration**: Edit `.agents/quench_stack.yaml` under the `reviewer_engine` section. Set `provider: "deepseek"`, `api_key_env: "DEEPSEEK_API_KEY"`, and export your key in your environment.
- **Corporate Proxy & Resilient Networking**: The engine respects standard environment proxies (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`) with automated SSL context handling.
- **Testing Connectivity**: Run the dedicated CLI diagnostic tool:
  ```bash
  quench check-engine
  ```
  This command tests provider initialization, API key presence, upstream connection, and latency without modifying any files.
- **Where are the thoughts stored?**: Streaming reasoning thoughts are written directly to `.agents/logs/reviewer/thinking.log` with automated 1024KB safe rotation and token redaction.

---

### 8. Draft Task State & Physical Feasibility Lint Gate

#### Q: What is the `📝 Draft` (`📝 草案`) state and how does it protect the project?
- **Purpose**: When proposing speculative or complex architecture tasks, tasks can be marked with `is_draft=True`. Draft tasks are strictly segregated from the confirmed execution queue so that Runner models never accidentally checkout unready tasks.
- **Physical Feasibility Lint Gate**: Before promoting a draft via `dev_tasks_promote_draft`, the lint gate automatically verifies:
  1. No path traversal attacks (`../`) in Affected Files;
  2. Modified files actually exist on disk;
  3. Pre-flight check against file overwrite collisions;
  4. Non-executing syntax check (`pytest --collect-only`) to catch syntax errors before opening the task to execution.

