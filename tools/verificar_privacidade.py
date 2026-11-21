#!/usr/bin/env python3
"""Procura dados pessoais e segredos nos arquivos que iriam para o Git. Rode antes de publicar.

    python3 tools/verificar_privacidade.py

Olha só o que o Git publicaria (respeita o .gitignore). Acusa e-mails, caminhos da sua pasta
pessoal, chaves e tokens conhecidos, o client_id do Google e o seu nome/cidade do jarvis.config.json.
Sai com código 1 se achar algo.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PADROES = {
    "e-mail": r"[\w.+-]+@[\w-]+\.[\w.-]+",
    "pasta pessoal": r"/(Users|home)/(?!ana\b|voce\b|usuario\b)[A-Za-z0-9._-]+",
    "chave do Google": r"AIza[0-9A-Za-z_-]{30,}",
    "token do Google": r"ya29\.[0-9A-Za-z_-]{20,}",
    "client_id do Google": r"\d{6,}-[0-9a-z]{20,}\.apps\.googleusercontent\.com",
    "segredo OAuth": r"GOCSPX-[0-9A-Za-z_-]{10,}|\"client_secret\"\s*:\s*\"[^\"]{8,}",
    "refresh token": r"\"refresh_token\"\s*:\s*\"[^\"]{8,}",
    "chave da Anthropic": r"sk-ant-[0-9A-Za-z_-]{10,}",
    "chave privada": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}
PERMITIDOS = {"noreply@anthropic.com", "exemplo@exemplo.com"}


def arquivos():
    try:
        r = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=RAIZ,
                           capture_output=True, text=True, check=True)
        return [RAIZ / l for l in r.stdout.splitlines() if l]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # sem Git: aplica o .gitignore do projeto de forma simples
        ignora = ["jarvis.config.json", "fontes.json", "CLAUDE.md", ".claude", ".mcp.json", "servidor/segredos",
                  "servidor/cache", "servidor/.venv", "__pycache__", ".git"]
        out = []
        for p in RAIZ.rglob("*"):
            rel = p.relative_to(RAIZ).as_posix()
            if p.is_file() and not any(rel == i or rel.startswith(i + "/") or f"/{i}/" in f"/{rel}" for i in ignora):
                if rel.startswith("conhecimento/") and p.name != ".gitkeep":
                    continue
                out.append(p)
        return out


def main():
    padroes = dict(PADROES)
    cfg = RAIZ / "jarvis.config.json"
    if cfg.exists():                                   # o seu nome e a sua cidade não podem aparecer no código
        c = json.loads(cfg.read_text())
        for rotulo, valor in (("seu nome", c.get("usuario", {}).get("nome")), ("sua cidade", c.get("local", {}).get("cidade"))):
            if valor and len(valor) >= 3 and valor not in ("São Paulo",):
                padroes[rotulo] = re.escape(valor)
    achados = 0
    for arq in arquivos():
        if arq.suffix in (".png", ".jpg", ".mp4", ".zip") or arq.name == Path(__file__).name:
            continue
        try:
            texto = arq.read_text(errors="ignore")
        except OSError:
            continue
        for n, linha in enumerate(texto.splitlines(), 1):
            for rotulo, p in padroes.items():
                for m in re.finditer(p, linha, re.I if rotulo.startswith("s") else 0):
                    if m.group(0) in PERMITIDOS:
                        continue
                    achados += 1
                    print(f"  {arq.relative_to(RAIZ)}:{n}  {rotulo}: {m.group(0)[:60]}")
    print(f"\n{achados} achado(s) em {len(arquivos())} arquivo(s) que iriam para o Git." if achados else
          f"Nada pessoal encontrado em {len(arquivos())} arquivo(s) que iriam para o Git.")
    sys.exit(1 if achados else 0)


if __name__ == "__main__":
    main()
