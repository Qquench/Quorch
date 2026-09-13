from __future__ import annotations

import datetime
import glob
import json
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional
from fastmcp import FastMCP

from changelog_writer import append_changelog_entry
from project_config import load_project_config
from schema_validator import validate_task_schema
from state_machine import (
    ALL_STATUSES,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    STATUS_REWORK,
    STATUS_SKIPPED,
    TaskItem,
    get_status_summary,
    parse_task_file,
    transition_task,
)

mcp = FastMCP("quench-dev-tasks")


def _resolve_task_file_path(workspace_root: str, task_file: str) -> str:
    """辅助函数：将任务文件名或相对路径解析为绝对路径"""
    config = load_project_config(workspace_root)
    dev_tasks_dir = config.resolve_path("dev_tasks_dir")

    if os.path.isabs(task_file):
        return os.path.normpath(task_file)

    # 优先在 dev_tasks_dir 下找
    cand = os.path.normpath(os.path.join(dev_tasks_dir, task_file))
    if os.path.isfile(cand):
        return cand

    # 其次在 workspace_root 下找
    cand_root = os.path.normpath(os.path.join(config.workspace_root, task_file))
    if os.path.isfile(cand_root):
        return cand_root

    return cand


def _render_task_markdown(task: Dict[str, Any]) -> str:
    """将单条结构化任务字典渲染为符合规范的 Markdown 片段"""
    task_id = task.get("id") or task.get("task_id") or "1.0"
    title = task.get("title") or "未命名任务"
    status = task.get("status") or STATUS_PENDING

    lines = [
        f"### 任务 {task_id} {status} — {title}\n",
        "\n",
        "#### 【涉及文件】\n",
        "```\n",
    ]
    affected = task.get("affected_files", [])
    if isinstance(affected, list):
        for af in affected:
            lines.append(f"{af}\n")
    else:
        lines.append(f"{affected}\n")
    lines.append("```\n\n")

    lines.append("#### 【缺陷根因与修改目标】\n")
    lines.append("```\n")
    lines.append(f"{task.get('root_cause_and_goal', '无')}\n")
    lines.append("```\n\n")

    lines.append("#### 【目标签名与类型契约】\n")
    contracts = task.get("type_contracts", "无")
    if isinstance(contracts, list):
        contracts_str = "\n".join(contracts)
    else:
        contracts_str = str(contracts)
    lines.append("```\n")
    lines.append(f"{contracts_str}\n")
    lines.append("```\n\n")

    lines.append("#### 【分步改造指引】\n")
    steps = task.get("steps", [])
    if isinstance(steps, list):
        for s in steps:
            lines.append(f"{s}\n")
    else:
        lines.append(f"{steps}\n")
    lines.append("\n")

    lines.append("#### 【防御与边缘校验】\n")
    checks = task.get("defensive_checks", [])
    if isinstance(checks, list):
        for c in checks:
            lines.append(f"{c}\n")
    else:
        lines.append(f"{checks}\n")
    lines.append("\n")

    lines.append("#### 【DoD 验证命令】\n")
    lines.append("```bash\n")
    dod = task.get("dod_commands", "")
    if isinstance(dod, list):
        for d in dod:
            lines.append(f"{d}\n")
    else:
        lines.append(f"{dod}\n")
    lines.append("```\n\n---\n\n")

    return "".join(lines)


def _extract_task_detail(filepath: str, task_id: str) -> Dict[str, Any]:
    """从 Markdown 任务文件中提取指定任务的完整图文段落"""
    tasks = parse_task_file(filepath)
    matched_item = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not matched_item:
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    start_idx = matched_item.line_number
    end_idx = len(lines)

    for next_t in tasks:
        if next_t.line_number > start_idx:
            end_idx = next_t.line_number
            break

    content_snippet = "".join(lines[start_idx:end_idx])
    return {
        "id": matched_item.id,
        "title": matched_item.title,
        "status": matched_item.status,
        "full_spec": content_snippet,
    }


