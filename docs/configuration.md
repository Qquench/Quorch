# Quench Configuration Guide (`quench_stack.yaml`)

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

The `reviewer_engine` block decouples strategic reasoning models (Reviewer) from everyday agile coding (Runner). It supports multiple pluggable LLM providers, corporate proxies, and streaming observability. By default, `provider: "none"` disables direct API calls, routing to native subagents or graceful manual fallbacks.

```yaml
reviewer_engine:
  # Dispatch mode: "auto" | "subagent" | "engine" | "manual"
  mode: "auto"

  # Strategy fallback sequence (falls back sequentially if a provider is unavailable)
  strategy_order:
    - "subagent"
    - "engine"
    - "manual"

  # Upstream API Provider: "none" | "openai" | "deepseek" | "ollama" | "vllm" | "generic-openai" | "custom"
  provider: "none"

  # Model identifier (defaults to "default" when provider is "none")
  model: "default"

  # Environment variable name containing your API key (NEVER hardcode keys in plaintext!)
  api_key_env: null

  # API Base URL endpoint (OpenAI-compatible /chat/completions endpoint)
  base_url: "https://api.openai.com/v1"

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

### Supported Provider Presets (`PROVIDER_PRESETS`)

| Provider Preset | Default Model | Default Base URL | Authentication | Key Features |
| :--- | :--- | :--- | :--- | :--- |
| **`none`** | `default` | `https://api.openai.com/v1` | None | Completely disables external API calls; triggers graceful fallback. |
| **`openai`** | `gpt-4o` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | Standard OpenAI endpoints and reasoning models (o1, o3-mini). |
| **`deepseek`** | `deepseek-chat` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | Native `reasoning_content` stream extraction & Prompt Cache detection. |
| **`ollama`** | `qwen2.5-coder:14b` | `http://localhost:11434/v1` | None (Local) | 100% offline local inference, zero external credentials required. |
| **`vllm`** | `default` | `http://localhost:8000/v1` | None (Local) | High-throughput local/private server deployment with OpenAI compatibility. |
| **`generic-openai`** | `default` | `https://api.openai.com/v1` | `OPENAI_API_KEY` | Compatible proxy gateway / aggregator for standard chat completions. |
| **`custom`** | User-defined | User-defined | User-defined | Custom private endpoint (remote endpoints require `api_key_env`). |

---

## 6. Observability & Thinking Stream Logs

When external reasoning models stream Chain-of-Thought thoughts, Quench automatically:
1. Pipes task refinement thoughts into `.agents/logs/reviewer/thinking.log`;
2. Pipes ad-hoc consultation thoughts into `.agents/logs/reviewer/latest-<session_id>.log`;
3. Enforces a **1024KB hard cap** with automated single-backup rotation (`*.log.1`);
4. Performs streaming regex redaction across chunk boundaries (masking API keys, secrets, and private tokens);
5. Emits ~1.0s throttled progress heartbeats back to the IDE, keeping the MCP `sys.stdout` JSON-RPC transport completely unpolluted.

---

## 7. Ad-Hoc Architecture Consultation (`dev_reviewer_consult`)

For spontaneous technical discussions, trade-off evaluations, or red-team audits without binding to a DevTask lifecycle, agents and users can invoke `dev_reviewer_consult`:

```python
dev_reviewer_consult(
    workspace_root=".",
    query="Evaluate state machine concurrency risks under multi-tab access",
    context_files=["server/state_machine.py:40-120"],
    mode="critique",      # "critique" | "evaluate" | "brainstorm" | "audit"
    max_hops=1,          # Multi-turn context extension rounds (0-3)
    session_id=None,     # Log file correlation identifier
)
```

### Consultation Modes

- **`critique`** (Red-Team Threat Modeling): Relentlessly challenges assumptions, highlights concurrency/persistence race conditions, and categorizes risks by severity.
- **`evaluate`** (Technical Trade-Off Matrix): Multi-dimensional comparative analysis (Theoretical Benefits vs. Operational Costs vs. Rollback Paths).
- **`brainstorm`** (Architectural Exploration): Explores divergent patterns, proof-of-concept tests, and novel architectural approaches.
- **`audit`** (Contract & Implementation Conformance): Read-only line-anchored audit checking code against architectural contracts.

### Anti-Roleplaying Invariant & Degraded Cards

If the Reviewer engine is unconfigured (`provider: "none"`), disconnected, or timed out:
- The tool returns a structured degraded card: `{"status": "degraded", "degraded_reason": "...", "findings": "", "handoff_prompt": "..."}`;
- **`findings` is strictly empty string (`""`)**;
- In-context roleplaying or hallucinating critique text by the everyday executor model is strictly prohibited by governance rules.

---

## 8. Diagnostics & Health Checks

You can verify your configuration and test your Reviewer Engine connectivity from the command line:

```bash
# Verify environment and quench_stack.yaml syntax
quench check

# Test Reviewer Engine connectivity, API key validity, and latency
quench check-engine
```

