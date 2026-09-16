$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$vendorDir = Join-Path $projectDir 'vendor\ffmpeg'
$buildDir = Join-Path $projectDir 'build'
$distDir = Join-Path $projectDir 'dist'
$extractDir = Join-Path $projectDir 'build\ffmpeg-download'
$archivePath = Join-Path $projectDir 'build\ffmpeg-release-essentials.zip'

# 判断候选路径是否严格位于独立工具目录内，避免清理到工作区其他位置。
function Test-PathInsideProject {
    param([string]$candidatePath)
    $resolvedProject = [System.IO.Path]::GetFullPath($projectDir).TrimEnd('\') + '\'
    $resolvedCandidate = [System.IO.Path]::GetFullPath($candidatePath)
    return $resolvedCandidate.StartsWith($resolvedProject, [System.StringComparison]::OrdinalIgnoreCase)
}

# 从系统 PATH 复制 ffmpeg，缺失时使用 wget 下载 Windows essentials 构建。
function Prepare-Ffmpeg {
    New-Item -ItemType Directory -Path $vendorDir -Force | Out-Null
    $systemFfmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    $systemFfprobe = Get-Command ffprobe.exe -ErrorAction SilentlyContinue
    if ($systemFfmpeg -and $systemFfprobe) {
        Copy-Item -LiteralPath $systemFfmpeg.Source -Destination (Join-Path $vendorDir 'ffmpeg.exe') -Force
        Copy-Item -LiteralPath $systemFfprobe.Source -Destination (Join-Path $vendorDir 'ffprobe.exe') -Force
        return
    }

    New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
    $wgetCommand = Get-Command wget.exe -ErrorAction SilentlyContinue
    if ($wgetCommand) {
        & $wgetCommand.Source 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' '-O' $archivePath
    } else {
        Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile $archivePath
    }
    if (Test-Path $extractDir) {
        if (-not (Test-PathInsideProject $extractDir)) {
            throw 'Refusing to clean a path outside the standalone project.'
        }
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir -Force
    $downloadedFfmpeg = Get-ChildItem -LiteralPath $extractDir -Filter 'ffmpeg.exe' -Recurse | Select-Object -First 1
    $downloadedFfprobe = Get-ChildItem -LiteralPath $extractDir -Filter 'ffprobe.exe' -Recurse | Select-Object -First 1
    if (-not $downloadedFfmpeg -or -not $downloadedFfprobe) {
        throw 'The downloaded ffmpeg archive is missing required executables.'
    }
    Copy-Item -LiteralPath $downloadedFfmpeg.FullName -Destination (Join-Path $vendorDir 'ffmpeg.exe') -Force
    Copy-Item -LiteralPath $downloadedFfprobe.FullName -Destination (Join-Path $vendorDir 'ffprobe.exe') -Force
}

Set-Location $projectDir
Write-Host '==> 1/4 Prepare Python build environment'
if (-not (Test-Path '.venv')) {
    python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host '==> 2/4 Prepare bundled ffmpeg'
Prepare-Ffmpeg

Write-Host '==> 3/4 Build single-file Windows application'
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name 'URLVideoDownloader' `
    --collect-all yt_dlp `
    --add-binary "$(Join-Path $vendorDir 'ffmpeg.exe');ffmpeg" `
    --add-binary "$(Join-Path $vendorDir 'ffprobe.exe');ffmpeg" `
    run_app.py

Write-Host '==> 4/4 Build completed'
Write-Host "Output: $(Join-Path $distDir 'URLVideoDownloader.exe')"
