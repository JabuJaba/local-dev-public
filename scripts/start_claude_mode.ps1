# Sprint 2 Phase 1 - Restaurar rota Claude Code padrao (Anthropic cloud)
# Limpa ANTHROPIC_BASE_URL / AUTH_TOKEN / CUSTOM_MODEL_OPTION e restaura backup se houver.

param(
    [switch]$NoLaunch,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ClaudeArgs
)

$ErrorActionPreference = "Stop"

if ($env:CLAUDE_LOCAL_MODE_BACKUP) {
    try {
        $backup = $env:CLAUDE_LOCAL_MODE_BACKUP | ConvertFrom-Json
        $env:ANTHROPIC_BASE_URL            = $backup.ANTHROPIC_BASE_URL
        $env:ANTHROPIC_AUTH_TOKEN          = $backup.ANTHROPIC_AUTH_TOKEN
        $env:ANTHROPIC_CUSTOM_MODEL_OPTION = $backup.ANTHROPIC_CUSTOM_MODEL_OPTION
        Write-Host "[claude-mode] backup restaurado" -ForegroundColor Cyan
    } catch {
        Write-Warning "[claude-mode] falha ao parsear backup: $($_.Exception.Message)"
    }
    Remove-Item Env:CLAUDE_LOCAL_MODE_BACKUP     -ErrorAction SilentlyContinue
    Remove-Item Env:CLAUDE_SAFETY_INTERCEPTOR    -ErrorAction SilentlyContinue
} else {
    # sem backup: assumir que estavamos em modo cloud default -> limpar
    Remove-Item Env:ANTHROPIC_BASE_URL            -ErrorAction SilentlyContinue
    Remove-Item Env:ANTHROPIC_AUTH_TOKEN          -ErrorAction SilentlyContinue
    Remove-Item Env:ANTHROPIC_CUSTOM_MODEL_OPTION -ErrorAction SilentlyContinue
    Remove-Item Env:CLAUDE_SAFETY_INTERCEPTOR     -ErrorAction SilentlyContinue
    Write-Host "[claude-mode] vars ANTHROPIC_* limpas" -ForegroundColor Cyan
}

Write-Host "[claude-mode] ANTHROPIC_BASE_URL=$env:ANTHROPIC_BASE_URL" -ForegroundColor Cyan
Write-Host "[claude-mode] ANTHROPIC_CUSTOM_MODEL_OPTION=$env:ANTHROPIC_CUSTOM_MODEL_OPTION" -ForegroundColor Cyan

if ($NoLaunch) { return }

Write-Host "[claude-mode] launching: claude $($ClaudeArgs -join ' ')" -ForegroundColor Green
& claude @ClaudeArgs
