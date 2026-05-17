# Inicia um container workspace isolado com o ProjectPath montado em /workspace.
# Uso:
#   .\docker\run_workspace.ps1 -ProjectPath "<workspace>/Subtitle-Forge_sandbox"
#   .\docker\run_workspace.ps1 -ProjectPath "<workspace>/Subtitle-Forge_sandbox" -Detached -Name sf-sbx
#
# Flags:
#   -Detached   Roda em background (docker run -d). Sem -Detached abre shell interativa.
#   -Name       Nome do container (default: workspace-<timestamp>).
#   -Rebuild    Forca docker build da imagem antes de rodar.

param(
    [Parameter(Mandatory=$true)][string]$ProjectPath,
    [switch]$Detached,
    [string]$Name = "workspace-$(Get-Date -Format 'yyyyMMdd-HHmmss')",
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# 1. Garantir daemon
& "$scriptDir\ensure_docker.ps1"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# 2. Validar ProjectPath
if (-not (Test-Path $ProjectPath)) {
    Write-Error "ProjectPath nao existe: $ProjectPath"
    exit 2
}
$ProjectPath = (Resolve-Path $ProjectPath).Path

# 3. Build (se necessario)
$imageExists = docker image inspect local-dev-workspace 2>$null
if ($Rebuild -or -not $imageExists) {
    Write-Host "[run_workspace] Building local-dev-workspace..." -ForegroundColor Yellow
    docker build -t local-dev-workspace -f "$scriptDir\Dockerfile.workspace" $scriptDir
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# 4. Run
$mountArg = "${ProjectPath}:/workspace"
Write-Host "[run_workspace] Mount: $mountArg  | Container: $Name" -ForegroundColor Cyan

$authToken = if ($env:ANTHROPIC_AUTH_TOKEN) { $env:ANTHROPIC_AUTH_TOKEN } else { "ollama" }

if ($Detached) {
    docker run -d --name $Name -v $mountArg -e "ANTHROPIC_AUTH_TOKEN=$authToken" local-dev-workspace tail -f /dev/null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[run_workspace] Container detached. Exec com: docker exec -it $Name bash" -ForegroundColor Green
    }
} else {
    docker run -it --rm --name $Name -v $mountArg -e "ANTHROPIC_AUTH_TOKEN=$authToken" local-dev-workspace
}
