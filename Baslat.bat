@echo off
chcp 65001 >nul
title Antigravity Remote - PC Kontrol Merkezi
echo Baslatiliyor: Antigravity Remote...
python "%~dp0run.py" %*
if errorlevel 1 (
    echo.
    echo Bir hata olustu. Cikmak icin bir tusa basin...
    pause >nul
)
