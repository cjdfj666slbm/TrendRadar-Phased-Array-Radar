# TrendRadar 开箱即用版 —— 单文件打包脚本
#
# 用途：把 TrendRadar + 图形管理器 + Python 运行时打包成一个独立 exe，
#       用户下载后双击即可使用，无需安装 Python。
#
# 用法（在项目根目录执行）：
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_standalone.ps1

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv312\Scripts\python.exe"
$templateDir = Join-Path $projectRoot "templates\config"
$entryFile = Join-Path $projectRoot "tools\standalone_entry.py"
$distPath = Join-Path $projectRoot "dist\Standalone"
$name = "TrendRadar"

Write-Output "=== TrendRadar 开箱即用版打包 ==="
Write-Output "项目根：$projectRoot"

# ---------- 1. 环境检查 ----------
if (-not (Test-Path $pythonPath)) {
    throw "找不到 $pythonPath。请先创建 .venv312 并安装依赖（uv sync）。"
}
if (-not (Test-Path $entryFile)) {
    throw "找不到入口脚本：$entryFile"
}

& $pythonPath -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Output "安装 PyInstaller..."
    & uv pip install --python $pythonPath pyinstaller | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败" }
}

foreach ($pkg in @("ruamel.yaml", "litellm", "feedparser", "requests", "yaml")) {
    & $pythonPath -c "import $pkg" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "缺少依赖：$pkg。请执行 uv sync" }
}

# ---------- 2. 生成干净配置模板（关键：不含任何凭据）----------
Write-Output ""
Write-Output "=== 生成干净配置模板 ==="
& uv tool run --python 3.12 --with ruamel.yaml python (Join-Path $projectRoot "tools\make_clean_template.py")
if ($LASTEXITCODE -ne 0) { throw "模板生成失败" }

# 再次确认模板不含凭据
$templateConfig = Get-Content (Join-Path $templateDir "config.yaml") -Raw -Encoding UTF8
foreach ($marker in @("sk-", "oapi.dingtalk.com/robot", "open.feishu.cn/open-apis/bot/v2/hook/")) {
    if ($templateConfig -match [regex]::Escape($marker)) {
        throw "模板中检测到凭据残留（$marker），已中止打包以免泄露。请检查 config.yaml。"
    }
}

# ---------- 3. 打包 ----------
Write-Output ""
Write-Output "=== PyInstaller 打包（约 1-2 分钟）==="
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
$buildDir = Join-Path $env:TEMP "TrendRadarStandalone-build"
$specDir = Join-Path $env:TEMP "TrendRadarStandalone-spec"

Push-Location $projectRoot
try {
    & $pythonPath -m PyInstaller --noconfirm --clean --onefile --console `
        --name $name `
        --distpath $distPath `
        --workpath $buildDir `
        --specpath $specDir `
        --paths $projectRoot `
        --paths (Join-Path $projectRoot "tools") `
        --add-data "$templateDir;config" `
        --hidden-import litellm `
        --hidden-import trendradar_manager `
        --hidden-import trendradar `
        --collect-data litellm `
        --collect-data pytz `
        --collect-submodules litellm `
        $entryFile
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败，退出码 $LASTEXITCODE" }
}
finally {
    Pop-Location
}

$exePath = Join-Path $distPath "$name.exe"
if (-not (Test-Path $exePath)) {
    throw "打包报告成功，但未找到产物：$exePath"
}

$sizeMb = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
Write-Output ""
Write-Output "=== 打包完成 ==="
Write-Output "产物：$exePath"
Write-Output "大小：$sizeMb MB"
Write-Output ""
Write-Output "发布前检查："
Write-Output "  1. 在一个空文件夹里单独运行该 exe，确认 GUI 能打开"
Write-Output "  2. 确认首次运行自动生成 runtime\\config（且 api_key 为空）"
Write-Output "  3. 确认产物未包含个人凭据"
