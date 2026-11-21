# 2026-11-21_v1_35_vendor_neutral_subagent_tier_routing Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-21

---

## Task List & Status / 任务清单与状态

### 任务 35.1 ✔️ 已完成 — 规则、Skill 与三端入口路由卡的厂商/档位中立路由契约补全

#### 【涉及文件】
```
[MODIFY] AGENTS.md
[MODIFY] plugins/quench-dev-tasks/rules/AGENTS.md
[MODIFY] plugins/quench-dev-tasks/templates/AGENTS.md
[MODIFY] plugins/quench-dev-tasks/rules/dev-tasks-discipline.md
[MODIFY] plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md
```

#### 【缺陷根因与修改目标】
```
在 inverted（委派）编排模式下，宿主子代理默认契约偏向 inherit，而 Quench 现有规则（dev-tasks-discipline.md）、操作手册（SKILL.md）与三端入口路由卡（AGENTS.md）尚未明确子代理委派的厂商与代际中立模型档位选择策略，导致主会话在未收到口头提醒时默认继承主会话推理大模型。目标：在不硬编码任何瞬态模型或档位字面量的前提下，按 Rules > Skills > AGENTS.md 分层补全两级优先级的语义档位路由契约（显式 runner_subagent_model_hint 优先；缺省时 RUNNER/RESEARCH 优先宿主轻量/快速执行档位而非 inherit，REVIEWER 优先强推理档位）。
```

#### 【目标签名与类型契约】
```
文档分层契约（Rules > Skills > AGENTS.md）：
- Rules (`dev-tasks-discipline.md` §4.④): 完整两级优先级路由契约 + 对称 REVIEWER 强推理档位约束 + 允许回退/升级条件 + 零瞬态字面量原则
- Skills (`dev-tasks-workflow/SKILL.md` §1): RESEARCH & RUNNER 派发时的实操档位选择指引（遵循 test_onboarding_doc_contract 无 param default 字面量正则）
- Router Cards (`AGENTS.md` / `rules/AGENTS.md` §4 & `templates/AGENTS.md` §6): <= 120 行预算，哨兵块三端逐字一致，紧凑 1 行 Delegation Tier 路由声明
```

#### 【分步改造指引】
1. 更新 plugins/quench-dev-tasks/rules/dev-tasks-discipline.md：在 §4 末尾（### ③ Resume Verification 之后、分隔线 --- 之前）新增 ### ④ Subagent Delegation Tier Routing (子代理委派档位路由纪律)，完整定义：零瞬态档位字面量约束、Priority 1（非空 runner_subagent_model_hint 优先）、Priority 2（缺省时 [QUENCH-DISPATCH: RUNNER] 与 [QUENCH-DISPATCH: RESEARCH] 优先选择宿主可用轻量/快速执行档位，禁止无条件继承主会话模型 inherit；仅在宿主无更轻档位或复杂推理连续失败时允许升级/回退）、以及对称约束（standard + host_subagent 下 [QUENCH-DISPATCH: REVIEWER] 优先强推理档位）。
2. 更新 plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md：在 ### Inverted Dual-Layer Code Exploration（Layer 1）与 ### Runner Subagent Reuse vs. Fresh Spawn Policy 中补充模型档位选择操作指引（显式 model_hint 优先，未显式配置时从宿主可用选项中择优选择轻量/快速执行档位而非直接继承主会话模型，失败时可升级；并注明 [QUENCH-DISPATCH: REVIEWER] 优先强推理档位）。务必避开 test_onboarding_doc_contract.py 的参数默认字面量正则陷阱。
3. 更新 AGENTS.md 与 plugins/quench-dev-tasks/rules/AGENTS.md（保持两文件逐字节完全一致，且不改动哨兵块）：在 ## 4. Subagent Protocol & Envelope Dispatch 末尾追加 1 行紧凑 Delegation Tier 路由原则。
4. 更新 plugins/quench-dev-tasks/templates/AGENTS.md（不改动任何 <!-- QUENCH-CORE-INVARIANTS:BEGIN/END --> 哨兵块，保持总行数 <= 120）：在 ## 5 哨兵块之后追加紧凑的 ## 6. Subagent Delegation Tier 节，承载同源的 1 行中立路由原则。
5. 运行 DoD 验证命令，确认三端同步、模板生成、文档卫生、onboarding 契约、反角色扮演与规则导出测试 100% 绿灯。

