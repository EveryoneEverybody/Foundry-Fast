@echo off
setlocal

if "%~1"=="" (
    echo Usage: %~nx0 ^<H3EK_ROOT^> [OUTPUT_DIR]
    echo Example: %~nx0 "D:\SteamLibrary\steamapps\common\H3EK" "D:\h3_shader_packet_040_voi"
    exit /b 2
)

set "H3EK_ROOT=%~1"
set "OUTPUT_DIR=%~2"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=%CD%\h3_shader_packet_040_voi"

py "%~dp0h3_shader_packet.py" "%H3EK_ROOT%" --output "%OUTPUT_DIR%" --copy-raw
exit /b %ERRORLEVEL%
