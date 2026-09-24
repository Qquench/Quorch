#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quench Dev Orchestrator (quorch) - 统一轻量 CLI 命令行工具.

为开发者提供非 AI 交互入口，支持在终端中直接进行任务状态巡检 (status)、
环境体检 (check)、项目快速接入 (init) 以及任务封板归档 (archive)。
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

# Windows UTF-8 console defense
if sys.version_info >= (3, 7):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure server and scripts directory are in sys.path
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(SERVER_DIR), "scripts")
)
for d in [SERVER_DIR, SCRIPTS_DIR]:
    if d not in sys.path:
        sys.path.insert(0, d)


class Colors:
    """自适应终端 ANSI 彩色格式化工具。"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._c("1", text)

    def green(self, text: str) -> str:
        return self._c("32", text)

    def yellow(self, text: str) -> str:
        return self._c("33", text)

    def red(self, text: str) -> str:
        return self._c("31", text)

    def cyan(self, text: str) -> str:
        return self._c("36", text)

    def dim(self, text: str) -> str:
        return self._c("2", text)


def should_enable_color(plain: bool = False) -> bool:
    """检测是否应开启 ANSI 彩色显示。"""
    if plain:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


def _mask_secret(secret: Optional[str]) -> str:
    """对敏感凭据（如 API Key）进行不可逆安全脱敏展示。
    - None 或空串 -> 'NOT SET'
    - 长度 <= 8 -> '****'
    - 否则保留前 4 位和后 4 位，中间使用 '****' 脱敏
    """
    if not secret:
        return "NOT SET"
    s = str(secret).strip()
    if not s:
        return "NOT SET"
    if len(s) <= 8:
        return "****"
    return f"{s[:4]}****{s[-4:]}"


def cmd_status(workspace_root: str, plain: bool = False) -> int:
    """终端渲染任务看板。"""
    c = Colors(should_enable_color(plain))
    ws = os.path.abspath(workspace_root)

    try:
        from server import dev_tasks_status

        st = dev_tasks_status(ws)
    except Exception as e:
        print(c.red(f"❌ 获取任务状态失败: {e}"), file=sys.stderr)
        return 1

    project_name = st.get("project_name", os.path.basename(ws))
    dev_tasks_dir = st.get("dev_tasks_dir", "")
    files = st.get("files", [])
    active_task = st.get("active_task")
    bypass = st.get("session_bypass")

    print(c.bold(f"\n======================================================="))
    print(c.bold(f"  Quench 任务状态看板 — [{project_name}]"))
    print(c.bold(f"======================================================="))
    print(f"📁 任务目录: {c.cyan(dev_tasks_dir)}")

    # 1. 活跃执行中任务
    if active_task:
        print(f"\n🔨 {c.bold('当前执行中任务')}:")
        print(
            f"   • [{c.yellow(active_task.get('id', ''))}] {c.bold(active_task.get('title', ''))}"
        )
        print(f"     来源单据: {active_task.get('file', '')}")
    else:
        print(f"\nℹ️  {c.dim('当前工作区无处于【🔨 执行中】的任务。')}")

    # 2. 会话旁路状态
    if bypass and bypass.get("active"):
        cat = bypass.get("category", "custom")
        exp = bypass.get("expires_at", "")
        print(f"\n⚡ {c.yellow('快速旁路生效中')}: [{cat}] (过期时间: {exp})")

    # 3. 任务文件分布
    print(f"\n📋 {c.bold('任务单据概览')} ({len(files)} 个活跃单据):")
    if not files:
        print(f"   {c.dim('暂无活跃任务单。可通过 dev_tasks_propose 提出新规划。')}")
    else:
        for f in files:
            fname = f.get("name", "")
            summary = f.get("summary", {})
            total = f.get("total_tasks", 0)
            status_parts = []
            if summary.get("⬜ 待确认"):
                status_parts.append(c.dim(f"待确认:{summary['⬜ 待确认']}"))
            if summary.get("✅ 已确认"):
                status_parts.append(c.cyan(f"已确认:{summary['✅ 已确认']}"))
            if summary.get("🔨 执行中"):
                status_parts.append(c.yellow(f"执行中:{summary['🔨 执行中']}"))
            if summary.get("✔️ 已完成"):
                status_parts.append(c.green(f"已完成:{summary['✔️ 已完成']}"))
            if summary.get("🔄 需返工"):
                status_parts.append(c.red(f"需返工:{summary['🔄 需返工']}"))

            status_str = " | ".join(status_parts) if status_parts else "空"
            print(f"   • {c.bold(fname)} (共 {total} 项) -> [{status_str}]")

    print(f"-------------------------------------------------------\n")
    return 0


def cmd_check(workspace_root: str) -> int:
    """运行环境与治理状态体检。"""
    ws = os.path.abspath(workspace_root)
    try:
        from init_project import diagnose_environment, print_diagnostic_report

        diag = diagnose_environment(ws)
        print_diagnostic_report(diag, ws)
        return 0 if not diag.get("issues") else 1
    except Exception as e:
        print(f"❌ 环境体检执行失败: {e}", file=sys.stderr)
        return 1


def cmd_check_engine(
    workspace_root: str,
    plain: bool = False,
    as_json: bool = False,
) -> int:
    """检查外部 ReviewerEngine 连通性、凭据可用性与思考流支持。

    Exit code: 0 = 连通正常且配置完备; 1 = 未配置/认证失败/网络异常/超时。
    """
    import json
    import time
    from project_config import load_project_config
    from reviewer_engine import ReviewerClient

    ws = os.path.abspath(workspace_root)
    c = Colors(should_enable_color(plain and not as_json))

    provider = "none"
    model = "none"
    api_key_env = None
    api_key_present = False
    api_key_masked = "NOT SET"
    connectivity_ok = False
    latency_ms: Optional[int] = None
    thinking_supported = False
    thinking_probe = "config"
    error_msg: Optional[str] = None

    try:
        cfg = load_project_config(ws)
        re_cfg = cfg.reviewer_engine
        provider = re_cfg.provider
        model = re_cfg.model
        api_key_env = re_cfg.api_key_env

        m_lower = model.lower()
        thinking_supported = (
            re_cfg.thinking
            or "reasoner" in m_lower
            or "r1" in m_lower
            or "思考" in m_lower
        )

        client = ReviewerClient(re_cfg)
        raw_key = client.resolve_api_key()
        api_key_present = bool(raw_key and raw_key.strip())
        api_key_masked = _mask_secret(raw_key)

        if provider == "none":
            error_msg = "ReviewerEngine provider is set to 'none' / 未启用外部审查引擎"
        elif not api_key_present:
            error_msg = f"API Key environment variable '{api_key_env}' is not set / 未配置环境变量"
        else:
            # 执行极短超时连通性探针 (≤5s)
            start_t = time.perf_counter()
            try:
                probe_res = client.complete(
                    [{"role": "user", "content": "ping"}],
                    timeout=5,
                    total_deadline_s=5.0,
                )
                latency_ms = max(1, int((time.perf_counter() - start_t) * 1000))
                connectivity_ok = True
                if probe_res.get("thinking_content") or probe_res.get("reasoning_content"):
                    thinking_probe = "live"
            except Exception as pe:
                latency_ms = max(1, int((time.perf_counter() - start_t) * 1000))
                connectivity_ok = False
                error_msg = f"Probe connection failed / 探针连接失败: {pe}"
    except Exception as e:
        error_msg = f"Configuration error / 配置读取失败: {e}"

    exit_code = 0 if (provider != "none" and api_key_present and connectivity_ok) else 1

    result = {
        "provider": provider,
        "model": model,
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "api_key_masked": api_key_masked,
        "connectivity_ok": connectivity_ok,
        "latency_ms": latency_ms,
        "thinking_supported": thinking_supported,
        "thinking_probe": thinking_probe,
        "exit_code": exit_code,
    }

    if as_json:
        # JSON 模式下保证 stdout 输出单行纯净 JSON
        print(json.dumps(result, ensure_ascii=False))
        return exit_code

    # 人类可读终端模式
    print(c.bold("\n======================================================="))
    print(c.bold("  Quench ReviewerEngine 体检报告"))
    print(c.bold("======================================================="))
    print(f"⚙️  Provider       : {c.cyan(provider)}")
    print(f"🤖 Model          : {c.cyan(model)}")
    print(f"🔑 API Key Env    : {api_key_env}")
    status_key = c.green(f"已配置 ({api_key_masked})") if api_key_present else c.red("未配置 (NOT SET)")
    print(f"🔒 Key Status     : {status_key}")

    think_desc = c.green(f"支持 ({thinking_probe})") if thinking_supported else c.dim("未开启/不支持")
    print(f"🧠 Thinking Mode  : {think_desc}")

    if connectivity_ok:
        print(f"🌐 Connectivity   : {c.green('✅ 连通正常')} (耗时: {latency_ms} ms)")
    else:
        print(f"🌐 Connectivity   : {c.red('❌ 连接失败')}")
        if error_msg:
            print(f"   {c.red(error_msg)}")

    print(f"-------------------------------------------------------\n")
    return exit_code


def cmd_init(
    project_root: str,
    ide: str = "antigravity",
    install_hook: bool = False,
    force: bool = False,
) -> int:
    """薄封装 init_project.py，支持 --ide 与 --install-git-hook 透传。"""
    proj = os.path.abspath(project_root)
    try:
        from init_project import init_project

        init_project(
            project_root=proj,
            force=force,
            ide=ide,
            install_hook=install_hook,
        )
        return 0
    except SystemExit as se:
        return se.code if se.code is not None else 0
    except Exception as e:
        print(f"❌ 项目初始化失败: {e}", file=sys.stderr)
        return 1


def cmd_archive(workspace_root: str, yes: bool = False) -> int:
    """执行已完成任务单的封板归档。"""
    ws = os.path.abspath(workspace_root)
    try:
        from server import dev_tasks_archive, dev_tasks_status

        st = dev_tasks_status(ws)
        files = st.get("files", [])
        if not files:
            print("ℹ️ 当前没有找到需要归档的任务单据。")
            return 0

        archived_count = 0
        for f in files:
            fname = f.get("name", "")
            summary = f.get("summary", {})
            pending = summary.get("⬜ 待确认", 0)
            in_prog = summary.get("🔨 执行中", 0)
            rework = summary.get("🔄 需返工", 0)

            if pending > 0 or in_prog > 0 or rework > 0:
                print(
                    f"⚠️ 任务单 [{fname}] 仍有未闭环任务 "
                    f"(待确认:{pending}, 执行中:{in_prog}, 需返工:{rework})，跳过归档。"
                )
                continue

            # 满足归档条件
            res = dev_tasks_archive(ws, fname)
            if res.get("archived"):
                print(f"✅ 成功归档任务单: {fname}")
                archived_count += 1
            else:
                print(f"❌ 归档失败 [{fname}]: {res.get('error', '未知原因')}")

        if archived_count > 0:
            print(f"\n🎉 归档完成，共封板归档 {archived_count} 个任务单据。")
            return 0
        else:
            print("\n⚠️ 未能成功归档任何任务单据（可能仍有未完成条目）。")
            return 1
    except Exception as e:
        print(f"❌ 归档过程发生异常: {e}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 统一主入口。返回进程退出码。"""
    parser = argparse.ArgumentParser(
        prog="quench",
        description="Quench Dev Orchestrator (quorch) 命令行工具中心",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        default=".",
        help="工作区根目录路径（默认当前目录）",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="禁用彩色输出，使用普通纯文本格式",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以单行纯净 JSON 格式输出机器可解析数据",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用子命令")

    # 1. status
    p_status = subparsers.add_parser("status", help="查看任务分布、活跃任务与治理看板")
    p_status.add_argument(
        "-w", "--workspace", default=argparse.SUPPRESS, help="工作区根目录（默认当前目录）"
    )
    p_status.add_argument("--plain", action="store_true", default=argparse.SUPPRESS, help="禁用彩色输出")

    # 2. check
    p_check = subparsers.add_parser("check", help="运行环境健康体检与依赖审计")
    p_check.add_argument(
        "-w", "--workspace", default=argparse.SUPPRESS, help="工作区根目录（默认当前目录）"
    )
    p_check.add_argument(
        "--engine", action="store_true", help="检查外部审查模型引擎连通性与配置体检"
    )
    p_check.add_argument("--plain", action="store_true", default=argparse.SUPPRESS, help="禁用彩色输出")
    p_check.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="以单行 JSON 输出")

    # 3. check-engine
    p_check_engine = subparsers.add_parser("check-engine", help="检查外部审查模型引擎连通性与体检")
    p_check_engine.add_argument(
        "-w", "--workspace", default=argparse.SUPPRESS, help="工作区根目录（默认当前目录）"
    )
    p_check_engine.add_argument("--plain", action="store_true", default=argparse.SUPPRESS, help="禁用彩色输出")
    p_check_engine.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="以单行 JSON 输出")

    # 4. init
    p_init = subparsers.add_parser("init", help="初始化目标项目接入 Quench 治理体系")
    p_init.add_argument(
        "project_root", nargs="?", default=".", help="目标项目目录（默认当前目录）"
    )
    p_init.add_argument(
        "--ide",
        choices=["antigravity", "cursor", "all"],
        default="antigravity",
        help="目标 IDE 环境 (antigravity | cursor | all，默认 antigravity)",
    )
    p_init.add_argument(
        "--cursor", action="store_true", help="快捷选项：等同于 --ide cursor"
    )
    p_init.add_argument(
        "--install-git-hook",
        action="store_true",
        help="自动将 Quench Git Pre-commit Guard 部署至目标项目",
    )
    p_init.add_argument(
        "--force", action="store_true", help="强制覆盖已有的配置文件"
    )

    # 5. archive
    p_archive = subparsers.add_parser("archive", help="归档已完工的任务单据至 archive/ 并同步 CHANGELOG")
    p_archive.add_argument(
        "-w", "--workspace", default=argparse.SUPPRESS, help="工作区根目录（默认当前目录）"
    )
    p_archive.add_argument(
        "-y", "--yes", action="store_true", help="非交互确认归档"
    )

    try:
        args = parser.parse_args(argv)
    except SystemExit as se:
        return se.code if se.code is not None else 0

    ws = getattr(args, "workspace", ".") or "."
    plain = getattr(args, "plain", False)
    as_json = getattr(args, "json", False)

    try:
        if args.command == "status" or args.command is None:
            return cmd_status(ws, plain=plain)
        elif args.command == "check":
            if getattr(args, "engine", False):
                return cmd_check_engine(ws, plain=plain, as_json=as_json)
            return cmd_check(ws)
        elif args.command == "check-engine":
            return cmd_check_engine(ws, plain=plain, as_json=as_json)
        elif args.command == "init":
            effective_ide = "cursor" if args.cursor else args.ide
            return cmd_init(
                project_root=args.project_root,
                ide=effective_ide,
                install_hook=args.install_git_hook,
                force=args.force,
            )
        elif args.command == "archive":
            return cmd_archive(ws, yes=args.yes)
        else:
            parser.print_help()
            return 0
    except Exception as e:
        print(f"❌ 执行命令出错: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
