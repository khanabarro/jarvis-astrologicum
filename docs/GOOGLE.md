# API do Google (opcional)

Sem a API, o JARVIS lê Gmail, Agenda e Drive pelos conectores do claude.ai, usando o modelo de
fundo (gasta alguns tokens a cada 30 min). Com a API, os cards carregam em ~3 s sem gastar tokens,
a janela do e-mail mostra anexos e imagens, e os docs do Google entram no grafo com o conteúdo.

## 1. Google Cloud (uns 10 minutos)
1. Em <https://console.cloud.google.com>, crie um projeto (ex.: "Jarvis").
2. **APIs e serviços → Biblioteca**: ative **Gmail API**, **Google Drive API** e **Google Calendar API**.
3. **Tela de consentimento OAuth** (ou *Google Auth Platform*): tipo **Externo**; preencha o nome do app
   e o seu e-mail.
4. Em **Público-alvo → Usuários de teste**, adicione o seu Gmail. Sem isso o Google responde
   `Erro 403: access_denied`.
5. **Credenciais → Criar credenciais → ID do cliente OAuth**, tipo **App para computador**.
   Baixe o JSON.

## 2. No computador
1. Salve o JSON como `servidor/segredos/google-cliente.json` (a pasta é criada pelo setup, só o
   seu usuário lê e ela nunca vai para o Git).
2. Garanta o ambiente com as bibliotecas: o setup cria `servidor/.venv` quando você responde
   "sim" à API do Google. À mão:
   `uv venv servidor/.venv && uv pip install --python servidor/.venv/bin/python -r servidor/requirements-google.txt`
3. Abra o JARVIS e clique em **Conectar Google** no card do Gmail. Autorize no navegador.
   O token fica em `servidor/segredos/google-token.json`.

## Permissões pedidas
- Gmail `gmail.modify`: ler, organizar (labels, arquivar, lixeira, não lido) e enviar. Não apaga
  definitivamente.
- Agenda `calendar.readonly` e `calendar.events`.
- Drive `drive.readonly`.

## Bom saber
- Com o app em modo de teste, o Google expira a autorização a cada 7 dias; o card do Gmail mostra
  "Conectar Google de novo" e é um clique.
- Imagens externas dos e-mails só carregam quando você clica em "Carregar imagens externas"
  (elas avisam ao remetente que você abriu).
