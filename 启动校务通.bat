@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title 校务通 - 本地启动

if not exist ".venv\Scripts\python.exe" (
    echo [未安装] 请先双击“安装校务通.bat”。
    pause
    exit /b 1
)
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

"%VENV_PY%" -c "import streamlit, langchain_chroma, langchain_ollama, docx, jieba, rank_bm25, pypdf, pdfplumber" >nul 2>nul
if errorlevel 1 (
    echo [依赖不完整] 请重新双击“安装校务通.bat”。
    pause
    exit /b 1
)

where ollama >nul 2>nul
if errorlevel 1 (
    echo [未找到 Ollama] 请先安装并运行 Ollama。
    pause
    exit /b 1
)
ollama list >nul 2>nul
if errorlevel 1 (
    echo 正在启动本机 Ollama 服务……
    start "Ollama 本地服务" /min cmd /c "ollama serve"
    timeout /t 5 /nobreak >nul
)
ollama list >nul 2>nul
if errorlevel 1 (
    echo [服务未启动] 请先打开 Ollama，再重新运行本文件。
    pause
    exit /b 1
)
ollama list | findstr /i /c:"bge-m3" >nul
if errorlevel 1 (
    echo [缺少 bge-m3] 请重新运行“安装校务通.bat”下载检索模型。
    pause
    exit /b 1
)
ollama list | findstr /i /c:"qwen2.5:7b" >nul
if errorlevel 1 (
    ollama list | findstr /i /c:"qwen2.5:3b" >nul
    if errorlevel 1 (
        echo [缺少回答模型] 请重新运行“安装校务通.bat”，或执行 ollama pull qwen2.5:3b。
        pause
        exit /b 1
    )
    echo 提示：检测到 3b。启动后请先在左侧“本地模型设置”切换为 qwen2.5:3b。
    "%VENV_PY%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false
    goto :end
)

echo 校务通正在启动，浏览器将打开 http://127.0.0.1:8501
echo 关闭此窗口会停止校务通；你的本机数据不会被删除。
"%VENV_PY%" -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --server.headless false

:end
pause
