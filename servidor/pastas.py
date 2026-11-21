"""Card de diretórios: lista as pastas das abas Claude, Drive e Mac e marca pastas para indexar.

Só lista nomes (nada é lido). Marcar uma pasta do Drive ou do Mac a acrescenta em fontes.json
(e nas pastas que o JARVIS pode ler); desmarcar tira. Pastas bloqueadas nunca são marcadas.
"""
import glob
import json
import os
from pathlib import Path

import indexador

HOME = Path.home()
FONTES = indexador.RAIZ / "fontes.json"
AJUSTES = indexador.RAIZ / ".claude" / "settings.json"


def _drive():
    achados = sorted(glob.glob(str(HOME / "Library/CloudStorage/GoogleDrive-*/Meu Drive")))
    return Path(achados[0]) if achados else None


def raiz_de(nome):
    return {"drive": _drive(), "mac": HOME}.get(nome)


def _til(p):
    s = str(p)
    return "~" + s[len(str(HOME)):] if s.startswith(str(HOME)) else s


def _cfg():
    return json.loads(FONTES.read_text())


def _bloqueadas(cfg):
    return [os.path.realpath(os.path.expanduser(b)) for b in cfg.get("bloqueadas", [])]


def _marcadas(cfg):
    """Caminhos absolutos marcados: as pastas do Drive e as do Mac (que entram em notas e artefatos)."""
    m = set()
    for lista in ("drive", "notas", "artefatos"):
        for f in cfg.get(lista, []):
            for g in glob.glob(os.path.expanduser(f)) if "*" in f else [os.path.expanduser(f)]:
                m.add(os.path.realpath(g if os.path.isabs(g) else indexador.RAIZ / g))
    return m


def _dentro(p, raiz):
    p, raiz = os.path.realpath(p), os.path.realpath(raiz)
    return p == raiz or p.startswith(raiz + os.sep)


def contar(estrelas, abs_):
    pre = abs_.rstrip("/") + "/"
    return sum(1 for e in estrelas if e["caminho"].startswith(pre) or e.get("projeto") == abs_)


def listar(nome, caminho, estrelas):
    cfg = _cfg()
    if nome == "claude":                       # projetos do Claude Code: um por pasta de trabalho
        projetos = {}
        for e in estrelas:
            if e["tipo"] == "conversa" and e.get("projeto"):
                projetos.setdefault(e["projeto"], 0)
                projetos[e["projeto"]] += 1
        pastas = [{"nome": Path(p).name, "abs": p, "curto": _til(p), "estrelas": contar(estrelas, p),
                   "conversas": n, "entrar": False} for p, n in projetos.items()]
        pastas.sort(key=lambda x: -x["conversas"])
        return {"raiz": "claude", "caminho": "", "titulo": "Projetos do Claude", "pastas": pastas, "podeMarcar": False}

    raiz = raiz_de(nome)
    if not raiz or not raiz.exists():
        return {"raiz": nome, "caminho": "", "titulo": "Drive não encontrado" if nome == "drive" else "—", "pastas": [], "podeMarcar": False}
    alvo = (raiz / caminho).resolve() if caminho else raiz
    if not _dentro(alvo, raiz) or not alvo.is_dir():
        raise ValueError("pasta fora da raiz")
    bloq, marc = _bloqueadas(cfg), _marcadas(cfg)
    pastas = []
    try:
        filhos = sorted((c for c in alvo.iterdir() if c.is_dir() and not c.name.startswith(".")
                         and not (nome == "mac" and c.name == "Library")), key=lambda c: c.name.lower())
    except OSError:
        filhos = []
    for c in filhos[:200]:
        real = os.path.realpath(c)
        bloqueada = any(_dentro(real, b) for b in bloq)
        pastas.append({"nome": c.name, "caminho": str(c.relative_to(raiz)), "abs": real, "curto": _til(c),
                       "estrelas": 0 if bloqueada else contar(estrelas, real), "marcada": real in marc,
                       "herdada": not real in marc and any(_dentro(real, m) for m in marc),
                       "bloqueada": bloqueada, "entrar": True})
    titulo = "Meu Drive" if nome == "drive" else "Mac"
    return {"raiz": nome, "caminho": str(alvo.relative_to(raiz)) if alvo != raiz else "",
            "titulo": titulo + ("" if alvo == raiz else " / " + alvo.name), "pastas": pastas, "podeMarcar": True}


def marcar(nome, caminho, ligar):
    raiz = raiz_de(nome)
    if not raiz:
        raise ValueError("raiz desconhecida")
    alvo = (raiz / caminho).resolve()
    if not caminho or not _dentro(alvo, raiz) or not alvo.is_dir():
        raise ValueError("pasta inválida")
    cfg = _cfg()
    if any(_dentro(alvo, b) for b in _bloqueadas(cfg)):
        raise ValueError("pasta bloqueada")
    til = _til(alvo)
    listas = ["drive"] if nome == "drive" else ["notas", "artefatos"]
    for lista in listas:
        atual = cfg.setdefault(lista, [])
        if ligar and til not in atual:
            atual.append(til)
        if not ligar:
            cfg[lista] = [f for f in atual if os.path.realpath(os.path.expanduser(f)) != str(alvo)]
    FONTES.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    # o JARVIS também precisa poder ler a pasta
    aj = json.loads(AJUSTES.read_text())
    dirs = aj.setdefault("permissions", {}).setdefault("additionalDirectories", [])
    if ligar and str(alvo) not in dirs:
        dirs.append(str(alvo))
    if not ligar and str(alvo) in dirs:
        dirs.remove(str(alvo))
    AJUSTES.write_text(json.dumps(aj, indent=2, ensure_ascii=False) + "\n")
    return {"ok": True, "marcada": ligar, "curto": til}
