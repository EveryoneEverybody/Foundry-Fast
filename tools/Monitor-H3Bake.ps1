[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$RunDirectory, [int]$IntervalSeconds = 30, [switch]$Once)
$ErrorActionPreference = 'Stop'
if ($IntervalSeconds -lt 1) { throw 'IntervalSeconds must be positive' }
do {
    $state = Get-Content -LiteralPath (Join-Path $RunDirectory 'status.json') -Raw | ConvertFrom-Json
    $state | Select-Object status,current_stage,elapsed_seconds,stage_elapsed_seconds,active_client_count,workers,pids,aggregate_cpu_seconds,aggregate_working_set_bytes,latest_progress,updated | Format-List
    Write-Host "Logs: $(Join-Path $RunDirectory 'logs')"
    if ($Once -or $state.status -in @('PASS','FAIL')) { break }
    Start-Sleep -Seconds $IntervalSeconds
} while ($true)
