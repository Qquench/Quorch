from schema_validator import (
    _parse_task_markdown_sections,
    lint_task_physical_feasibility,
    validate_task_schema,
)

def test_valid_task_schema():
    valid_task = {
        "title": "测试任务",
        "affected_files": ["[MODIFY] server/test.py", "[NEW] server/new.py"],
        "root_cause_and_goal": "根因：缺少测试用例。目标：补全单元测试覆盖。",
        "type_contracts": "def test_foo() -> None: ...",
        "steps": ["1. 创建测试文件", "2. 执行断言验证"],
        "defensive_checks": ["- 输入为空时安全抛出异常"],
        "dod_commands": ["python -m pytest tests/"]
    }
    res = validate_task_schema(valid_task)
    assert res.is_valid is True
    assert len(res.errors) == 0

def test_missing_required_fields():
    incomplete_task = {
        "title": "不完整的任务",
        "affected_files": ["[MODIFY] server/test.py"]
    }
    res = validate_task_schema(incomplete_task)
    assert res.is_valid is False
    assert any("root_cause_and_goal" in err for err in res.errors)
    assert any("steps" in err for err in res.errors)
    assert any("dod_commands" in err for err in res.errors)

def test_granularity_warning():
    bulky_task = {
        "title": "过大的任务",
        "affected_files": [
            "[MODIFY] a.py",
            "[MODIFY] b.py",
            "[MODIFY] c.py",
            "[MODIFY] d.py"
        ],
        "root_cause_and_goal": "根因明确。目标明确。",
        "type_contracts": "无",
        "steps": ["1. 动作一", "2. 动作二"],
        "defensive_checks": ["无"],
        "dod_commands": ["pytest"]
    }
    res = validate_task_schema(bulky_task)
    assert res.is_valid is True
    assert any("粒度偏粗" in w for w in res.warnings)


def test_parse_markdown_hyphenated_id_out_of_order_and_fenced_headers():
    """支持连字符 ID、无序标题定位并忽略代码围栏内的 #### 假标题。"""
    md = """### 任务 36.10-rc1 🔨 执行中 — 混合边界解析测试

#### 【DoD 验证命令】
```bash
pytest -q
```

#### 【分步改造指引】
1. 保留示例代码块中的假标题：
```markdown
#### 【DoD 验证命令】
should_not_break_steps
```
2. 完成校验。

#### 【涉及文件】
- `[MODIFY] src/a.py`

#### 【缺陷根因与修改目标】
根因与目标明确。

#### 【目标签名与类型契约】
无

#### 【防御与边缘校验】
- 校验项
"""
    parsed = _parse_task_markdown_sections(md)
    assert parsed["id"] == "36.10-rc1"
    assert parsed["title"] == "混合边界解析测试"
    assert parsed["dod_commands"] == "pytest -q"
    assert len(parsed["steps"]) >= 4
    assert any("should_not_break_steps" in s for s in parsed["steps"])


def test_validate_task_schema_rejects_empty_and_bare_prefix_affected_files():
    """affected_files 中出现全空白或仅标签 '[MODIFY]' 无路径必须报错。"""
    bad_task = {
        "title": "空路径或纯标签拦截",
        "affected_files": ["   ", "[MODIFY]", "- `[NEW]`"],
        "root_cause_and_goal": "根因明确。",
        "type_contracts": "无",
        "steps": ["1. 第一步", "2. 第二步"],
        "defensive_checks": ["- 防御"],
        "dod_commands": ["pytest"],
    }
    res = validate_task_schema(bad_task)
    assert res.is_valid is False
    assert len(res.errors) >= 3


def test_lint_physical_feasibility_catches_untagged_traversal(tmp_path):
    """无操作标签的 '../evil.py' 必须经过 sanitize_workspace_path 拦截。"""
    task = {
        "id": "1.9",
        "title": "无前缀路径穿越",
        "affected_files": ["../evil.py"],
        "root_cause_and_goal": "根因",
        "type_contracts": "无",
        "steps": ["1. 一", "2. 二"],
        "defensive_checks": ["无"],
        "dod_commands": [],
    }
    res = lint_task_physical_feasibility(str(tmp_path), task)
    assert res.passed is False
    assert any("路径穿越安全违规" in issue.message for issue in res.issues)
