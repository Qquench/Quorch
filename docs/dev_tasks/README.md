# Quench Dev-Orchestrator Task Management

> This directory follows the **Quench Dual-Model DevTask Management Workflow (Architect Reviewer + Agile Runner)**.  
> All development conventions (status markers, the six core fields, session initiation protocols, architectural review guidelines, DoD verification standards) are defined in the built-in specifications:
> - Core Workflow: [`plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md`](../../plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md)
> - Reviewer Model Guidelines: [`plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md`](../../plugins/quench-dev-tasks/skills/dev-tasks-review/SKILL.md)
> - Coding & Testing Standards: [`plugins/quench-dev-tasks/rules/coding-standards.md`](../../plugins/quench-dev-tasks/rules/coding-standards.md)

---

## Technical Stack & Acceptance Criteria

| Attribute | Requirement |
| :--- | :--- |
| **Tech Stack** | Python (FastMCP) + Antigravity Plugin & Cursor Adapter Layer + CLI Tools |
| **Test Suite** | `$env:PYTHONPATH="plugins/quench-dev-tasks/server"; pytest plugins/quench-dev-tasks/server/tests -v` |
| **Architecture Spec** | [`dev_tasks_mcp_specification.md`](../../dev_tasks_mcp_specification.md) |
| **DoD Standards** | Full unit test suite passes 100%, zero hardcoded local machine paths, cross-platform UTF-8 encoding |

---

## Active & Archived Tasks

- **Active Tasks**: Tracked in current task documents in this directory (e.g. `2026-09-XX_*.md`).
- **Archived Tasks**: Completed tasks are archived in [`archive/`](./archive/) and automatically indexed in [`CHANGELOG.md`](../../CHANGELOG.md).
- **Inspecting Status**: Run `quench status` or invoke `dev_tasks_status` to view real-time state.

---

## 🌐 Language Freedom & Chinese Task Format (任务语言自由与中文规范)

Quench explicitly decouples **protocol specifications** (English SSOT) from **task content language** (Freedom of Choice):

- **Full Native Chinese Support**: DevTasks support Chinese headings and descriptions with zero friction. The backend schema validator natively accepts both English and Chinese heading aliases (`【涉及文件】` ≡ `[Affected Files]`, `【缺陷根因与修改目标】` ≡ `[Root Cause & Target]`, etc.).
- **Anti-Translation Invariant**: AI models are bound by the **Language Mirroring Contract** — models MUST mirror the task's existing language and are strictly forbidden from translating or normalizing Chinese tasks into English.

### Canonical Chinese 6-Core-Field Template (标准中文六大字段模板)

```markdown
### 任务 1 ⬜ 待确认: <任务标题>

#### 【涉及文件】
```
[MODIFY] path/to/source_file.py
[NEW] path/to/test_file.py
```

#### 【缺陷根因与修改目标】
根因：<缺陷根因或业务演进契机>
目标：<本任务期望达成的确定性工程交付物>

#### 【目标签名与类型契约】
```python
# 函数接口、数据模型或协议契约
```

#### 【分步改造指引】
1. 步骤一：数据结构与依赖变动
2. 步骤二：核心业务逻辑改造
3. 步骤三：编写配套单元测试断言

#### 【防御与边缘校验】
- 边界越界与空值防范
- 并发锁与超时保护
- 异常熔断与幂等清理

#### 【DoD 验证命令】
```bash
$env:PYTHONPATH="plugins/quench-dev-tasks/server"; python -m pytest plugins/quench-dev-tasks/server/tests -k "test_feature" -v
```
```

