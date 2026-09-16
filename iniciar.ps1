$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$backendPython = Join-Path $root ".venv\Scripts\python.exe"
$frontendDir = Join-Path $root "frontend_app"
$backendHealthUrl = "http://127.0.0.1:8000/health"
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
    Write-Host "ERRO: venv do backend nao encontrado em .venv" -ForegroundColor Red
    Write-Host "Rode primeiro (Python 3.11+):"
    Write-Host "  py -m venv .venv"
    Write-Host "  .venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "ERRO: dependencias do frontend nao instaladas (frontend_app\node_modules ausente)" -ForegroundColor Red
    Write-Host "Rode primeiro:"
    Write-Host "  npm --prefix frontend_app install"
    exit 1
}

# --- docker (postgres + redis) ------------------------------------------
Write-Host "[docker] verificando o daemon..." -ForegroundColor Cyan
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERRO: o Docker Desktop nao esta rodando (ou ainda esta iniciando)." -ForegroundColor Red
    Write-Host "Abra o Docker Desktop manualmente, espere ele ficar pronto (icone parar de animar)" -ForegroundColor Red
    Write-Host "e rode este script de novo." -ForegroundColor Red
    exit 1
}

$dbUp = (docker ps --filter "name=marketton-db" --filter "health=healthy" --format "{{.Names}}") -contains "marketton-db"
$redisUp = (docker ps --filter "name=marketton-redis" --filter "health=healthy" --format "{{.Names}}") -contains "marketton-redis"
if ($dbUp -and $redisUp) {
    Write-Host "[docker] marketton-db e marketton-redis ja estao saudaveis" -ForegroundColor Yellow
} else {
    Write-Host "[docker] subindo postgres + redis (docker compose up -d db redis)..." -ForegroundColor Cyan
    Push-Location $root
    docker compose up -d db redis
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERRO: falha ao subir os containers. Veja a saida do docker compose acima." -ForegroundColor Red
        exit 1
    }
    Write-Host "[docker] aguardando containers ficarem saudaveis..." -ForegroundColor Cyan
    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        $dbUp = (docker ps --filter "name=marketton-db" --filter "health=healthy" --format "{{.Names}}") -contains "marketton-db"
        $redisUp = (docker ps --filter "name=marketton-redis" --filter "health=healthy" --format "{{.Names}}") -contains "marketton-redis"
        if ($dbUp -and $redisUp) { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) {
        Write-Host "ERRO: containers nao ficaram saudaveis a tempo. Rode 'docker compose logs db redis'." -ForegroundColor Red
        exit 1
    }
    Write-Host "[docker] OK" -ForegroundColor Green
}

# --- migrations -----------------------------------------------------------
Write-Host "[banco] aplicando migrations (alembic upgrade head)..." -ForegroundColor Cyan
Push-Location $root
& $backendPython -m alembic upgrade head
$migrationExit = $LASTEXITCODE
Pop-Location
if ($migrationExit -ne 0) {
    Write-Host "ERRO: alembic upgrade head falhou. Veja a saida acima." -ForegroundColor Red
    exit 1
}
Write-Host "[banco] OK" -ForegroundColor Green

# --- backend -------------------------------------------------------------
if (Test-Url -Url $backendHealthUrl) {
    Write-Host "[backend] ja estava rodando em http://127.0.0.1:8000" -ForegroundColor Yellow
} else {
    Write-Host "[backend] subindo FastAPI na porta 8000..." -ForegroundColor Cyan
    Start-Process -FilePath $backendPython -ArgumentList @("-m", "uvicorn", "backend.main:app", "--port", "8000") -WorkingDirectory $root | Out-Null

    if (-not (Wait-ForUrl -Url $backendHealthUrl -MaxSeconds 30)) {
        Write-Host ""
        Write-Host "ERRO: backend nao respondeu em http://127.0.0.1:8000 depois de 30s." -ForegroundColor Red
        Write-Host "Confira a janela do backend que abriu para ver o erro." -ForegroundColor Red
        Write-Host "Frontend NAO foi iniciado." -ForegroundColor Red
        exit 1
    }
    Write-Host "[backend] OK - http://127.0.0.1:8000" -ForegroundColor Green
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
Write-Host "  API:       http://127.0.0.1:8000"
Write-Host "  Docs:      http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host "Backend e frontend rodam em janelas separadas (abertas agora)." -ForegroundColor DarkGray
Write-Host "Para parar: feche essas janelas ou de Ctrl+C em cada uma." -ForegroundColor DarkGray
Write-Host "Postgres/Redis continuam rodando em background (docker compose stop db redis para parar)." -ForegroundColor DarkGray