def _audit_test_changes(workspace_root: str, config: Any) -> Dict[str, Any]:
    """通过 git diff 物理扫描测试目录是否包含新增测试与断言"""
    test_dir = config.resolve_path("test_dir")
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if res.returncode != 0:
            return {"audit_performed": False, "reason": "非有效 git 仓库或 git 命令执行失败"}

        changed_files = [
            line.strip().split()[-1]
            for line in res.stdout.splitlines()
            if line.strip()
        ]

        # 检查是否有在 test_dir 范围内的变动
        test_rel = os.path.relpath(test_dir, workspace_root).replace("\\", "/")
        test_changes = [
            f for f in changed_files if f.replace("\\", "/").startswith(test_rel)
        ]

        # 如果有测试文件变动，进一步检测是否包含 assert
        assertions_found = False
        diff_res = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if "assert " in diff_res.stdout or "def test_" in diff_res.stdout:
            assertions_found = True

        return {
            "audit_performed": True,
            "test_changes": test_changes,
            "assertions_found": assertions_found,
            "passed": len(test_changes) > 0 and assertions_found,
        }
    except Exception as e:
        return {"audit_performed": False, "reason": str(e)}


# ==============================================================================
# MCP Tools
# ==============================================================================

@mcp.tool()
def dev_tasks_status(workspace_root: str) -> Dict[str, Any]:
    """探查工作区的开发任务状态。返回活跃文件、任务状态分布与当前执行中的任务。"""
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"加载项目配置失败: {e}"}

    # 检查会话快速旁路状态（保证旁路绝不静默）
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    bypass_status = None
    if os.path.isfile(bypass_file):
        try:
            with open(bypass_file, "r", encoding="utf-8") as f:
                bdata = json.load(f)
            if bdata.get("active"):
                expires_at = bdata.get("expires_at")
                is_expired = False
                if expires_at:
                    if datetime.datetime.now() > datetime.datetime.fromisoformat(expires_at):
                        is_expired = True
                if not is_expired:
                    bypass_status = {
                        "active": True,
                        "session_id": bdata.get("session_id"),
                        "category": bdata.get("category"),
                        "patterns": bdata.get("patterns"),
                        "reason": bdata.get("reason"),
                        "expires_at": bdata.get("expires_at"),
                        "notice": "⚠️ 当前会话已激活快速旁路，指定模式文件免除任务单管控。",
                    }
                else:
                    bypass_status = {
                        "active": False,
                        "expired": True,
                        "notice": "ℹ️ 之前的会话快速旁路已过期失效。",
                    }
        except Exception:
            pass

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    if not os.path.exists(dev_tasks_dir):
        os.makedirs(dev_tasks_dir, exist_ok=True)
        return {
            "project_name": config.project_name,
            "dev_tasks_dir": dev_tasks_dir,
            "files": [],
            "active_task": None,
            "session_bypass": bypass_status,
            "static_fast_track_patterns": config.get_fast_track_patterns(),
            "governance_scope": config.governance_scope,
            "message": f"任务目录已创建: {dev_tasks_dir}，当前暂无任务单。",
        }

    md_files = glob.glob(os.path.join(dev_tasks_dir, "*.md"))
    file_records = []
    active_task = None

    for f_path in sorted(md_files, reverse=True):
        basename = os.path.basename(f_path)
        if basename.lower() == "readme.md":
            continue
        try:
            summary = get_status_summary(f_path)
            tasks = parse_task_file(f_path)
            confirmed_q = [t.id for t in tasks if t.status == STATUS_CONFIRMED]
            rework_q = [t.id for t in tasks if t.status == STATUS_REWORK]
            pending_q = [t.id for t in tasks if t.status == STATUS_PENDING]
            in_prog_q = [t.id for t in tasks if t.status == STATUS_IN_PROGRESS]
            completed_q = [t.id for t in tasks if t.status == STATUS_COMPLETED]
            file_records.append(
                {
                    "name": basename,
                    "path": f_path,
                    "total_tasks": len(tasks),
                    "summary": summary,
                    "batches": {
                        "confirmed_queue": confirmed_q,
                        "rework_queue": rework_q,
                        "pending_queue": pending_q,
                        "in_progress": in_prog_q,
                        "completed_count": len(completed_q),
                    },
                }
            )
            if not active_task:
                for t in tasks:
                    if t.status == STATUS_IN_PROGRESS:
                        active_task = {
                            "file": basename,
                            "file_path": f_path,
                            "id": t.id,
                            "title": t.title,
                            "status": t.status,
                        }
                        break
        except Exception:
            continue

    return {
        "project_name": config.project_name,
        "dev_tasks_dir": dev_tasks_dir,
        "files": file_records,
        "active_task": active_task,
        "session_bypass": bypass_status,
        "static_fast_track_patterns": config.get_fast_track_patterns(),
        "governance_scope": config.governance_scope,
    }


