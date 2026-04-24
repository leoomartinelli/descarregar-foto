# 📸 Descarregador de Fotos - Ministério

Aplicação desktop desenvolvida em Python para facilitar a transferência de fotos de cartões SD para o computador, com foco em **simplicidade, automação e inclusão digital**.

---

## 🙌 Sobre o projeto

Este sistema foi desenvolvido para uso em igrejas e comunidades, especialmente pensado para pessoas com pouca familiaridade com computadores.

O objetivo é permitir que qualquer pessoa consiga descarregar fotos de câmeras (cartão SD) de forma simples, rápida e sem complicações técnicas.

---

## 🚀 Funcionalidades

- 🔌 Detecção automática de cartão SD  
- 📂 Listagem automática de pastas (DCIM e outras)  
- ✅ Seleção de pastas para importação  
- 🏷️ Renomeação automática com nome do fotógrafo  
- 📥 Cópia inteligente de arquivos (evita duplicados)  
- 🖼️ Suporte a imagens e vídeos:
  - JPG / JPEG / PNG  
  - RAW (CR2, NEF, ARW)  
  - MP4  
- 🎞️ Conversão de arquivos RAW para JPEG (alta qualidade)  
- ⚡ Processamento paralelo (multithread)  
- 📊 Barra de progresso em tempo real  
- 📁 Abertura automática da pasta ao finalizar  

---

## 🎯 Público-alvo

- Igrejas  
- Ministérios de mídia  
- Fotógrafos iniciantes  
- Pessoas com pouca experiência em tecnologia  
- Idosos  

---

## 🧠 Diferenciais

Este projeto vai além de um simples copiador de arquivos:

- Automatiza processos técnicos complexos  
- Elimina erros humanos  
- Interface simples e intuitiva  
- Pensado para quem não domina tecnologia  
- Conversão RAW profissional usando CPU  

---

## ⚙️ Tecnologias utilizadas

- Python 3  
- CustomTkinter  
- rawpy  
- imageio  
- psutil  
- threading / concurrent.futures  

---

## 📦 Instalação

Clone o repositório:

    git clone https://github.com/leoomartinelli/descarregar-foto.git
    cd descarregar-foto

Instale as dependências:

    pip install customtkinter psutil rawpy imageio

---

## ▶️ Como executar

    python app.py

---

## 🖥️ Como usar

1. Insira o cartão SD no computador  
2. O sistema detectará automaticamente o dispositivo  
3. Digite o nome do fotógrafo  
4. Selecione as pastas desejadas  
5. Escolha a pasta de destino  
6. (Opcional) Ative conversão RAW → JPEG  
7. Clique em **Iniciar Transferência**  

---

## 🔄 Como funciona internamente

- Monitora dispositivos conectados em tempo real  
- Detecta automaticamente novos drives  
- Busca pastas padrão (DCIM)  
- Processa arquivos em paralelo (4 threads)  
- Converte arquivos RAW usando `rawpy`  
- Evita sobrescrita de arquivos duplicados  

---

## ❤️ Propósito

Este projeto foi criado com um propósito maior:

> Tornar a tecnologia acessível para todos.

Muitas pessoas ainda enfrentam dificuldades com tarefas simples no computador.  
Essa aplicação foi desenvolvida para **incluir, simplificar e ajudar**.

---

## ✝️ Aplicação na Igreja

- Organização de fotos de eventos  
- Agilidade no fluxo de mídia  
- Apoio ao ministério de comunicação  
- Inclusão digital de membros  

---

## 📌 Melhorias futuras

- Versão instalável (.exe)  
- Interface ainda mais simplificada  
- Backup automático  
- Integração com nuvem (Google Drive / OneDrive)  
- Drag & Drop de arquivos  

---

## 🤝 Contribuição

Contribuições são bem-vindas!

Abra uma issue ou envie um pull request.

---

## 📄 Licença

Uso livre para fins educacionais, comunitários e religiosos.

---

## 👨‍💻 Autor

Leonardo Martinelli
