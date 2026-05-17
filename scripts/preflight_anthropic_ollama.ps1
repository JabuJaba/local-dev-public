# Preflight - Sprint 1.5 Phase 1
# Verifica se Ollama responde ao endpoint Anthropic-compat (/v1/messages) com payload de tool use.
# Roda um modelo de cada vez (VRAM contention). Gera scripts/preflight_report.md.

param(
    [string[]]$Models = @("qwen3coder-local", "gemma4:26b"),
    [string]$BaseUrl = "http://localhost:11434",
    [string]$ReportPath = (Join-Path $PSScriptRoot "preflight_report.md")
)

$ErrorActionPreference = "Stop"
$env:ANTHROPIC_BASE_URL   = $BaseUrl
$env:ANTHROPIC_AUTH_TOKEN = "dummy"

function Invoke-Preflight {
    param([string]$Model)

    $env:ANTHROPIC_CUSTOM_MODEL_OPTION = $Model

    $result = [ordered]@{
        model         = $Model
        tags_listed   = $false
        http_status   = $null
        has_content   = $false
        has_stop      = $false
        first_resp_ms = $null
        error         = $null
        raw_snippet   = $null
    }

    try {
        $tags = Invoke-RestMethod -Uri "$BaseUrl/api/tags" -Method Get -TimeoutSec 10
        $names = $tags.models | ForEach-Object { $_.name }
        $result.tags_listed = ($names -contains $Model) -or ($names -contains "$Model`:latest")
    } catch {
        $result.error = "tags_fail: $($_.Exception.Message)"
        return $result
    }

    $body = @{
        model      = $Model
        max_tokens = 256
        tools      = @(
            @{
                name         = "get_weather"
                description  = "Return the weather for a city"
                input_schema = @{
                    type       = "object"
                    properties = @{ city = @{ type = "string" } }
                    required   = @("city")
                }
            }
        )
        messages   = @(
            @{ role = "user"; content = "What is the weather in Paris? Use the tool." }
        )
    } | ConvertTo-Json -Depth 10

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-WebRequest -Uri "$BaseUrl/v1/messages" `
            -Method Post `
            -Headers @{ "Content-Type" = "application/json"; "x-api-key" = "dummy"; "anthropic-version" = "2023-06-01" } `
            -Body $body `
            -TimeoutSec 120 `
            -UseBasicParsing
        $sw.Stop()
        $result.http_status   = $resp.StatusCode
        $result.first_resp_ms = [int]$sw.ElapsedMilliseconds

        $json = $resp.Content | ConvertFrom-Json
        $result.has_content = $null -ne $json.content
        $result.has_stop    = $null -ne $json.stop_reason
        $result.raw_snippet = ($resp.Content.Substring(0, [Math]::Min(500, $resp.Content.Length)))
    } catch {
        $sw.Stop()
        $result.error = "messages_fail: $($_.Exception.Message)"
        try {
            if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
                $em = $_.ErrorDetails.Message
                $result.raw_snippet = $em.Substring(0, [Math]::Min(500, $em.Length))
            }
        } catch {}
    }

    return $result
}

$results = @()
foreach ($m in $Models) {
    Write-Output "=== Preflight: $m ==="
    $results += Invoke-Preflight -Model $m
    try { & ollama stop $m 2>$null } catch {}
}

$lines = @()
$lines += "# Preflight Anthropic-compat Ollama - Sprint 1.5 Phase 1"
$lines += ""
$lines += "Executado: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
$lines += "BaseUrl: $BaseUrl"
$lines += ""
$lines += "| Modelo | Tags OK | HTTP | content | stop_reason | 1a resp (ms) | Erro |"
$lines += "|--------|---------|------|---------|-------------|--------------|------|"
foreach ($r in $results) {
    $lines += "| $($r.model) | $($r.tags_listed) | $($r.http_status) | $($r.has_content) | $($r.has_stop) | $($r.first_resp_ms) | $($r.error) |"
}
$lines += ""
$lines += "## Raw snippets (primeiros 500 chars)"
foreach ($r in $results) {
    $lines += ""
    $lines += "### $($r.model)"
    $lines += ""
    $lines += '``````json'
    if ($r.raw_snippet) { $lines += $r.raw_snippet } else { $lines += "(sem corpo)" }
    $lines += '``````'
}

Set-Content -Path $ReportPath -Value ($lines -join "`r`n") -Encoding UTF8
Write-Output "Relatorio: $ReportPath"

$allGood = $true
foreach ($r in $results) {
    if ($r.http_status -ne 200 -or -not $r.has_content -or -not $r.has_stop) { $allGood = $false }
}
if (-not $allGood) { exit 1 }
