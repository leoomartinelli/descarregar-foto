# Guia de Configuração da API do Google Drive

Este guia explica, passo a passo, como obter as credenciais da API do Google Drive (`credentials.json`) para habilitar o envio automático das fotos selecionadas do seu computador diretamente para o Google Drive.

---

## 🛠️ Passo a Passo no Console do Google Cloud

Siga as etapas abaixo para criar o seu projeto e gerar as credenciais necessárias:

### 1. Acessar o Google Cloud Console
1. Abra o seu navegador e acesse: [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Faça login com a sua conta Google (a mesma conta que você deseja usar para guardar as fotos).

### 2. Criar um Novo Projeto
1. No topo esquerdo da tela, clique no seletor de projetos (geralmente diz "Selecione um projeto" ou mostra o nome do projeto atual).
2. Na janela que se abrir, clique em **Novo Projeto** (New Project) no canto superior direito.
3. Dê um nome amigável para o projeto, por exemplo: `Descarregador de Fotos`.
4. Clique em **Criar** (Create) e aguarde alguns segundos até que a criação seja concluída.
5. Certifique-se de que o novo projeto está selecionado no topo esquerdo.

### 3. Ativar a API do Google Drive
1. No campo de pesquisa no topo do console, digite `Google Drive API`.
2. Clique na opção **Google Drive API** que aparece nos resultados da pesquisa.
3. Clique no botão azul **Ativar** (Enable) e aguarde o processo terminar.

### 4. Configurar a Tela de Consentimento OAuth (OAuth Consent Screen)
Como este é um aplicativo para uso próprio ou de uma equipe restrita, precisamos configurar a tela de consentimento para permitir logins:
1. No menu lateral esquerdo, navegue até **APIs e Serviços** > **Tela de consentimento OAuth** (OAuth consent screen).
2. Selecione o tipo de usuário como **Externo** (External) e clique em **Criar** (Create).
3. Preencha as informações básicas obrigatórias:
   - **Nome do aplicativo**: `Descarregador de Fotos`
   - **E-mail de suporte do usuário**: Selecione o seu próprio e-mail.
   - **Dados de contato do desenvolvedor**: Coloque o seu e-mail.
4. Clique em **Salvar e Continuar** (Save and Continue).
5. Na aba **Escopos** (Scopes), não é necessário adicionar nada manualmente agora. Apenas role até o final e clique em **Salvar e Continuar**.
6. Na aba **Usuários de teste** (Test users) — **ISSO É MUITO IMPORTANTE**:
   - Clique em **+ ADD USERS** (Adicionar Usuários).
   - Digite o seu e-mail do Google (e de qualquer outro fotógrafo que usará o aplicativo).
   - Clique em **Add** / **Salvar**. *Sem este passo, a API bloqueará o login do aplicativo por estar em modo de teste.*
7. Clique em **Salvar e Continuar** e depois em **Voltar para o painel**.

### 5. Criar as Credenciais (OAuth Client ID)
1. No menu lateral esquerdo, clique em **Credenciais** (Credentials).
2. No topo da página, clique em **+ Criar Credenciais** (+ Create Credentials) e escolha a opção **ID do cliente OAuth** (OAuth client ID).
3. No campo **Tipo de aplicativo** (Application type), selecione **App de desktop** (Desktop app).
4. No campo **Nome**, você pode manter o padrão ou dar um nome como `Descarregador Desktop`.
5. Clique em **Criar** (Create).
6. Uma janela popup aparecerá informando que o cliente OAuth foi criado. Clique em **OK**.

### 6. Baixar o arquivo `credentials.json`
1. Na lista de "IDs de cliente OAuth 2.0" que agora exibe o seu novo cliente, clique no ícone de **Download** (uma seta para baixo) na extremidade direita da linha correspondente ao cliente que você acabou de criar.
2. O arquivo será baixado com um nome longo (ex: `client_secret_xxxxxx.json`).
3. **Renomeie o arquivo baixado exatamente para:** `credentials.json`
4. Mova esse arquivo `credentials.json` para a pasta raiz do projeto (onde o arquivo `app.py` está localizado).

---

## 🚀 Como Funciona no Aplicativo?

1. **Primeiro Upload**: Quando você clicar no botão **"📤 Enviar Fotos para o Google Drive"** pela primeira vez, o aplicativo mostrará um aviso e abrirá automaticamente uma página no seu navegador padrão.
2. **Autorização**: No navegador, selecione a sua conta Google. Se aparecer uma mensagem dizendo que "O Google não verificou este app", clique em **Avançado** (Advanced) e depois em **Ir para Descarregador de Fotos (não seguro)**. Isso é normal porque o projeto que você criou é privatizado e não passou pelo processo de verificação do Google.
3. **Persistência**: Uma vez autorizado, o aplicativo gerará um arquivo local chamado `token.json` na mesma pasta. Nas próximas vezes que você usar o aplicativo, ele usará esse token automático e **não precisará abrir o navegador novamente**, a menos que o token expire ou seja deletado.
4. **Organização no Drive**: O app cria automaticamente uma pasta organizada no seu Google Drive com o seguinte padrão de nome:  
   `Fotos - [Nome do Fotógrafo] - [Data Atual]` (ex: `Fotos - JoaoSilva - 02-06-2026`).

---

> [!TIP]
> **Segurança**: Nunca compartilhe o seu arquivo `credentials.json` ou `token.json` publicamente em repositórios do Git (como GitHub). Eles já estão adicionados ao seu `.gitignore` para proteção das suas credenciais!
