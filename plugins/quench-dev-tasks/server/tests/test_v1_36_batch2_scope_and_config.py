# -*- coding: utf-8 -*-
"""Regression tests for v1.36 Batch 2 (Tasks 36.4 & 36.5):
Scope guards escape closure, Stop Hook circuit-breaker precision,
project_config local override monotonicity/migration lock, and code_explorer symlink sandbox.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(SERVER_DIR, "hooks")
SCRIPTS_DIR = os.path.normpath(os.path.join(SERVER_DIR, "..", "scripts"))
for _p in (SERVER_DIR, HOOKS_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import context_injector
from file_scope_guard import (
    _extract_task_affected_files,
    detect_shell_write_bypass,
    is_agent_brain_artifact,
    is_meta_file,
    matches_pattern,
    verify_session_integrity,
)
from git_pre_commit_guard import (
    check_violations,
    find_active_task,
    install_hook,
)
from path_guard import (
    PathTraversalError,
    canonicalize_path,
    is_within_whitelist,
)


# ---------------------------------------------------------------------------
# Task 36.4 Tests
# ---------------------------------------------------------------------------


def test_pre_commit_dotted_task_id_and_strict_whitelist(tmp_path: Path):
    """点分任务 ID (36.4) 正确识别，禁止同名 basename 与双向 endswith 绕过。"""
    tasks_dir = tmp_path / "docs" / "dev_tasks"
    tasks_dir.mkdir(parents=True)
    task_file = tasks_dir / "2026-11-26_batch.md"
    task_file.write_text(
        """# Batch

### 任务 1.1 ✔️ 已完成 — 前置任务

#### 【涉及文件】
```
[MODIFY] src/secret.py
```

```markdown
### 任务 99.9 🔨 执行中 — 围栏内伪造任务
```

### 任务 36.4 🔨 执行中 — 范围守卫加固

#### 【涉及文件】
```
- [MODIFY] `src/core/guard.py` (主守卫)
- [RENAME] `src/old.py` -> `src/new.py`
- [MODIFY] src/(auth)/login.py（路由组路径）
```
""",
        encoding="utf-8",
    )

    active = find_active_task(str(tasks_dir))
    assert active is not None
    task_id, title, allowed = active
    assert task_id == "36.4"
    assert "范围守卫加固" in title
    assert "src/core/guard.py" in allowed
    assert "src/old.py" in allowed
    assert "src/new.py" in allowed
    assert "src/(auth)/login.py" in allowed

    # 同名 basename 与 suffix endswith 必须被拦截
    violations = check_violations(
        [
            "src/core/guard.py",
            "other/guard.py",
            "x_src/core/guard.py",
            "src/(auth)/login.py",
        ],
        allowed,
        str(tmp_path),
    )
    assert "src/core/guard.py" not in violations
    assert "src/(auth)/login.py" not in violations
    assert "other/guard.py" in violations
    assert "x_src/core/guard.py" in violations


def test_pre_commit_install_hook_worktree_git_file(tmp_path: Path):
    """Git worktree 下 .git 为文件时 install_hook 正常解析 git_dir 并安装 pre-commit。"""
    actual_git_dir = tmp_path / "main_repo_git" / "worktrees" / "wt1"
    actual_git_dir.mkdir(parents=True)
    wt_root = tmp_path / "wt1"
    wt_root.mkdir()
    (wt_root / ".git").write_text(f"gitdir: {actual_git_dir}\n", encoding="utf-8")

    rc = install_hook(str(wt_root))
    assert rc == 0
    assert (actual_git_dir / "hooks" / "pre-commit").is_file()


def test_path_guard_literal_basename_and_canonicalize_hardening(tmp_path: Path):
    """path_guard 禁止字面量按 basename 放行，并拦截 C:foo / ADS / 点尾 / 保留设备名。"""
    assert is_within_whitelist("sub/README.md", ["README.md"]) is False
    assert is_within_whitelist("README.md", ["README.md"]) is True
    assert is_within_whitelist("sub/notes.md", ["*.md"]) is True

    ws = str(tmp_path)
    for bad in ("C:foo.py", "file.txt:evil", "sub/foo. ", "sub/foo.", "CON.txt", "sub/NUL"):
        with pytest.raises(PathTraversalError):
            canonicalize_path(bad, base_dir=ws)


def test_file_scope_guard_pattern_and_section_boundaries(tmp_path: Path):
    """docs/** 与 docs/* 段边界隔离、外部路径拒绝非 **/ 模式、brain 跨盘豁免及跨任务头隔离。"""
    ws = str(tmp_path)

    # docs/** 不得匹配 backend/docs/secret.py
    assert matches_pattern(str(tmp_path / "docs" / "guide.md"), "docs/**", ws) is True
    assert matches_pattern(str(tmp_path / "backend" / "docs" / "secret.py"), "docs/**", ws) is False

    # docs/* 仅匹配直接子文件，不匹配多级嵌套
    assert matches_pattern(str(tmp_path / "docs" / "a.md"), "docs/*", ws) is True
    assert matches_pattern(str(tmp_path / "docs" / "a" / "b" / "c.md"), "docs/*", ws) is False

    # 字面量文件名不按 basename 跨目录匹配
    assert matches_pattern(str(tmp_path / "backend" / "main.py"), "main.py", ws) is False

    # 工作区外部路径拒绝 docs/** / *.css / *，但保留 **/brain/**
    assert matches_pattern("C:/outside/style.css", "*.css", ws) is False
    assert matches_pattern("C:/outside/docs/a.md", "docs/**", ws) is False
    assert matches_pattern("C:/outside/secret.py", "*", ws) is False
    assert is_agent_brain_artifact("C:/Users/u/app/brain/conv-1/walkthrough.md", ws) is True

    # _extract_task_affected_files 不跨任务头吞入后续白名单
    md_doc = """### 任务 36.4 🔨 执行中 — 当前任务

