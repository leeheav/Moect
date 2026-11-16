<#
.SYNOPSIS
    Moect 一键自动化打包构建脚本 (PowerShell)
.DESCRIPTION
    自动检测环境、安装/检查依赖（使用国内加速源）、编译前端、打包 Python 桌面应用及生成 Inno Setup 安装包。
#>
param(
    [switch]$SkipPip,
    [switch]$SkipNpm,
    [switch]$NoInstaller,
    [string]$OutputDirectory = "release"
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot

function Write-Step {
    param([string]$Text)
    Write-Host "`n========================================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "========================================================" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "[!] $Text" -ForegroundColor Yellow
}

function Write-Failure {
    param([string]$Text)
    Write-Host "[X] $Text" -ForegroundColor Red
}

try {
    Write-Host "`n========================================================" -ForegroundColor Magenta
    Write-Host "             Moect 一键自动化打包构建程序              " -ForegroundColor Magenta
    Write-Host "========================================================" -ForegroundColor Magenta

    # -------------------------------------------------------------------------
    # [1/5] 检查系统环境与基础工具
    # -------------------------------------------------------------------------
    Write-Step "[1/5] 检查系统环境与基础工具..."

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        throw "未检测到 Python。请先安装 Python 3.11 或 3.12 (64位) 并勾选 'Add Python to PATH'。"
    }
    $pyVer = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    Write-Success "检测到 Python 版本: $pyVer ($($pythonCmd.Source))"

    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $nodeCmd -or -not $npmCmd) {
        throw "未检测到 Node.js / npm。请先安装 Node.js (推荐 v18 或 v22+)。"
    }
    $nodeVer = node -v
    Write-Success "检测到 Node.js 版本: $nodeVer ($($nodeCmd.Source))"

    # -------------------------------------------------------------------------
    # [2/5] 准备 Python 虚拟环境与依赖
    # -------------------------------------------------------------------------
    Write-Step "[2/5] 准备 Python 虚拟环境与依赖..."

    $venvDir = Join-Path $projectRoot '.venv'
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "正在创建 Python 虚拟环境 (.venv)..." -ForegroundColor Gray
        python -m venv .venv
        if (-not (Test-Path -LiteralPath $venvPython)) {
            throw "虚拟环境创建失败，请检查 Python 安装与权限。"
        }
        Write-Success "已成功创建虚拟环境: $venvDir"
    } else {
        Write-Success "复用现有虚拟环境: $venvDir"
    }

    if (-not $SkipPip) {
        # 检查核心依赖是否存在，不存在则执行安装
        $needsInstall = $true
        $checkScript = "import PySide6, PyInstaller, webview, zstandard, pysilk; print('OK')"
        $checkResult = & $venvPython -c $checkScript 2>$null
        if ($checkResult -match 'OK') {
            Write-Success "核心 Python 依赖已就绪，跳过全量下载。"
            $needsInstall = $false
        }

        if ($needsInstall) {
            Write-Host "正在通过国内清华源安装依赖包 (设置 600s 超时防断流)..." -ForegroundColor Gray
            $pipArgs = @('install', '-r', 'requirements.txt', '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple', '--default-timeout=600')
            & $venvPython -m pip @pipArgs
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "清华源安装遇到波动，尝试切换至阿里云镜像源重试..."
                $pipArgsAli = @('install', '-r', 'requirements.txt', '-i', 'https://mirrors.aliyun.com/pypi/simple/', '--default-timeout=600')
                & $venvPython -m pip @pipArgsAli
                if ($LASTEXITCODE -ne 0) {
                    throw "Python 依赖安装失败，请检查网络或代理配置。"
                }
            }
            Write-Success "Python 依赖包安装完成。"
        }
    } else {
        Write-Host "已跳过 Python 依赖检查与安装 (-SkipPip)。" -ForegroundColor Gray
    }

    # -------------------------------------------------------------------------
    # [3/5] 构建前端界面 (Vite + React)
    # -------------------------------------------------------------------------
    Write-Step "[3/5] 构建前端静态资源 (ui-qce)..."

    $frontendDir = Join-Path $projectRoot 'frontend'
    $nodeModules = Join-Path $frontendDir 'node_modules'

    if (-not (Test-Path -LiteralPath $nodeModules) -and -not $SkipNpm) {
        Write-Host "正在安装前端依赖 (npm ci)..." -ForegroundColor Gray
        & npm ci --prefix frontend
        if ($LASTEXITCODE -ne 0) {
            throw "前端 npm ci 执行失败。"
        }
        Write-Success "前端依赖安装完成。"
    }

    Write-Host "正在执行 TypeScript 校验与 Vite 生产打包..." -ForegroundColor Gray
    & npm run build --prefix frontend
    if ($LASTEXITCODE -ne 0) {
        throw "前端构建失败 (npm run build)。"
    }

    # 恢复图标到 ui-qce
    $uiQceDir = Join-Path $projectRoot 'ui-qce'
    Copy-Item (Join-Path $projectRoot 'ui\icon.svg') (Join-Path $uiQceDir 'icon.svg') -Force
    if (Test-Path (Join-Path $projectRoot 'icon.ico')) {
        Copy-Item (Join-Path $projectRoot 'icon.ico') (Join-Path $uiQceDir 'icon.ico') -Force
    }
    Write-Success "前端打包完成，资源已同步至 ui-qce/。"

    # -------------------------------------------------------------------------
    # [4/5] 打包独立桌面程序 (PyInstaller onedir)
    # -------------------------------------------------------------------------
    Write-Step "[4/5] 打包独立 Windows 桌面程序 (build.py)..."

    & $venvPython build.py
    if ($LASTEXITCODE -ne 0) {
        throw "Python 桌面程序打包失败 (build.py)。"
    }

    $distExe = Join-Path $projectRoot 'dist\Moect\Moect.exe'
    if (-not (Test-Path -LiteralPath $distExe)) {
        throw "未找到构建目标程序: $distExe"
    }
    $exeSizeMb = [math]::Round((Get-Item -LiteralPath $distExe).Length / 1MB, 2)
    Write-Success "独立运行目录打包成功: dist\Moect\Moect.exe ($exeSizeMb MB)"

    # -------------------------------------------------------------------------
    # [5/5] Inno Setup 一键安装包生成 (可选)
    # -------------------------------------------------------------------------
    Write-Step "[5/5] 检查 Inno Setup 安装包制作..."

    $outputResolved = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
    New-Item -ItemType Directory -Path $outputResolved -Force | Out-Null

    if ($NoInstaller) {
        Write-Host "已跳过安装包生成 (-NoInstaller)。" -ForegroundColor Gray
    } else {
        $compiler = Join-Path $env:LOCALAPPDATA 'Programs\InnoSetup\ISCC.exe'
        if (-not (Test-Path -LiteralPath $compiler)) {
            $compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
        }
        if (-not (Test-Path -LiteralPath $compiler)) {
            $compiler = Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'
        }

        if (Test-Path -LiteralPath $compiler) {
            Write-Host "检测到 Inno Setup 编译器: $compiler" -ForegroundColor Gray
            Write-Host "正在编译 Windows 安装包 (Setup.exe)..." -ForegroundColor Gray
            & (Join-Path $projectRoot 'installer\build.ps1') -OutputDirectory $outputResolved
            if ($LASTEXITCODE -eq 0) {
                Write-Success "一键安装包制作完成！"
                Write-Host "正在生成便携 ZIP 与哈希校验 (SHA256SUMS.txt)..." -ForegroundColor Gray
                & $venvPython (Join-Path $projectRoot 'scripts\package_release.py') $outputResolved --no-source
                Write-Success "发布包已生成至: $outputResolved"
            } else {
                Write-Warn "Inno Setup 编译退出异常，安装包未能生成；绿色版 dist\Moect 仍可用。"
            }
        } else {
            Write-Warn "未检测到 Inno Setup 6.5+ (ISCC.exe)。"
            Write-Host "  -> 绿色免安装版已在 dist\Moect\ 准备就绪，可直接分发运行。" -ForegroundColor Gray
            Write-Host "  -> 若需要生成 Setup 安装包，请下载安装 Inno Setup: https://jrsoftware.org/isdl.php" -ForegroundColor Gray
        }
    }

    Write-Host "`n========================================================" -ForegroundColor Green
    Write-Host "                   全部构建流程成功完成！               " -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host "绿色免安装版位置: $(Join-Path $projectRoot 'dist\Moect')" -ForegroundColor White
    if (Test-Path -LiteralPath $outputResolved) {
        $setupFiles = Get-ChildItem -LiteralPath $outputResolved -Filter *.exe
        if ($setupFiles.Count -gt 0) {
            Write-Host "一键安装包位置:   $($setupFiles[0].FullName)" -ForegroundColor White
        }
    }
    Write-Host ""
}
catch {
    Write-Host "`n========================================================" -ForegroundColor Red
    Write-Host "                     构建过程中断                       " -ForegroundColor Red
    Write-Host "========================================================" -ForegroundColor Red
    Write-Failure $_.Exception.Message
    exit 1
}