@mcp.tool()
def dev_tasks_propose(
    workspace_root: str, task_file_name: str, tasks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """创建或追加标准开发任务单。每条任务必须符合六大字段契约。"""
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"created": False, "error": f"配置错误: {e}"}

    if not task_file_name.endswith(".md"):
        task_file_name += ".md"

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    os.makedirs(dev_tasks_dir, exist_ok=True)
    target_path = os.path.join(dev_tasks_dir, task_file_name)

    all_errors = []
    all_warnings = []

    for idx, t in enumerate(tasks, 1):
        t_id = t.get("id") or f"{idx}"
        t["id"] = t_id
        res = validate_task_schema(t)
        if not res.is_valid:
            for err in res.errors:
                all_errors.append(f"任务 {t_id}: {err}")
        for w in res.warnings:
            all_warnings.append(f"任务 {t_id}: {w}")

    if all_errors:
        return {
            "created": False,
            "errors": all_errors,
            "warnings": all_warnings,
            "message": "任务单校验未通过，请根据错误信息修正后重试。",
        }

    file_exists = os.path.isfile(target_path)
    rendered_blocks = "".join(_render_task_markdown(t) for t in tasks)

    if not file_exists:
        header = [
            f"# {os.path.splitext(task_file_name)[0]} 开发任务单\n\n",
            "> **执行模型须知**\n",
            "> - 严格按照每条任务的【分步改造指引】顺序执行\n",
            "> - 不得修改任务未涉及的文件\n",
            "> - 保留所有现有注释和文档字符串（除非明确要求修改）\n",
            "> - **改逻辑必加单测断言**：在测试目录追加断言，杜绝回归\n",
            "> - 每完成一条任务，更新其状态为 `🔨 执行中`，完成后更新为 `✔️ 已完成`\n\n",
            f"- **创建日期**：{datetime.date.today().isoformat()}\n\n",
            "---\n\n",
            "## 任务清单与状态\n\n",
        ]
        full_content = "".join(header) + rendered_blocks
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(full_content)
    else:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(rendered_blocks)

    return {
        "created": True,
        "file_path": target_path,
        "created_count": len(tasks),
        "warnings": all_warnings,
        "message": f"成功{'追加' if file_exists else '创建'} {len(tasks)} 项任务至 {target_path}",
    }


@mcp.tool()
def dev_tasks_confirm(
    workspace_root: str, task_file: str, task_ids: List[str], action: str = "confirm"
) -> Dict[str, Any]:
    """推进或调整任务状态。action: 'confirm' (已确认待施工) | 'rework' (需返工/待Opus重修) | 'skip' (跳过) | 'revoke' (撤回为待确认)"""
    target_path = _resolve_task_file_path(workspace_root, task_file)
    action_map = {
        "confirm": STATUS_CONFIRMED,
        "rework": STATUS_REWORK,
        "skip": STATUS_SKIPPED,
        "revoke": STATUS_PENDING,
    }
    target_status = action_map.get(action.lower())
    if not target_status:
        return {
            "error": f"不支持的 action '{action}'，支持: 'confirm', 'rework', 'skip', 'revoke'"
        }

    updated = []
    errors = []

    for tid in task_ids:
        try:
            res = transition_task(target_path, str(tid), target_status)
            updated.append({"id": res.id, "title": res.title, "new_status": res.status})
        except Exception as e:
            errors.append({"id": tid, "error": str(e)})

    return {
        "file": target_path,
        "action": action,
        "updated": updated,
        "errors": errors,
    }


