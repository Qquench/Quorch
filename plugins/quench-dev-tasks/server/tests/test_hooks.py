import datetime
import json
import os
import subprocess
import sys
import tempfile
import pytest

PYTHON_EXE = sys.executable
HOOKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")
FILE_GUARD = os.path.join(HOOKS_DIR, "file_scope_guard.py")
CONTEXT_INJECTOR = os.path.join(HOOKS_DIR, "context_injector.py")


def run_hook(hook_script: str, input_dict: dict) -> dict:
    proc = subprocess.Popen(
        [PYTHON_EXE, hook_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    stdout, stderr = proc.communicate(input=json.dumps(input_dict, ensure_ascii=False))
    assert proc.returncode == 0, f"Hook failed with stderr: {stderr}"
    return json.loads(stdout)


def test_file_scope_guard_non_quench_project(tmp_path):
    # Workspace without .agents/quench_stack.yaml should silently allow
    ws_str = str(tmp_path)
    res = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "main.py")}},
        "workspacePaths": [ws_str],
    })
    assert res == {"decision": "allow"}


def test_file_scope_guard_meta_files_exempt(tmp_path):
    # Meta files like dev_tasks/*.md, CHANGELOG.md, .agents/* should be exempted
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text("project_name: 'TestProj'\n", encoding="utf-8")

    ws_str = str(tmp_path)

    # 1. Dev tasks markdown file
    res1 = run_hook(FILE_GUARD, {
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": str(tmp_path / "docs" / "dev_tasks" / "2026-09-11_task.md")}},
        "workspacePaths": [ws_str],
    })
    assert res1["decision"] == "allow"

    # 2. CHANGELOG.md
    res2 = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "CHANGELOG.md")}},
        "workspacePaths": [ws_str],
    })
    assert res2["decision"] == "allow"

    # 3. .agents config file
    res3 = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / ".agents" / "quench_stack.yaml")}},
        "workspacePaths": [ws_str],
    })
    assert res3["decision"] == "allow"


def test_file_scope_guard_no_active_task_triggers_ask(tmp_path):
    # When no active task and empty whitelist, modifying source code should trigger ask modal
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: 'TestProj'\nfast_track_rules:\n  allow_untracked_patterns: []\n",
        encoding="utf-8",
    )
    ws_str = str(tmp_path)

    res = run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "replace_file_content",
            "args": {
                "TargetFile": str(tmp_path / "src" / "main.py"),
                "Description": "Adjust core business logic",
            },
        },
        "workspacePaths": [ws_str],
    })
    assert res["decision"] == "ask"
    assert "未纳管代码修改确认" in res["reason"]
    assert "Adjust core business logic" in res["reason"]


def test_file_scope_guard_layer1_static_whitelist(tmp_path):
    # Layer 1: files matching config whitelist should be allowed
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: 'TestProj'\nfast_track_rules:\n  allow_untracked_patterns:\n    - '*.css'\n    - 'docs/**'\n",
        encoding="utf-8",
    )
    ws_str = str(tmp_path)

    # 1. Matching *.css -> allowed
    res_css = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "style.css")}},
        "workspacePaths": [ws_str],
    })
    assert res_css["decision"] == "allow"

    # 2. Matching docs/** -> allowed
    res_docs = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "docs" / "manual.txt")}},
        "workspacePaths": [ws_str],
    })
    assert res_docs["decision"] == "allow"

    # 3. Not in whitelist -> ask
    res_py = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "app.py")}},
        "workspacePaths": [ws_str],
    })
    assert res_py["decision"] == "ask"


