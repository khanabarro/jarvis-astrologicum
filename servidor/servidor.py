#!/usr/bin/env python3
"""Servidor local do JARVIS Astrologicum.

Serve o frontend e faz a ponte entre o chat da página e o Claude Code, que roda sem
interface (claude -p) a partir da pasta jarvis/. Só Python padrão, sem dependências.

  python3 servidor/servidor.py         -> http://127.0.0.1:8742
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grafo  # noqa: E402
import indexador  # noqa: E402
import painel  # noqa: E402
import pastas  # noqa: E402

import config  # noqa: E402
PORTA = int(os.environ.get("JARVIS_PORTA", config.PORTA))
RAIZ = Path(__file__).resolve().parent.parent          # jarvis/
FRONT = RAIZ / "frontend"
HOSTS_OK = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}

MODELOS = config.MODELOS                                # nome no seletor -> id do modelo (o "cérebro", no setup)
PADRAO = config.PADRAO
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
         ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
         ".jpg": "image/jpeg", ".woff2": "font/woff2"}


def achar_claude():
    """O Claude Code instalado; na falta dele, a cópia que vem dentro do app Desktop."""
    for c in (os.environ.get("JARVIS_CLAUDE"), shutil.which("claude"),
              os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.claude/local/claude")):
        if c and os.access(c, os.X_OK):
            return c
    app = sorted(glob.glob(os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")))
    return app[-1] if app else None


CLAUDE = achar_claude()
_indice = {"t": 0, "lista": [], "ids": {}}


def estrelas(forcar=False):
    """O índice das estrelas, refeito no máximo a cada 30 s (é só leitura de metadados)."""
    with trava:
        if forcar or time.time() - _indice["t"] > 30:
            lista = indexador.indexar()
            _indice.update(t=time.time(), lista=lista, ids={e["id"]: e for e in lista}, caminhos={})
        return _indice["lista"]


def caminhos():
    """caminho completo -> id da estrela (para reconhecer um Read de arquivo indexado)."""
    estrelas()
    if not _indice.get("caminhos"):
        _indice["caminhos"] = {e["caminho"]: e["id"] for e in _indice["lista"]}
    return _indice["caminhos"]


def por_id(i):
    estrelas()
    return _indice["ids"].get(i)
processos = {}                                          # id da conversa na página -> Popen em curso
filas = {}                                              # id da conversa -> fila de eventos (para os cartões de autorização)
pendentes = {}                                          # id do pedido -> {conversa, ok (Event), permitir}


def descrever(ferramenta, e):
    """Texto do cartão de autorização: o quê, onde e o que muda."""
    h = str(Path.home())
    curto = lambda p: str(p or "").replace(h, "~")
    d = {"ferramenta": ferramenta, "titulo": ferramenta, "onde": "", "detalhe": "", "antes": "", "depois": ""}
    if ferramenta in ("Edit", "MultiEdit"):
        d.update(titulo="Editar um arquivo", onde=curto(e.get("file_path")),
                 antes=str(e.get("old_string", ""))[:1500], depois=str(e.get("new_string", ""))[:1500])
        if ferramenta == "MultiEdit":
            d.update(antes="\n…\n".join(x.get("old_string", "") for x in e.get("edits", []))[:1500],
                     depois="\n…\n".join(x.get("new_string", "") for x in e.get("edits", []))[:1500])
    elif ferramenta == "Write":
        d.update(titulo="Criar ou substituir um arquivo", onde=curto(e.get("file_path")), depois=str(e.get("content", ""))[:1500])
    elif ferramenta == "Bash":
        d.update(titulo="Rodar um comando no Mac", detalhe=str(e.get("command", ""))[:800], onde=e.get("description", ""))
    elif "Gmail" in ferramenta:
        acao = ferramenta.rsplit("__", 1)[-1]
        nomes = {"send_message": "Enviar um e-mail", "reply": "Responder um e-mail", "forward": "Encaminhar um e-mail",
                 "create_draft": "Criar um rascunho", "delete_draft": "Apagar um rascunho", "delete_label": "Apagar uma label"}
        d.update(titulo=nomes.get(acao, "Gmail: " + acao), onde=", ".join(str(x) for x in (e.get("to") or e.get("recipients") or []) if x) or str(e.get("thread_id", "")),
                 detalhe=(str(e.get("subject", "")) + "\n\n" + str(e.get("body", e.get("text", "")))).strip()[:1500])
    elif "Calendar" in ferramenta:
        acao = ferramenta.rsplit("__", 1)[-1]
        nomes = {"create_event": "Criar um compromisso", "update_event": "Mudar um compromisso",
                 "delete_event": "Apagar um compromisso", "respond_to_event": "Responder a um convite"}
        d.update(titulo=nomes.get(acao, "Agenda: " + acao), onde=str(e.get("summary") or e.get("event_id") or ""),
                 detalhe=json.dumps({k: v for k, v in e.items() if k in ("start", "end", "summary", "location", "attendees", "response")}, ensure_ascii=False)[:1200])
    else:
        d.update(titulo=ferramenta.replace("mcp__claude_ai_", "").replace("__", ": "), detalhe=json.dumps(e, ensure_ascii=False)[:1200])
    return d
trava = threading.Lock()


def alvo_ferramenta(nome, entrada):
    """Um resumo curto do que a ferramenta está tocando, para mostrar no chat."""
    if nome == "ToolSearch":
        return ""
    for k in ("skill", "question", "label", "node", "file_path", "path", "pattern", "query", "url", "command", "description"):
        v = entrada.get(k)
        if isinstance(v, str) and v:
            return v.replace(str(Path.home()), "~")[:120]
    return ""


class Handler(BaseHTTPRequestHandler):
    server_version = "Jarvis/1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[jarvis] " + (fmt % args) + "\n")

    # só aceita pedidos desta máquina e desta página (protege contra outros sites no navegador)
    def confiavel(self, api=False):
        if self.headers.get("Host") not in HOSTS_OK:
            return False
        origem = self.headers.get("Origin")
        if origem and origem.split("//", 1)[-1] not in HOSTS_OK:
            return False
        return not api or self.headers.get("X-Jarvis") == "1"

    def responder(self, codigo, corpo, tipo="application/json"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if not self.confiavel():
            return self.responder(403, {"erro": "origem recusada"})
        caminho = self.path.split("?", 1)[0]
        if caminho == "/api/config":
            return self.responder(200, config.publico())
        if caminho == "/api/saude":
            return self.responder(200, {"ok": True, "claude": CLAUDE, "modelos": list(MODELOS), "padrao": PADRAO})
        if caminho == "/api/estrelas":
            return self.responder(200, {"estrelas": estrelas(forcar="novo=1" in self.path)})
        if caminho == "/api/pastas":
            q = parse_qs(urlsplit(self.path).query)
            try:
                return self.responder(200, pastas.listar(q.get("raiz", ["claude"])[0], q.get("caminho", [""])[0], estrelas()))
            except ValueError as e:
                return self.responder(400, {"erro": str(e)})
        if caminho == "/api/painel":
            g = painel.google_api.estado() if painel.google_api else {"conectado": False, "cliente": False, "sem_bibliotecas": True}
            return self.responder(200, {**painel.ler(), "atualizando": _painel_rodando.locked(), "google": g})
        if caminho == "/api/gmail/html":               # o e-mail original, isolado (sem script; imagens externas só com externas=1)
            q = parse_qs(urlsplit(self.path).query)
            msg, ext = q.get("msg", [""])[0], q.get("externas", ["0"])[0] == "1"
            if not painel.google_ok() or not msg.isalnum():
                return self.responder(400, {"erro": "e-mail indisponível (conecte o Google)"})
            try:
                dados = painel.google_api.html_original(msg, ext).encode("utf-8")
            except Exception as e:  # noqa: BLE001
                return self.responder(502, {"erro": str(e)[:200]})
            img = "data: https: http:" if ext else "data:"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", f"default-src 'none'; img-src {img}; style-src 'unsafe-inline'; font-src data:; "
                                                        "sandbox allow-popups allow-popups-to-escape-sandbox")
            self.end_headers()
            self.wfile.write(dados)
            return
        if caminho == "/api/gmail/anexo":              # abre um anexo no navegador (PDF e imagens aparecem direto)
            q = parse_qs(urlsplit(self.path).query)
            msg, att = q.get("msg", [""])[0], q.get("att", [""])[0]
            nome = os.path.basename(q.get("nome", ["anexo"])[0]) or "anexo"
            if not painel.google_ok() or not msg.isalnum() or not all(c.isalnum() or c in "-_" for c in att):
                return self.responder(400, {"erro": "anexo indisponível (conecte o Google)"})
            try:
                dados = painel.google_api.anexo(msg, att)
            except Exception as e:  # noqa: BLE001
                return self.responder(502, {"erro": str(e)[:200]})
            import mimetypes
            from urllib.parse import quote
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(nome)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(dados)))
            self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(nome)}")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "sandbox")      # HTML de anexo não roda script nem toca no JARVIS
            self.end_headers()
            self.wfile.write(dados)
            return
        if caminho == "/api/tarefas":
            return self.responder(200, {"tarefas": ler_tarefas()})
        if caminho == "/api/grafo":
            return self.responder(200, grafo.resumo())
        if caminho == "/api/conversa":
            e = por_id(parse_qs(urlsplit(self.path).query).get("id", [""])[0])
            if not e or e["tipo"] != "conversa":
                return self.responder(404, {"erro": "conversa não encontrada"})
            return self.responder(200, {"titulo": e["titulo"], "sessao": e["sessao"], "caminho": e["caminho"],
                                        "doJarvis": e.get("projeto") == str(RAIZ),
                                        "mensagens": indexador.conversa_mensagens(e["caminho"])})
        arq = (FRONT / (caminho.lstrip("/") or "index.html")).resolve()
        if not str(arq).startswith(str(FRONT)) or not arq.is_file():
            return self.responder(404, {"erro": "não encontrado"})
        dados = arq.read_bytes()
        if arq.name == "index.html":               # a configuração entra na página antes do script (nome, cidade, menu, modelos)
            dados = dados.replace(b"/*JARVIS_CONFIG*/", b"window.JARVIS = " + json.dumps(config.publico(), ensure_ascii=False).encode() + b";")
        self.responder(200, dados, TIPOS.get(arq.suffix, "application/octet-stream"))

    def do_POST(self):
        if not self.confiavel(api=True):
            return self.responder(403, {"erro": "origem recusada"})
        try:
            pedido = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.responder(400, {"erro": "json inválido"})
        if self.path == "/api/chat":
            return self.chat(pedido)
        if self.path == "/api/autorizacao/pedido":
            return self.autorizacao_pedido(pedido)
        if self.path == "/api/autorizacao":           # a decisão do usuário no cartão
            pd = pendentes.get(str(pedido.get("id")))
            if not pd:
                return self.responder(404, {"erro": "pedido não encontrado (já respondido ou expirado)"})
            pd["permitir"] = bool(pedido.get("permitir"))
            pd["ok"].set()
            return self.responder(200, {"ok": True})
        if self.path == "/api/abrir":                  # abre no Mac só o que está no índice (nunca um caminho qualquer)
            e = por_id(pedido.get("id", ""))
            if not e:
                return self.responder(404, {"erro": "item não encontrado"})
            alvo = e["caminho"] if e["tipo"] != "skill" else str(Path(e["caminho"]).parent)
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", alvo] if pedido.get("revelar") else ["open", alvo])
            else:                                      # Linux
                subprocess.Popen(["xdg-open", os.path.dirname(alvo) if pedido.get("revelar") else alvo])
            return self.responder(200, {"ok": True})
        if self.path == "/api/marcar":                 # marcar/desmarcar uma pasta do Drive ou do Mac para indexar
            try:
                r = pastas.marcar(pedido.get("raiz"), pedido.get("caminho") or "", bool(pedido.get("marcar")))
            except ValueError as e:
                return self.responder(400, {"erro": str(e)})
            estrelas(forcar=True)
            return self.responder(200, r)
        if self.path == "/api/app":                    # atalhos do menu: liga o app local (se preciso) e devolve o endereço
            app = APPS.get(pedido.get("app"))
            if not app:
                return self.responder(404, {"erro": "app desconhecido"})
            return self.responder(200, ligar_app(app))
        if self.path == "/api/painel":                 # pede uma atualização agora (em segundo plano)
            threading.Thread(target=atualizar_painel, daemon=True).start()
            return self.responder(202, {"ok": True})
        if self.path == "/api/google/conectar":        # abre o navegador para autorizar o Google (uma vez)
            if not painel.google_api:
                return self.responder(503, {"erro": "rode o JARVIS pelo Abrir Jarvis.command (ambiente com as bibliotecas do Google)"})
            return self.responder(200, painel.google_api.conectar())
        if self.path == "/api/gmail":                  # janela do e-mail: ler, labels, responder, encaminhar, arquivar, lixeira
            if not CLAUDE:
                return self.responder(503, {"erro": "Claude Code não encontrado"})
            try:
                return self.responder(200, painel.gmail(CLAUDE, pedido))
            except Exception as e:  # noqa: BLE001 — erro da API ou do Haiku vira mensagem na janela
                return self.responder(400, {"erro": str(e)[:300]})
        if self.path == "/api/tarefas":                # marca/desmarca a tarefa da linha i
            try:
                return self.responder(200, {"tarefas": marcar_tarefa(int(pedido.get("i", -1)), bool(pedido.get("feita")))})
            except (ValueError, IndexError) as e:
                return self.responder(400, {"erro": str(e)})
        if self.path == "/api/parar":
            with trava:
                p = processos.get(pedido.get("conversa"))
            if p and p.poll() is None:
                p.terminate()
            return self.responder(200, {"ok": True})
        self.responder(404, {"erro": "rota desconhecida"})

    def evento(self, dados):
        self.wfile.write(b"data: " + json.dumps(dados, ensure_ascii=False).encode() + b"\n\n")
        self.wfile.flush()

    def chat(self, pedido):
        texto = (pedido.get("texto") or "").strip()
        conversa = str(pedido.get("conversa") or "")
        if not texto:
            return self.responder(400, {"erro": "mensagem vazia"})
        if not CLAUDE:
            return self.responder(503, {"erro": "Claude Code não encontrado"})
        cwd = RAIZ
        args = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                "--model", MODELOS.get(pedido.get("modelo"), MODELOS[PADRAO])]
        sessao = pedido.get("sessao")
        outra = pedido.get("outra")               # responder numa conversa de outro projeto (fase 6)
        if outra:
            e = por_id(outra)
            if not e or e["tipo"] != "conversa" or not e.get("projeto") or not os.path.isdir(e["projeto"]):
                return self.responder(400, {"erro": "conversa de outro projeto não encontrada"})
            cwd = e["projeto"]
            if not (sessao and all(c.isalnum() or c == "-" for c in sessao)):
                sessao = e["sessao"]               # a primeira mensagem retoma a conversa; as seguintes, a continuação dela
        if sessao and all(c.isalnum() or c == "-" for c in sessao):
            args += ["--resume", sessao]
        else:
            ref = por_id(pedido.get("referencia") or "")      # uma estrela aberta no cluster vira contexto da conversa nova
            if ref:
                texto = (f"[Contexto: {config.NOME} está olhando {ref['tipo']} \"{ref['titulo']}\" em {ref['curto']}. "
                         f"Leia só o que precisar.]\n\n{texto}")
        # o que não está liberado nas permissões vira um cartão de autorização no chat
        mcp = {"mcpServers": {"jarvis": {"command": sys.executable, "args": [str(RAIZ / "servidor" / "autorizador.py")],
                                         "env": {"JARVIS_CONVERSA": conversa, "JARVIS_URL": f"http://127.0.0.1:{PORTA}", "JARVIS_NOME": config.NOME}}}}
        args += ["--mcp-config", json.dumps(mcp), "--permission-prompt-tool", "mcp__jarvis__autorizar"]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        fila = queue.Queue()
        p = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, bufsize=1)
        with trava:
            processos[conversa] = p
            filas[conversa] = fila
        erros = []
        def ler_saida():
            for l in p.stdout:
                fila.put(("linha", l))
            fila.put(("eof", None))
        threading.Thread(target=ler_saida, daemon=True).start()
        threading.Thread(target=lambda: erros.extend(p.stderr), daemon=True).start()
        teve_texto = False
        try:
            p.stdin.write(texto)
            p.stdin.close()
            while True:
                tipo, linha = fila.get()
                if tipo == "eof":
                    break
                if tipo == "evento":                   # pedido de autorização vindo do autorizador
                    self.evento(linha)
                    continue
                try:
                    m = json.loads(linha)
                except ValueError:
                    continue
                t = m.get("type")
                if t == "system" and m.get("subtype") == "init":
                    self.evento({"tipo": "sessao", "id": m.get("session_id"), "outra": bool(outra)})
                elif t == "stream_event":
                    ev = m.get("event", {})
                    if ev.get("type") == "content_block_start" and ev.get("content_block", {}).get("type") == "text" and teve_texto:
                        self.evento({"tipo": "texto", "t": "\n\n"})
                    elif ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                        teve_texto = True
                        self.evento({"tipo": "texto", "t": ev["delta"]["text"]})
                elif t == "assistant":
                    for bloco in m.get("message", {}).get("content", []):
                        if bloco.get("type") == "tool_use":
                            entrada = bloco.get("input") or {}
                            self.evento({"tipo": "ferramenta", "nome": bloco.get("name"),
                                         "alvo": alvo_ferramenta(bloco.get("name"), entrada)})
                            # o que a ferramenta vai tocar já acende (ex.: Read de uma nota)
                            es, cs = grafo.tocados(json.dumps(entrada, ensure_ascii=False), caminhos())
                            if es or cs:
                                self.evento({"tipo": "tocou", "estrelas": es, "conceitos": cs})
                elif t == "user":
                    # resultados das ferramentas: estrelas e conceitos que apareceram no caminho
                    for bloco in m.get("message", {}).get("content", []) if isinstance(m.get("message", {}).get("content"), list) else []:
                        if bloco.get("type") == "tool_result":
                            c = bloco.get("content")
                            txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                            es, cs = grafo.tocados(txt[:200000], caminhos())
                            if es or cs:
                                self.evento({"tipo": "tocou", "estrelas": es, "conceitos": cs})
                elif t == "result":
                    if m.get("is_error"):
                        self.evento({"tipo": "erro", "msg": m.get("result") or "erro no Claude Code"})
                    self.evento({"tipo": "fim", "sessao": m.get("session_id"), "custo": m.get("total_cost_usd"),
                                 "ms": m.get("duration_ms"), "turnos": m.get("num_turns"),
                                 "negadas": [d.get("tool_name") for d in m.get("permission_denials") or []]})
            p.wait()
            if "has not been trusted" in "".join(erros):
                self.evento({"tipo": "erro", "msg": "O Claude Code ainda não confia na pasta do JARVIS, então ignorou a personalidade e "
                                                    "as permissões. Rode `claude` uma vez na pasta, aceite e saia com /exit."})
            if p.returncode not in (0, None) and p.returncode > 0:
                erro = "".join(erros).strip()[-400:]
                if erro:
                    self.evento({"tipo": "erro", "msg": erro})
        except (BrokenPipeError, ConnectionResetError):
            p.terminate()                               # a página fechou ou parou a resposta
        finally:
            with trava:
                processos.pop(conversa, None)
                filas.pop(conversa, None)
            for i, pd in list(pendentes.items()):       # pedidos sem resposta desta conversa: recusados
                if pd["conversa"] == conversa:
                    pd["permitir"] = False
                    pd["ok"].set()

    def autorizacao_pedido(self, pedido):
        """Vem do autorizador.py: mostra o cartão na conversa e espera a decisão do usuário (até 10 min)."""
        conversa = str(pedido.get("conversa") or "")
        with trava:
            fila = filas.get(conversa)
        if not fila:
            return self.responder(200, {"permitir": False, "motivo": "Não há ninguém olhando esta conversa para autorizar."})
        pid = uuid.uuid4().hex[:12]
        pd = {"conversa": conversa, "ok": threading.Event(), "permitir": False}
        pendentes[pid] = pd
        fila.put(("evento", {"tipo": "autorizacao", "id": pid, **descrever(pedido.get("ferramenta", "?"), pedido.get("entrada") or {})}))
        pd["ok"].wait(600)
        pendentes.pop(pid, None)
        return self.responder(200, {"permitir": pd["permitir"],
                                    "motivo": None if pd["permitir"] else f"{config.NOME} recusou (ou não respondeu a tempo)."})


APPS = {i: {**a, "pasta": os.path.expanduser(a["pasta"]), "comando": [os.path.expanduser(c) for c in a["comando"]]}
        for i, a in config.APPS.items()}     # atalhos do menu (setup.py): liga o app local e abre no navegador

def _porta_aberta(porta):
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", porta)) == 0


def ligar_app(app):
    url = f"http://localhost:{app['porta']}"
    if _porta_aberta(app["porta"]):
        return {"url": url, "ligado": "já estava"}
    if not os.path.isdir(app["pasta"]):
        return {"erro": f"pasta não encontrada: {app['pasta']}"}
    log = open(RAIZ / "servidor" / "cache" / f"app-{app['porta']}.log", "a")
    subprocess.Popen(app["comando"], cwd=app["pasta"], stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):                                # até ~10 s para subir
        time.sleep(0.25)
        if _porta_aberta(app["porta"]):
            return {"url": url, "ligado": "agora"}
    return {"url": url, "ligado": "demorando", "aviso": "o app ainda está subindo; tente de novo em alguns segundos"}


_painel_rodando = threading.Lock()


def atualizar_painel():
    """Gmail e Agenda pelo Haiku (só leitura). Um por vez; erro fica no log e o cache anterior continua."""
    if not CLAUDE or not _painel_rodando.acquire(blocking=False):
        return
    try:
        d = painel.atualizar(CLAUDE)
        print(f"[jarvis] painel: {len(d.get('emails', []))} e-mails, {len(d.get('agenda', []))} eventos, US$ {d.get('custo')}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[jarvis] painel falhou: {e}", flush=True)
    finally:
        _painel_rodando.release()


TAREFAS = RAIZ / "conhecimento" / "notas" / "Tarefas.md"
_RE_TAREFA = __import__("re").compile(r"^\s*[-*] \[( |x|X)\] (.+)$")


def ler_tarefas():
    try:
        linhas = TAREFAS.read_text().splitlines()
    except OSError:
        return []
    out = []
    for n, l in enumerate(linhas):
        m = _RE_TAREFA.match(l)
        if m:
            out.append({"linha": n, "texto": m.group(2).strip(), "feita": m.group(1) != " "})
    return out


def marcar_tarefa(i, feita):
    linhas = TAREFAS.read_text().splitlines()
    t = ler_tarefas()[i]
    l = linhas[t["linha"]]
    linhas[t["linha"]] = l.replace("[ ]", "[x]", 1) if feita else l.replace("[x]", "[ ]", 1).replace("[X]", "[ ]", 1)
    TAREFAS.write_text("\n".join(linhas) + "\n")
    return ler_tarefas()


GRAPHIFY = shutil.which("graphify") or os.path.expanduser("~/.local/bin/graphify")
_grafo_rodando = threading.Lock()


def atualizar_grafo():
    """Remonta o corpus e roda o graphify só no que mudou (Haiku, pela assinatura). Um por vez."""
    if not os.access(GRAPHIFY, os.X_OK) or not _grafo_rodando.acquire(blocking=False):
        return
    try:
        import corpus
        corpus.montar(estrelas(forcar=True))
        amb = dict(os.environ, PATH=os.path.dirname(CLAUDE or "") + ":" + os.environ.get("PATH", ""),
                   GRAPHIFY_CLAUDE_CLI_MODEL=config.FUNDO, GRAPHIFY_QUERY_LOG_DISABLE="1")
        cache = RAIZ / "servidor" / "cache"
        log = open(cache / "grafo.log", "a")
        r = subprocess.run([GRAPHIFY, "extract", "corpus", "--backend", "claude-cli", "--out", "grafo",
                            "--token-budget", "20000", "--allow-partial"], cwd=cache, env=amb, stdout=log, stderr=log)
        if r.returncode == 0:
            subprocess.run([GRAPHIFY, "cluster-only", "grafo", "--backend=claude-cli", "--no-viz"],
                           cwd=cache, env=amb, stdout=log, stderr=log)
        print(f"[jarvis] grafo atualizado (código {r.returncode})", flush=True)
    except Exception as e:  # noqa: BLE001 — a atualização de fundo nunca derruba o servidor
        print(f"[jarvis] falha ao atualizar o grafo: {e}", flush=True)
    finally:
        _grafo_rodando.release()


def agendar_grafo(intervalo=6 * 3600, inicio=90):
    """Ao ligar (depois de 90 s) e a cada 6 h. Arquivos sem mudança saem do cache, sem custo."""
    def laco():
        time.sleep(inicio)
        while True:
            atualizar_grafo()
            time.sleep(intervalo)
    threading.Thread(target=laco, daemon=True).start()


def main():
    if not CLAUDE:
        print("[jarvis] aviso: Claude Code não encontrado. Instale com o instalador oficial.", file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    if os.environ.get("JARVIS_SEM_GRAFO") != "1":
        agendar_grafo()
    if os.environ.get("JARVIS_SEM_PAINEL") != "1":            # Gmail e Agenda: ao ligar (10 s) e a cada 30 min
        def laco_painel():
            time.sleep(10)
            while True:
                atualizar_painel()
                time.sleep(5 * 60 if painel.google_ok() else 30 * 60)   # pela API é de graça: a cada 5 min
        threading.Thread(target=laco_painel, daemon=True).start()
    print(f"[jarvis] http://127.0.0.1:{PORTA}  ·  motor: {CLAUDE}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
