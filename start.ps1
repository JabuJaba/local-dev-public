param(
    [switch]$Status,
    [switch]$OnlyOllama,
    [switch]$OnlyLlama
)

$SERVER = "llama_cpp\llama-server.exe"
$MODEL  = "models\Qwen3-Coder-Next-Q3_K_M.gguf"

function Get-Status {
    $ol = try { (Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 2).models.Count } catch { $null }
    $ll = try { (Invoke-RestMethod "http://localhost:8081/health" -TimeoutSec 2).status } catch { $null }
    Write-Host "Ollama   :11434 -- $(if ($ol -ne $null) {"OK $ol modelos"} else {'OFFLINE'})"
    Write-Host "llama.cpp :8081 -- $(if ($ll) {"OK $ll"} else {'OFFLINE'})"
}

if ($Status) { Get-Status; exit 0 }

if (-not $OnlyLlama) {
    $ol = try { Invoke-RestMethod "http://localhost:11434/api/tags" -TimeoutSec 1 } catch { $null }
    if (-not $ol) {
        Write-Host "Iniciando Ollama..." -ForegroundColor Cyan
        Start-Process "ollama" "serve" -WindowStyle Hidden
        Start-Sleep 3
    } else { Write-Host "Ollama: ja rodando" -ForegroundColor Green }
}

if (-not $OnlyOllama) {
    if (-not (Test-Path $MODEL)) {
        Write-Host "AVISO: Modelo nao encontrado em $MODEL" -ForegroundColor Yellow
        Write-Host "Download ainda em andamento? Verificar: models\" -ForegroundColor Yellow
        exit 1
    }
    $ll = try { Invoke-RestMethod "http://localhost:8081/health" -TimeoutSec 1 } catch { $null }
    if (-not $ll) {
        Write-Host "Iniciando Qwen3-Coder-Next (llama.cpp)..." -ForegroundColor Cyan
        Start-Process $SERVER -ArgumentList @(
            "-m", $MODEL,
            "--host", "127.0.0.1", "--port", "8081",
            "-ngl", "99", "-ot", ".ffn_.*_exps.=CPU",
            "-c", "32768", "-t", "16",
            "--temp", "0.7", "--top-p", "0.8", "--top-k", "20",
            "--repeat-penalty", "1.05",
            "--jinja", "--api-key", "local-only",
            "--flash-attn", "on",
            "--cache-prompt"
        ) -WindowStyle Hidden
        Write-Host "Aguardando inicializacao (~20s)..."
        Start-Sleep 20
    } else { Write-Host "llama.cpp: ja rodando" -ForegroundColor Green }
}

Write-Host ""
Get-Status