def test_file_scope_guard_layer2_session_bypass(tmp_path):
    # Layer 2: session bypass in .agents/.quench_bypass.json
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: 'TestProj'\nfast_track_rules:\n  allow_untracked_patterns: []\n",
        encoding="utf-8",
    )

    ws_str = str(tmp_path)

    # Create active session bypass for ui_styling
    bypass_file = agents_dir / ".quench_bypass.json"
    now = datetime.datetime.now()
    exp = now + datetime.timedelta(hours=2)
    bypass_file.write_text(
        json.dumps({
            "active": True,
            "category": "ui_styling",
            "patterns": ["*.css", "*.vue"],
            "reason": "用户指令：调整按钮颜色",
            "expires_at": exp.isoformat(),
        }),
        encoding="utf-8",
    )

    # 1. .vue file matches bypass -> allowed
    res_vue = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "App.vue")}},
        "workspacePaths": [ws_str],
    })
    assert res_vue["decision"] == "allow"

    # 2. .py file doesn't match ui_styling -> ask
    res_py = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "server.py")}},
        "workspacePaths": [ws_str],
    })
    assert res_py["decision"] == "ask"

    # 3. Test expired bypass
    past = now - datetime.timedelta(minutes=5)
    bypass_file.write_text(
        json.dumps({
            "active": True,
            "category": "ui_styling",
            "patterns": ["*.css", "*.vue"],
            "reason": "过期测试",
            "expires_at": past.isoformat(),
        }),
        encoding="utf-8",
    )
    res_expired = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "App.vue")}},
        "workspacePaths": [ws_str],
    })
    assert res_expired["decision"] == "ask"


def test_file_scope_guard_with_in_progress_task(tmp_path):
    # Setup mock workspace
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: 'TestProj'\ndev_tasks_dir: 'docs/dev_tasks'\n",
        encoding="utf-8",
    )

    dev_tasks = tmp_path / "docs" / "dev_tasks"
    dev_tasks.mkdir(parents=True)
    task_file = dev_tasks / "2026-09-11_test_task.md"

    md_content = """# 测试任务集

### 任务 1.1 🔨 执行中 — 核心功能开发

#### 【涉及文件】

```
[MODIFY] src/core/main.py
[NEW] src/core/helper.py
```

#### 【分步改造指引】
1. 实现核心逻辑
"""
    task_file.write_text(md_content, encoding="utf-8")

    ws_str = str(tmp_path)

    # 1. Target file in scope (matching exactly)
    res_allow1 = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "core" / "main.py")}},
        "workspacePaths": [ws_str],
    })
    assert res_allow1["decision"] == "allow"

    # 2. Target file in scope (matching relative/basename)
    res_allow2 = run_hook(FILE_GUARD, {
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": "src/core/helper.py"}},
        "workspacePaths": [ws_str],
    })
    assert res_allow2["decision"] == "allow"

    # 3. Target file OUT of scope -> should ask with reason
    res_ask = run_hook(FILE_GUARD, {
        "toolCall": {
            "name": "replace_file_content",
            "args": {
                "TargetFile": str(tmp_path / "backend" / "server.py"),
                "Description": "Fixing an unhandled edge case in backend",
            },
        },
        "workspacePaths": [ws_str],
    })
    assert res_ask["decision"] == "ask"
    assert "范围外修改拦截" in res_ask["reason"]
    assert "Fixing an unhandled edge case in backend" in res_ask["reason"]
    assert "backend" in res_ask["reason"]


def test_context_injector(tmp_path):
    # Setup mock workspace
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: 'TestProj'\ndev_tasks_dir: 'docs/dev_tasks'\n",
        encoding="utf-8",
    )

    dev_tasks = tmp_path / "docs" / "dev_tasks"
    dev_tasks.mkdir(parents=True)
    task_file = dev_tasks / "2026-09-11_test_task.md"

    md_content = """# 测试任务集

### 任务 1.1 🔨 执行中 — 核心模块开发
"""
    task_file.write_text(md_content, encoding="utf-8")
    ws_str = str(tmp_path)

    res = run_hook(CONTEXT_INJECTOR, {
        "workspacePaths": [ws_str],
    })
    assert "injectSteps" in res
    assert len(res["injectSteps"]) == 1
    msg = res["injectSteps"][0]["ephemeralMessage"]
    assert "Quench DevTasks 上下文守卫" in msg
    assert "Task 1.1 — 核心模块开发" in msg


