[CmdletBinding()]
param(
    [string]$H3Root = 'D:\SteamLibrary\steamapps\common\H3EK',
    [string]$ReachRoot = 'D:\SteamLibrary\steamapps\common\HREK',
    [string]$Blender = 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe',
    [string]$Fixtures = "$env:USERPROFILE\Downloads\H3_Reach_Box_Fixtures.zip",
    [string]$WorkDir = 'D:\HaloRE\PortCensus\proof_box_build_1948',
    [string]$Namespace = 'levels/h3_port/proof_box',
    [string]$AddonPath,
    [ValidateSet('direct_only','draft','none')][string]$Lighting = 'direct_only',
    [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'
if (-not $AddonPath) {
    $candidates = @((Join-Path $PSScriptRoot '..\blender\addons\io_scene_foundry'), (Join-Path $PSScriptRoot 'io_scene_foundry'))
    $AddonPath = $candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'h3_import\port_environment\cli.py') } | Select-Object -First 1
    if (-not $AddonPath) { throw 'Cannot locate the compiler addon. Supply -AddonPath or extract the complete runner package.' }
}
$compiler = Join-Path (Resolve-Path -LiteralPath $AddonPath).Path 'h3_import\port_environment\cli.py'
$blenderPath = (Resolve-Path -LiteralPath $Blender).Path
$pythonPath = Join-Path (Split-Path -Parent $blenderPath) '5.2\python\bin\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Expected the Python bundled with Blender 5.2.1; verify -Blender.' }
$compilerArgs = @($compiler, '--h3-root', $H3Root, '--reach-root', $ReachRoot, '--blender', $blenderPath,
    '--fixtures', $Fixtures, '--work-dir', $WorkDir, '--namespace', $Namespace, '--lighting', $Lighting)
if ($PlanOnly) { $compilerArgs += '--plan-only' }
& $pythonPath @compilerArgs
exit $LASTEXITCODE