#### 【修改目标】
无涉及文件代码块。

### 任务 36.5 ⬜ 待确认 — 后续任务

#### 【涉及文件】
```
[MODIFY] secret/other_task.py
```
"""
    assert _extract_task_affected_files(md_doc, "36.4") == []


def test_file_scope_guard_session_lock_missing_id_and_shell_delete(tmp_path: Path):
    """缺失 conversationId 时拒绝有会话锁的 bypass；detect_shell_write_bypass 支持自定义目录与删除命令。"""
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    ok, reason = verify_session_integrity(
        {"active": True, "session_id": "sess-lock-1", "expires_at": future},
        None,
    )
    assert ok is False
    assert "缺失当前会话 ID" in reason

    ws = str(tmp_path)
    assert detect_shell_write_bypass("rm -f custom_tasks/2026_a.md", ws, dev_tasks_dir="custom_tasks") is not None
    assert detect_shell_write_bypass("mv custom_tasks/a.md /tmp/b.md", ws, dev_tasks_dir="custom_tasks") is not None
    assert detect_shell_write_bypass("echo hi > docs/dev_tasks/a.md", ws, dev_tasks_dir="custom_tasks") is not None
    assert detect_shell_write_bypass("echo hi > docs/notes/a.md", ws, dev_tasks_dir="custom_tasks") is None


def test_file_scope_guard_is_meta_file_prefix_boundary(tmp_path: Path):
    """is_meta_file 对 dev_tasks_evil/README.md 保持前缀边界隔离。"""
    from types import SimpleNamespace

    ws = tmp_path
    evil_dir = ws / "docs" / "dev_tasks_evil"
    evil_dir.mkdir(parents=True)
    evil_readme = evil_dir / "README.md"
    evil_readme.write_text("# evil", encoding="utf-8")

    cfg = SimpleNamespace(
        changelog_path="CHANGELOG.md",
        resolve_path=lambda k: str(ws / "docs" / "dev_tasks") if k == "dev_tasks_dir" else "",
    )
    assert is_meta_file(str(evil_readme), str(ws), cfg) is False


def test_stop_hook_multi_task_progression_and_subagent_fields(tmp_path: Path, monkeypatch):
    """同文件多任务推进时指纹随任务状态变化，不会因前一任务熔断而阻断后续任务；识别 snake_case 与子代理字段。"""
    ws = tmp_path / "ws"
    agents_dir = ws / ".agents"
    dev_tasks_dir = ws / "docs" / "dev_tasks"
    agents_dir.mkdir(parents=True)
    dev_tasks_dir.mkdir(parents=True)
    (agents_dir / "quench_stack.yaml").write_text(
        "project_name: test\ndev_tasks_dir: docs/dev_tasks\n", encoding="utf-8"
    )

    task_file = dev_tasks_dir / "2026-11-26_multi.md"
    task_file.write_text(
        """# Batch
