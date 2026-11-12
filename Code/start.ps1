# Start the E-Bidding backend and frontend on Windows.

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$backendDir = Join-Path $scriptDir "backend"
$frontendDir = Join-Path $scriptDir "frontend"
$venvDir = Join-Path $scriptDir ".venv-windows"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$backendLogDir = Join-Path $scriptDir "runtime-logs"
$frontendLogDir = Join-Path $scriptDir "runtime-logs"
$backendOut = Join-Path $backendLogDir "backend.log"
$backendErr = Join-Path $backendLogDir "backend-error.log"
$frontendOut = Join-Path $frontendLogDir "frontend.log"
$frontendErr = Join-Path $frontendLogDir "frontend-error.log"
$backendProcess = $null
$frontendProcess = $null
$backendListenerProcessId = $null
$frontendListenerProcessId = $null

function Test-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][int]$Port
    )

    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($listener) {
            try {
                $response = Invoke-WebRequest -Uri $Url -TimeoutSec 2 -UseBasicParsing
                if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                    return [int]$listener.OwningProcess
                }
            }
            catch {
                Start-Sleep -Seconds 1
            }
        }
        elseif ($Process.HasExited) {
            throw "$ServiceName exited before port $Port became ready. Check $LogPath."
        }
        else { Start-Sleep -Seconds 1 }
    }

    throw "$ServiceName did not respond on port $Port at $Url within 60 seconds. Check $LogPath."
}

function Test-ServiceReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][int]$ListenerProcessId,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][string]$LogPath
    )

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -eq $ListenerProcessId } |
        Select-Object -First 1
    if (-not $listener) {
        throw "$ServiceName stopped listening on port $Port. Check $LogPath."
    }

    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 500) {
            throw "$ServiceName returned HTTP $($response.StatusCode) at $Url."
        }
    }
    catch {
        throw "$ServiceName is not healthy at $Url. Check $LogPath. $($_.Exception.Message)"
    }
}

try {
    $python = Get-Command python -ErrorAction SilentlyContinue
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue

    if (-not $python) { throw "Python was not found on PATH." }
    if (-not $node) { throw "Node.js was not found on PATH." }
    if (-not $npm) { throw "npm.cmd was not found on PATH." }
    if (-not (Test-Path (Join-Path $backendDir "requirements.txt"))) {
        throw "Backend requirements.txt was not found."
    }
    if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
        throw "Frontend package.json was not found."
    }

    New-Item -ItemType Directory -Force -Path $backendLogDir | Out-Null

    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating Windows Python environment..."
        & $python.Source -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Windows Python environment." }
    }

    & $venvPython -c "import dotenv, fastapi, sqlalchemy, uvicorn"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing backend requirements..."
        & $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "Backend dependency installation failed." }
    }

    $vitePath = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
    Push-Location $frontendDir
    try {
        if (-not (Test-Path $vitePath)) {
            Write-Host "Installing frontend dependencies..."
            & $npm.Source install --include=optional --no-save --package-lock=false
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        }

        & $node.Source -e "require('rollup'); require('@rollup/rollup-win32-x64-msvc'); require('esbuild').transformSync('let x = 1'); require('@swc/core')"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Repairing platform-specific frontend dependencies..."
            & $npm.Source install --include=optional --no-save --package-lock=false
            if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
        }

        & $node.Source -e "require('rollup'); require('@rollup/rollup-win32-x64-msvc'); require('esbuild').transformSync('let x = 1'); require('@swc/core')"
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend dependencies are still incomplete after repair."
        }
    }
    finally {
        Pop-Location
    }

    $portsInUse = @(8000, 8080) | ForEach-Object {
        Get-NetTCPConnection -State Listen -LocalPort $_ -ErrorAction SilentlyContinue
    }
    if ($portsInUse) {
        $portList = ($portsInUse | Select-Object -ExpandProperty LocalPort -Unique) -join ", "
        throw "Required port(s) $portList are already in use. Stop the owning service before starting E-Bidding."
    }

    Write-Host "Starting backend..."
    $backendProcess = Start-Process `
        -FilePath $venvPython `
        -ArgumentList @("-m", "uvicorn", "backend_server:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $backendDir `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr `
        -PassThru
    $backendListenerProcessId = Test-HttpReady `
        -Url "http://127.0.0.1:8000/openapi.json" `
        -Process $backendProcess -ServiceName "Backend" -LogPath $backendErr -Port 8000

    Write-Host "Starting frontend..."
    $frontendProcess = Start-Process `
        -FilePath $node.Source `
        -ArgumentList @("`"$vitePath`"", "--host", "127.0.0.1", "--strictPort") `
        -WorkingDirectory $frontendDir `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr `
        -PassThru
    $frontendListenerProcessId = Test-HttpReady `
        -Url "http://127.0.0.1:8080/" `
        -Process $frontendProcess -ServiceName "Frontend" -LogPath $frontendErr -Port 8080

    $masterDataAvailable = $true
    $masterDataSource = "database"
    try {
        $masterDataResponse = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8000/api/zones" `
            -TimeoutSec 5 `
            -UseBasicParsing
        $masterData = $masterDataResponse.Content | ConvertFrom-Json
        $masterDataSource = [string]$masterData.source
        $masterDataAvailable = $masterDataResponse.StatusCode -eq 200 -and
            $masterDataSource -eq "database"
    }
    catch {
        $masterDataAvailable = $false
    }

    Write-Host ""
    if ($masterDataAvailable) {
        Write-Host "E-Bidding services are ready:" -ForegroundColor Green
    }
    elseif ($masterDataSource -eq "snapshot") {
        Write-Warning "Services started with backup master data dated $($masterData.snapshot_date). Live bids remain disabled until MySQL reconnects and the data is verified."
    }
    else {
        Write-Warning "Services started, but master data is unavailable. Check the configured MySQL service before bidding."
    }
    Write-Host "  Frontend:  http://127.0.0.1:8080"
    Write-Host "  Backend:   http://127.0.0.1:8000"
    Write-Host "  API docs:  http://127.0.0.1:8000/docs"
    Write-Host "  Logs:      $backendLogDir"
    Write-Host "Press Ctrl+C to stop both services."

    while ($true) {
        Start-Sleep -Seconds 1
        Test-ServiceReady `
            -Url "http://127.0.0.1:8000/openapi.json" `
            -Port 8000 -ListenerProcessId $backendListenerProcessId `
            -ServiceName "Backend" -LogPath $backendErr
        Test-ServiceReady `
            -Url "http://127.0.0.1:8080/" `
            -Port 8080 -ListenerProcessId $frontendListenerProcessId `
            -ServiceName "Frontend" -LogPath $frontendErr
    }
}
catch {
    Write-Error $_
    exit 1
}
finally {
    foreach ($listenerProcessId in @($frontendListenerProcessId, $backendListenerProcessId)) {
        if ($listenerProcessId) {
            $listener = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -eq $listenerProcessId }
            if ($listener) {
                Stop-Process -Id $listenerProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    }

    foreach ($process in @($frontendProcess, $backendProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
