param([switch]$Restart)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$logFolder = 'D:\CampusIQ-data\logs'
[void](New-Item -ItemType Directory -Force -Path $logFolder)
$pythonCommand = if (Test-Path "$project\.venv\Scripts\python.exe") { "$project\.venv\Scripts\python.exe" } else { (Get-Command python.exe).Source }
if (Test-Path "$project\ai-service\.deps") { $env:PYTHONPATH = "$project\ai-service\.deps" }
if ($Restart) {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('node.exe', 'python.exe') -and $_.CommandLine -and $_.CommandLine.Contains($project) -and
        $_.CommandLine -match 'server\.js|worker\.py|uvicorn|vite[\\/]bin[\\/]vite\.js'
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
}
function Listening([int]$port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}
function Start-ServiceProcess([string]$name, [string]$exe, [string[]]$arguments, [string]$folder) {
    $options = @{ FilePath = $exe; WorkingDirectory = $folder; WindowStyle = 'Hidden';
        RedirectStandardOutput = "$logFolder/$name.log"; RedirectStandardError = "$logFolder/$name.err" }
    if ($arguments.Count) { $options.ArgumentList = $arguments }
    Start-Process @options | Out-Null
}
if (!(Listening 27018)) {
    $mongoFolder = 'D:\CampusIQ-data\mongo-native'
    [void](New-Item -ItemType Directory -Force -Path $mongoFolder)
    Start-ServiceProcess 'mongo' (Get-Command mongod.exe).Source @('--dbpath', $mongoFolder, '--port', '27018', '--bind_ip', '127.0.0.1', '--wiredTigerCacheSizeGB', '0.25', '--logpath', "$mongoFolder/mongo.log", '--logappend') $mongoFolder
}
if (!(Listening 6333)) {
    $qdrantFolder = 'D:\CampusIQ-data\qdrant'
    if (!(Test-Path "$qdrantFolder/qdrant.exe")) { throw "Install Qdrant in $qdrantFolder first." }
    $env:QDRANT__SERVICE__HOST = '127.0.0.1'
    $env:QDRANT__SERVICE__HTTP_PORT = '6333'
    Start-ServiceProcess 'qdrant' "$qdrantFolder/qdrant.exe" @() $qdrantFolder
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if ((Listening 27018) -and (Listening 6333)) { break }
    Start-Sleep -Milliseconds 300
}
if (!(Listening 27018) -or !(Listening 6333)) { throw "Database startup failed. Check $logFolder." }
if (!(Listening 4000)) {
    Start-ServiceProcess 'express' (Get-Command node.exe).Source @("--env-file=$project/backend/.env", "$project/backend/src/server.js") "$project/backend"
}
if (!(Listening 8000)) {
    Start-ServiceProcess 'fastapi' $pythonCommand @('-m', 'uvicorn', '--app-dir', "$project/ai-service", 'main:app', '--host', '127.0.0.1', '--port', '8000') "$project/ai-service"
}
$existingWorker = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -and $_.CommandLine.Contains($project) -and $_.CommandLine -match 'worker\.py'
}
if (!$existingWorker) { Start-ServiceProcess 'worker' $pythonCommand @("$project/ai-service/worker.py") "$project/ai-service" }
if (!(Listening 5173)) {
    Start-ServiceProcess 'frontend' (Get-Command node.exe).Source @("$project/frontend/node_modules/vite/bin/vite.js", '--host', 'localhost', '--port', '5173', '--strictPort') "$project/frontend"
}
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $ready = Invoke-RestMethod 'http://127.0.0.1:4000/health' -TimeoutSec 2
        if ($ready.status -eq 'ok' -and (Listening 8000) -and (Listening 5173)) { break }
    } catch {}
    Start-Sleep -Milliseconds 300
}
if (!(Listening 4000) -or !(Listening 8000) -or !(Listening 5173)) { throw "Service startup failed. Check $logFolder." }
Write-Host 'Open http://localhost:5173'
Write-Host "Service logs are in $logFolder"
