#!/usr/bin/env python3
"""Servidor MCP mínimo (stdio) que responde aos pedidos de permissão do Claude Code.

O servidor do JARVIS liga o Claude Code com `--permission-prompt-tool mcp__jarvis__autorizar`.
Quando o JARVIS tenta algo que não está liberado nas permissões, o Claude Code chama esta
ferramenta; ela repassa o pedido ao servidor do JARVIS (que mostra um cartão no chat) e espera
o usuário autorizar ou recusar. Sem resposta em 10 min, recusa.

Só Python padrão. A conversa vem da variável JARVIS_CONVERSA.
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get("JARVIS_URL", "http://127.0.0.1:8742") + "/api/autorizacao/pedido"
CONVERSA = os.environ.get("JARVIS_CONVERSA", "")
NOME = os.environ.get("JARVIS_NOME", "O usuário")

FERRAMENTA = {
    "name": "autorizar",
    "description": "Pede ao usuário, no chat do JARVIS, autorização para uma ação.",
    "inputSchema": {"type": "object", "properties": {
        "tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"]},
}


def perguntar(nome, entrada):
    corpo = json.dumps({"conversa": CONVERSA, "ferramenta": nome, "entrada": entrada}).encode()
    req = urllib.request.Request(URL, data=corpo, method="POST",
                                 headers={"Content-Type": "application/json", "X-Jarvis": "1"})
    try:
        with urllib.request.urlopen(req, timeout=660) as r:
            d = json.loads(r.read())
    except Exception as e:  # noqa: BLE001 — sem resposta, a ação não acontece
        return {"behavior": "deny", "message": f"Sem autorização (o pedido não chegou ao usuário: {e})."}
    if d.get("permitir"):
        return {"behavior": "allow", "updatedInput": entrada}
    return {"behavior": "deny", "message": d.get("motivo") or f"{NOME} recusou esta ação. Não tente de novo por outro caminho; pergunte o que ele prefere."}


def responder(i, resultado=None, erro=None):
    msg = {"jsonrpc": "2.0", "id": i}
    if erro:
        msg["error"] = erro
    else:
        msg["result"] = resultado
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


for linha in sys.stdin:
    try:
        m = json.loads(linha)
    except ValueError:
        continue
    metodo, i = m.get("method"), m.get("id")
    if metodo == "initialize":
        responder(i, {"protocolVersion": m.get("params", {}).get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "jarvis", "version": "1"}})
    elif metodo == "tools/list":
        responder(i, {"tools": [FERRAMENTA]})
    elif metodo == "tools/call":
        args = m.get("params", {}).get("arguments", {})
        r = perguntar(args.get("tool_name", "?"), args.get("input") or {})
        responder(i, {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False)}]})
    elif metodo == "ping":
        responder(i, {})
    elif i is not None:
        responder(i, erro={"code": -32601, "message": "método desconhecido"})