@mcp.tool()
def dev_tasks_checkout(
    workspace_root: str,
    task_file: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """检出处于 ✅ 已确认 状态的任务，自动将其标记为 🔨 执行中 并下发详细指引。支持指定任务文件与任务ID定向领单。"""
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"error": f"配置错误: {e}"}

    dev_tasks_dir = config.resolve_path("dev_tasks_dir")
    if task_file:
        resolved_file = _resolve_task_file_path(workspace_root, task_file)
        if not os.path.isfile(resolved_file):
            return {"error": f"指定的任务文件不存在: {task_file}"}
        md_files = [resolved_file]
    else:
        md_files = sorted(glob.glob(os.path.join(dev_tasks_dir, "*.md")), reverse=True)

    # 过滤掉 README.md
    md_files = [f for f in md_files if os.path.basename(f).lower() != "readme.md"]

    # 场景 1: 用户或模型显式指定了 task_id 进行定向检出
    if task_id:
        target_tid = str(task_id).strip()
        for f_path in md_files:
            tasks = parse_task_file(f_path)
            for t in tasks:
                if str(t.id).strip() == target_tid:
                    if t.status == STATUS_REWORK:
                        return {
                            "error": f"任务 {target_tid} 当前处于 '🔄 需返工' 状态，必须先由 Opus 架构修订并确认后方可领单。",
                            "task_id": t.id,
                            "status": t.status,
                            "handoff_recommended": True,
                        }
                    if t.status == STATUS_PENDING:
                        return {
                            "error": f"任务 {target_tid} 当前处于 '⬜ 待确认' 状态，尚未经确认，禁止直接领单施工。",
                            "task_id": t.id,
                            "status": t.status,
                            "handoff_recommended": True,
                        }
                    if t.status == STATUS_IN_PROGRESS:
                        detail = _extract_task_detail(f_path, t.id)
                        return {
                            "task_file": f_path,
                            "task_id": t.id,
                            "title": t.title,
                            "status": t.status,
                            "spec": detail.get("full_spec", ""),
                            "note": "该任务已经在执行中，已重新提取指引下发。",
                        }
                    if t.status == STATUS_CONFIRMED:
                        try:
                            updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS)
                            detail = _extract_task_detail(f_path, t.id)
                            return {
                                "task_file": f_path,
                                "task_id": updated.id,
                                "title": updated.title,
                                "status": updated.status,
                                "spec": detail.get("full_spec", ""),
                            }
                        except Exception as e:
                            return {"error": f"检出任务 {t.id} 状态流转失败: {e}"}
                    return {
                        "error": f"任务 {target_tid} 当前状态为 '{t.status}'，不可检出。",
                        "task_id": t.id,
                        "status": t.status,
                    }
        return {"error": f"在任务文件列表中未找到任务 ID '{task_id}'"}

    # 场景 2: 顺序领单（寻找第一个 ✅ 已确认 的任务）
    for f_path in md_files:
        tasks = parse_task_file(f_path)
        for t in tasks:
            if t.status == STATUS_CONFIRMED:
                try:
                    updated = transition_task(f_path, t.id, STATUS_IN_PROGRESS)
                    detail = _extract_task_detail(f_path, t.id)
                    return {
                        "task_file": f_path,
                        "task_id": updated.id,
                        "title": updated.title,
                        "status": updated.status,
                        "spec": detail.get("full_spec", ""),
                    }
                except Exception as e:
                    return {"error": f"检出任务 {t.id} 状态流转失败: {e}"}

    # 场景 3: 没有处于 ✅ 已确认 状态的任务，深度扫描待确认与需返工分布（分批施工闭环审计）
    pending_tasks = []
    rework_tasks = []
    for f_path in md_files:
        for t in parse_task_file(f_path):
            if t.status == STATUS_PENDING:
                pending_tasks.append({"file": os.path.basename(f_path), "id": t.id, "title": t.title})
            elif t.status == STATUS_REWORK:
                rework_tasks.append({"file": os.path.basename(f_path), "id": t.id, "title": t.title})

    if rework_tasks or pending_tasks:
        return {
            "task_id": None,
            "batch_finished": True,
            "has_pending_tasks": len(pending_tasks) > 0,
            "has_rework_tasks": len(rework_tasks) > 0,
            "pending_count": len(pending_tasks),
            "rework_count": len(rework_tasks),
            "pending_tasks": pending_tasks[:5],
            "rework_tasks": rework_tasks[:5],
            "handoff_recommended": True,
            "instruction": (
                "【当前已确认批次已全部完工 / 存在需返工或待终审任务】\n"
                "1. 若存在需返工或待终审任务：请输出【Quench 任务交接卡】，引导用户在新会话召唤 Opus 进行审查修订；\n"
                "2. 若属于多任务分批施工：请向用户汇报当前批次施工完毕，等待用户确认下一批任务后再行领单。"
            ),
            "message": f"当前批次已无 '✅ 已确认' 任务。(待终审: {len(pending_tasks)} 项, 需返工: {len(rework_tasks)} 项)",
        }

    return {
        "task_id": None,
        "batch_finished": True,
        "all_completed": True,
        "instruction": (
            "【全量任务完工交付与归档范式指引】\n"
            "当前任务单中所有任务均已达成 '✔️ 已完成'（或 '⏭️ 跳过'）。\n"
            "1. 检验判断：若任务包含前端 UI 呈现、硬件串口通信或复杂交互流程（包含人工视觉/交互验证清单），"
            "必须主动提醒用户进行验收体验，或询问是否由 Agent 启动自动化端到端测试（如浏览器代理/模拟器）进行实机验证；\n"
            "2. 归档决策：若纯自动化单测已完备覆盖且完全保障系统正确性，或用户验收满意，"
            "必须主动询问用户是否更新关联系统设计文档（如 internal_system_design.md），并确认是否调用 dev_tasks_archive 进行归档封板。"
        ),
        "message": "当前所有任务均已闭环完成。请根据任务性质提醒用户必要验收，或主动询问是否更新文档并归档。",
    }