def test_file_scope_guard_session_lock_match_and_mismatch(tmp_path):
    # Setup mock workspace
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        "project_name: 'TestProj'\nfast_track_rules:\n  allow_untracked_patterns: []\n",
        encoding="utf-8",
    )
    ws_str = str(tmp_path)

    # 1. 创建绑定特定会话 session-101 的旁路配置
    bypass_file = agents_dir / ".quench_bypass.json"
    now = datetime.datetime.now()
    exp = now + datetime.timedelta(hours=2)
    bypass_file.write_text(
        json.dumps({
            "active": True,
            "session_id": "session-101",
            "category": "ui_styling",
            "patterns": ["*.vue", "*.css"],
            "reason": "会话专属旁路测试",
            "expires_at": exp.isoformat(),
        }),
        encoding="utf-8",
    )

    # 2. 会话 ID 匹配（session-101）➔ 旁路生效放行
    res_matched = run_hook(FILE_GUARD, {
        "conversationId": "session-101",
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "App.vue")}},
        "workspacePaths": [ws_str],
    })
    assert res_matched["decision"] == "allow"
    assert bypass_file.exists(), "匹配的会话应保留旁路配置"

    # 3. 会话 ID 不匹配（新打开会话 session-999）➔ 物理锁判定失效，并自愈清理前一会话的旁路文件
    res_mismatched = run_hook(FILE_GUARD, {
        "conversationId": "session-999",
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "App.vue")}},
        "workspacePaths": [ws_str],
    })
    assert res_mismatched["decision"] == "ask"
    assert not bypass_file.exists(), "跨会话访问应触发自动清理前一会话遗留配置"


def test_file_scope_guard_dual_track_boundary_smart_exemption(tmp_path):
    # 验证非代码资产（未来路线、客户材料、模拟数据、Markdown说明）天然免受任务状态机阻断
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text(
        """project_name: 'TestProj'
governance_scope:
  managed_paths:
    - 'src/**'
    - 'requirements.txt'
  unmanaged_paths:
    - 'future_roadmap/**'
    - 'docs/client_materials/**'
    - 'sample_data/**'
    - '*.md'
""",
        encoding="utf-8",
    )
    ws_str = str(tmp_path)

    # 1. 修改 future_roadmap 文档 ➔ 天然直接放行
    res_roadmap = run_hook(FILE_GUARD, {
        "toolCall": {"name": "write_to_file", "args": {"TargetFile": str(tmp_path / "future_roadmap" / "q3_plan.md")}},
        "workspacePaths": [ws_str],
    })
    assert res_roadmap["decision"] == "allow"

    # 2. 修改面向客户演示文稿 ➔ 天然直接放行
    res_client = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "docs" / "client_materials" / "pitch.md")}},
        "workspacePaths": [ws_str],
    })
    assert res_client["decision"] == "allow"

    # 3. 修改模拟样本数据 ➔ 天然直接放行
    res_sample = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "sample_data" / "plc_dump.json")}},
        "workspacePaths": [ws_str],
    })
    assert res_sample["decision"] == "allow"

    # 4. 修改受管业务代码 src/api.py ➔ 强行拦截并触发确认
    res_code = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "api.py")}},
        "workspacePaths": [ws_str],
    })
    assert res_code["decision"] == "ask"

    # 5. 修改高危依赖文件 requirements.txt ➔ 强行拦截并触发确认
    res_dep = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "requirements.txt")}},
        "workspacePaths": [ws_str],
    })
    assert res_dep["decision"] == "ask"


def test_file_scope_guard_hook_logging(tmp_path):
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    stack_yaml = agents_dir / "quench_stack.yaml"
    stack_yaml.write_text("schema_version: '1.0'\nproject_name: 'HookLogProj'\n", encoding="utf-8")

    ws_str = str(tmp_path)
    res = run_hook(FILE_GUARD, {
        "toolCall": {"name": "replace_file_content", "args": {"TargetFile": str(tmp_path / "src" / "test.py")}},
        "workspacePaths": [ws_str],
    })
    assert res["decision"] == "ask"

    log_file = agents_dir / ".quench_hook.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "[ASK_MODAL]" in content
    assert "target=" in content