#### 【防御与边缘校验】
严格遵守三端哨兵块同步契约：AGENTS.md、plugins/quench-dev-tasks/rules/AGENTS.md、plugins/quench-dev-tasks/templates/AGENTS.md 的两个 <!-- QUENCH-CORE-INVARIANTS:BEGIN/END --> 区块逐字完全一致，且三文件总行数均严格 <= 120 行。
严防 test_onboarding_doc_contract.py 参数默认字面量误杀：plugins/quench-dev-tasks/skills/dev-tasks-workflow/SKILL.md 正文严禁出现 '默认 <标识符>'、'默认 `<标识符>`'、'defaults to <标识符>' 或 'default: <标识符>' 连续搭配，改用 '禁止直接继承主会话模型（`inherit`）'、'未显式配置时' 等语义表达。
保持 dev-tasks-discipline.md 全部既有标题与契约不删减（BASELINE_DISCIPLINE_HEADINGS、INV-1..INV-9、六核心字段双语标题、> [!IMPORTANT] 且无 > [!NOTE]、Continuous Relay Non-Braking Invariant）。
所有新增规则与 Skill 文档均遵循零厂商与零瞬态档位字面量原则（不出现具体厂商/代际档位名称），仅以能力与成本语义表达（lightweight/fast tier vs strong-reasoning tier）与可选键 runner_subagent_model_hint。
保持宿主中立抽象动词（test_doc_contract_hygiene.py），不引入宿主私有工具名。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_agents_md_sync.py plugins/quench-dev-tasks/server/tests/test_agents_md_template.py plugins/quench-dev-tasks/server/tests/test_doc_contract_hygiene.py plugins/quench-dev-tasks/server/tests/test_onboarding_doc_contract.py plugins/quench-dev-tasks/server/tests/test_anti_roleplay_discipline_contract.py plugins/quench-dev-tasks/server/tests/test_rules_exporter.py
```

---

### 任务 35.2 ✔️ 已完成 — Runtime Role Contract、Harness Instruction 与 Hook Baton 档位语义对齐及门禁测试

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/runtime_mode.py
[MODIFY] plugins/quench-dev-tasks/server/autopilot_harness.py
[MODIFY] plugins/quench-dev-tasks/server/hooks/context_injector.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py
```

#### 【缺陷根因与修改目标】
```
当前服务端三处运行时信号存在断层：(1) runtime_mode.py::generate_session_role_contract 在 inverted 模式下未随 runner_subagent_model_hint 状态提供档位选择指引；(2) autopilot_harness.py::compute_next_action 生成的 DISPATCH_RUNNER.instruction 在 in_progress 与 confirmed 两个分支均缺失档位偏好语义；(3) hooks/context_injector.py::_resolve_harness_baton 调用 compute_next_action 时漏传 runner_subagent_model_hint=snapshot.runner_subagent_model_hint。目标：对齐三端运行时与 Hook 接力信号，补齐单测与核心模块/规范文档零瞬态档位字面量回归门禁，并保持响应字节预算与零 Schema 膨胀。
```

#### 【目标签名与类型契约】
```
- runtime_mode.py:
  def generate_session_role_contract(
      effective_mode: OrchestrationMode,
      runner_subagent_model_hint: Optional[str] = None,
  ) -> SessionRoleContract
- autopilot_harness.py:
  def _format_runner_tier_guidance(runner_subagent_model_hint: Optional[str]) -> str
  # compute_next_action(...) 签名不变，DISPATCH_RUNNER 两分支 instruction 携带紧凑档位提示
- hooks/context_injector.py:
  # _resolve_harness_baton 调用 compute_next_action(..., runner_subagent_model_hint=snapshot.runner_subagent_model_hint)
- tests/test_no_vendor_literals_in_core.py:
  TRANSIENT_TIER_PATTERN: re.Pattern[str] = re.compile(r"\b(?:flash|flash_lite|pro|hydrogen)\b", re.IGNORECASE)
  def find_transient_tier_violations(targets: Iterable[Path]) -> list[VendorViolation]
```

