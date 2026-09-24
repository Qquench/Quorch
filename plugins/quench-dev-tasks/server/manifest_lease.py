# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at http://mozilla.org/MPL/2.0/.

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

try:
    from .manifest import (
        load_manifest,
        touch_heartbeat,
        Manifest,
        TaskRecord,
        ManifestIntegrityError,
    )
except (ImportError, ValueError):
    from manifest import (
        load_manifest,
        touch_heartbeat,
        Manifest,
        TaskRecord,
        ManifestIntegrityError,
    )


class LeaseContractError(Exception):
    """租约契约校验失败（参数越界、session 映射不存在等），调用方须在发起前修正。"""
    pass


MAX_TTL: int = 3600  # 秒，可由项目配置覆写


def extract_session_id_from_holder_token(holder_token: str) -> Optional[str]:
    """从 token_<clean_sid>_<timestamp>_<pid> 中安全提取 session_id。"""
    if not holder_token:
        return None
    if holder_token.startswith("token_"):
        parts = holder_token.split("_")
        if len(parts) >= 4:
            extracted = "_".join(parts[1:-2])
            if extracted:
                return extracted
    return None


def is_workspace_actively_modifying(
    workspace_root: str,
    files: Sequence[str],
    window_seconds: int = 300,
    *,
    max_scan: int = 256,
    now_ts: Optional[float] = None,
) -> bool:
    """检查工作区白名单文件中，是否存在 mtime 距 now 在 window_seconds 内的文件。
    - 纯读函数，无副作用。
    - 进入循环前对每个 path 做 resolve() + is_relative_to(workspace_root) 校验；
      越界/穿越项（如 ../、绝对路径跨盘符等）静默剔除。
    - 全部 stat 失败 / 非 OSError：返回 True（保守存活，防误杀），stderr 告警。
    - 命中首个新鲜 mtime 即短路返回 True（early-exit）。
    - 扫描数不超过 max_scan（超出截断，记录告警）。
    - 父目录兜底：白名单缺省纳入不存在文件的父目录 mtime，覆盖 [NEW] 文件冷启动场景。

    【已知局限声明】
    长时间纯计算/网络等待（>window_seconds）且不留白名单文件 mtime 时，hb_stale ∧ mtime_stale
    两套机制同时失效，仍会触发 STALE_SUSPECT。此为设计已知局限。
    """
    ws_path = Path(workspace_root).resolve()
    current_time = float(now_ts) if now_ts is not None else time.time()

    # 1. 路径规整与穿越过滤
    candidate_paths: list[Path] = []
    parent_fallbacks: list[Path] = []

    for f in files:
        if not f or not isinstance(f, str):
            continue
        try:
            p = Path(f)
            if not p.is_absolute():
                p = ws_path / f
            p_resolved = p.resolve()

            # 严格校验是否在 workspace_root 范围内，越界/穿越项静默剔除
            try:
                if not p_resolved.is_relative_to(ws_path):
                    continue
            except AttributeError:
                if p_resolved != ws_path and ws_path not in p_resolved.parents:
                    continue

            candidate_paths.append(p_resolved)

            # 父目录兜底冷启动：若文件尚未物理生成，提取其有效父目录
            if not p_resolved.exists():
                parent = p_resolved.parent
                try:
                    is_rel = parent.is_relative_to(ws_path)
                except AttributeError:
                    is_rel = (parent == ws_path or ws_path in parent.parents)
                if is_rel and parent.exists():
                    if parent not in parent_fallbacks and parent not in candidate_paths:
                        parent_fallbacks.append(parent)
        except Exception:
            # 任何路径解析异常静默剔除
            continue

    # 追加父目录检查点兜底冷启动
    all_scan_targets = candidate_paths + parent_fallbacks

    # 2. max_scan 截断防卫
    if len(all_scan_targets) > max_scan:
        sys.stderr.write(
            f"[WARN] is_workspace_actively_modifying: targets count {len(all_scan_targets)} exceeds max_scan {max_scan}, truncating.\n"
        )
        all_scan_targets = all_scan_targets[:max_scan]

    if not all_scan_targets:
        # 如果传入白名单过滤后无任何有效工作区目标，视为全部 stat 失败（保守存活）
        sys.stderr.write(
            "[WARN] is_workspace_actively_modifying: no valid target files to stat, returning True (fail-safe conservative alive).\n"
        )
        return True

    # 3. 遍历 stat 检查新鲜度
    stat_success_count = 0

    for path_obj in all_scan_targets:
        try:
            st = path_obj.stat()
            stat_success_count += 1
            age = current_time - st.st_mtime
            if 0.0 <= age <= float(window_seconds):
                # 命中首个新鲜 mtime 即短路返回 True（early-exit）
                return True
        except (OSError, Exception):
            # stat 失败（文件不存在、权限受限等）
            pass

    # 4. 全部 stat 失败检测（保守存活）
    if stat_success_count == 0:
        sys.stderr.write(
            "[WARN] is_workspace_actively_modifying: all stat calls failed, returning True (fail-safe conservative alive).\n"
        )
        return True

    # 至少有一个成功 stat 但均超过 window_seconds，判定为不活跃
    return False