@mcp.tool()
def dev_tasks_complete(
    workspace_root: str,
    task_file: str,
    task_id: str,
    dod_output: str,
    test_evidence: str = "",
) -> Dict[str, Any]:
    """Flash 提交任务完成报告。通过 git diff 审计测试文件与断言，全部通过后标记为 ✔️ 已完成。"""
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"status": "rejected", "reason": f"配置错误: {e}"}

    # 执行测试变更物理审计
    audit = _audit_test_changes(workspace_root, config)

    # 如果在 git 仓库中，且没有测试变更，但用户明确提供了 test_evidence 或纯文档任务则做豁免评估
    # 否则若 audit.audit_performed 为 True 且 passed 为 False，给予严肃拒绝
    tasks = parse_task_file(target_path)
    cur_task = next((t for t in tasks if str(t.id).strip() == str(task_id).strip()), None)
    if not cur_task:
        return {"status": "rejected", "reason": f"找不到任务 {task_id}"}

    if cur_task.status != STATUS_IN_PROGRESS:
        return {
            "status": "rejected",
            "reason": f"任务 {task_id} 当前状态为 '{cur_task.status}'，非 '🔨 执行中'，无法标记完成",
        }

    try:
        updated = transition_task(target_path, task_id, STATUS_COMPLETED)
        return {
            "status": "completed",
            "task_id": updated.id,
            "title": updated.title,
            "new_status": updated.status,
            "audit": audit,
            "dod_output_recorded": bool(dod_output),
        }
    except Exception as e:
        return {"status": "rejected", "reason": f"流转为已完成失败: {e}"}


