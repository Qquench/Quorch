<#
.SYNOPSIS
    Quench DevTasks 一键初始化与环境体检脚本 (PowerShell)

.DESCRIPTION
    为指定项目或当前目录快速初始化 Quench 任务治理体系，包括自动生成 .agents/plugins.json、
    .agents/quench_stack.yaml 与 .agents/hooks.json（支持 Windows cmd.exe /c 安全引号防护），
    或执行全量环境就绪度健康体检（包括 Hooks 完整性诊断）。

.NOTES
    Windows ExecutionPolicy 说明:
    若在执行时提示 "在此系统上禁止运行脚本" (PSSecurityException)，请使用 Bypass 策略单次执行:
        powershell -ExecutionPolicy Bypass -File .\quench-init.ps1 [-Check]
    
    或在当前 PowerShell 会话临时放行:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

    或直接将本脚本 dot-source 加载至当前 Session / $PROFILE:
        . .\quench-init.ps1
        quench-init -Check
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$TargetDir = (Get-Location).Path,

    [Parameter()]
    [string]$ProjectName,

    [Parameter()]
    [switch]$Check,

    [Parameter(HelpMessage = "强制覆盖已存在的 quench_stack.yaml 与 hooks.json")]
    [switch]$Force
)

$ScriptDirectory = $PSScriptRoot
if (-not $ScriptDirectory) {
    $ScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $ScriptDirectory) {
    $ScriptDirectory = (Get-Location).Path
}

$InitPy = Join-Path $ScriptDirectory "init_project.py"
if (-not (Test-Path $InitPy)) {
    Write-Error "❌ 未找到 init_project.py: $InitPy"
    return
}

# 查找可用 Python 解释器（优先虚拟环境）
$PythonExe = "python"
$VenvCandidates = @(
    (Join-Path $TargetDir "venv\Scripts\python.exe"),
    (Join-Path $TargetDir ".venv\Scripts\python.exe"),
    (Join-Path $ScriptDirectory "..\..\..\venv\Scripts\python.exe")
)

foreach ($candidate in $VenvCandidates) {
    if (Test-Path $candidate) {
        $PythonExe = (Resolve-Path $candidate).Path
        break
    }
}

$CallArgs = @($InitPy, $TargetDir)
if ($Check) {
    $CallArgs += "--check"
}
if ($Force) {
    $CallArgs += "--force"
}
if ($ProjectName) {
    $CallArgs += "--name"
    $CallArgs += $ProjectName
}

& $PythonExe $CallArgs

function global:quench-init {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)]
        [string]$TargetDir = (Get-Location).Path,

        [Parameter()]
        [string]$ProjectName,

        [Parameter()]
        [switch]$Check,

        [Parameter()]
        [switch]$Force
    )

    $ScriptDir = $PSScriptRoot
    if (-not $ScriptDir) {
        $ScriptDir = (Get-Location).Path
    }
    $PyScript = Join-Path $ScriptDir "init_project.py"
    $PyExe = "python"
    $Candidates = @(
        (Join-Path $TargetDir "venv\Scripts\python.exe"),
        (Join-Path $TargetDir ".venv\Scripts\python.exe"),
        (Join-Path $ScriptDir "..\..\..\venv\Scripts\python.exe")
    )
    foreach ($cand in $Candidates) {
        if (Test-Path $cand) {
            $PyExe = (Resolve-Path $cand).Path
            break
        }
    }
    $ArgsList = @($PyScript, $TargetDir)
    if ($Check) { $ArgsList += "--check" }
    if ($Force) { $ArgsList += "--force" }
    if ($ProjectName) { $ArgsList += @("--name", $ProjectName) }
    & $PyExe $ArgsList
}
