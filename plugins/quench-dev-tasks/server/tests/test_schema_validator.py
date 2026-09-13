import pytest
from schema_validator import validate_task_schema

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
