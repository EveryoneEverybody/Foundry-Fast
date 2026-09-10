[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ReclaimerRoot,
    [string]$Dotnet = 'C:\Program Files\dotnet\dotnet.exe'
)
$ErrorActionPreference = 'Stop'
$readerRoot = (Resolve-Path -LiteralPath $ReclaimerRoot).Path
$revision = & git -C $readerRoot rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $revision -ne '6209415badf398a17a895d4d726b67eea850c67f') {
    throw 'Reclaimer source must be the verified revision 6209415badf398a17a895d4d726b67eea850c67f.'
}
$dirty = & git -C $readerRoot status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Pinned Reclaimer source has local modifications; evidence reader identity is unverified.' }
$project = Join-Path $PSScriptRoot 'h3_cache_evidence\H3CacheEvidence.csproj'
& $Dotnet build $project --configuration Release "-p:ReclaimerRoot=$readerRoot" --nologo
if ($LASTEXITCODE -ne 0) { throw 'Read-only H3 cache evidence reader build failed.' }