### 任务 1.1 ✅ 已确认 — Task 1
### 任务 1.2 ✅ 已确认 — Task 2
""",
        encoding="utf-8",
    )

    # snake_case last_user_input 与 parentConversationId 必须立即放行
    assert context_injector._handle_stop_event({
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "last_user_input": "[QUENCH-DISPATCH: RUNNER] work",
        "workspacePaths": [str(ws)],
    }) == {"decision": "allow"}

    assert context_injector._handle_stop_event({
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "parent_conversation_id": "parent-1",
        "workspacePaths": [str(ws)],
    }) == {"decision": "allow"}

    monkeypatch.setattr(
        context_injector,
        "_resolve_harness_baton",
        lambda *args, **kwargs: ("DISPATCH_RUNNER", "Dispatch next task"),
    )

    payload = {
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "conversationId": "conv-multi",
        "workspacePaths": [str(ws)],
    }

    # Task 1.1 首次触发 -> continue；再次同状态触发 -> allow
    assert context_injector._handle_stop_event(payload)["decision"] == "continue"
    assert context_injector._handle_stop_event(payload) == {"decision": "allow"}

    # Task 1.1 完成后，Task 1.2 仍为已确认 -> 状态摘要变化，新指纹允许续跑！
    task_file.write_text(
        """# Batch