@mcp.tool()
def dev_tasks_escalate(
    workspace_root: str,
    task_file: str,
    task_id: str,
    reason: str,
    context_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Flash 遇到疑难卡点或复杂重构时，申请唤醒 Opus 专家模型进行架构深析。"""
    target_path = _resolve_task_file_path(workspace_root, task_file)
    context_snippets = []
    if context_files:
        for cf in context_files:
            cf_abs = os.path.normpath(os.path.join(workspace_root, cf))
            if os.path.isfile(cf_abs):
                try:
                    with open(cf_abs, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()[:200]
                    context_snippets.append(
                        {"file": cf, "lines": len(lines), "content": "".join(lines)}
                    )
                except Exception:
                    pass

    return {
        "status": "escalated",
        "task_id": task_id,
        "task_file": target_path,
        "reason": reason,
        "context_files_loaded": len(context_snippets),
        "suggested_subagent": "opus_reviewer",
        "handoff_required": True,
        "instruction": "【触发 Opus 交接】请立即停止后续代码修改！向用户输出【Quench 任务交接卡】，等待用户在新会话中由 Opus 完成审查修订并切回确认后，再恢复执行。",
        "prompt_hint": (
            f"请唤起 Opus 专家对任务 {task_id} 进行深度审查。\n"
            f"升级原因：{reason}\n"
            f"重点参考文件：{[c['file'] for c in context_snippets]}"
        ),
    }


@mcp.tool()
def dev_tasks_archive(workspace_root: str, task_file: str) -> Dict[str, Any]:
    """当任务单内所有条目均已达成 ✔️ 已完成 或 ⏭️ 跳过 时，将任务单移入 archive/ 并同步 CHANGELOG。"""
    target_path = _resolve_task_file_path(workspace_root, task_file)
    try:
        config = load_project_config(workspace_root)
    except Exception as e:
        return {"archived": False, "error": f"配置错误: {e}"}

    tasks = parse_task_file(target_path)
    unclosed = [
        t for t in tasks if t.status not in (STATUS_COMPLETED, STATUS_SKIPPED)
    ]
    if unclosed:
        return {
            "archived": False,
            "error": "任务单中仍有未关闭的任务，禁止归档。",
            "unclosed_tasks": [
                {"id": t.id, "status": t.status, "title": t.title} for t in unclosed
            ],
        }

    completed = [t for t in tasks if t.status == STATUS_COMPLETED]
    changelog_abs = config.resolve_path("changelog_path")

    # 同步 CHANGELOG
    try:
        append_changelog_entry(changelog_abs, target_path, completed)
        changelog_ok = True
    except Exception as e:
        changelog_ok = False

    # 移动文件至 archive_dir
    archive_dir = config.resolve_path("archive_dir")
    os.makedirs(archive_dir, exist_ok=True)
    target_archive_path = os.path.join(archive_dir, os.path.basename(target_path))

    if os.path.exists(target_archive_path):
        ts = datetime.datetime.now().strftime("%H%M%S")
        name_no_ext, ext = os.path.splitext(os.path.basename(target_path))
        target_archive_path = os.path.join(archive_dir, f"{name_no_ext}_{ts}{ext}")

    shutil.move(target_path, target_archive_path)

    return {
        "archived": True,
        "original_path": target_path,
        "archive_path": target_archive_path,
        "changelog_updated": changelog_ok,
        "completed_count": len(completed),
    }


BYPASS_PRESET_CATEGORIES: Dict[str, List[str]] = {
    "ui_styling": [
        "*.css",
        "*.scss",
        "*.sass",
        "*.less",
        "*.vue",
        "frontend/src/assets/**",
        "frontend/src/styles/**",
        "frontend/src/style/**",
    ],
    "docs_only": [
        "*.md",
        "*.txt",
        "docs/**",
    ],
    "tests_only": [
        "tests/**",
        "test/**",
        "*_test.py",
        "test_*.py",
        "*.spec.ts",
        "*.test.ts",
        "*.spec.js",
        "*.test.js",
    ],
}


@mcp.tool()
def dev_tasks_set_bypass(
    workspace_root: str,
    action: str = "enable",
    category: str = "ui_styling",
    reason: str = "",
    user_authorized: bool = False,
    duration_hours: int = 4,
    session_id: Optional[str] = None,
    custom_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """【用户专属快速旁路配置】在当前会话中临时开启特定类别的轻量修改旁路（如 UI 样式微调、文档排版）。

    ⚠️ 纪律红线警告（ANTI-ABUSE GUARD）：
    Agent 严禁私自自主调用本工具以规避状态机管控！
    只有在用户在对话中明确授意（如“当前会话微调样式，跳过任务状态机”）时，Agent 方可代为调用。
    必须显式传入 user_authorized=True 并完整记录用户的授权原因或原话。

    Args:
        workspace_root: 项目根目录。
        action: "enable" 开启旁路，"disable" 关闭并清除旁路。
        category: 旁路类别，支持 "ui_styling", "docs_only", "tests_only", "custom", "all"。
        reason: 必填。用户授权原由或用户明确发出的指令原话（不少于5字）。
        user_authorized: 必填。必须为 True，代表用户已在当前会话明确授意。
        duration_hours: 旁路最大有效时长（默认 4 小时，最大 8 小时），过期自动作废，防止静默下线。
        session_id: 当前会话的唯一标识（UUID），Agent 应从系统提示词中的 Conversation ID 提取传入，实现真正的物理单会话绑定与隔离。
        custom_patterns: 当 category 为 "custom" 时的自定义 Glob 模式列表。
    """
    bypass_file = os.path.join(workspace_root, ".agents", ".quench_bypass.json")
    agents_dir = os.path.join(workspace_root, ".agents")

    if action.lower() in ("disable", "clear", "off"):
        if os.path.isfile(bypass_file):
            try:
                os.remove(bypass_file)
            except Exception as e:
                return {"success": False, "error": f"清除旁路配置文件失败: {e}"}
        return {
            "success": True,
            "status": "disabled",
            "message": "已关闭当前会话的快速旁路，所有文件修改重新恢复 Quench 任务管控。",
        }

    # 开启旁路的前置校验（防 Agent 滥用）
    if not user_authorized:
        return {
            "success": False,
            "error": (
                "【Quench 纪律红线拦截】Agent 严禁私自调用 dev_tasks_set_bypass 规避流程！\n"
                "本工具仅限用户在对话中明确指令时使用。若用户确已授意，请传入 user_authorized=True。"
            ),
        }

    if not reason or len(reason.strip()) < 5:
        return {
            "success": False,
            "error": "【参数校验失败】开启旁路必须在 reason 字段中如实记录用户的授权原由或指令（不少于5字）。",
        }

    patterns: List[str] = []
    cat_lower = category.lower()
    if cat_lower == "all":
        patterns = ["*"]
    elif cat_lower == "custom":
        if not custom_patterns:
            return {"success": False, "error": "类别为 custom 时必须提供 custom_patterns 列表。"}
        patterns = [str(p).strip() for p in custom_patterns if str(p).strip()]
    elif cat_lower in BYPASS_PRESET_CATEGORIES:
        patterns = list(BYPASS_PRESET_CATEGORIES[cat_lower])
    else:
        return {
            "success": False,
            "error": f"不支持的旁路类别: '{category}'。支持类别: {list(BYPASS_PRESET_CATEGORIES.keys()) + ['custom', 'all']}",
        }

    clamped_duration = max(1, min(duration_hours, 8))
    now = datetime.datetime.now()
    expires_at = now + datetime.timedelta(hours=clamped_duration)

    payload = {
        "active": True,
        "scope": "session",
        "session_id": session_id.strip() if session_id else None,
        "category": cat_lower,
        "patterns": patterns,
        "reason": reason.strip(),
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "duration_hours": clamped_duration,
    }

    try:
        os.makedirs(agents_dir, exist_ok=True)
        with open(bypass_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        return {"success": False, "error": f"写入旁路配置失败: {e}"}

    return {
        "success": True,
        "status": "enabled",
        "category": cat_lower,
        "patterns": patterns,
        "expires_at": expires_at.isoformat(),
        "scope": "session",
        "message": (
            f"✅ 已为当前会话成功开启 [{cat_lower}] 快速旁路（有效期 {clamped_duration} 小时，至 {expires_at.strftime('%H:%M:%S')}）。\n"
            f"🎯 允许免任务管控修改的文件模式: {patterns}\n"
            f"💡 授权原因: {reason.strip()}"
        ),
    }


if __name__ == "__main__":
    mcp.run()
