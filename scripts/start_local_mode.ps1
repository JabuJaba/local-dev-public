# Sprint 2 Phase 1 - Rota Claude Code local (primario)
# Seta ANTHROPIC_* para Ollama e invoca Claude Code com tool surface reduzida.
# Modelo primario Sprint 1.5: qwen3.6:35b-a3b-q4_k_m (6/10 tool match).

param(
    [string]$BaseUrl = "http://localhost:11434",
    [string]$Model   = "qwen3.6:35b-a3b-q4_k_m",
    [string[]]$AllowedTools = @("Read","Edit","Write","Bash","Glob","Grep"),
    [switch]$NoLaunch,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ClaudeArgs
)

$ErrorActionPreference = "Stop"

# Preservar vars originais para start_claude_mode restaurar
if (-not $env:CLAUDE_LOCAL_MODE_BACKUP) {
    $backup = [ordered]@{
        ANTHROPIC_BASE_URL            = $env:ANTHROPIC_BASE_URL
        ANTHROPIC_AUTH_TOKEN          = $env:ANTHROPIC_AUTH_TOKEN
        ANTHROPIC_CUSTOM_MODEL_OPTION = $env:ANTHROPIC_CUSTOM_MODEL_OPTION
    }
    $env:CLAUDE_LOCAL_MODE_BACKUP = ($backup | ConvertTo-Json -Compress)
}

$env:ANTHROPIC_BASE_URL            = $BaseUrl
$env:ANTHROPIC_AUTH_TOKEN          = "dummy"
$env:ANTHROPIC_CUSTOM_MODEL_OPTION = $Model
$env:CLAUDE_SAFETY_INTERCEPTOR     = "1"

Write-Host "[local-mode] ANTHROPIC_BASE_URL=$env:ANTHROPIC_BASE_URL" -ForegroundColor Cyan
Write-Host "[local-mode] model=$Model" -ForegroundColor Cyan
Write-Host "[local-mode] allowedTools=$($AllowedTools -join ',')" -ForegroundColor Cyan

# Verificar que Ollama tem o modelo carregavel
try {
    $tags = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -Method Get -TimeoutSec 5
    $names = $tags.models | ForEach-Object { $_.name }
    if (-not (($names -contains $Model) -or ($names -contains "$Model`:latest"))) {
        Write-Warning "[local-mode] modelo '$Model' nao encontrado em /api/tags. Prosseguindo mesmo assim."
    }
} catch {
    Write-Warning "[local-mode] Ollama nao respondeu em $BaseUrl/api/tags: $($_.Exception.Message)"
}

if ($NoLaunch) {
    Write-Host "[local-mode] -NoLaunch setado; variaveis exportadas, nao iniciando Claude." -ForegroundColor Yellow
    return
}

$toolsArg = "--allowedTools=" + ($AllowedTools -join ",")
$argList  = @("--bare", $toolsArg) + $ClaudeArgs
Write-Host "[local-mode] launching: claude $($argList -join ' ')" -ForegroundColor Green
& claude @argList
