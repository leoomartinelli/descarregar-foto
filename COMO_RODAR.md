# 📸 Guia de Preparação e Execução (Windows & macOS)

Este guia explica como baixar, configurar e executar o **Descarregador de Fotos** diretamente do código-fonte (sem compilar um executável `.exe` ou `.app`) no **Windows** e no **macOS**.

Com as atualizações recentes, **você não precisa instalar o Python manualmente** antes! Nossos scripts de inicialização automática cuidam de tudo.

---

## 🖥️ Como Executar no Windows (Método com Um Clique) 🚀

1.  Baixe ou clone o projeto na sua máquina.
2.  Abra a pasta do projeto.
3.  Dê dois cliques no arquivo **`rodar.bat`**.
4.  O script irá:
    *   **Verificar se você tem o Python instalado**.
    *   Se não tiver, ele **baixará o instalador oficial do Python 3.10 em segundo plano** e fará a instalação de forma 100% invisível e automática para o seu usuário.
    *   Criar a pasta `.venv` (ambiente virtual) para isolar as bibliotecas do projeto.
    *   Instalar todas as dependências necessárias descritas no arquivo `requirements.txt`.
    *   Iniciar o aplicativo automaticamente.
5.  Nas próximas vezes que rodar o `rodar.bat`, como o ambiente já estará preparado, o programa abrirá instantaneamente em menos de 2 segundos!

> [!TIP]
> **Instalação Manual (Alternativa via Terminal)**:
> Se preferir controlar tudo passo a passo pelo Prompt de Comando (`cmd`):
> 1. Na pasta do projeto, abra o terminal e crie o ambiente virtual: `python -m venv .venv`
> 2. Ative-o: `call .venv\Scripts\activate`
> 3. Instale as dependências: `pip install -r requirements.txt`
> 4. Execute: `python app.py`

---

## 🍎 Como Executar no macOS (Método com Um Clique) 🚀

Para rodar no Mac, o macOS precisa de uma permissão inicial rápida de segurança para permitir que o script execute. Siga os passos abaixo:

1.  Baixe ou clone o projeto na sua máquina.
2.  Abra o **Terminal** do seu Mac.
3.  Navegue até a pasta do projeto (digite `cd ` com espaço e arraste a pasta do projeto do Finder para dentro da janela do terminal, apertando `Enter`).
4.  Dê permissão de execução ao script com o seguinte comando:
    ```bash
    chmod +x rodar.command
    ```
5.  Pronto! Agora você já pode fechar o terminal. A partir de agora, **basta dar dois cliques no arquivo `rodar.command`** pelo Finder.
6.  O script irá:
    *   **Verificar se o Python 3 está instalado**. Se não estiver, ele fará o download do instalador `.pkg` oficial e o abrirá na tela para você prosseguir com a instalação nativa do macOS em poucos cliques.
    *   Criar o ambiente virtual `.venv` e instalar as bibliotecas do `requirements.txt`.
    *   Iniciar o aplicativo automaticamente.

> [!TIP]
> **Instalação Manual (Alternativa via Terminal)**:
> 1. No Terminal, navegue até a pasta: `cd /caminho/do/projeto`
> 2. Crie o ambiente virtual: `python3 -m venv .venv`
> 3. Ative-o: `source .venv/bin/activate`
> 4. Instale as dependências: `pip install -r requirements.txt`
> 5. Execute: `python3 app.py`

---

## ☁️ Configurando o Google Drive (Opcional)

Se o aplicativo precisar enviar as fotos diretamente para o Google Drive:

1.  Siga o guia detalhado em `google_drive_credentials_guide.md` para gerar as credenciais do seu projeto no Google Cloud Console.
2.  Coloque o arquivo baixado e renomeado `credentials.json` na mesma pasta do arquivo `app.py`.
3.  Ao usar o botão de upload para o Drive pela primeira vez, uma página de login abrirá no navegador para autorizar a conta. Após autorizar, o arquivo `token.json` será gerado localmente e o processo será 100% automático dali em diante.

---

## ❓ Resolução de Problemas Comuns

### 1. Mensagem de erro "Tkinter" ou "Tcl/Tk" no macOS 🔴
Se ao rodar você receber uma mensagem informando que o `tkinter` não está instalado:
*   Se você instalou o Python via **Homebrew**, rode no terminal:
    ```bash
    brew install python-tk
    ```
*   Se você usou o instalador automático ou baixou diretamente do site oficial [python.org](https://www.python.org/), o Tkinter é instalado automaticamente. Recomenda-se reinstalar por lá.

### 2. Erro de download ou falha na instalação silenciosa no Windows 🔴
Se sua máquina corporativa ou rede possuir bloqueio de firewall impedindo o download automático do Python:
*   Baixe e instale manualmente a versão de instalação do Python em: [python.org/downloads](https://www.python.org/downloads/)
*   **Importante**: Lembre-se de marcar a opção **"Add Python to PATH"** na primeira tela da instalação manual.