#### 【分步改造指引】
1. 修改 plugins/quench-dev-tasks/server/runtime_mode.py::generate_session_role_contract：在 effective_mode == 'inverted' 分支的 primary_guidelines 末尾追加第 4 条中立指引：当 normalized_hint 非空时注入 '委派 Runner / Research 子代理优先使用指定档位提示: {normalized_hint}（若宿主不可用则回退轻量执行档位）。'；为空时注入 '委派 Runner / Research 子代理时优先选用宿主可用的轻量/快速执行档位（prefer lightweight/fast tier over inheriting main session model），勿默认继承主会话模型。'。
2. 修改 plugins/quench-dev-tasks/server/autopilot_harness.py：新增纯辅助函数 _format_runner_tier_guidance(runner_subagent_model_hint: Optional[str]) -> str（非空返回 'model_hint={hint}'，否则返回 'prefer lightweight/fast tier, not inherit / 优先轻量快速档位，勿继承主模型'）；在 compute_next_action 的 DISPATCH_RUNNER 两个分支（in_progress_tasks 与 confirmed_tasks）的 instruction 中紧凑拼接该档位提示，同时完整保留原有 reuse/spawn 提示子串。
3. 修改 plugins/quench-dev-tasks/server/hooks/context_injector.py::_resolve_harness_baton：在调用 compute_next_action(...) 时补传 runner_subagent_model_hint=snapshot.runner_subagent_model_hint。
4. 补齐单元测试：在 test_autopilot_harness_baton.py 增加 in_progress/confirmed 两分支的 None、非空自定义占位 hint（如 'custom-lightweight-tier'）与纯空白 hint 断言及 compact payload 字节预算断言；在 test_dual_mode_runtime_switch.py 增加 generate_session_role_contract inverted/standard 模式及 hint 空/非空断言；在 test_context_injector_autopilot_harness.py 增加 _resolve_harness_baton 真实透传 runner_subagent_model_hint（None 与自定义值）端到端单测。
5. 强化 plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py：新增词边界正则瞬态档位字面量扫描器（覆盖顶层核心 server/*.py、hooks/context_injector.py 以及 AGENTS.md / rules/AGENTS.md / templates/AGENTS.md / rules/dev-tasks-discipline.md / skills/dev-tasks-workflow/SKILL.md），并新增正负向自证单测（命中孤立瞬态档位词且不误杀 process/project/propose 等词）。
6. 执行针对性测试套件及全量 pytest plugins/quench-dev-tasks/server/tests，确认 100% 通过。

#### 【防御与边缘校验】
对 runner_subagent_model_hint 进行空白安全归一化（仅剥离首尾空白判断非空，空白字符串回退到轻量档位语义提示），避免仅含空格的字符串误触发 model_hint= 空值。
严守 RESPONSE_BUDGET_BYTES（dev_tasks_status compact <= 2048B 硬上限，常规状态保持 < 1024B 软警告线），DISPATCH_RUNNER.instruction 附加提示必须极简且保留既有 'reuse active runner subagent' / 'spawn a fresh isolated runner subagent' 子串以维持向后兼容。
保持 compute_next_action 纯函数零磁盘 I/O 特性（test_compute_next_action_zero_io_pure）。
test_no_vendor_literals_in_core.py 新增瞬态档位字面量回归门禁必须使用词边界正则（如 \\b(?:flash|flash_lite|pro|hydrogen)\\b），严禁使用子串匹配导致误杀 process/project/propose/protocol 等合法英文词，并附带自证正负向用例防假绿。
不修改 dev_tasks_status 工具参数签名，保持 MAX_TOOL_SCHEMA_BYTES 零增长。

#### 【DoD 验证命令】
```bash
pytest plugins/quench-dev-tasks/server/tests/test_autopilot_harness_baton.py plugins/quench-dev-tasks/server/tests/test_dual_mode_runtime_switch.py plugins/quench-dev-tasks/server/tests/test_context_injector_autopilot_harness.py plugins/quench-dev-tasks/server/tests/test_no_vendor_literals_in_core.py plugins/quench-dev-tasks/server/tests/test_response_budget_ssot.py plugins/quench-dev-tasks/server/tests/test_observability.py
pytest plugins/quench-dev-tasks/server/tests
```

---

