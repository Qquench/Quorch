> **Status**: ✅ Resolved & Archived (2026-11-26, Task 36.16)
>
> **Resolution Summary**:
> 1. `project_config.py::QuenchStackConfig.is_path_governed` now exempts Quench internal ephemeral runtime state files under `.agents/.quench_*` (while keeping `.agents/quench_stack.yaml`, `hooks.json`, `mcp_config.json`, and `plugins.json` governed), and `server.py::dev_tasks_checkout` resets `cumulative_runner_tasks` only when `> 0`. Regression coverage added in `tests/test_dod_guard.py::test_dod_guard_natural_pass_on_docs_only`.
> 2. `tests/test_log_naming.py::test_gc_with_active_registry_zero_stat` scopes the `os.stat` / `os.lstat` / `os.path.realpath` monkeypatches inside `with monkeypatch.context()` and verifies file survival via `os.listdir(tmp_path)` inside the context before calling `os.path.exists(pinned_path)` after exit (fixing the Ubuntu POSIX `genericpath.exists` `os.stat` call).

# CI Failure Report — commit 6b14210

- Repo: Qquench/Quorch (branch `main`)
- Commit: `6b14210be45ea132b6799ea7ec10e4e17702fcf2` — "feat: v1.36 full repo audit remediation (batches 1-6.1)"
- Workflow: CI — run [45786190281](https://github.com/Qquench/Quorch/actions/runs/45786190281)
- Conclusion: **failure**
- Previous run (`287802a`, run 44910650548): success

## Failed jobs

| Job | Job ID | Failed step | Result |
|-----|--------|-------------|--------|
| Test (windows-latest - Python 3.12) | 139793423514 | Run test suite | exit code 1 |
| Test (ubuntu-latest - Python 3.12) | 139793423653 | Run test suite | exit code 1 |

Failing step command (`.github/workflows/ci.yml`):

```
PYTHONPATH=plugins/quench-dev-tasks/server
pytest plugins/quench-dev-tasks/server/tests -v -rA --tb=short
```

## Test results

| Job | Result |
|-----|--------|
| Windows, Py 3.12 | 1 failed, 1416 passed, 12 warnings (116s) |
| Ubuntu, Py 3.12 | 2 failed, 1414 passed, 1 skipped, 12 warnings (78s) |

### Failures

1. `tests/test_dod_guard.py::test_dod_guard_natural_pass_on_docs_only` (Windows + Ubuntu)
   ```
   test_dod_guard.py:261: assert res["status"] == "completed"
   E  AssertionError: assert 'rejected' == 'completed'
   ```
2. `tests/test_log_naming.py::test_gc_with_active_registry_zero_stat` (Ubuntu only)
   ```
   test_log_naming.py:494: assert os.path.exists(pinned_path)
   test_log_naming.py:474: in _boom_stat
   E  RuntimeError: stat/lstat called on 20261126_001_pinned_sess.log
   ```
   The test's own stat-boom patch fires on the test's `os.path.exists` call (same class as case 6 in `docs/ci_incident_tracker_and_compatibility_guide.md`: global stdlib monkeypatch).

Annotations from the API only say `Process completed with exit code 1` (plus an unrelated Node.js 20 deprecation warning).

## Log retrieval

Full logs were fetched with the repo's documented protocol (`docs/ci_incident_tracker_and_compatibility_guide.md` §2.2: reuse the Git Credential Manager token). Raw logs saved locally (not committed):
`brain/85d5378b-.../scratch/job_139793423514.log` (Windows), `job_139793423653.log` (Ubuntu).

## Relation to uncommitted task 36.14

The failures are in `test_dod_guard.py` and `test_log_naming.py`, not in tier1 collection. 36.14 only changes the `conftest.py` tier1_fast filter, so it is unlikely to fix these (unverified; the tests were not run locally).
