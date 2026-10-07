# 2026-10-04_hotfix_crlf_and_gitattributes Development Tasks / 开发任务单

> **Execution Guidelines for AI Models / 执行模型须知**
> - Strictly follow each task's [Step-by-Step Instructions / 分步改造指引] in sequential order
> - Do not modify files outside the declared task scope / 不得修改任务未涉及的文件
> - Preserve all existing comments and docstrings unless explicitly instructed / 保留所有现有注释和文档字符串
> - **Mandatory Unit Test Assertions / 改逻辑必加单测断言**：Append assertions in the test directory to prevent regressions
> - Upon starting a task, update its status to `🔨 执行中`; upon completion, update to `✔️ 已完成`

- **Created Date / 创建日期**：2026-10-04

---

## Task List & Status / 任务清单与状态

### 任务 1 ✔️ 已完成 — 修复架构清单 CRLF 污染、落地 .gitattributes 换行契约与生成器加固

#### 【涉及文件】
```
[NEW] .gitattributes
[MODIFY] docs/architecture/over_engineering_inventory.md
[MODIFY] scripts/asset_inventory.py
[MODIFY] plugins/quench-dev-tasks/server/tests/test_asset_inventory.py
```

#### 【缺陷根因与修改目标】
```
Root Cause:
仓库缺少 .gitattributes 导致跨平台换行符漂移，且 docs/architecture/over_engineering_inventory.md 在近期提交中残留 CRLF (\r\n)，导致 Linux CI runner 运行 test_13_output_crlf_free 失败。
Target:
根治 CRLF 污染，配置 .gitattributes 规范，加固 asset_inventory.py 生成器强制 LF 写入，确保跨平台无论 Git 配置如何均恒为纯 LF。
```

#### 【目标签名与类型契约】
```
# .gitattributes 声明
* text=auto eol=lf
*.md text eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
*.png binary
*.jpg binary
*.ico binary
*.pdf binary
*.zip binary

```

#### 【分步改造指引】
1. 新增仓库根级 .gitattributes，确立默认所有文本及 Markdown 检出/提交均强制 LF。
2. 修复 docs/architecture/over_engineering_inventory.md，将所有 CRLF 归一为纯 LF。
3. 加固 scripts/asset_inventory.py，在写入 OUTPUT_MD_REL 前做字符串换行归一化，并以 newline='\n' 显式写入。
4. 加固 tests/test_asset_inventory.py，验证 test_13_output_crlf_free 及 .gitattributes 配置契约。
5. 运行完整测试集确保无回归。

#### 【防御与边缘校验】
- 二进制文件安全：.gitattributes 必须显式声明 binary 豁免，防止图片或二进制产物被破坏。
- Windows 脚本兼容：保留 .bat/.cmd/.ps1 的 CRLF 兼容声明。
- 文本写换行保护：生成器在写文件前统一做 replace('\r\n', '\n')，防止内嵌模板带入 CRLF。
- 零依赖破坏：asset_inventory.py 保持纯标准库实现。

#### 【DoD 验证命令】
```bash
python -c "raw=open('docs/architecture/over_engineering_inventory.md','rb').read(); assert b'\r\n' not in raw, 'CRLF still present'"
git check-attr eol -- docs/architecture/over_engineering_inventory.md
uv run --directory plugins/quench-dev-tasks/server --extra dev python -m pytest tests/test_asset_inventory.py -v
```

---

