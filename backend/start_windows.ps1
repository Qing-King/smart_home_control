param(
    [switch]$SkipRun
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $scriptDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$envFile = Join-Path $scriptDir ".env"
$envExampleFile = Join-Path $scriptDir ".env.example"
$requirementsFile = Join-Path $scriptDir "requirements.txt"
$entryFile = Join-Path $scriptDir "run_web.py"

function Get-PythonCommand {
    $commands = @(
        @{ Name = "py"; Args = @("-3") },
        @{ Name = "python"; Args = @() }
    )

    foreach ($candidate in $commands) {
        if (Get-Command $candidate.Name -ErrorAction SilentlyContinue) {
            return $candidate
        }
    }

    throw "未找到 Python。请先安装 Python 3，并确保 `py` 或 `python` 可用。"
}

function Ensure-Venv {
    if (Test-Path $venvPython) {
        return
    }

    $python = Get-PythonCommand
    Write-Host "创建虚拟环境..."
    & $python.Name @($python.Args + @("-m", "venv", $venvDir))
}

function Ensure-EnvFile {
    if (Test-Path $envFile) {
        return
    }

    if (-not (Test-Path $envExampleFile)) {
        throw "缺少 .env.example，无法自动生成 .env。"
    }

    Copy-Item $envExampleFile $envFile
    Write-Host "已创建 backend/.env，请按需填写 MQTT 配置。"
}

Set-Location $scriptDir

Ensure-Venv
Ensure-EnvFile

Write-Host "安装或更新依赖..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirementsFile

if ($SkipRun) {
    Write-Host "依赖安装完成。已跳过启动。"
    exit 0
}

Write-Host "启动后端服务..."
& $venvPython $entryFile
