# JARVIS Astrologicum

Um agente pessoal com cara de galáxia. O centro é a inteligência do agente; cada estrela é um
conhecimento seu (notas, skills, conversas, artefatos); o anel externo mostra o céu real da sua
cidade (ascendente, meio do céu, descendente). O cérebro é o **Claude Code**, rodando numa sessão
própria a partir desta pasta.

*A personal agent shaped like a galaxy, powered by Claude Code. Portuguese UI; English notes at the end.*

## O que ele faz
- **Chat de verdade** com o Claude Code (Opus, Sonnet, Haiku ou Fable, você escolhe o cérebro),
  com ditado por voz e cartões de autorização: o que não está liberado pausa o agente e pede o seu
  "sim" no chat, mostrando o que muda.
- **Cluster vivo**: cada arquivo indexado vira uma estrela; as mais recentes ficam perto do núcleo.
  O menu inferior centraliza os tipos (Notas, Históricos, Skills, Artefatos e nichos seus).
- **Grafo de conhecimento** com o [graphify](https://github.com/Graphify-Labs/graphify): o agente
  acha as coisas sem ler arquivos inteiros, e o raciocínio aparece como constelações que se
  desenham e se desfazem.
- **Gmail, Agenda e Drive**: cards com e-mails e compromissos, janela do e-mail com anexos,
  imagens, responder, encaminhar, arquivar, lixeira e não lido.
- **Diretórios**: abas Claude (projetos do Claude Code), Drive e Computador; clique numa pasta e
  as estrelas dela acendem; marque pastas para indexar.
- **Tarefas** numa nota (`conhecimento/notas/Tarefas.md`), compatível com Obsidian.

## Requisitos
- macOS (Linux funciona, com menos testes). Python 3.9+.
- [Claude Code](https://claude.com/claude-code) com login (assinatura do Claude ou chave de API).
- Opcional: [uv](https://docs.astral.sh/uv/) (instala o graphify e as bibliotecas do Google).

## Instalação
```bash
git clone <este-repositório> jarvis-astrologicum
cd jarvis-astrologicum
claude            # uma vez: aceite a pasta e faça /login; depois /exit
python3 setup.py  # perguntas com respostas sugeridas (Enter aceita)
./jarvis.sh       # ou dois cliques em "Abrir Jarvis.command" no macOS
```

O setup pergunta, nesta ordem:
1. **Você**: nome, uma ou duas linhas sobre o seu trabalho, tom e idioma (vira o `CLAUDE.md`, a
   personalidade do agente).
2. **Cidade**: busca latitude, longitude e fuso (Open-Meteo, sem chave) para o céu real.
3. **Cérebro**: o modelo da conversa e o do trabalho de fundo (dá para acrescentar outro id).
4. **Menu inferior**: os botões padrão (Notas, Históricos, Skills, Artefatos), nichos sugeridos
   (Mapas astrais, Cursos, Design) e nichos seus por palavras; atalhos para apps locais.
5. **Fontes**: as pastas que viram estrelas (só leitura) e as bloqueadas.
6. **Google**: conectores do claude.ai (leitura) e, se quiser, a API do Google ([docs/GOOGLE.md](docs/GOOGLE.md)).
7. **graphify**: o grafo de conhecimento.

Rodar o setup de novo refaz a configuração. `python3 setup.py --config meu.json` aplica uma
configuração pronta sem perguntas.

## Motor: só Claude Code, por enquanto
O cérebro do JARVIS é o Claude Code. Dá para escolher o modelo do Claude (Opus, Sonnet, Haiku,
Fable ou outro id), mas não trocar por ChatGPT, Gemini ou outra LLM: o chat em tempo real, os
cartões de autorização (`--permission-prompt-tool`), as skills, os conectores do claude.ai e a
retomada de sessões são recursos do Claude Code. Outros motores (por exemplo Codex CLI e Gemini
CLI, com adaptadores no servidor) são uma possibilidade futura, com menos recursos.

Fora do chat, o resto já é independente: o graphify extrai o grafo com Claude, Gemini, OpenAI ou
modelos locais (Ollama), e com a API do Google os cards de Gmail e Agenda não usam modelo nenhum.

## Privacidade e segurança
- **Nada pessoal fica no repositório.** O setup gera `jarvis.config.json`, `fontes.json`,
  `CLAUDE.md`, `.claude/` e `.mcp.json`, todos no `.gitignore`, junto com `servidor/segredos/`
  (credenciais e token do Google), `servidor/cache/` (índice, grafo, painel) e o conteúdo de
  `conhecimento/`.
- O servidor escuta só em `127.0.0.1` e recusa pedidos de outros sites.
- O agente lê as fontes e escreve só em `conhecimento/`. Editar fora dali, rodar comandos,
  enviar e-mail ou mexer na agenda passa por um cartão de autorização, um por ação.
- Pastas bloqueadas e `servidor/segredos/` ficam proibidas para o agente.
- Serviços externos: Open-Meteo (temperatura e busca da cidade, recebe só a cidade); o
  reconhecimento de fala usa o do navegador (no Chrome o áudio vai para o Google, no Safari para a
  Apple); o graphify e o painel usam o seu Claude Code.
- Antes de publicar um fork, rode `python3 tools/verificar_privacidade.py`.

## Estrutura
```
setup.py                    setup guiado
jarvis.sh, Abrir Jarvis.command
config/                     exemplo de configuração e modelo do CLAUDE.md
frontend/index.html         a galáxia (Canvas 2D + HTML/CSS, sem bibliotecas)
servidor/                   ponte com o Claude Code (Python padrão) e módulos opcionais
  servidor.py               HTTP local, chat em tempo real, autorizações
  indexador.py, corpus.py   estrelas e corpus do grafo
  grafo.py                  conceitos e constelações
  pastas.py                 card de diretórios
  painel.py, google_api.py  Gmail, Agenda e Drive (conectores ou API)
  autorizador.py            MCP mínimo que leva os pedidos de permissão ao chat
conhecimento/               o seu cofre (fora do Git)
docs/GOOGLE.md              passo a passo da API do Google
```

## English notes
JARVIS Astrologicum is a local web UI (a living star cluster) on top of Claude Code running headless
(`claude -p`) from this folder. Run `python3 setup.py` to configure your name, city, preferred
Claude model ("brain"), bottom menu groups, indexed folders and Google integrations. Everything
personal is generated into git-ignored files. MIT license.
