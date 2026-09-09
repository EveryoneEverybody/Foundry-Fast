param(
    [Parameter(Mandatory=$true)][string]$H3EKRoot,
    [string]$OutputDir = (Join-Path (Get-Location) 'h3_shader_packet_040_voi')
)

$script = Join-Path $PSScriptRoot 'h3_shader_packet.py'
py $script $H3EKRoot --output $OutputDir --copy-raw
exit $LASTEXITCODE
