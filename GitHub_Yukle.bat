@echo off
chcp 65001 >nul
title Antigravity Remote - GitHub Yükleyici
cd /d "%~dp0"

set "GH_DESKTOP=%LOCALAPPDATA%\GitHubDesktop\GitHubDesktop.exe"
if exist "%GH_DESKTOP%" (
    echo [✓] GitHub Desktop açılıyor...
    start "" "%GH_DESKTOP%" --open-repo "%~dp0"
    echo.
    echo GitHub Desktop penceresinde üstteki "Publish repository" butonuna tıklayarak projeyi tek tıkla GitHub hesabına yükleyebilirsin!
    pause
    exit /b 0
)

echo GitHub Desktop bulunamadı. Lütfen GitHub repo URL'sini girin:
set /p REPO_URL="GitHub Repo URL (ör. https://github.com/kullanici/antigravity-remote.git): "
if "%REPO_URL%"=="" exit /b 0

for /d %%D in ("%LOCALAPPDATA%\GitHubDesktop\app-*") do (
    if exist "%%D\resources\app\git\cmd\git.exe" set "GIT_EXE=%%D\resources\app\git\cmd\git.exe"
)
if not defined GIT_EXE set "GIT_EXE=git"

"%GIT_EXE%" remote remove origin 2>nul
"%GIT_EXE%" remote add origin "%REPO_URL%"
"%GIT_EXE%" branch -M main
"%GIT_EXE%" push -u origin main
pause
