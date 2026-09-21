# Agenda a coleta diaria de produtos (Mercado Livre) no Agendador de Tarefas do Windows.
#   .\agendar_coleta.ps1                 -> agenda para 06:00 todo dia
#   .\agendar_coleta.ps1 -Hora 22:30     -> outro horario
#   .\agendar_coleta.ps1 -Remover        -> remove o agendamento
# Precisa do Docker (Postgres) de pe na hora da coleta; o log fica em logs\coleta.log.
param([string]$Hora = "06:00", [switch]$Remover)

$nome = "marketTon-coleta-diaria"
$root = $PSScriptRoot

if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Agendamento '$nome' removido." -ForegroundColor Yellow
    exit 0
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "ERRO: venv nao encontrado em .venv (rode o iniciar.ps1 primeiro)." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force (Join-Path $root "logs") | Out-Null
$cmd = "cd /d `"$root`" && `"$python`" scripts\ingest.py --marketplace mercado_livre --limit 60 --no-ai >> logs\coleta.log 2>&1"
$acao = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $cmd"
$gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config -Force | Out-Null
Write-Host "Coleta agendada: todo dia as $Hora (tarefa '$nome')." -ForegroundColor Green
Write-Host "Se o PC estiver desligado no horario, roda assim que ligar. Log: logs\coleta.log"
