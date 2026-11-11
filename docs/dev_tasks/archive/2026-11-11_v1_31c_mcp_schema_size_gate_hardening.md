# 2026-11-11_v1_31c_mcp_schema_size_gate_hardening Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-11

---

## Task List & Status / 任务清单与状态

### 任务 31.3 ✔️ 已完成 — Schema 尺寸门禁物理化落地与模板断言硬化

#### 【涉及文件】
```
[MODIFY] plugins/quench-dev-tasks/server/ide_schema_export.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_templates.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py
```

#### 【缺陷根因与修改目标】
```
根据外部 Reviewer 架构审查裁决（Job: job_1794370768_75f83887, job_1794371019_75d1e98b, job_1794371259_8d4ca3f1, job_1794371495_ae8ad9e8, job_1794371714_881f294a）：
根因 D1（门禁外挂 fail-open）：v1.31-R1 引入的 1000B 物理尺寸门禁仅存在于 test_snapshot_drift_gate_contract.py 的 pytest 单测中；生产生成管道 export_ide_schemas / ide_schema_export.run_cli 的 --check 只做字节比对、--write 不拒超限写入。开发者在本地 --write 生成超限快照后只要不跑特定用例即可提交，违背「软约束必须下沉为物理硬门禁」。
根因 D2（静默回退绿）：test_templates.py 以 or / if-else 兼容 legacy 键 quench-dev-tasks，导致 server key 被静默回退时渲染测试仍绿。
修改目标：
1. 在 ide_schema_export.run_cli 的 check 与 write 两条咽喉（write 落盘前）注入 fail-closed 尺寸校验，违规统一返回 EXIT_INVALID=2 且绝不触碰目标文件；
2. validate_schema_size_budget 内部自剥离 volatile 键，复用 measure_tool_schema_bytes，并断言三元相对不变式 MAX_TOOL_SCHEMA_BYTES < MAX_TOTAL_SCHEMA_BYTES < TOOL_COUNT * MAX_TOOL_SCHEMA_BYTES；
3. test_templates.py 三处 fallback 全部收敛为硬编码 'core' 并反向断言 legacy 键不存在；
4. 替换测试中字面量为 TOOL_COUNT 与 SNAPSHOT_FILENAME，强化 SSOT 纪律。
```

#### 【目标签名与类型契约】
```
from typing import Any, NamedTuple
from tool_surface_constants import (
    MAX_TOOL_SCHEMA_BYTES, MAX_TOTAL_SCHEMA_BYTES, measure_tool_schema_bytes, SCHEMA_META_KEY,
)

class SizeViolation(NamedTuple):
    kind: str            # 'tool' | 'total'
    tool_name: str       # '' for total
    measured_bytes: int
    limit_bytes: int

def validate_schema_size_budget(
    snapshot: dict[str, Any],
    *,
    max_tool_bytes: int = MAX_TOOL_SCHEMA_BYTES,
    max_total_bytes: int = MAX_TOTAL_SCHEMA_BYTES,
) -> list[SizeViolation]:
    """Pure validator. Skips SCHEMA_META_KEY; strips volatile keys internally; measures via measure_tool_schema_bytes (SSOT).
    判据严格为 >：单工具 > max_tool_bytes 违规；累计 > max_total_bytes 违规；
    == 上限放行；空快照 / 仅 _meta 返回 []。不写盘、无副作用。"""

def format_size_violations(violations: list[SizeViolation]) -> list[str]:
    """Format violations sorted by (kind, tool_name) with stable prefix for deterministic assertions."""
```

#### 【分步改造指引】
1) ide_schema_export.py
   a) 扩充导入：NamedTuple；从 tool_surface_constants 导入 MAX_TOOL_SCHEMA_BYTES, MAX_TOTAL_SCHEMA_BYTES, measure_tool_schema_bytes。
   b) 新增数据契约与纯函数：
      - SizeViolation(NamedTuple): kind ('tool'|'total'), tool_name (str), measured_bytes (int), limit_bytes (int)
      - validate_schema_size_budget(snapshot, *, max_tool_bytes=MAX_TOOL_SCHEMA_BYTES, max_total_bytes=MAX_TOTAL_SCHEMA_BYTES) -> list[SizeViolation]
        内部先对每个 tool 结构执行 _strip_volatile_keys；跳过 SCHEMA_META_KEY；对每个 tool 执行 sz = measure_tool_schema_bytes(tool)，> max_tool_bytes 追加 kind='tool' 违规；累加各工具 sz 为 total（排除 _meta），> max_total_bytes 追加 kind='total'（tool_name=''）违规；基于 > 判定，== 放行；空快照返回 []。
      - format_size_violations(violations: list[SizeViolation]) -> list[str]：
        按 (v.kind, v.tool_name) 稳定排序输出 'SCHEMA_SIZE_VIOLATION: ...' 格式。
   c) run_cli 注入（双咽喉拦截，零 stdout 污染）：
      - check 分支：在 validate_schema_doc 后，vs = validate_schema_size_budget(disk_data)；非空打印至 stderr 并 return EXIT_INVALID(2)——早于字节比对。
      - write 分支：在 validate_schema_doc 后、tempfile.mkstemp 之前，vs = validate_schema_size_budget(live_schemas)；非空打印至 stderr、return EXIT_INVALID(2)，绝不写盘。

