@echo off
rem Abre HERMES-RESCATE pidiendo permisos de administrador (UAC).
setlocal
set "BAT=%~dp0Rescate.bat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\"%BAT%\"' -Verb RunAs"
