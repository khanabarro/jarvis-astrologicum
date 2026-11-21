"""Indexador do JARVIS: percorre as fontes de fontes.json e devolve uma estrela por item.

Só lê metadados (nome, data, tamanho) e, nas conversas, o título e a primeira pergunta.
Nada é copiado. O resultado também vai para servidor/cache/estrelas.json.
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "servidor" / "cache"
HOME = str(Path.home())


def _caminho(p):
    p = os.path.expanduser(p)
    return Path(p if os.path.isabs(p) else RAIZ / p).resolve()


def _id(tipo, chave):
    return tipo[0] + hashlib.sha1(chave.encode()).hexdigest()[:11]


def _curto(p):
    return str(p).replace(HOME, "~")


def _bloqueado(p, bloqueadas):
    s = str(p)
    return any(s == b or s.startswith(b + os.sep) for b in bloqueadas)


def _andar(raiz, exts, ignorar, bloqueadas):
    """Arquivos com as extensões pedidas, pulando pastas ignoradas e bloqueadas."""
    if not raiz.exists() or _bloqueado(raiz, bloqueadas):
        return
    for pasta, subs, arqs in os.walk(raiz):
        subs[:] = [s for s in subs if s not in ignorar and not s.startswith(".") and not _bloqueado(Path(pasta) / s, bloqueadas)]
        for a in arqs:
            if Path(a).suffix.lower() in exts and not a.startswith("."):
                yield Path(pasta) / a


GENERICOS = {"readme", "claude", "index", "notas", "notes", "todo", "main", "untitled", "documento sem título"}


def _titulo(p, nome):
    """Nomes genéricos (README, index.html…) ganham a pasta na frente."""
    return f"{p.parent.name}/{nome}" if p.stem.lower() in GENERICOS else nome


def _frontmatter(texto):
    m = re.match(r"^---\s*\n(.*?)\n---", texto, re.S)
    if not m:
        return {}
    campos = {}
    for linha in m.group(1).splitlines():
        if ":" in linha and not linha.startswith(" "):
            k, v = linha.split(":", 1)
            campos[k.strip()] = v.strip().strip('"\'')
    return campos


def _projeto_de(pasta_proj):
    """'-Users-ana-Documents-Meu-Projeto' -> 'Meu Projeto' (aproximado: o nome real vem do cwd)."""
    return pasta_proj.rsplit("-Documents-", 1)[-1].replace("-", " ")


def _texto_usuario(m):
    c = m.get("message", {}).get("content")
    if isinstance(c, list):
        c = " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str):
        return ""
    c = c.strip()
    return "" if (not c or c.startswith("<") or m.get("isMeta")) else c


def conversa_meta(arq):
    titulo, primeira, cwd, n = None, None, None, 0
    try:
        with open(arq, encoding="utf-8", errors="replace") as f:
            for linha in f:
                if '"custom-title"' in linha or '"type":"user"' in linha or '"type": "user"' in linha:
                    try:
                        m = json.loads(linha)
                    except ValueError:
                        continue
                    if m.get("type") == "custom-title":
                        titulo = m.get("customTitle") or titulo
                    elif m.get("type") == "user":
                        cwd = cwd or m.get("cwd")
                        t = _texto_usuario(m)
                        if t:
                            n += 1
                            primeira = primeira or t
    except OSError:
        return None
    if not n:
        return None
    return {"titulo": titulo or primeira[:70], "resumo": primeira[:200], "cwd": cwd, "mensagens": n}


def conversa_mensagens(arq, limite=60):
    """As mensagens de texto de uma conversa (sem ferramentas), para mostrar no chat."""
    saida = []
    with open(arq, encoding="utf-8", errors="replace") as f:
        for linha in f:
            try:
                m = json.loads(linha)
            except ValueError:
                continue
            if m.get("type") == "user" and not m.get("isSidechain"):
                t = _texto_usuario(m)
                if t:
                    saida.append({"eu": True, "texto": t, "quando": m.get("timestamp")})
            elif m.get("type") == "assistant" and not m.get("isSidechain"):
                partes = [b.get("text", "") for b in m.get("message", {}).get("content", []) if isinstance(b, dict) and b.get("type") == "text"]
                t = "".join(partes).strip()
                if t:
                    if saida and not saida[-1]["eu"]:
                        saida[-1]["texto"] += "\n\n" + t
                    else:
                        saida.append({"eu": False, "texto": t, "quando": m.get("timestamp")})
    return saida[-limite:]


def indexar():
    cfg = json.loads((RAIZ / "fontes.json").read_text())
    ignorar = set(cfg.get("ignorar", []))
    bloqueadas = [str(_caminho(b)) for b in cfg.get("bloqueadas", [])]
    estrelas, vistos = [], set()

    def add(tipo, caminho, titulo, **extra):
        chave = str(caminho)
        if (tipo, chave) in vistos:
            return
        vistos.add((tipo, chave))
        try:
            st = os.stat(caminho)
        except OSError:
            return
        estrelas.append({"id": _id(tipo, chave), "tipo": tipo, "titulo": titulo, "caminho": chave,
                         "curto": _curto(caminho), "modificado": int(st.st_mtime), "tamanho": st.st_size, **extra})

    # notas: .md e .txt (as memórias do Claude também entram)
    exts = set(cfg.get("extensoes_notas", [".md"]))
    for fonte in cfg.get("notas", []):
        raiz = _caminho(fonte)
        for p in _andar(raiz, exts, ignorar, bloqueadas):
            if p.name.upper() in ("SKILL.MD",):
                continue
            add("nota", p, _titulo(p, p.stem), fonte=_curto(raiz))
    for p in Path(HOME, ".claude", "projects").glob("*/memory/*.md"):
        if p.name != "MEMORY.md":
            add("nota", p, p.stem, fonte="memória do Claude · " + _projeto_de(p.parent.parent.name))

    # skills: uma por SKILL.md, sem repetir o mesmo nome (plugins guardam cópias)
    nomes = set()
    for fonte in cfg.get("skills", []):
        raiz = _caminho(fonte)
        for p in _andar(raiz, {".md"}, ignorar - {".claude"}, bloqueadas):
            if p.name != "SKILL.md":
                continue
            try:
                fm = _frontmatter(p.read_text(errors="replace")[:3000])
            except OSError:
                continue
            nome = fm.get("name") or p.parent.name
            if nome in nomes:
                continue
            nomes.add(nome)
            add("skill", p, nome, fonte=_curto(raiz), resumo=fm.get("description", "")[:240])

    # conversas: uma por sessão do Claude Code
    for p in _caminho(cfg.get("conversas", "~/.claude/projects")).glob("*/*.jsonl"):
        meta = conversa_meta(p)
        if meta:
            fonte = Path(meta["cwd"]).name if meta["cwd"] else _projeto_de(p.parent.name)
            add("conversa", p, meta["titulo"], fonte=fonte, sessao=p.stem,
                projeto=meta["cwd"], resumo=meta["resumo"], mensagens=meta["mensagens"])

    # artefatos: arquivos produzidos (html, pdf, imagens, documentos)
    exts = set(cfg.get("extensoes_artefatos", []))
    for fonte in cfg.get("artefatos", []):
        raiz = _caminho(fonte)
        for p in _andar(raiz, exts, ignorar, bloqueadas):
            add("artefato", p, _titulo(p, p.name), fonte=_curto(raiz))

    # Google Drive: só as pastas marcadas. Documentos viram notas; o resto, artefatos
    import glob as _glob
    docs = {".gdoc", ".gsheet", ".gslides", ".md", ".txt", ".docx"}
    for fonte in cfg.get("drive", []):
        for raiz in _glob.glob(os.path.expanduser(fonte)):
            raiz = Path(raiz)
            for p in _andar(raiz, docs | exts | {".gform", ".gdraw"}, ignorar, bloqueadas):
                tipo = "nota" if p.suffix.lower() in docs else "artefato"
                add(tipo, p, _titulo(p, p.stem if tipo == "nota" else p.name), fonte="Drive · " + raiz.name, drive=True)

    # arquivos de sistema: ficam no índice e no grafo, mas o cluster não mostra
    padroes = [re.compile(x) for x in cfg.get("sistema", [])]
    for e in estrelas:
        if e["tipo"] in ("nota", "artefato") and any(r.search(e["caminho"]) for r in padroes):
            e["sistema"] = True

    estrelas.sort(key=lambda e: -e["modificado"])
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "estrelas.json").write_text(json.dumps({"gerado": int(time.time()), "estrelas": estrelas}, ensure_ascii=False))
    return estrelas


if __name__ == "__main__":
    t = time.time()
    e = indexar()
    from collections import Counter
    print(Counter(x["tipo"] for x in e), f"{time.time() - t:.2f}s")