### 任务 1.1 ✔️ 已完成 — Task 1
### 任务 1.2 ✅ 已确认 — Task 2
""",
        encoding="utf-8",
    )
    assert context_injector._handle_stop_event(payload)["decision"] == "continue"


# ---------------------------------------------------------------------------
# Task 36.5 Tests
# ---------------------------------------------------------------------------


def test_project_config_local_override_strict_bool_and_omitted_baseline(tmp_path: Path):
    """audit_gate.enabled: 0/'false'/'no'/'off' 与缺省基线注入 unmanaged_paths/managed_paths/accepted_sources 必须被拦截。"""
    import yaml
    from project_config import ConfigError, ConfigFault, _coerce_strict_bool, load_project_config

    assert _coerce_strict_bool(0) is False
    assert _coerce_strict_bool("0") is False
    assert _coerce_strict_bool("false") is False
    assert _coerce_strict_bool("NO") is False
    assert _coerce_strict_bool("off") is False
    assert _coerce_strict_bool("true") is True

    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir(parents=True)
    stack_yaml = agents_dir / "quench_stack.yaml"
    local_yaml = agents_dir / "quench_stack.local.yaml"

    stack_yaml.write_text(
        yaml.dump({
            "schema_version": "1.0",
            "config_version": 1,
            "project_name": "strict-proj",
            "audit_gate": {
                "enabled": True,
                "on_missing_record": "BLOCK",
                "on_degraded": "WARN",
            },
        }),
        encoding="utf-8",
    )

    # 1. 大写安全枚举正常加载为小写
    cfg_ok = load_project_config(str(tmp_path))
    assert cfg_ok.audit_gate.on_missing_record == "block"
    assert cfg_ok.audit_gate.on_degraded == "warn"

    # 2. enabled: 0 / 'false' / 'off' / 'no' 企图绕过 is False 拦截
    for falsy in (0, "0", "false", "no", "off"):
        local_yaml.write_text(yaml.dump({"audit_gate": {"enabled": falsy}}), encoding="utf-8")
        with pytest.raises(ConfigError) as exc:
            load_project_config(str(tmp_path))
        assert ConfigFault.SAFETY_DOWNGRADE_DENIED.value in str(exc.value)

    # 3. 缺省基线注入 unmanaged_paths: ['**'] 必须拦截
    local_yaml.write_text(yaml.dump({"governance_scope": {"unmanaged_paths": ["**"]}}), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_project_config(str(tmp_path))
    assert ConfigFault.SAFETY_DOWNGRADE_DENIED.value in str(exc.value)

    # 4. 缺省基线注入 managed_paths 窄化列表必须拦截
    local_yaml.write_text(yaml.dump({"governance_scope": {"managed_paths": ["docs/**"]}}), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_project_config(str(tmp_path))
    assert ConfigFault.SAFETY_DOWNGRADE_DENIED.value in str(exc.value)

    # 5. 缺省基线在 standard 模式下放宽 accepted_sources 必须拦截
    local_yaml.write_text(yaml.dump({"audit_gate": {"accepted_sources": ["reviewer_client", "host_subagent"]}}), encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_project_config(str(tmp_path))
    assert ConfigFault.SAFETY_DOWNGRADE_DENIED.value in str(exc.value)

    # 6. 非字典 local.yaml 必须抛出 ConfigError
    local_yaml.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_project_config(str(tmp_path))


def test_project_config_bom_migration_protected_backslash_cross_drive_and_reviewer_jobs(tmp_path: Path):
    """验证 UTF-8 BOM 迁移保留、零缩进锚定、POSIX 反斜杠识别、跨盘 canonical_artifact_ref 及 reviewer_jobs 零告警。"""
    from project_config import (
        ConfigError,
        ConfigFault,
        canonical_artifact_ref,
        is_protected_config_path,
        migrate_and_validate,
        migrate_config_if_needed,
    )

    # 1. BOM 保留与缩进子键不误匹配
    yaml_path = tmp_path / "quench_stack.yaml"
    yaml_path.write_bytes(
        "\ufeffproject_name: bom_proj\nnested:\n  schema_version: '0.9'\n  fast_track_rules: false\n".encode("utf-8")
    )
    migrated, changed = migrate_config_if_needed(str(yaml_path), {"project_name": "bom_proj"})
    assert changed is True
    raw_bytes = yaml_path.read_bytes()
    assert raw_bytes.startswith(b"\xef\xbb\xbf")
    assert migrated["schema_version"] == "1.0"
    assert migrated["fast_track_rules"] == {"allow_untracked_patterns": []}

    # 2. POSIX 反斜杠受保护配置识别
    assert is_protected_config_path(".agents\\quench_stack.yaml") is True
    assert is_protected_config_path("sub\\quench_stack.local.yaml") is True

    # 3. 跨盘 canonical_artifact_ref 抛出 ConfigError
    with patch("os.path.relpath", side_effect=ValueError("path is on mount 'Z:', start on mount 'D:'")):
        with pytest.raises(ConfigError):
            canonical_artifact_ref(str(tmp_path), "Z:/tasks/a.md", "1.1")

    # 4. reviewer_jobs 纳入 KNOWN_TOP_LEVEL_KEYS 无 UNKNOWN_KEY 告警，真未知键仍告警
    cfg, faults = migrate_and_validate({"project_name": "p", "reviewer_jobs": {"timeout": 10}})
    assert ConfigFault.UNKNOWN_KEY not in faults
    assert cfg.project_name == "p"

    with pytest.warns(UserWarning):
        _, unknown_faults = migrate_and_validate({"project_name": "p", "bogus_unknown_key": 1})
    assert ConfigFault.UNKNOWN_KEY in unknown_faults


def test_code_explorer_drive_relative_and_grep_symlink_sandbox(tmp_path: Path):
    """code_explorer 拦截 Windows 驱动器相对路径，并在 grep 中阻止外部软链接与敏感文件软链接逃逸。"""
    from code_explorer import UnsafePathError, grep, resolve_within_roots

    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    ws.mkdir()
    outside.mkdir()
    (ws / "safe.py").write_text("NEEDLE_TOKEN = 1\n", encoding="utf-8")
    (ws / ".env").write_text("NEEDLE_TOKEN = secret\n", encoding="utf-8")
    ext_secret = outside / "ext_secret.py"
    ext_secret.write_text("NEEDLE_TOKEN = external\n", encoding="utf-8")

    # 1. C:foo.py 拦截
    assert resolve_within_roots(str(ws), "C:foo.py") is None
    with pytest.raises(UnsafePathError):
        grep(str(ws), "NEEDLE_TOKEN", rel_path="C:foo.py")

    # 2. grep 软链接逃逸 & 指向敏感文件拦截（兼容无 symlink 权限环境使用 mock）
    try:
        os.symlink(str(ext_secret), str(ws / "link_ext.py"))
        os.symlink(str(ws / ".env"), str(ws / "link_env.txt"))
        res = grep(str(ws), "NEEDLE_TOKEN")
        paths = {m.rel_path for m in res.matches}
        assert paths == {"safe.py"}
    except (OSError, NotImplementedError):
        (ws / "link_ext.py").write_text("NEEDLE_TOKEN = fake\n", encoding="utf-8")
        (ws / "link_env.txt").write_text("NEEDLE_TOKEN = fake\n", encoding="utf-8")
        orig_realpath = os.path.realpath

        def _fake_realpath(p):
            s = str(p)
            if s.endswith("link_ext.py"):
                return str(ext_secret)
            if s.endswith("link_env.txt"):
                return str(orig_realpath(str(ws / ".env")))
            return orig_realpath(p)

        with patch("os.path.realpath", side_effect=_fake_realpath):
            res = grep(str(ws), "NEEDLE_TOKEN")
        paths = {m.rel_path for m in res.matches}
        assert paths == {"safe.py"}

