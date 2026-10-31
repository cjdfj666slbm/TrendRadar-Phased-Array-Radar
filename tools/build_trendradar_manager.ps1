$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv312\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    throw "Python environment not found: $pythonPath"
}
if (-not (Test-Path (Join-Path $projectRoot "config\config.yaml"))) {
    throw "TrendRadar config.yaml not found in $projectRoot"
}

$distPath = Join-Path $projectRoot "dist"
New-Item -ItemType Directory -Force -Path $distPath | Out-Null

# 固定产物名：每次构建覆盖，避免 dist 目录无限的 -2/-3/-4 堆积
$name = "TrendRadarManager"
$exePath = Join-Path $distPath "${name}.exe"

# 若旧 exe 正在运行，先终止，否则覆盖会因文件占用失败
Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output "Stopping running instance PID $($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
if (Test-Path $exePath) {
    Remove-Item $exePath -Force
}

# 清理历史遗留的带序号产物（TrendRadarManager-2.exe 等）
Get-ChildItem -LiteralPath $distPath -Filter "${name}-*.exe" -File -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output "Removing legacy artifact: $($_.Name)"
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}

Push-Location $projectRoot
try {
    & uv tool run --python 3.12 --with pyinstaller --with ruamel.yaml pyinstaller `
        --noconfirm --clean --onefile --noconsole `
        --name $name `
        --distpath $distPath `
        --workpath (Join-Path $env:TEMP "TrendRadarManager-build") `
        --specpath (Join-Path $env:TEMP "TrendRadarManager-spec") `
        --paths (Join-Path $projectRoot "tools") `
        (Join-Path $projectRoot "tools\trendradar_manager.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE; no Desktop shortcut was created."
    }
}
finally {
    Pop-Location
}

if (-not (Test-Path $exePath)) {
    throw "Packaging reported success, but the executable is missing: $exePath"
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$shortcut = $null
$distPrefix = [IO.Path]::GetFullPath($distPath).TrimEnd('\') + '\'
foreach ($candidatePath in Get-ChildItem -LiteralPath $desktop -Filter "TrendRadar Manager*.lnk" -File) {
    $candidate = $shell.CreateShortcut($candidatePath.FullName)
    if (-not $candidate.TargetPath) {
        continue
    }
    $candidateTarget = [IO.Path]::GetFullPath($candidate.TargetPath)
    $candidateName = [IO.Path]::GetFileName($candidateTarget)
    if (
        $candidateTarget.StartsWith($distPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        $candidateName.StartsWith("TrendRadarManager", [StringComparison]::OrdinalIgnoreCase) -and
        $candidateName.EndsWith(".exe", [StringComparison]::OrdinalIgnoreCase)
    ) {
        $shortcut = $candidate
        $shortcutPath = $candidatePath.FullName
        break
    }
}
if ($null -eq $shortcut) {
    $shortcutName = "TrendRadar Manager"
    $shortcutPath = Join-Path $desktop "${shortcutName}.lnk"
    $shortcutSuffix = 2
    while (Test-Path $shortcutPath) {
        $shortcutName = "TrendRadar Manager ($shortcutSuffix)"
        $shortcutPath = Join-Path $desktop "${shortcutName}.lnk"
        $shortcutSuffix++
    }
    $shortcut = $shell.CreateShortcut($shortcutPath)
}
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "TrendRadar Windows Manager"
$shortcut.IconLocation = "$exePath,0"
$shortcut.Save()

$verification = $shell.CreateShortcut($shortcutPath)
$expectedTarget = [IO.Path]::GetFullPath($exePath)
$actualTarget = [IO.Path]::GetFullPath($verification.TargetPath)
if ($actualTarget -ne $expectedTarget) {
    throw "Desktop shortcut verification failed. Expected '$expectedTarget'; got '$actualTarget'."
}

Write-Output "Executable: $exePath"
Write-Output "Desktop shortcut: $shortcutPath"
Write-Output "Shortcut target verified: $actualTarget"
