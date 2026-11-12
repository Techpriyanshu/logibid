$ErrorActionPreference = "Stop"

$scriptDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$backendPython = Join-Path $scriptDir ".venv-windows\Scripts\python.exe"
$viteScript = Join-Path $scriptDir "frontend\node_modules\vite\bin\vite.js"
$processes = @(Get-CimInstance Win32_Process)
$serverProcesses = @(
    $processes | Where-Object {
        $_.ExecutablePath -eq $backendPython -and
        $_.CommandLine -match "uvicorn\s+backend_server:app"
    }
    $processes | Where-Object {
        $_.CommandLine -and
        $_.CommandLine.IndexOf($viteScript, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    }
)

if ($serverProcesses.Count -eq 0) {
    Write-Host "No E-Bidding server processes are running."
    exit 0
}

foreach ($process in $serverProcesses) {
    Stop-Process -Id $process.ProcessId -Force
}

Write-Host "Stopped E-Bidding server processes: $($serverProcesses.ProcessId -join ', ')"
