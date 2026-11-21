"""Configuração do JARVIS: um arquivo só, `jarvis.config.json` na raiz (gerado pelo setup.py).

Sem ele, vale `config/jarvis.config.example.json`, para a página abrir mesmo antes do setup.
Nada pessoal fica no código: nome, cidade, modelos, nichos e atalhos vêm daqui.
"""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = RAIZ / "jarvis.config.json"
EXEMPLO = RAIZ / "config" / "jarvis.config.example.json"


def _ler():
    for p in (ARQUIVO, EXEMPLO):
        if p.exists():
            return json.loads(p.read_text())
    raise FileNotFoundError("rode `python3 setup.py` para criar o jarvis.config.json")


CFG = _ler()
USUARIO = CFG.get("usuario", {})
NOME = USUARIO.get("nome") or "você"
LOCAL = CFG.get("local", {})
FUSO = LOCAL.get("fuso") or "America/Sao_Paulo"
CEREBRO = CFG.get("cerebro", {})
MODELOS = {m["nome"]: m["id"] for m in CEREBRO.get("modelos", [])} or {"Sonnet": "sonnet"}
PADRAO = next((m["nome"] for m in CEREBRO.get("modelos", []) if m["id"] == CEREBRO.get("padrao")), next(iter(MODELOS)))
FUNDO = CEREBRO.get("fundo") or "haiku"           # trabalho de fundo: painel, grafo, ações do Gmail sem API
PORTA = int(CFG.get("porta", 8742))
APPS = {a["id"]: a for a in CFG.get("apps", [])}


def publico():
    """O que a página precisa saber (nada de caminhos nem segredos)."""
    return {
        "nome": NOME,
        "local": {k: LOCAL.get(k) for k in ("cidade", "lat", "lon", "fuso")},
        "modelos": CEREBRO.get("modelos", []),
        "padrao": PADRAO,
        "nichos": CFG.get("nichos", []),
        "apps": [{"id": a["id"], "nome": a["nome"], "padrao": a.get("padrao", "")} for a in CFG.get("apps", [])],
    }
