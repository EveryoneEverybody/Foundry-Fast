<# Manual coordinator; default ValidateOnly never starts Faux. See docs/manual-h3-lighting.md. #>
[CmdletBinding()]
param(
    [string]$Config,
    [string]$Preset,
    [string]$PresetDirectory,
    [string]$HrekRoot,
    [string]$Scenario,
    [string[]]$Bsp,
    [ValidateSet('draft','direct_only','low','medium','high','super_slow')][string]$Quality,
    [ValidateRange(1,64)][int]$Workers,
    [string]$LightGroup,
    [string]$Name,
    [ValidateSet('ValidateOnly','PrepareOnly','BakeOnly','PrepareAndBake')][string]$Mode,
    [switch]$ValidateOnly, [switch]$PrepareOnly, [switch]$BakeOnly, [switch]$PrepareAndBake,
    [string]$Plan,
    [string]$OutputNamespace,
    [ValidateSet('Refuse','GuardedInPlace')][string]$OutputPolicy,
    [switch]$ConfirmInPlace,
    [string]$RunRoot,
    [string]$Blender,
    [ValidateRange(1,3600)][int]$IntervalSeconds,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$settings = @{}
if ($Preset) {
    if ($Config -or !$PresetDirectory -or $Preset -notmatch '^[A-Za-z0-9_-]+$') { throw 'Preset requires PresetDirectory and cannot be combined with Config' }
    $Config = Join-Path $PresetDirectory ($Preset + '.json')
}
if ($Config) {
    $loaded = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
    foreach ($property in $loaded.PSObject.Properties) { $settings[$property.Name] = $property.Value }
}
$modeSwitches = @('ValidateOnly','PrepareOnly','BakeOnly','PrepareAndBake') | Where-Object { $PSBoundParameters.ContainsKey($_) -and $PSBoundParameters[$_] }
if (@($modeSwitches).Count -gt 1 -or (@($modeSwitches).Count -and $PSBoundParameters.ContainsKey('Mode'))) { throw 'Choose one mode' }
foreach ($key in $PSBoundParameters.Keys) {
    if ($key -notin @('Config','Preset','PresetDirectory','Python','ValidateOnly','PrepareOnly','BakeOnly','PrepareAndBake')) { $settings[$key] = $PSBoundParameters[$key] }
}
if (@($modeSwitches).Count) { $settings['Mode'] = @($modeSwitches)[0] }
# Permission to overwrite is always an explicit invocation, never stored in a preset.
$settings['ConfirmInPlace'] = [bool]$ConfirmInPlace
foreach ($required in @('HrekRoot','Scenario','RunRoot','Blender')) {
    if (!$settings[$required]) { throw "Missing $required (argument or local config)" }
}
$temporaryConfig = Join-Path ([IO.Path]::GetTempPath()) ('foundry-manual-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    $settings | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $temporaryConfig -Encoding UTF8
    & $Python (Join-Path $PSScriptRoot 'manual_bake\runner.py') --config $temporaryConfig
    $runnerExit = $LASTEXITCODE
} finally { Remove-Item -LiteralPath $temporaryConfig -ErrorAction SilentlyContinue }
exit $runnerExit
