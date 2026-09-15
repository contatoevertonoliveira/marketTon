$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$backendPython = Join-Path $root "server\.venv\Scripts\python.exe"
$managePy = Join-Path $root "server\manage.py"
$frontendDir = Join-Path $root "frontend_app"
$backendHealthUrl = "http://127.0.0.1:8001/api/marketplaces/"
$frontendUrl = "http://localhost:5173"

function Test-Url {
    param([string]$Url, [int]$TimeoutSec = 2)
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec | Out-Null
        return $true
    } catch {
        # A non-2xx HTTP response still means something is listening and
        # answering - only "no response at all" counts as down.
        if ($_.Exception.Response) { return $true }
        return $false
    }
}

function Wait-ForUrl {
    param([string]$Url, [int]$MaxSeconds = 30)
    for ($i = 0; $i -lt $MaxSeconds; $i++) {
        if (Test-Url -Url $Url) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

Write-Host "== Affiliate Intelligence System - subindo servicos ==" -ForegroundColor Cyan
Write-Host ""

# --- pre-flight checks -------------------------------------------------
if (-not (Test-Path $backendPython)) {
    Write-Host "ERRO: venv do backend nao encontrado em server\.venv" -ForegroundColor Red
    Write-Host "Rode primeiro:"
    Write-Host "  py -m venv server\.venv"
    Write-Host "  server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "ERRO: dependencias do frontend nao instaladas (frontend_app\node_modules ausente)" -ForegroundColor Red
    Write-Host "Rode primeiro:"
    Write-Host "  npm --prefix frontend_app install"
    exit 1
}

# --- backend -------------------------------------------------------------
if (Test-Url -Url $backendHealthUrl) {
    Write-Host "[backend] ja estava rodando em http://127.0.0.1:8001" -ForegroundColor Yellow
} else {
    Write-Host "[backend] subindo Django na porta 8001..." -ForegroundColor Cyan
    Start-Process -FilePath $backendPython -ArgumentList @($managePy, "runserver", "8001") -WorkingDirectory $root | Out-Null

    if (-not (Wait-ForUrl -Url $backendHealthUrl -MaxSeconds 30)) {
        Write-Host ""
        Write-Host "ERRO: backend nao respondeu em http://127.0.0.1:8001 depois de 30s." -ForegroundColor Red
        Write-Host "Confira a janela do backend que abriu para ver o erro." -ForegroundColor Red
        Write-Host "Frontend NAO foi iniciado." -ForegroundColor Red
        exit 1
    }
    Write-Host "[backend] OK - http://127.0.0.1:8001" -ForegroundColor Green
}

# --- frontend --------------------------------------------------------------
if (Test-Url -Url $frontendUrl) {
    Write-Host "[frontend] ja estava rodando em $frontendUrl" -ForegroundColor Yellow
} else {
    Write-Host "[frontend] subindo Vite na porta 5173..." -ForegroundColor Cyan
    Start-Process -FilePath "npm.cmd" -ArgumentList @("run", "dev") -WorkingDirectory $frontendDir | Out-Null

    if (-not (Wait-ForUrl -Url $frontendUrl -MaxSeconds 30)) {
        Write-Host ""
        Write-Host "ERRO: frontend nao respondeu em $frontendUrl depois de 30s." -ForegroundColor Red
        Write-Host "Confira a janela do frontend que abriu para ver o erro." -ForegroundColor Red
        exit 1
    }
    Write-Host "[frontend] OK - $frontendUrl" -ForegroundColor Green
}

Write-Host ""
Write-Host "Tudo no ar:" -ForegroundColor Cyan
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  API:       http://127.0.0.1:8001/api/"
Write-Host "  Admin:     http://127.0.0.1:8001/admin/"
Write-Host ""
Write-Host "Backend e frontend rodam em janelas separadas (abertas agora)." -ForegroundColor DarkGray
Write-Host "Para parar: feche essas janelas ou de Ctrl+C em cada uma." -ForegroundColor DarkGray
