# Quench Dev-Orchestrator 编码标准强制规则

> **来源**：2026-09-13 系统性架构审查 → 编码标准提炼  
> **约束级别**：执行模型（Flash）在实施 `quench-dev-tasks` 模块的任何任务时**必须遵守**以下全部标准。  
> **生效范围**：`plugins/quench-dev-tasks/server/` 下所有 Python 源码。

---

## 1. 时间处理标准

```python
# ✅ 统一标准：所有时间生成与比较使用 UTC aware datetime
from datetime import datetime, timezone

now = datetime.now(timezone.utc)  # 生成
expires_at = datetime.fromisoformat(iso_str)  # 解析
if expires_at.tzinfo is None:
    expires_at = expires_at.replace(tzinfo=timezone.utc)  # 兼容旧数据
```

**禁止**：
- ❌ `datetime.datetime.now()`（无参数，naive datetime）
- ❌ `datetime.utcnow()`（Python 3.12 已废弃）
- ❌ 直接对比 aware datetime 与 naive datetime（抛 TypeError）

---

## 2. 文件写入标准

```python
# ✅ 统一标准：所有结构化数据文件写入使用原子替换模式
import tempfile, os, json

def _atomic_write_json(filepath: str, data: dict) -> None:
    """使用临时文件 + os.replace 实现原子写入"""
    dir_name = os.path.dirname(os.path.abspath(filepath))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, filepath)  # 原子操作
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
```

**禁止**：
- ❌ 直接 `open(filepath, "w")` 写入任务文件、bypass 文件或状态文件
- ❌ 不清理临时文件的异常路径

**适用对象**：bypass JSON 写入（server.py）、state_machine.py 锁内写回、任何 `.json` / `.yaml` 状态文件。

---

## 3. FileLock 使用标准

```python
# ✅ 统一标准：所有 FileLock 调用设置超时
from filelock import FileLock, Timeout

LOCK_TIMEOUT = 5.0  # 秒

lock = FileLock(lock_path, timeout=LOCK_TIMEOUT)
try:
    with lock:
        # 锁内操作（读取 → 校验 → 条件写入）
        pass
except Timeout:
    logger.warning("锁获取超时，降级处理")
    # 降级策略（不阻断 IDE 工作流）
```

**禁止**：
- ❌ `FileLock(path)` 无 timeout 参数（可能无限等待导致 IDE 死锁）
- ❌ 在锁外执行读-改-写序列（破坏原子性）

---

## 4. 输入校验标准

```python
import re

# ✅ 统一标准：所有外部输入在入口处校验
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9\-]{1,128}$", re.IGNORECASE)
MAX_REASON_LENGTH = 500

def _validate_session_id(session_id: str | None) -> str | None:
    """校验 session_id 格式（UUID 正则白名单）"""
    if session_id is None:
        return None
    session_id = session_id.strip()
    if not SESSION_ID_PATTERN.match(session_id):
        return None
    return session_id

def _sanitize_reason(reason: str) -> str:
    """截断至最大长度"""
    return reason.strip()[:MAX_REASON_LENGTH]
```

**禁止**：
- ❌ 将未校验的外部输入直接用于文件路径构造或 JSON 键
- ❌ 无长度限制的字符串字段写入持久化文件

---

## 5. 异常处理标准

```python
import logging

logger = logging.getLogger("quench.file_scope_guard")

# ❌ 禁止：静默吞掉异常
except Exception:
    pass

# ✅ 改为：记录日志 + 原有兜底行为
except Exception as e:
    logger.warning(f"[file_scope_guard] 异常: {e}", exc_info=True)
    return {"decision": "allow"}  # 原有的兜底放行策略不变
```

**原则**：Hook 的 `except Exception` 兜底策略（放行而非阻断）保持不变，但必须记录日志使异常可追溯。

---

## 6. 路径处理标准

```python
# ✅ 统一标准：所有路径引用使用动态定位
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "scripts"))

# ✅ 路径比较前解析 symlink
real_path = os.path.realpath(target_file)

# ✅ 路径越界防御
try:
    common = os.path.commonpath([real_path, real_root])
    if common != real_root:
        return True  # 逃逸出工作区 → 受管（触发拦截）
except ValueError:
    return True  # 跨驱动器 → 受管
```

**禁止**：
- ❌ 在代码中出现任何硬编码的本机绝对路径（如 `D:\Work\...`、`C:\Users\...`）
- ❌ 使用 `os.path.normpath` 而不先 `os.path.realpath` 解析 symlink
- ❌ 忽略 `os.path.commonpath` 的 `ValueError`（跨驱动器场景）

---

## 7. 测试命名与覆盖规范

```python
# ✅ 测试函数命名：test_<被测功能>_<测试场景>_<预期行为>
def test_bypass_concurrent_read_write_no_data_race():
    """验证多线程并发读写 bypass 文件不产生数据竞争"""

def test_session_id_rejects_overlong_input():
    """验证超长 session_id 被正则白名单拒绝"""

def test_is_path_governed_symlink_traversal_blocked():
    """验证 symlink 穿透被 os.path.realpath 阻止"""
```

**强制要求**：每条改造指引完成后，必须同步在对应 `tests/test_*.py` 中追加断言用例。改逻辑不加测试视为任务未完成。
