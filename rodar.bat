@echo off
title Descarregador de Fotos - Inicializador
cd /d "%~dp0"

echo ===================================================
echo    DESCARREGADOR DE FOTOS - INICIALIZADOR AUTOMATICO
echo ===================================================
echo.

set "PYTHON_EXE=python"
set "PYTHON_FOUND=0"

rem Verifica se o Python esta instalado no PATH
where python > "%temp%\py_path.txt" 2>nul
if %errorlevel% equ 0 (
    rem Verifica se e apenas o atalho vazio da Windows Store
    findstr /i "WindowsApps" "%temp%\py_path.txt" >nul
    if errorlevel 1 (
        set "PYTHON_EXE=python"
        set "PYTHON_FOUND=1"
    )
    del "%temp%\py_path.txt" 2>nul
)

if %PYTHON_FOUND% equ 0 (
    rem Tenta verificar se ja esta instalado na pasta local padrao do usuario
    if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
        echo [INFO] Python 3.10 encontrado no caminho local do usuario.
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python310\python.exe"
        set "PATH=%LocalAppData%\Programs\Python\Python310;%LocalAppData%\Programs\Python\Python310\Scripts;%PATH%"
        set "PYTHON_FOUND=1"
    ) else if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
        echo [INFO] Python 3.11 encontrado no caminho local do usuario.
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
        set "PATH=%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%PATH%"
        set "PYTHON_FOUND=1"
    ) else if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
        echo [INFO] Python 3.12 encontrado no caminho local do usuario.
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
        set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
        set "PYTHON_FOUND=1"
    ) else (
        echo [INFO] Python nao foi encontrado no seu computador!
        echo [INFO] Iniciando o download automatico do Python 3.10...
        echo.
        
        rem Baixa o instalador do site oficial
        curl -L -o "%temp%\python_installer.exe" https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
        if %errorlevel% neq 0 (
            echo [ERRO] Falha ao baixar o instalador do Python.
            echo Por favor, verifique sua conexao com a internet ou instale o Python manualmente em:
            echo https://www.python.org/downloads/
            goto :error
        )
        
        echo [INFO] Instalando Python 3.10 em segundo plano...
        echo Por favor, aguarde alguns instantes ate que a instalacao termine.
        start /wait "" "%temp%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
        del "%temp%\python_installer.exe" 2>nul
        
        if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
            echo [INFO] Python instalado com sucesso!
            set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python310\python.exe"
            set "PATH=%LocalAppData%\Programs\Python\Python310;%LocalAppData%\Programs\Python\Python310\Scripts;%PATH%"
            set "PYTHON_FOUND=1"
        ) else (
            echo [ERRO] A instalacao silenciosa falhou ou nao foi concluida.
            echo Por favor, instale o Python manualmente em: https://www.python.org/downloads/
            goto :error
        )
    )
)

rem Verifica/Cria o ambiente virtual (.venv)
if not exist .venv (
    echo [INFO] Criando ambiente virtual (.venv) para isolar as dependencias...
    "%PYTHON_EXE%" -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERRO] Falha ao criar o ambiente virtual. Verifique a instalacao do Python.
        goto :error
    )
)

rem Ativa o ambiente virtual
echo [INFO] Ativando ambiente virtual...
call .venv\Scripts\activate
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao ativar o ambiente virtual (.venv).
    goto :error
)

rem Atualiza o pip e instala as dependencias
echo [INFO] Verificando e instalando dependencias (requirements.txt)...
python -m pip install --upgrade pip -q
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERRO] Falha ao instalar as dependencias. Verifique sua conexao com a internet.
    goto :error
)

rem Executa a aplicacao
echo.
echo [INFO] Iniciando o aplicativo...
python app.py
if %errorlevel% neq 0 (
    echo [ERRO] O aplicativo encerrou com erro.
    goto :error
)

goto :success

:error
echo.
echo ===================================================
echo [ERRO] Ocorreu uma falha no processo de inicializacao.
echo O terminal continuara aberto para que voce possa ler as mensagens.
echo ===================================================
pause
exit /b 1

:success
exit /b 0
