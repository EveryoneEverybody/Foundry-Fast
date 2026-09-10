[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('Sky','Bake')][string]$Action,
    [Parameter(Mandatory)][string]$Config,
    [string]$Blender = 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe'
)
$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$settings = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
$runPath = [IO.Path]::GetFullPath($settings.run)
if (Test-Path -LiteralPath $runPath) { throw 'Use a new run directory in the config; previous results are preserved.' }
$logPath = $runPath + '.launcher.log'
if (Test-Path -LiteralPath $logPath) { throw 'This launch log already exists; choose a new run directory.' }
$module = if ($Action -eq 'Sky') { 'runtime_sky.py' } else { 'runtime_bake.py' }
$script = Join-Path $settings.addon ('h3_import\port_environment\' + $module)
$blenderPath = (Resolve-Path -LiteralPath $Blender).Path
$scriptPath = (Resolve-Path -LiteralPath $script).Path
Write-Host "Running $Action against the hash-pinned parent manifest. Log: $logPath"
& $blenderPath --background --factory-startup --python-exit-code 1 --python $scriptPath -- $configPath *> $logPath
$result = $LASTEXITCODE
Get-Content -LiteralPath $logPath -Tail 25
if ($result -ne 0) { throw "Stabilization failed (exit $result). Review $logPath before retrying." }
$reportName = if ($Action -eq 'Sky') { 'runtime-sky-report.json' } else { 'runtime-bake-report.json' }
$report = Get-Content -Raw -LiteralPath (Join-Path $runPath $reportName) | ConvertFrom-Json
if ($report.status -ne 'GENERATED_PENDING_RUNTIME') { throw "Unexpected result: $($report.status)" }
if ($report.intensity_diagnostic) {
    Write-Host "Diagnostic only: BSP $($report.intensity_diagnostic.source_bsp_index) static power x$($report.intensity_diagnostic.factor). This is not a converter correction."
    Write-Host "Baseline tags are preserved under $runPath\before."
}
Write-Host 'Ready for Nate to check in Tag Test. Runtime acceptance remains pending.'
Write-Host 'game_start levels\h3_port\040_voi\factory_a_env\factory_a_env'
