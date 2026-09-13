# Quench Dev-Orchestrator Coding Standards (编码标准强制规则)

> **Origin**: Systemic Architecture Review → Refined Coding Standards  
> **Enforcement Level**: Mandatory for all runner models implementing tasks within `quench-dev-tasks`.  
> **Scope**: All Python source code under `plugins/quench-dev-tasks/server/`.

---

## 1. Datetime Handling Standard (时间处理标准)

```python
# ✅ Standard: All datetimes generated and compared MUST use UTC-aware objects
from datetime import datetime, timezone

now = datetime.now(timezone.utc)  # Generation
expires_at = datetime.fromisoformat(iso_str)  # Parsing
if expires_at.tzinfo is None:
    expires_at = expires_at.replace(tzinfo=timezone.utc)  # Backward compatibility
```

**Prohibited (禁止)**:
- ❌ `datetime.datetime.now()` (without timezone arguments; yields naive datetime)
- ❌ `datetime.utcnow()` (deprecated in Python 3.12)
- ❌ Direct comparison between aware and naive datetimes (raises `TypeError`)

---

## 2. File Writing Standard (文件写入标准)

```python
# ✅ Standard: All structured state data must use atomic replacement
import tempfile, os, json

def _atomic_write_json(filepath: str, data: dict) -> None:
    """Atomic write via temporary file + os.replace."""
    dir_name = os.path.dirname(os.path.abspath(filepath))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, filepath)  # Atomic operation
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
```

**Prohibited (禁止)**:
- ❌ Direct `open(filepath, "w")` on state, bypass, or task markdown files without atomic protection
- ❌ Failure to clean up temporary files in exception branches

---

## 3. FileLock Usage Standard (FileLock 使用标准)

```python
# ✅ Standard: All FileLock acquisitions must enforce explicit timeouts
from filelock import FileLock, Timeout

LOCK_TIMEOUT = 5.0  # seconds

lock = FileLock(lock_path, timeout=LOCK_TIMEOUT)
try:
    with lock:
        # Operations within lock (Read -> Validate -> Conditional Write)
        pass
except Timeout:
    logger.warning("Lock acquisition timed out; executing graceful fallback")
```

**Prohibited (禁止)**:
- ❌ `FileLock(path)` without timeout parameters (risks infinite hangs in IDE host processes)
- ❌ Performing read-modify-write sequences outside lock context

---

## 4. Input Sanitization Standard (输入校验标准)

```python
import re

# ✅ Standard: External inputs must be validated at entry points
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9\-]{1,128}$", re.IGNORECASE)
MAX_REASON_LENGTH = 500

def _validate_session_id(session_id: str | None) -> str | None:
    """Validate session_id format via UUID regex whitelist."""
    if session_id is None:
        return None
    session_id = session_id.strip()
    if not SESSION_ID_PATTERN.match(session_id):
        return None
    return session_id

def _sanitize_reason(reason: str) -> str:
    """Truncate to safe maximum length."""
    return reason.strip()[:MAX_REASON_LENGTH]
```

---

## 5. Exception Handling Standard (异常处理标准)

```python
import logging

logger = logging.getLogger("quench.file_scope_guard")

# ❌ Prohibited: Silently swallowing exceptions
except Exception:
    pass

# ✅ Standard: Log exception with trace + retain graceful fallback
except Exception as e:
    logger.warning(f"[file_scope_guard] Exception: {e}", exc_info=True)
    return {"decision": "allow"}  # Fail-open fallback policy remains intact
```

---

## 6. Dynamic Path Resolution Standard (路径处理标准)

```python
# ✅ Standard: All internal path references must use dynamic resolution
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "scripts"))

# ✅ Resolve symlinks before path comparison
real_path = os.path.realpath(target_file)

# ✅ Workspace escape defense
try:
    common = os.path.commonpath([real_path, real_root])
    if common != real_root:
        return True  # Escaped workspace boundary -> governed
except ValueError:
    return True  # Cross-drive path -> governed
```

**Prohibited (禁止)**:
- ❌ Hardcoded local absolute paths (`C:\Users\...`, `D:\Work\...`)
- ❌ Using `os.path.normpath` without resolving symlinks via `os.path.realpath`
- ❌ Unhandled `ValueError` in `os.path.commonpath` (Windows cross-drive operations)

---

## 7. Test Naming & Assertion Mandate (测试命名与覆盖规范)

```python
# ✅ Function naming convention: test_<feature>_<scenario>_<expected_behavior>
def test_bypass_concurrent_read_write_no_data_race():
    """Verify concurrent reads and writes on bypass file do not produce data races."""
```

**Mandatory Assertion Rule (改逻辑必加单测断言)**: Every non-trivial logic change must be accompanied by new or updated unit test assertions in `tests/test_*.py`.
