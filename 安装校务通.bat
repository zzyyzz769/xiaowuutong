@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title 校务通 - 一键安装
echo ========================================
echo           校务通：一键安装
echo  所有文档和问答均在本机处理，不使用在线 API
echo ========================================
echo.

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
    echo [失败] 没有找到 Python。请先安装 Python 3.10—3.12，并勾选 Add Python to PATH。
    pause
    exit /b 1
)

echo [1/5] 检查 Python……
%PY_CMD% -c "import sys; print(sys.version); assert sys.version_info >= (3, 10), '请使用 Python 3.10 或更高版本'"
if errorlevel 1 (
    echo [失败] Python 版本不符合要求。
    pause
    exit /b 1
)

echo [2/5] 创建本项目的独立环境……
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 goto :failed
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

echo [3/5] 安装项目依赖。首次安装较慢，请保持网络畅通……
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 goto :failed
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [4/5] 检查 Ollama 本地模型服务……
where ollama >nul 2>nul
if errorlevel 1 (
    echo [失败] 没有找到 Ollama。请先从 https://ollama.com/download 安装并运行，再重新双击本文件。
    pause
    exit /b 1
)
ollama list >nul 2>nul
if errorlevel 1 (
    echo 正在尝试启动本机 Ollama 服务……
    start "Ollama 本地服务" /min cmd /c "ollama serve"
    timeout /t 5 /nobreak >nul
)
ollama list >nul 2>nul
if errorlevel 1 (
    echo [失败] Ollama 仍无法连接。请先打开 Ollama，再重新运行安装。
    pause
    exit /b 1
)

echo [5/5] 检查并下载本地模型。模型文件较大，只需首次下载……
ollama list | findstr /i /c:"bge-m3" >nul
if errorlevel 1 (
    echo 正在下载文档检索模型 bge-m3……
    ollama pull bge-m3
    if errorlevel 1 goto :failed
)
ollama list | findstr /i /c:"qwen2.5:7b" >nul
if errorlevel 1 (
    echo 正在下载默认回答模型 qwen2.5:7b……
    echo 如果电脑内存不足，可安装 qwen2.5:3b，并在启动后的侧栏切换。
    ollama pull qwen2.5:7b
    if errorlevel 1 goto :failed
)

echo.
echo ========================================
echo 安装检查已完成。以后双击“启动校务通.bat”即可。
echo 首次登录后必须修改默认密码。
echo ========================================
pause
exit /b 0

:failed
echo.
echo [失败] 安装未完成。请查看上方错误，修复后重新双击本文件；已下载的内容通常会保留。
pause
exit /b 1
