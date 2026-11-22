@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title HERMES-RESCATE 1.0
set "BASE=%~dp0"
set "PY=%BASE%runtime\python\python.exe"
set "APP=%BASE%app\rescate.py"

if not exist "%PY%" (
    echo.
    echo   ERROR: no encuentro el runtime del USB: runtime\python\python.exe
    echo   Copia la carpeta HERMES-RESCATE completa al USB, sin quitar nada.
    echo.
    pause
    exit /b 1
)
if not exist "%APP%" (
    echo   ERROR: no encuentro app\rescate.py
    pause
    exit /b 1
)

"%PY%" "%APP%" %*
set "CODIGO=%ERRORLEVEL%"

if "%~1"=="" pause
exit /b %CODIGO%
