# 2026-11-14_exclude_archive_from_vscode_search Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-11-14

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — 配置仓库级 VS Code 搜索排除规则并放行 settings.json（rev.3）

#### 【涉及文件】
```
.gitignore
.vscode/settings.json
```

#### 【缺陷根因与修改目标】
根因：`docs/dev_tasks/archive/**` 历史任务单累积导致全局搜索噪声；`.gitignore:52` 以 `.vscode/` 整目录排除，直接追加 `!.vscode/settings.json` 会因**父目录剪枝**静默失效。
目标：`.vscode/` → `.vscode/*`（仅排除直接子项、保留目录可遍历）并紧随负向规则；落盘单键 `search.exclude`。

#### 【目标签名与类型契约】
```
# IDE & OS
.vscode/*
!.vscode/settings.json
.idea/
```
（顺序不得颠倒；`.vscode/*` 不得写回 `.vscode/`。）

`.vscode/settings.json`：严格 JSON（无注释/尾逗号）、UTF-8 无 BOM、LF-only、末尾单 LF；顶层仅 `search.exclude`；值为 `{"docs/dev_tasks/archive/**": true}`，**布尔 true（非 1、非 "true"）**；POSIX `/`，禁止反斜杠与 `//`。

#### 【分步改造指引】
1. 编辑 `.gitignore` 的 `# IDE & OS` 区块（当前区块首行第 51 行、`.vscode/` 第 52 行），以**区块注释 + 精确行内容**定位，不依赖固定行号。将 `.vscode/` 改为 `.vscode/*`，紧随下一行新增 `!.vscode/settings.json`；`.idea/` 及各 OS 条目保持不动。
2. 确定性写盘（**不含任何反斜杠转义；`chr(10)` 即 LF**）：
```python
import json, pathlib
p = pathlib.Path(".vscode/settings.json")
p.parent.mkdir(exist_ok=True)
if p.exists() and p.read_bytes() != b"":
    p.with_name("settings.json.pre-quench.bak").write_bytes(p.read_bytes())
obj = {"search.exclude": {"docs/dev_tasks/archive/**": True}}
p.write_bytes(
    (json.dumps(obj, indent=2, ensure_ascii=True) + chr(10)).encode("utf-8")
)
```
3. 在**仓库根**执行 `【DoD 验证命令】`，全绿后方可 `dev_tasks_complete`。

#### 【防御与边缘校验】
1. 仅 `search.exclude`，禁用 `files.exclude`（避免隐藏 Explorer 树）。
2. 极性双向：`git add --dry-run .vscode/settings.json` 必须 exit 0（权威正判，可捕获父目录剪枝）；`git check-ignore -q .vscode/launch.json` 必须 exit 0（兄弟项仍被忽略）；`git check-ignore -q .vscode/settings.json` 必须 exit 1。
3. 索引前置：`.vscode/settings.json` 必须**尚未被跟踪**（`ls-files --error-unmatch` == 1），否则 `add --dry-run` 正判恒真、判定失真。
4. 字节级契约以 **`bytes([0xEF,0xBB,0xBF])` / `bytes([13])` / `bytes([10])`** 表达，**严禁**在写入器与 DoD 中出现反斜杠转义字面量。
5. `.gitignore` 结构性断言：不存在匹配目录本身的排除行；`.vscode/*` 必须位于 `!.vscode/settings.json` 之前。不依赖 `git check-ignore -v` 的版本相关语义。
6. 拒绝 `write_text`（跨平台换行翻译会破坏 LF-only 契约）；`json.loads` 前先完成 BOM/CR/LF 三断言，避免解析先行掩盖编码违约。
7. 不得静默覆盖开发者私有 `.vscode/settings.json`：已存在非空文件时先备份为 `settings.json.pre-quench.bak`（`*.bak` 已被 `.gitignore` 覆盖）。严禁写入解释器路径、插件个性化项等私有配置。
8. `search.exclude` 为对象型设置，工作区值不与用户个人条目深合并；本任务接受该取舍，后续不作为回归上报。
9. DoD 单行命令不得含 `!`（交互式 bash history expansion 风险）；`git add --dry-run` 不写索引、不触发提交钩子，可安全使用。

#### 【DoD 验证命令】
```bash
python -c "import json, pathlib, subprocess; LF = bytes([10]); CR = bytes([13]); BOM = bytes([0xEF, 0xBB, 0xBF]); F = '.vscode/settings.json'; KEY = 'docs/dev_tasks/archive/**'; p = pathlib.Path(F); rc = lambda *a: subprocess.run(['git', '--no-pager', *a], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode; assert p.is_file(), 'missing ' + F; assert rc('ls-files', '--error-unmatch', '--', F) == 1, 'settings.json 已在索引中，add --dry-run 正判失真（先 git rm --cached）'; assert rc('add', '--dry-run', '--', F) == 0, 'settings.json 被忽略（疑似父目录剪枝或负向规则顺序颠倒）'; assert rc('check-ignore', '-q', '--', '.vscode/launch.json') == 0, '.vscode/launch.json 应仍被忽略'; assert rc('check-ignore', '-q', '--', F) == 1, 'settings.json 不应被忽略'; gi = [ln.strip() for ln in pathlib.Path('.gitignore').read_text(encoding='utf-8').splitlines()]; assert not any(ln.rstrip('/') in ('.vscode', '/.vscode') for ln in gi), '仍存在 .vscode 整目录排除'; NEG = chr(33) + '.vscode/settings.json'; assert '.vscode/*' in gi and NEG in gi, gi; assert gi.index('.vscode/*') < gi.index(NEG), '负向规则必须位于 .vscode/* 之后'; b = p.read_bytes(); assert not b.startswith(BOM), '存在 UTF-8 BOM'; assert CR not in b, '存在 CR 字符（CRLF 行尾）'; assert b.endswith(LF) and not b.endswith(LF + LF), '须以恰好单个 LF 结尾'; data = json.loads(b.decode('utf-8')); assert set(data) == {'search.exclude'}, sorted(data); se = data['search.exclude']; assert isinstance(se, dict) and len(se) == 1, se; k = list(se)[0]; assert k == KEY, k; assert chr(92) not in k and '//' not in k, k; assert se[k] is True, '值必须为 JSON 布尔 true，实际 ' + repr(se[k]); assert pathlib.Path('docs/dev_tasks/archive').is_dir(), 'docs/dev_tasks/archive 不存在，排除规则将空转'; print('OK: gitignore polarity + settings.json contract valid')" && uv run pytest -m tier1_fast -q
```