2) test_templates.py（三处全部收敛，删除 else 分支）
   - L41: assert "core" in mcp_data["mcpServers"]；追加 assert "quench-dev-tasks" not in mcp_data["mcpServers"]
   - L95 与 L141: server_key = "core"（硬编码，删除 if-else 回退）。

3) test_snapshot_drift_gate_contract.py 新增
   - 增加 F-2 常量三元相对不变式断言：assert MAX_TOOL_SCHEMA_BYTES < MAX_TOTAL_SCHEMA_BYTES < TOOL_COUNT * MAX_TOOL_SCHEMA_BYTES。
   - 替换测试中的硬编码字面量：16 替换为 TOOL_COUNT，"ide_tool_schemas.json" 替换为 SNAPSHOT_FILENAME。
   - P-1 纯函数确定性聚合：覆写极小阈值构造双工具超限 + 总量超限，严格匹配 sorted((v.kind, v.tool_name))。
   - P-2 收敛式边界 helper：_pad_to_exact_bytes(tool, target) 线性收敛自断言，断言 == 上限放行，+1 产生 1 条违规；空快照与仅 _meta 返回 []。
   - P-3 run_cli 直调正反例对照：正例 write 返回 EXIT_OK 且 check 返回 EXIT_OK；反例 write 返回 EXIT_INVALID 且目标文件未变、无 .tmp 残留、stderr 含 SCHEMA_SIZE_VIOLATION。
   - P-5 同源不变量：断言 validate_schema_size_budget(raw) == validate_schema_size_budget(_strip_volatile_keys(raw))。
   - 显式声明改写既有 F-1 为调用 validate_schema_size_budget 驱动真实生产门禁拦截。

#### 【防御与边缘校验】
- 测量口径唯一：严格复用 tool_surface_constants.measure_tool_schema_bytes；输入域排除 _meta，序列化参数固定为 compact JSON（separators=(',', ':'), ensure_ascii=False, utf-8 编码），与 IDE 注入序列化物理同源。
- 常量三元相对不变式（F-2 保护）：断言 MAX_TOOL_SCHEMA_BYTES < MAX_TOTAL_SCHEMA_BYTES < TOOL_COUNT * MAX_TOOL_SCHEMA_BYTES，杜绝门禁静默空转或不可达。
- 边界判据严格 >（== 放行、+1 拒绝），单工具与总量同构；使用收敛式 _pad_to_exact_bytes 并带前置自断言防测量漂移。
- 门禁落点安全公理：门禁严格挂接于 run_cli 双咽喉，显式禁止在 server.py boot 期抛异常（避免造成 stdio 客户端握手超时与工具链死锁）。
- 违规路径零副作用：目标文件字节未变、目录条目集合一致（无 .tmp 残留）、stderr 输出带 'SCHEMA_SIZE_VIOLATION' 前缀。
- check 违规退出码锁死 EXIT_INVALID=2，早于字节比对；禁止退化为 1。
- 现网余量实测：实测 TOTAL 10875 <= 12000、PEAK 896 <= 1000。
- 回滚锚点：git checkout plugins/quench-dev-tasks/server/ide_schema_export.py plugins/quench-dev-tasks/server/tests/test_templates.py plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py

#### 【DoD 验证命令】
```bash
python -c "import json,sys; sys.path.insert(0,'plugins/quench-dev-tasks/server'); from tool_surface_constants import measure_tool_schema_bytes as m, SCHEMA_META_KEY as K; d=json.load(open('docs/architecture/ide_tool_schemas.json',encoding='utf-8')); t=sum(m(v) for k,v in d.items() if k!=K); print('TOTAL',t,'PEAK',max((m(v),k) for k,v in d.items() if k!=K))"
python -m pytest plugins/quench-dev-tasks/server/tests/test_snapshot_drift_gate_contract.py plugins/quench-dev-tasks/server/tests/test_templates.py -v
python scripts/export_ide_schemas.py --check
python -m pytest -m tier1_fast -q
```

---

