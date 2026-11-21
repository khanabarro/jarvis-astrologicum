#!/usr/bin/env python3
"""Setup guiado do JARVIS Astrologicum.

    python3 setup.py                 # perguntas, com respostas sugeridas (Enter aceita)
    python3 setup.py --padrao        # sem perguntas: usa config/jarvis.config.example.json
    python3 setup.py --config x.json # sem perguntas: usa a sua configuração

Gera (tudo fora do Git): jarvis.config.json, fontes.json, CLAUDE.md, .claude/settings.json,
.mcp.json, conhecimento/notas/Tarefas.md e servidor/segredos/. Só Python padrão.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
HOME = Path.home()
EXEMPLO = json.loads((RAIZ / "config" / "jarvis.config.example.json").read_text())
NICHOS_BASE = [
    {"id": "notas", "nome": "Notas", "tipo": "nota", "sobre": "suas notas em .md e .txt"},
    {"id": "historicos", "nome": "Históricos", "tipo": "conversa", "sobre": "conversas do Claude Code"},
    {"id": "skills", "nome": "Skills", "tipo": "skill", "sobre": "as skills instaladas"},
    {"id": "artefatos", "nome": "Artefatos", "tipo": "artefato", "sobre": "HTML, PDF, imagens, documentos"},
]
NICHOS_SUGERIDOS = [
    {"id": "mapas", "nome": "Mapas astrais", "tipo": "artefato", "padrao": "natal|revolu[cç][aã]o.?solar|hor[aá]ria|sinastria",
     "sobre": "mapas natais, revoluções solares e horárias"},
    {"id": "cursos", "nome": "Cursos", "tipo": "*", "padrao": "certificado|\\baula|apostila|curso", "sobre": "aulas, apostilas, certificados"},
    {"id": "design", "nome": "Design", "tipo": "*", "padrao": "design|figma|mockup|identidade", "sobre": "materiais de design"},
]

# ---------- conversa no terminal ----------
C = {"t": "\033[1m", "d": "\033[2m", "o": "\033[33m", "v": "\033[32m", "x": "\033[0m"} if sys.stdout.isatty() else {k: "" for k in "tdovx"}


def titulo(t):
    print(f"\n{C['o']}✦ {t}{C['x']}")


def perguntar(p, padrao=""):
    r = input(f"  {p}{f' {C[chr(100)]}[{padrao}]{C[chr(120)]}' if padrao != '' else ''}: ").strip()
    return r or padrao


AUTOMATICO = False                            # --padrao / --config: sem perguntas (instalações ficam como instrução)


def sim(p, padrao=True):
    if AUTOMATICO:
        return False
    r = input(f"  {p} {C['d']}[{'S/n' if padrao else 's/N'}]{C['x']}: ").strip().lower()
    return padrao if not r else r.startswith("s") or r.startswith("y")


def escolher(p, opcoes, padrao=0):
    for i, o in enumerate(opcoes, 1):
        print(f"   {i}. {o}")
    while True:
        r = perguntar(p, str(padrao + 1))
        if r.isdigit() and 1 <= int(r) <= len(opcoes):
            return int(r) - 1


def varios(p, opcoes, padrao=()):
    for i, o in enumerate(opcoes, 1):
        print(f"   {i}. {o}")
    r = perguntar(p + " (números separados por vírgula, vazio = nenhum)", ",".join(str(i + 1) for i in padrao))
    return [int(x) - 1 for x in re.split(r"[,\s]+", r) if x.isdigit() and 1 <= int(x) <= len(opcoes)]


# ---------- verificações ----------
def achar_claude():
    for c in (shutil.which("claude"), HOME / ".local/bin/claude", HOME / ".claude/local/claude"):
        if c and os.access(str(c), os.X_OK):
            return str(c)
    return None


def verificar():
    titulo("Verificando o que o JARVIS precisa")
    ok = True
    print(f"  Python {sys.version.split()[0]} {C['v']}✓{C['x']}")
    claude = achar_claude()
    if not claude:
        print(f"  Claude Code: não encontrado. Instale com:\n    curl -fsSL https://claude.ai/install.sh | bash")
        ok = False
    else:
        try:
            st = json.loads(subprocess.run([claude, "auth", "status"], capture_output=True, text=True, timeout=30).stdout or "{}")
        except (ValueError, subprocess.TimeoutExpired):
            st = {}
        logado = st.get("loggedIn")
        print(f"  Claude Code em {claude} {C['v']}✓{C['x']}" + ("" if logado else
              f"\n  {C['o']}Sem login.{C['x']} Abra o terminal nesta pasta, rode `claude`, aceite a pasta e faça /login."))
    uv = shutil.which("uv") or (str(HOME / ".local/bin/uv") if (HOME / ".local/bin/uv").exists() else None)
    print(f"  uv: {uv or 'não encontrado (opcional; instala o graphify e as bibliotecas do Google)'}")
    return ok, claude, uv


# ---------- cidade (Open-Meteo, sem chave) ----------
def buscar_cidade(nome):
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": nome, "count": 5, "language": "pt"})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read()).get("results", [])
    except Exception:  # noqa: BLE001
        return []


def perguntar_cidade():
    titulo("Sua cidade (para o céu real: ascendente, meio do céu, hora e temperatura)")
    while True:
        nome = perguntar("Cidade", "São Paulo")
        rs = buscar_cidade(nome)
        if rs:
            i = escolher("Qual delas", [f"{r['name']}, {r.get('admin1', '')} · {r.get('country', '')} ({r['timezone']})" for r in rs])
            r = rs[i]
            return {"cidade": r["name"], "lat": round(r["latitude"], 2), "lon": round(r["longitude"], 2), "fuso": r["timezone"]}
        print("  Não achei (ou sem internet). Digite à mão.")
        try:
            return {"cidade": nome, "lat": float(perguntar("Latitude (ex.: -23.55)")), "lon": float(perguntar("Longitude (ex.: -46.63)")),
                    "fuso": perguntar("Fuso (ex.: America/Sao_Paulo)", "America/Sao_Paulo")}
        except ValueError:
            print("  Latitude e longitude são números. Vamos de novo.")


# ---------- perguntas ----------
def perguntas():
    cfg = json.loads(json.dumps(EXEMPLO))
    cfg.pop("_leia", None)
    titulo("Quem vai usar o JARVIS")
    cfg["usuario"] = {
        "nome": perguntar("Seu nome (como o JARVIS vai te chamar)", ""),
        "sobre": perguntar("Uma ou duas linhas sobre você e o seu trabalho", ""),
        "tom": perguntar("Tom das respostas", "direto e caloroso"),
        "idioma": perguntar("Idioma", "português do Brasil"),
    }
    cfg["local"] = perguntar_cidade()

    titulo("O cérebro: qual modelo do Claude o JARVIS usa")
    ms = EXEMPLO["cerebro"]["modelos"]
    print("  Conversa: o modelo padrão do chat (dá para trocar a qualquer hora no seletor).")
    p = escolher("Modelo da conversa", [f"{m['nome']} · {m['nota']}" for m in ms], 1)
    print("  Fundo: o que trabalha sozinho (montar o grafo, ler Gmail e Agenda sem a API). Barato é melhor.")
    f = escolher("Modelo do trabalho de fundo", [f"{m['nome']} · {m['nota']}" for m in ms], 2)
    cfg["cerebro"] = {"padrao": ms[p]["id"], "fundo": ms[f]["id"], "modelos": ms}
    if sim("Quer acrescentar outro modelo (id do Claude Code, ex.: um modelo novo)?", False):
        nm, i = perguntar("Nome no seletor"), perguntar("Id do modelo")
        if nm and i:
            ms.append({"nome": nm, "id": i, "nota": "personalizado"})

    titulo("Menu inferior: os centralizadores das estrelas")
    base = varios("Quais botões padrão", [f"{n['nome']} · {n['sobre']}" for n in NICHOS_BASE], range(len(NICHOS_BASE)))
    nichos = [{k: v for k, v in NICHOS_BASE[i].items() if k != "sobre"} for i in base]
    sug = varios("Nichos sugeridos (separam um tipo de arquivo por palavras)", [f"{n['nome']} · {n['sobre']}" for n in NICHOS_SUGERIDOS])
    nichos += [{k: v for k, v in NICHOS_SUGERIDOS[i].items() if k != "sobre"} for i in sug]
    while sim("Criar um nicho seu (ex.: um cliente, um projeto)?", False):
        nm = perguntar("Nome do botão")
        palavras = [w.strip() for w in perguntar("Palavras que aparecem no nome ou na pasta dos arquivos (separadas por vírgula)").split(",") if w.strip()]
        if nm and palavras:
            nichos.append({"id": re.sub(r"\W+", "-", nm.lower()).strip("-"), "nome": nm, "tipo": "*",
                           "padrao": "|".join(re.escape(w) for w in palavras)})
    cfg["nichos"] = nichos or [dict((k, v) for k, v in NICHOS_BASE[0].items() if k != "sobre")]

    cfg["apps"] = []
    while sim("Criar um atalho para um app local no menu (abre no navegador)?", False):
        nm, pasta = perguntar("Nome"), perguntar("Pasta do app")
        cmd, porta = perguntar("Comando que liga o app (ex.: npm run dev)"), perguntar("Porta", "3000")
        if nm and pasta and cmd and porta.isdigit():
            i = re.sub(r"\W+", "-", nm.lower()).strip("-")
            cfg["apps"].append({"id": i, "nome": nm, "pasta": pasta, "comando": cmd.split(), "porta": int(porta)})
            cfg["nichos"].append({"id": i, "nome": nm, "tipo": "*", "padrao": re.escape(nm), "app": i})

    titulo("Fontes: as pastas que viram estrelas (só leitura, nada é copiado)")
    docs = HOME / "Documents"
    pastas = sorted([p for p in docs.iterdir() if p.is_dir() and not p.name.startswith(".")], key=lambda p: p.name.lower()) if docs.exists() else []
    esc = varios("Quais pastas de Documentos indexar", [p.name for p in pastas])
    fontes = [str(pastas[i]) for i in esc]
    while sim("Acrescentar outra pasta (caminho completo)?", False):
        p = os.path.expanduser(perguntar("Caminho"))
        if os.path.isdir(p):
            fontes.append(p)
    bloq = varios("Alguma dessas deve ficar BLOQUEADA (documentos pessoais, contratos)?", [p.name for p in pastas])
    cfg["_fontes"], cfg["_bloqueadas"] = fontes, [str(pastas[i]) for i in bloq]

    titulo("Google (Gmail, Agenda e Drive)")
    print("  Conectores do claude.ai: o chat do JARVIS lê o seu Gmail, Agenda e Drive pela sua conta do Claude.")
    cfg["conectores"] = {"gmail": sim("Liberar leitura do Gmail?"), "agenda": sim("Liberar leitura da Agenda?"), "drive": sim("Liberar leitura do Drive?")}
    print("  API do Google (opcional): cards de Gmail e Agenda sem gastar tokens, anexos, imagens dos e-mails e\n"
          "  conteúdo dos docs do Drive no grafo. Precisa criar uma credencial no Google Cloud (docs/GOOGLE.md).")
    cfg["google_api"] = sim("Usar a API do Google?", False)

    titulo("Grafo de conhecimento (graphify)")
    print("  Transforma notas, skills e conversas num grafo: o JARVIS acha as coisas sem ler arquivos inteiros\n"
          "  (economiza tokens) e o raciocínio aparece como constelações. A primeira extração gasta tokens do modelo de fundo.")
    cfg["graphify"] = sim("Usar o graphify?")
    cfg["porta"] = int(perguntar("Porta do servidor local", str(EXEMPLO.get("porta", 8742))))
    return cfg


# ---------- arquivos gerados ----------
def gerar(cfg, claude, uv):
    titulo("Gerando os arquivos")
    fontes = cfg.pop("_fontes", None)
    bloq = cfg.pop("_bloqueadas", None)
    cfg.pop("_leia", None)
    (RAIZ / "jarvis.config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    print("  jarvis.config.json")

    arq_f = RAIZ / "fontes.json"
    if fontes is None and arq_f.exists():
        f = json.loads(arq_f.read_text())                 # rodar de novo sem perguntas não perde as fontes
    else:
        fontes = fontes or []
        f = {
            "_leia": "Fontes do indexador. O card de diretórios também edita isto (estrela ☆). Caminhos com ~ valem.",
            "notas": ["conhecimento/notas", "conhecimento/memoria"] + fontes,
            "skills": ["~/.claude/skills", "~/.claude/plugins", "conhecimento/skills"],
            "conversas": "~/.claude/projects",
            "artefatos": ["conhecimento/artefatos"] + fontes,
            "drive": [],
            "extensoes_notas": [".md", ".txt"],
            "extensoes_artefatos": [".html", ".pdf", ".png", ".jpg", ".jpeg", ".svg", ".pptx", ".docx", ".xlsx", ".mp4"],
            "ignorar": ["node_modules", ".git", ".venv", "venv", "dist", "build", ".next", "__pycache__", ".claude", "graphify-out", "marketplaces"],
            "bloqueadas": (bloq or []) + [str(RAIZ / "servidor" / "segredos"), str(RAIZ / "servidor" / "cache")],
            "sistema": ["/skills-main/", "/references/", "/synced/", "/\\.claude/projects/[^/]+/memory/",
                        "/(README|AGENTS|LICENSE|SPECS|CLAUDE|CHANGELOG)(\\.md)?$"],
        }
        arq_f.write_text(json.dumps(f, indent=2, ensure_ascii=False) + "\n")
    print("  fontes.json")

    u, loc = cfg["usuario"], cfg["local"]
    nome = u.get("nome") or "você"
    grafo = ("O grafo de conhecimento (ferramentas `mcp__grafo__*`, feito pelo graphify) liga conceitos, notas,\n"
             "skills e conversas. Use nesta ordem e pare assim que tiver o suficiente:\n"
             "1. `query_graph` com a pergunta (orçamento baixo, ~1500 tokens); `get_neighbors`/`shortest_path` para seguir ligações.\n"
             "2. `get_section` para ler só a seção que interessa.\n"
             "3. Read de um arquivo inteiro só se ainda faltar algo; Glob/Grep para o que não está no grafo.\n"
             "Os caminhos do grafo começam em `servidor/cache/corpus/` (cópias de leitura dos originais).") if cfg.get("graphify") else \
            "Procure primeiro (Glob/Grep) e leia só o trecho que importa."
    t = (RAIZ / "config" / "CLAUDE.template.md").read_text()
    for k, v in {"nome": nome, "sobre": u.get("sobre") or "(sem descrição: pergunte e grave em conhecimento/memoria/)",
                 "cidade": loc.get("cidade", ""), "fuso": loc.get("fuso", ""), "idioma": (lambda t: t[:1].upper() + t[1:])(u.get("idioma") or "português do Brasil"),
                 "tom": u.get("tom") or "direto e caloroso", "bloco_grafo": grafo}.items():
        t = t.replace("{{" + k + "}}", v)
    (RAIZ / "CLAUDE.md").write_text(t)
    print("  CLAUDE.md (a personalidade do JARVIS: edite à vontade)")

    G, A, D = "mcp__claude_ai_Gmail__", "mcp__claude_ai_Google_Calendar__", "mcp__claude_ai_Google_Drive__"
    con = cfg.get("conectores", {})
    allow = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", f"Edit(/{RAIZ / 'conhecimento'}/**)"]
    if con.get("gmail"):
        allow += [G + x for x in ("search_threads", "get_thread", "get_message", "list_labels", "list_drafts", "get_draft", "create_draft",
                                   "trash_thread", "trash_message", "label_thread", "unlabel_thread", "label_message", "unlabel_message",
                                   "update_message_labels", "create_label")]
    if con.get("agenda"):
        allow += [A + x for x in ("list_calendars", "list_events", "get_event", "search_events", "suggest_time")]
    if con.get("drive"):
        allow += [D + x for x in ("search_files", "list_recent_files", "get_file_metadata", "read_file_content")]
    if cfg.get("graphify"):
        allow += ["mcp__grafo__" + x for x in ("query_graph", "get_node", "get_section", "get_neighbors", "get_community",
                                               "god_nodes", "graph_stats", "shortest_path")]
    deny = [f"Edit(/{HOME / '.claude/projects'}/**)", f"Read(/{RAIZ / 'servidor/segredos'}/**)", f"Edit(/{RAIZ / 'servidor/segredos'}/**)"]
    deny += [f"Read(/{b}/**)" for b in f.get("bloqueadas", []) if "segredos" not in b and "cache" not in b]
    dirs = [str(HOME / ".claude/projects"), str(HOME / ".claude/skills")] + [os.path.expanduser(p) for p in f["notas"] if not p.startswith("conhecimento")]
    ajustes = {"permissions": {"allow": allow, "deny": deny, "additionalDirectories": sorted(set(dirs))}}
    if cfg.get("graphify"):
        ajustes["enabledMcpjsonServers"] = ["grafo"]
    (RAIZ / ".claude").mkdir(exist_ok=True)
    (RAIZ / ".claude" / "settings.json").write_text(json.dumps(ajustes, indent=2, ensure_ascii=False) + "\n")
    print("  .claude/settings.json (o que o JARVIS pode fazer sem pedir)")

    if cfg.get("graphify"):
        mcp = shutil.which("graphify-mcp") or str(HOME / ".local/bin/graphify-mcp")
        (RAIZ / ".mcp.json").write_text(json.dumps({"mcpServers": {"grafo": {"command": mcp, "args": [
            str(RAIZ / "servidor/cache/grafo/graphify-out/graph.json")], "env": {"GRAPHIFY_QUERY_LOG_DISABLE": "1"}}}}, indent=2) + "\n")
        print("  .mcp.json (o grafo para o JARVIS)")

    tarefas = RAIZ / "conhecimento" / "notas" / "Tarefas.md"
    if not tarefas.exists():
        tarefas.parent.mkdir(parents=True, exist_ok=True)
        tarefas.write_text("# Tarefas\n\nUma tarefa por linha: `- [ ]` aberta, `- [x]` feita. O card de Tarefas mostra.\n\n")
    seg = RAIZ / "servidor" / "segredos"
    seg.mkdir(parents=True, exist_ok=True)
    os.chmod(seg, 0o700)
    print("  servidor/segredos/ (só o seu usuário lê)")

    # dependências opcionais
    if cfg.get("graphify") and not shutil.which("graphify") and not (HOME / ".local/bin/graphify").exists():
        if uv and sim("Instalar o graphify agora (uv tool install \"graphifyy[mcp]\")?"):
            subprocess.run([uv, "tool", "install", "graphifyy[mcp]"])
        else:
            print("  Depois: uv tool install \"graphifyy[mcp]\"  (ou pipx install \"graphifyy[mcp]\")")
    if cfg.get("google_api"):
        venv = RAIZ / "servidor" / ".venv"
        if not (venv / "bin" / "python").exists() and sim("Criar o ambiente com as bibliotecas do Google (servidor/.venv)?"):
            if uv:
                subprocess.run([uv, "venv", str(venv), "--python", "3.12", "-q"])
                subprocess.run([uv, "pip", "install", "-q", "--python", str(venv / "bin/python"), "-r", str(RAIZ / "servidor/requirements-google.txt")])
            else:
                subprocess.run([sys.executable, "-m", "venv", str(venv)])
                subprocess.run([str(venv / "bin/pip"), "install", "-q", "-r", str(RAIZ / "servidor/requirements-google.txt")])
        print(f"  Falta a credencial: siga docs/GOOGLE.md e salve o JSON em {seg / 'google-cliente.json'}.\n"
              "  Depois, no card do Gmail, clique em \"Conectar Google\".")


def pasta_confiavel():
    """O Claude Code só aplica o CLAUDE.md e as permissões numa pasta que já foi aceita uma vez."""
    try:
        d = json.loads((HOME / ".claude.json").read_text())
    except (OSError, ValueError):
        return False
    return bool(d.get("projects", {}).get(str(RAIZ), {}).get("hasTrustDialogAccepted"))


def main():
    ap = argparse.ArgumentParser(description="Setup do JARVIS Astrologicum")
    ap.add_argument("--padrao", action="store_true", help="sem perguntas, com a configuração de exemplo")
    ap.add_argument("--config", help="sem perguntas, com este jarvis.config.json")
    a = ap.parse_args()
    global AUTOMATICO
    AUTOMATICO = bool(a.config or a.padrao)
    print(f"{C['t']}JARVIS Astrologicum · setup{C['x']}")
    ok, claude, uv = verificar()
    if a.config:
        cfg = json.loads(Path(a.config).read_text())
    elif a.padrao:
        cfg = json.loads(json.dumps(EXEMPLO))
    else:
        cfg = perguntas()
    gerar(cfg, claude, uv)
    titulo("Pronto")
    print(f"  Para abrir: dois cliques em \"Abrir Jarvis.command\" (ou ./jarvis.sh) → http://127.0.0.1:{cfg.get('porta', 8742)}")
    if not ok:
        print("  Antes, instale o Claude Code e faça login (veja acima).")
    if not pasta_confiavel():
        print(f"\n  {C['o']}Importante:{C['x']} o Claude Code ainda não confia nesta pasta, e sem isso ignora a personalidade\n"
              f"  (CLAUDE.md) e as permissões. Rode uma vez, aqui:  cd \"{RAIZ}\" && claude\n"
              "  aceite a pasta (e faça /login se pedir) e saia com /exit.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n  Setup interrompido. Nada foi apagado; rode de novo quando quiser.")
