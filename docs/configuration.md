# Quench Configuration Guide (`quench_stack.yaml`)

[English](configuration.md) | [简体中文](configuration_zh.md)

This document provides a comprehensive reference for configuring **Quench Dev-Orchestrator (`quorch`)** in your repository via `.agents/quench_stack.yaml`.

---

## 1. Overview & Architecture

Every repository governed by Quench defines its rules, constraints, and model routing in `.agents/quench_stack.yaml`.  
This manifest completely decouples the governance engine from specific project business logic and programming languages.

```text
<your-project-root>/
├── .agents/
│   ├── plugins.json            # Registers quench-dev-tasks plugin
│   ├── quench_stack.yaml       # Project governance manifest (Single Source of Truth)
│   └── logs/reviewer/          # Real-time thinking stream logs (Auto-created)
│       └── thinking.log
└── docs/dev_tasks/             # Task lifecycle workflow sheets
    └── archive/                # Completed task archives
```

---

## 2. Core Repository Metadata

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `schema_version` | `string` | `"1.0"` | Configuration schema version (managed automatically by migration engine). |
| `project_name` | `string` | **Required** | Canonical name of the target project or service. |
| `dev_tasks_dir` | `string` | `"docs/dev_tasks"` | Relative directory path where active task markdown sheets are located. |
| `archive_dir` | `string` | `"docs/dev_tasks/archive"` | Relative directory path where completed task sheets are retired. |
| `changelog_path` | `string` | `"CHANGELOG.md"` | Relative path to the project changelog file. |
| `test_runner` | `string` | `null` | Default automated test command executed during DoD audit (e.g. `pytest tests/ -v` or `npm test`). |
| `test_dir` | `string` | `"tests"` | Primary test suite directory. |
| `architecture_doc`| `string` | `null` | Optional path to primary system architecture specification (e.g. `docs/architecture.md`). |

---

## 3. Engineering Constraints & Guidelines

The `constraints` list injects domain-specific architectural boundaries and security invariants directly into agent system prompts during task proposing, refinement, and review:

```yaml
constraints:
  - "All core algorithmic updates must be covered by automated unit tests"
  - "Public API interface changes must remain backward-compatible"
  - "Production secrets, credentials, and API keys must never be hardcoded"
```

---

## 4. Governance Boundaries & Fast-Track Tiers

Quench employs a **3-tier defense** against unauthorized modifications:

```yaml
# Layer 1: Static Whitelist (Glob patterns exempt from task state-machine checks)
fast_track_rules:
  allow_untracked_patterns:
    - "docs/**"
    - "*.md"
    - "notes/**"

# Optional: Explicit Governance Boundaries
governance_scope:
  # 🔴 Managed production scope (Strict state machine & Affected Files whitelist enforced)
  managed_paths:
    - "src/**"
    - "plugins/**"
    - "package.json"
  # 🟢 Unmanaged documentation & assets (Exempt from task interception)
  unmanaged_paths:
    - "docs/**"
    - "*.md"
```

- **Tier 1 (Static Whitelist)**: Patterns defined in `allow_untracked_patterns` bypass PreToolUse interception automatically. Keep this list minimal!
- **Tier 2 (Session Bypass)**: Agents can request temporary fast-track bypass (`dev_tasks_set_bypass`) for micro-edits (e.g. typo fixes). Sessions are time-bounded (default 4 hours) with anti-abuse guards.
- **Tier 3 (Interactive Ask Modal)**: Out-of-scope edits trigger an interactive prompt in the IDE, requiring developer confirmation before modification touches disk.

---

## 5. Reviewer Engine & External Architect Dispatch (`reviewer_engine`)

The `reviewer_engine` block decouples strategic reasoning models (Reviewer) from everyday agile coding (Runner). It supports multiple pluggable LLM providers, corporate proxies, and streaming observability.

```yaml
reviewer_engine:
  # Dispatch mode: "auto" | "subagent" | "engine" | "manual"
  mode: "auto"

  # Strategy fallback sequence (falls back sequentially if a provider is unavailable)
  strategy_order:
    - "subagent"
    - "engine"
    - "manual"

  # Upstream API Provider: "deepseek" | "openai" | "ollama" | "custom" | "none"
  provider: "deepseek"

  # Model identifier
  model: "deepseek-flash"

  # Environment variable name containing your API key (NEVER hardcode keys in plaintext!)
  api_key_env: "DEEPSEEK_API_KEY"

  # API Base URL endpoint
  base_url: "https://api.deepseek.com"

  # Enable streaming reasoning_content (Chain-of-Thought thinking stream)
  thinking: true

  # Reasoning effort budget: "low" | "medium" | "high"
  reasoning_effort: "high"

  # Network timeout in seconds per request
  timeout_seconds: 60

  # Max retry attempts on transient network errors
  max_retries: 2

  # Max multi-turn tool hops during specification refinement
  max_tool_hops: 3
```

### Supported Providers

| Provider | Typical Models | Base URL | Highlights |
| :--- | :--- | :--- | :--- |
| **`deepseek`** | `deepseek-chat`, `deepseek-reasoner`, `deepseek-flash` | `https://api.deepseek.com` | Native `reasoning_content` stream extraction, automated Prompt Cache token billing detection. |
| **`openai`** | `gpt-4o`, `gpt-4o-mini`, `o1`, `o3-mini` | `https://api.openai.com/v1` | Standard OpenAI chat completion format. |
| **`ollama`** | `deepseek-r1:14b`, `qwen2.5-coder:14b` | `http://localhost:11434/v1` | 100% offline, local GPU inference, zero external API key requirements. |
| **`subagent`** | IDE Native Subagent (`reviewer`) | N/A | Leverages IDE host subscription quota (e.g. Antigravity Pro Plan) with zero incremental API cost. |
| **`manual`** | Human Architect | N/A | Graceful fallback generating structured interactive review handoff cards. |

---

## 6. Observability & Thinking Stream Logs

When external reasoning models stream Chain-of-Thought thoughts, Quench automatically:
1. Pipes thoughts into `.agents/logs/reviewer/thinking.log`;
2. Enforces a **1024KB hard cap** with automated single-backup rotation (`thinking.log.1`);
3. Performs streaming regex redaction across chunk boundaries (masking API keys, secrets, and private tokens);
4. Emits ~1.0s throttled progress heartbeats back to the IDE, keeping the MCP `sys.stdout` JSON-RPC transport completely unpolluted.

---

## 7. Diagnostics & Health Checks

You can verify your configuration and test your Reviewer Engine connectivity from the command line:

```bash
# Verify environment and quench_stack.yaml syntax
quench check

# Test Reviewer Engine connectivity, API key validity, and latency
quench check-engine
```