def touch_lease_heartbeat(
    workspace_root: str,
    session_id: str,
    ttl_seconds: int,
    *,
    holder_token: Optional[str] = None,
    generation: Optional[int] = None,
    task_id: Optional[str] = None,
) -> bool:
    """面向外部调用方的显式心跳刷新。
    - ttl_seconds 须满足 0 < ttl_seconds <= MAX_TTL，否则抛 LeaseContractError。
    - 锁内同时校验 session_id ∧ holder_token ∧ generation 三者一致时续约；
    - 任何不一致：fail-closed 返回 False；
    - 读取 generation/holder_token 后立即委托，不得缓存（避免 TOCTOU）。

    【设计与并发安全性声明】
    fail-closed 校验发生在 touch_heartbeat 临界区内且同时校验 holder_token 与 generation；
    manifest_lease 侧只读加载清单不额外持锁，但绝不缓存结果（避免 TOCTOU），读取后立即下发委托。
    """
    if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0 or ttl_seconds > MAX_TTL:
        raise LeaseContractError(
            f"ttl_seconds must be in (0, {MAX_TTL}], got {ttl_seconds} / ttl_seconds 必须在 (0, {MAX_TTL}] 范围内"
        )

    if not session_id or not isinstance(session_id, str):
        return False

    clean_sid = session_id.strip()
    if not clean_sid:
        return False

    try:
        manifest = load_manifest(workspace_root)
    except Exception:
        return False

    # 查找符合 session_id 的活跃未释放任务记录
    target_record: Optional[TaskRecord] = None

    for tid, rec in manifest.records.items():
        if rec.released:
            continue
        if task_id:
            clean_tid = str(task_id).strip()
            if rec.task_id != clean_tid and not rec.task_id.endswith(f"::{clean_tid}"):
                continue

        # 匹配 session_id：直接匹配 holder_token 或提取 token 中的 session_id
        if rec.holder_token == clean_sid:
            target_record = rec
            break
        extracted_sid = extract_session_id_from_holder_token(rec.holder_token)
        if extracted_sid and extracted_sid == clean_sid:
            target_record = rec
            break

    if target_record is None:
        return False

    # 校验调用方若提供了 holder_token / generation 是否匹配
    token_to_verify = holder_token if holder_token is not None else target_record.holder_token
    gen_to_verify = generation if generation is not None else target_record.generation

    if holder_token is not None and target_record.holder_token != holder_token:
        return False
    if generation is not None and target_record.generation != generation:
        return False

    # 立即委托 manifest.touch_heartbeat（在锁内同时原子校验 generation ∧ holder_token）
    # 不在 manifest_lease 侧重复持锁，亦不缓存 generation/holder_token（避免 TOCTOU）
    try:
        return touch_heartbeat(
            workspace_root,
            task_id=target_record.task_id,
            holder_token=token_to_verify,
            generation=gen_to_verify,
        )
    except Exception:
        return False
