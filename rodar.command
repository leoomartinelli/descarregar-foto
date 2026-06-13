#!/bin/bash

# Define o diretorio atual como o diretorio onde o script esta
cd "$(dirname "$0")"

clear
echo "==================================================="
echo "   DESCARREGADOR DE FOTOS - INICIALIZADOR AUTOMATICO"
echo "==================================================="
echo

# Verifica se o Python 3 esta instalado
if ! command -v python3 &> /dev/null
then
    echo "[INFO] Python 3 nao foi encontrado no seu Mac."
    echo "[INFO] Baixando instalador oficial do Python 3.10..."
    echo
    curl -L -o /tmp/python_installer.pkg https://www.python.org/ftp/python/3.10.11/python-3.10.11-macos11.pkg
    if [ $? -ne 0 ]; then
        echo "[ERRO] Falha ao baixar o instalador do Python."
        echo "Por favor, instale o Python manualmente em: https://www.python.org/downloads/"
        read -p "Pressione [Enter] para fechar..."
        exit 1
    fi
    echo "[INFO] Abrindo o instalador do Python."
    echo "Siga os passos na tela do assistente para concluir a instalacao..."
    open /tmp/python_installer.pkg
    
    # Espera o usuario terminar a instalacao
    echo
    echo "--> ATENCAO: Depois que o instalador terminar, pressione [Enter] aqui para continuar."
    read -p ""
    
    # Verifica novamente se foi instalado
    if ! command -v python3 &> /dev/null
    then
        echo "[ERRO] Python 3 ainda nao foi detectado."
        echo "Por favor, conclua a instalacao e tente rodar o script novamente."
        read -p "Pressione [Enter] para fechar..."
        exit 1
    fi
fi

# Verifica/Cria o ambiente virtual (.venv)
if [ ! -d ".venv" ]; then
    echo "[INFO] Criando ambiente virtual (.venv) para isolar as dependencias..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[ERRO] Falha ao criar o ambiente virtual. Verifique a instalacao do Python."
        read -p "Pressione [Enter] para fechar..."
        exit 1
    fi
fi

# Ativa o ambiente virtual
echo "[INFO] Ativando ambiente virtual..."
source .venv/bin/activate

# Atualiza o pip e instala as dependencias
echo "[INFO] Verificando e instalando dependencias (requirements.txt)..."
python3 -m pip install --upgrade pip -q
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[ERRO] Falha ao instalar as dependencias. Verifique a conexao com a internet."
    read -p "Pressione [Enter] para fechar..."
    exit 1
fi

# Executa a aplicacao
echo
echo "[INFO] Iniciando o aplicativo..."
python3 app.py
if [ $? -ne 0 ]; then
    echo
    echo "[ERRO] O aplicativo encerrou com erro."
    read -p "Pressione [Enter] para fechar..."
fi
