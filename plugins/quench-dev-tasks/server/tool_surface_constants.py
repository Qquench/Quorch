"""tool_surface_constants.py - MCP Tool Surface Single Source of Truth Constants.

Defines the expected MCP tools, versioning metadata, sentinel object for missing defaults,
and parameter default accessors.
DO NOT RELOAD THIS MODULE.
"""

from __future__ import annotations

from typing import Any, Callable, Final

EXPECTED_TOOL_NAMES: Final[frozenset[str]] = frozenset({
    "dev_tasks_status",
    "dev_tasks_propose",
    "dev_tasks_confirm",
    "dev_tasks_checkout",
    "dev_tasks_complete",
    "dev_tasks_heartbeat",
    "dev_tasks_reclaim",
    "dev_tasks_promote_draft",
    "dev_tasks_refine_spec",
    "dev_tasks_escalate",
    "dev_tasks_export_handoff_card",
    "dev_tasks_archive",
    "dev_tasks_set_bypass",
    "dev_reviewer_submit",
    "dev_reviewer_poll",
    "dev_reviewer_cancel",
})

TOOL_COUNT: Final[int] = len(EXPECTED_TOOL_NAMES)
TOOL_ALLOWS_CTX: Final[frozenset[str]] = frozenset()
CTX_PARAM_ALIASES: Final[frozenset[str]] = frozenset({"ctx"})
SCHEMA_META_KEY: Final[str] = "_meta"
SNAPSHOT_SCHEMA_VERSION: Final[int] = 1
META_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({"schema_version"})


def _missing_singleton() -> "_MissingSentinel":
    return MISSING


class _MissingSentinel:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<MISSING>"

    def __reduce__(self) -> tuple[Callable[[], "_MissingSentinel"], tuple[()]]:
        return (_missing_singleton, ())

    def __copy__(self) -> "_MissingSentinel":
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "_MissingSentinel":
        return self

    def __bool__(self) -> bool:
        raise TypeError("MISSING 禁止用于布尔上下文；请使用 has_default()")

    def __eq__(self, other: Any) -> bool:
        return other is self

    def __hash__(self) -> int:
        return hash("<QUENCH_MISSING_SENTINEL>")


MISSING: Final[_MissingSentinel] = _MissingSentinel()


def _get_param_info(snapshot: dict[str, Any], tool: str, param: str) -> dict[str, Any] | None:
    if not isinstance(snapshot, dict) or tool not in snapshot:
        return None
    t_val = snapshot[tool]
    if not isinstance(t_val, dict):
        return None

    # 1. 直接键结构: d[tool][param]
    if param in t_val and isinstance(t_val[param], dict):
        return t_val[param]

    # 2. properties: d[tool]["properties"][param] 或 d[tool]["parameters"]["properties"][param]
    props = None
    if "properties" in t_val and isinstance(t_val["properties"], dict):
        props = t_val["properties"]
    elif "parameters" in t_val and isinstance(t_val["parameters"], dict):
        p_obj = t_val["parameters"]
        if "properties" in p_obj and isinstance(p_obj["properties"], dict):
            props = p_obj["properties"]

    if props is not None and param in props and isinstance(props[param], dict):
        return props[param]

    return None


def has_default(snapshot: dict[str, Any], tool: str, param: str) -> bool:
    info = _get_param_info(snapshot, tool, param)
    if info is None:
        return False
    return "default" in info


def get_default(snapshot: dict[str, Any], tool: str, param: str) -> Any:
    info = _get_param_info(snapshot, tool, param)
    if info is None or "default" not in info:
        return MISSING
    return info["default"]


def iter_param_names(snapshot: dict[str, Any], tool: str) -> frozenset[str]:
    if not isinstance(snapshot, dict) or tool not in snapshot:
        return frozenset()
    t_val = snapshot[tool]
    if not isinstance(t_val, dict):
        return frozenset()

    if "parameters" in t_val and isinstance(t_val["parameters"], dict):
        p_obj = t_val["parameters"]
        if "properties" in p_obj and isinstance(p_obj["properties"], dict):
            return frozenset(p_obj["properties"].keys())
    if "properties" in t_val and isinstance(t_val["properties"], dict):
        return frozenset(t_val["properties"].keys())

    excluded = {"description", "title", "$schema", "type", "required", "additionalProperties", "_meta"}
    return frozenset(k for k, v in t_val.items() if k not in excluded and isinstance(v, dict))
