# Ensures Docker Desktop is running; starts it if needed and waits until the daemon responds.
# Usage:  .\docker\ensure_docker.ps1           (timeout 90s)
#         .\docker\ensure_docker.ps1 -TimeoutSeconds 180

param(
    [int]$TimeoutSeconds = 90,
    [string]$DockerDesktopExe = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
)

$ErrorActionPreference = "Stop"

function Test-DockerDaemon {
    $null = docker info 2>$null
    return $LASTEXITCODE -eq 0
}

if (Test-DockerDaemon) {
    Write-Host "[ensure_docker] Daemon ja esta respondendo." -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $DockerDesktopExe)) {
    Write-Error "Docker Desktop nao encontrado em: $DockerDesktopExe"
    exit 2
}

$running = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
if (-not $running) {
    Write-Host "[ensure_docker] Iniciando Docker Desktop..." -ForegroundColor Yellow
    Start-Process -FilePath $DockerDesktopExe | Out-Null
} else {
    Write-Host "[ensure_docker] Docker Desktop ja em execucao, aguardando engine..." -ForegroundColor Yellow
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-DockerDaemon) {
        $elapsed = [int]($TimeoutSeconds - ($deadline - (Get-Date)).TotalSeconds)
        Write-Host "[ensure_docker] Engine pronto em ~${elapsed}s." -ForegroundColor Green
        exit 0
    }
}

Write-Error "[ensure_docker] Timeout ($TimeoutSeconds s) aguardando engine do Docker Desktop."
exit 1
