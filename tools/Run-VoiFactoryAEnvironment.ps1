[CmdletBinding()]
param(
    [string]$H3Root = 'D:\SteamLibrary\steamapps\common\H3EK',
    [string]$ReachRoot = 'D:\SteamLibrary\steamapps\common\HREK',
    [string]$Blender = 'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe',
    [string]$WorkDir = 'D:\HaloRE\PortCensus\voi_factory_a_environment_1949',
    [string]$Namespace = 'levels/h3_port/040_voi/factory_a_env',
    [string]$H3XmlEvidence = 'D:\HaloRE\H3TagXML.zip',
    [string]$ReachXmlEvidence = 'D:\HaloRE\ReachTagXML.zip',
    [string]$Templates,
    [string]$AddonPath,
    [string]$Helpers,
    [string]$SourceCacheEvidence,
    [string]$SourceHistoryEvidence,
    [string]$SemanticBaseline,
    [string]$AcceptedPlan,
    [string]$ValidateExistingRun,
    [string]$SourceCacheReader,
    [string]$ReclaimerRoot = 'D:\HaloRE\PortCensus\references\Reclaimer',
    [string]$SourceCache = 'D:\SteamLibrary\steamapps\common\Halo The Master Chief Collection\halo3\maps\040_voi.map',
    [ValidateSet('direct_only','none')][string]$Lighting = 'direct_only',
    [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'
if (-not $AddonPath) {
    $candidates = @((Join-Path $PSScriptRoot '..\blender\addons\io_scene_foundry'), (Join-Path $PSScriptRoot 'io_scene_foundry'))
    $AddonPath = $candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'h3_import\port_environment\cli.py') } | Select-Object -First 1
    if (-not $AddonPath) { throw 'Cannot locate the environment compiler. Supply -AddonPath.' }
}
if (-not $Templates) { $Templates = Join-Path $ReachRoot 'bin\tools\templates.zip' }
if (-not $Helpers) {
    $builtHelpers = Join-Path $PSScriptRoot 'h3_object_bridge\target\release'
    $missingHelpers = @('h3-scenario-inspect.exe','h3-object-bridge.exe','h3-shader-bridge.exe') |
        Where-Object { -not (Test-Path -LiteralPath (Join-Path $builtHelpers $_)) }
    if (-not $missingHelpers) { $Helpers = $builtHelpers }
}
$compiler = Join-Path (Resolve-Path -LiteralPath $AddonPath).Path 'h3_import\port_environment\cli.py'
$blenderPath = (Resolve-Path -LiteralPath $Blender).Path
$pythonPath = Join-Path (Split-Path -Parent $blenderPath) '5.2\python\bin\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Expected Python bundled with Blender 5.2.1; verify -Blender.' }
$compilerArgs = @($compiler, '--h3-root', $H3Root, '--reach-root', $ReachRoot, '--blender', $blenderPath,
    '--scenario', 'levels/solo/040_voi/040_voi.scenario', '--zone-set', 'intro_faa',
    '--spawn-flag', 'teleport_factorya_player0', '--work-dir', $WorkDir, '--namespace', $Namespace,
    '--lighting', $Lighting, '--h3-xml-evidence', $H3XmlEvidence, '--reach-xml-evidence', $ReachXmlEvidence,
    '--templates', $Templates)
if ($Helpers) { $compilerArgs += @('--helpers', $Helpers) }
if ($SourceCacheEvidence) { $compilerArgs += @('--source-cache-evidence', $SourceCacheEvidence) }
if ($SourceHistoryEvidence) { $compilerArgs += @('--source-history-evidence', $SourceHistoryEvidence) }
if ($SemanticBaseline) { $compilerArgs += @('--semantic-baseline', $SemanticBaseline) }
if ($AcceptedPlan) { $compilerArgs += @('--accepted-plan', $AcceptedPlan) }
if ($ValidateExistingRun) { $compilerArgs += @('--validate-existing-run', $ValidateExistingRun) }
if (-not $AcceptedPlan -and -not $SourceCacheEvidence -and -not $SourceCacheReader -and (Test-Path -LiteralPath $SourceCache)) {
    $readerProject = Join-Path $PSScriptRoot 'h3_cache_evidence\H3CacheEvidence.csproj'
    if ((Test-Path -LiteralPath $readerProject) -and (Test-Path -LiteralPath $ReclaimerRoot)) {
        & (Join-Path $PSScriptRoot 'Build-H3CacheEvidence.ps1') -ReclaimerRoot $ReclaimerRoot
        $SourceCacheReader = Join-Path $PSScriptRoot 'h3_cache_evidence\bin\Release\net9.0-windows\H3CacheEvidence.exe'
    }
}
if ($SourceCacheReader) {
    if (-not (Test-Path -LiteralPath $SourceCache)) { throw 'Stock H3 cache path does not exist; verify -SourceCache.' }
    $compilerArgs += @('--source-cache-reader', $SourceCacheReader, '--source-cache', $SourceCache)
}
if ($PlanOnly) { $compilerArgs += '--plan-only' }
& $pythonPath @compilerArgs
exit $LASTEXITCODE
