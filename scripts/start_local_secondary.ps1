# Sprint 2 Phase 1 - Rota Claude Code local (secundario: gemma4:26b)
# Descarrega o primario antes via 'ollama stop' para evitar VRAM contention.

param(
    [string]$BaseUrl  = "http://localhost:11434",
    [string]$Model    = "gemma4:26b",
    [string]$Primary  = "qwen3.6:35b-a3b-q4_k_m",
    [string[]]$AllowedTools = @("Read","Edit","Write","Bash","Glob","Grep"),
    [switch]$NoLaunch,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ClaudeArgs
)

$ErrorActionPreference = "Stop"

try {
    Write-Host "[local-secondary] stopping primary '$Primary' to free VRAM..." -ForegroundColor Yellow
    & ollama stop $Primary 2>$null | Out-Null
} catch {
    Write-Warning "[local-secondary] ollama stop falhou (ok se nao estava carregado): $($_.Exception.Message)"
}

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

Write-Host "[local-secondary] model=$Model" -ForegroundColor Cyan
Write-Host "[local-secondary] allowedTools=$($AllowedTools -join ',')" -ForegroundColor Cyan

if ($NoLaunch) {
    Write-Host "[local-secondary] -NoLaunch setado; variaveis exportadas." -ForegroundColor Yellow
    return
}

$toolsArg = "--allowedTools=" + ($AllowedTools -join ",")
$argList  = @("--bare", $toolsArg) + $ClaudeArgs
Write-Host "[local-secondary] launching: claude $($argList -join ' ')" -ForegroundColor Green
& claude @argList
