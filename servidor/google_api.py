"""APIs do Google (Gmail, Agenda e Drive) direto, sem modelo no meio.

Login OAuth uma vez (abre o navegador); o token fica em servidor/segredos/google-token.json
(só o seu usuário lê). Permissões: Gmail para ler, organizar e enviar (gmail.modify não apaga
definitivamente), Agenda para ler e criar eventos, Drive só leitura.
"""
import base64
import email.utils
import json
import os
import re
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SEGREDOS = Path(__file__).resolve().parent / "segredos"
CLIENTE = SEGREDOS / "google-cliente.json"
TOKEN = SEGREDOS / "google-token.json"
ESCOPOS = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]
import config
FUSO = ZoneInfo(config.FUSO)
_trava, _servicos, _login = threading.Lock(), {}, {"rodando": False, "erro": None}


# ---------- login ----------
def credenciais():
    if not TOKEN.exists():
        return None
    c = Credentials.from_authorized_user_file(str(TOKEN), ESCOPOS)
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
        _salvar(c)
    return c if c and c.valid else None


def _salvar(c):
    TOKEN.write_text(c.to_json())
    os.chmod(TOKEN, 0o600)


def estado():
    try:
        ok = credenciais() is not None
    except Exception as e:  # noqa: BLE001 — token revogado ou expirado
        return {"conectado": False, "cliente": CLIENTE.exists(), "erro": str(e)[:200], "login": _login["rodando"]}
    return {"conectado": ok, "cliente": CLIENTE.exists(), "login": _login["rodando"], "erro": _login["erro"]}


def conectar():
    """Abre o navegador para autorizar e espera o retorno numa porta local (em segundo plano)."""
    if _login["rodando"] or not CLIENTE.exists():
        return estado()

    def fluxo():
        _login.update(rodando=True, erro=None)
        try:
            f = InstalledAppFlow.from_client_secrets_file(str(CLIENTE), ESCOPOS)
            c = f.run_local_server(port=0, open_browser=True, prompt="consent", access_type="offline", timeout_seconds=300,
                                   success_message="Pronto: o JARVIS está conectado ao Google. Pode fechar esta aba.")
            _salvar(c)
            _geracao[0] += 1
        except Exception as e:  # noqa: BLE001 — inclui o prazo de 5 min sem resposta do Google
            _login["erro"] = (str(e) or "o Google não devolveu a autorização em 5 min")[:300]
        finally:
            _login["rodando"] = False
    threading.Thread(target=fluxo, daemon=True).start()
    return {**estado(), "login": True}


_local = threading.local()


def _svc(nome, versao):
    """Um cliente por thread: a conexão HTTP do Google não pode ser compartilhada entre consultas
    simultâneas (compartilhar dava '[SSL] record layer failure' ao abrir um e-mail)."""
    cache = getattr(_local, "servicos", None)
    if cache is None or _local.geracao != _geracao[0]:
        cache = _local.servicos = {}
        _local.geracao = _geracao[0]
    if nome not in cache:
        with _trava:
            c = credenciais()
        if not c:
            raise PermissionError("Google não conectado")
        cache[nome] = build(nome, versao, credentials=c, cache_discovery=False)
    return cache[nome]


_geracao = [0]                                 # muda a cada login novo: as threads refazem os clientes


gmail = lambda: _svc("gmail", "v1")
agenda = lambda: _svc("calendar", "v3")
drive = lambda: _svc("drive", "v3")


# ---------- Gmail ----------
def _cab(msg, nome):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == nome.lower():
            return h["value"]
    return ""


def _nome(de):
    n, end = email.utils.parseaddr(de)
    return (n or end or de).strip().strip('"')


def _quando(ms):
    d = datetime.fromtimestamp(int(ms) / 1000, FUSO)
    return d.strftime("%H:%M") if d.date() == datetime.now(FUSO).date() else d.strftime("%d/%m")


def emails(n=8):
    g = gmail()
    r = g.users().threads().list(userId="me", q="in:inbox -category:promotions -category:social", maxResults=n).execute(num_retries=2)
    saida = []
    for t in r.get("threads", []):
        th = g.users().threads().get(userId="me", id=t["id"], format="metadata", metadataHeaders=["From", "Subject"]).execute(num_retries=2)
        ult = th["messages"][-1]
        rotulos = set().union(*(m.get("labelIds", []) for m in th["messages"]))
        saida.append({"thread_id": t["id"], "de": _nome(_cab(ult, "From")), "assunto": _cab(th["messages"][0], "Subject") or "(sem assunto)",
                      "resumo": unescape(ult.get("snippet", ""))[:120], "quando": _quando(ult["internalDate"]),
                      "nao_lido": "UNREAD" in rotulos, "importante": "IMPORTANT" in rotulos and "UNREAD" in rotulos})
    return saida


def _partes(p, out):
    """Texto e anexos de uma mensagem (percorre as partes MIME)."""
    corpo = p.get("body", {})
    cid = next((h["value"].strip("<> ") for h in p.get("headers", []) if h["name"].lower() == "content-id"), "")
    disp = next((h["value"].lower() for h in p.get("headers", []) if h["name"].lower() == "content-disposition"), "")
    if p.get("filename") and corpo.get("attachmentId"):
        out["anexos"].append({"nome": p["filename"], "tipo": p.get("mimeType"), "tamanho": corpo.get("size", 0), "id": corpo["attachmentId"],
                              "cid": cid, "embutida": bool(cid) and not disp.startswith("attachment")})
    elif cid and (p.get("mimeType") or "").startswith("image/") and (corpo.get("attachmentId") or corpo.get("data")):
        out["anexos"].append({"nome": p.get("filename") or cid, "tipo": p.get("mimeType"), "tamanho": corpo.get("size", 0),
                              "id": corpo.get("attachmentId"), "dados": corpo.get("data"), "cid": cid, "embutida": True})
    elif p.get("mimeType") == "text/plain" and corpo.get("data"):
        out["texto"].append(base64.urlsafe_b64decode(corpo["data"]).decode("utf-8", "replace"))
    elif p.get("mimeType") == "text/html" and corpo.get("data"):
        out["html"].append(base64.urlsafe_b64decode(corpo["data"]).decode("utf-8", "replace"))
    for sub in p.get("parts", []) or []:
        _partes(sub, out)


def _limpar(txt):
    linhas = []
    for l in txt.splitlines():
        if re.match(r"^\s*>", l) or re.match(r"^(Em|On) .+(escreveu|wrote):\s*$", l.strip()):
            break                                   # o resto é citação da mensagem anterior
        linhas.append(l.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()


def _html_texto(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", h)
    return unescape(re.sub(r"<[^>]+>", "", h))


def ler(thread_id, n=4):
    th = gmail().users().threads().get(userId="me", id=thread_id, format="full").execute(num_retries=2)
    msgs = []
    for m in th["messages"][-n:]:
        out = {"texto": [], "html": [], "anexos": []}
        _partes(m["payload"], out)
        txt = "\n".join(out["texto"]) or _html_texto("\n".join(out["html"]))
        h = "\n".join(out["html"])
        srcs = re.findall(r"""<img[^>]+src=["']([^"']+)""", h, re.I)
        msgs.append({"id": m["id"], "de": _nome(_cab(m, "From")), "quando": datetime.fromtimestamp(int(m["internalDate"]) / 1000, FUSO).strftime("%d/%m %H:%M"),
                     "texto": _limpar(txt)[:4000], "anexos": [a for a in out["anexos"] if not a.get("embutida")],
                     "html": bool(h), "externas": sum(1 for x in srcs if x.lower().startswith("http")),
                     "embutidas": sum(1 for x in srcs if x.lower().startswith("cid:"))})
    return {"mensagens": msgs}


def html_original(msg_id, externas=False):
    """O HTML da mensagem como foi desenhado: imagens embutidas (cid:) viram data: URLs; as externas só
    carregam se o usuário pedir (a CSP do servidor bloqueia, e assim o remetente não sabe que ele abriu)."""
    m = gmail().users().messages().get(userId="me", id=msg_id, format="full").execute(num_retries=2)
    out = {"texto": [], "html": [], "anexos": []}
    _partes(m["payload"], out)
    h = "\n".join(out["html"])
    if not h:
        h = "<pre style='white-space:pre-wrap;font:14px/1.5 sans-serif'>" + unescape("\n".join(out["texto"])).replace("&", "&amp;").replace("<", "&lt;") + "</pre>"
    for a in out["anexos"]:
        if not a.get("cid") or a.get("tamanho", 0) > 4_000_000:
            continue
        dados = base64.urlsafe_b64decode(a["dados"]) if a.get("dados") else anexo(msg_id, a["id"]) if a.get("id") else None
        if dados:
            url = f"data:{a['tipo'] or 'image/png'};base64," + base64.b64encode(dados).decode()
            h = re.sub(r"cid:" + re.escape(a["cid"]), url, h, flags=re.I)
    img = "data: https: http:" if externas else "data:"
    cabeca = ('<meta charset="utf-8"><meta name="referrer" content="no-referrer"><base target="_blank">'
              f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src {img}; style-src \'unsafe-inline\'; font-src data:">'
              '<style>body{margin:12px;background:#fff;color:#111;font-family:-apple-system,Helvetica,Arial,sans-serif}img{max-width:100%;height:auto}</style>')
    return cabeca + h


def anexo(msg_id, att_id):
    a = gmail().users().messages().attachments().get(userId="me", messageId=msg_id, id=att_id).execute(num_retries=2)
    return base64.urlsafe_b64decode(a["data"])


def labels():
    r = gmail().users().labels().list(userId="me").execute(num_retries=2)
    us = [{"id": l["id"], "nome": l["name"]} for l in r.get("labels", []) if l.get("type") == "user"]
    return {"labels": sorted(us, key=lambda x: x["nome"].lower())}


def nao_lido(thread_id):
    """Marca a última mensagem da conversa como não lida (como o Gmail faz)."""
    th = gmail().users().threads().get(userId="me", id=thread_id, format="minimal").execute(num_retries=2)
    gmail().users().messages().modify(userId="me", id=th["messages"][-1]["id"], body={"addLabelIds": ["UNREAD"]}).execute(num_retries=2)
    return {"ok": True, "detalhe": "Marcado como não lido."}


def lixeira(thread_id):
    gmail().users().threads().trash(userId="me", id=thread_id).execute(num_retries=2)
    return {"ok": True, "detalhe": "Na lixeira."}


def arquivar(thread_id, nome_label):
    ls = {l["nome"]: l["id"] for l in labels()["labels"]}
    if nome_label not in ls:
        raise ValueError(f"label não existe: {nome_label}")
    gmail().users().threads().modify(userId="me", id=thread_id, body={"addLabelIds": [ls[nome_label]], "removeLabelIds": ["INBOX"]}).execute(num_retries=2)
    return {"ok": True, "detalhe": f"Arquivado em {nome_label}."}


def _enviar(msg, thread_id=None):
    corpo = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:
        corpo["threadId"] = thread_id
    gmail().users().messages().send(userId="me", body=corpo).execute(num_retries=2)


def responder(thread_id, texto):
    th = gmail().users().threads().get(userId="me", id=thread_id, format="metadata",
                                       metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"]).execute(num_retries=2)
    ult = th["messages"][-1]
    m = EmailMessage()
    m["To"] = _cab(ult, "Reply-To") or _cab(ult, "From")
    assunto = _cab(th["messages"][0], "Subject")
    m["Subject"] = assunto if assunto.lower().startswith("re:") else "Re: " + assunto
    mid = _cab(ult, "Message-ID")
    if mid:
        m["In-Reply-To"] = mid
        m["References"] = (_cab(ult, "References") + " " + mid).strip()
    m.set_content(texto)
    _enviar(m, thread_id)
    return {"ok": True, "detalhe": f"Resposta enviada para {_nome(m['To'])}."}


def encaminhar(thread_id, para, nota):
    """Encaminha a última mensagem, com o texto dela e os anexos."""
    g = gmail()
    th = g.users().threads().get(userId="me", id=thread_id, format="full").execute(num_retries=2)
    ult = th["messages"][-1]
    out = {"texto": [], "html": [], "anexos": []}
    _partes(ult["payload"], out)
    original = "\n".join(out["texto"]) or _html_texto("\n".join(out["html"]))
    m = EmailMessage()
    m["To"] = para
    assunto = _cab(ult, "Subject")
    m["Subject"] = assunto if assunto.lower().startswith("fwd:") else "Fwd: " + assunto
    m.set_content(f"{nota}\n\n---------- Mensagem encaminhada ----------\nDe: {_cab(ult, 'From')}\nData: {_cab(ult, 'Date')}\n"
                  f"Assunto: {assunto}\n\n{original}".lstrip())
    for a in out["anexos"]:
        dados = anexo(ult["id"], a["id"])
        principal, _, sub = (a["tipo"] or "application/octet-stream").partition("/")
        m.add_attachment(dados, maintype=principal, subtype=sub or "octet-stream", filename=a["nome"])
    _enviar(m)
    return {"ok": True, "detalhe": f"Encaminhado para {para}" + (f" com {len(out['anexos'])} anexo(s)." if out["anexos"] else ".")}


# ---------- Agenda ----------
def _ev(e, dia_ref):
    ini = e["start"].get("dateTime") or e["start"].get("date")
    fim = e["end"].get("dateTime") or e["end"].get("date")
    todo = "date" in e["start"]
    d = datetime.fromisoformat(ini).astimezone(FUSO) if not todo else datetime.fromisoformat(ini).replace(tzinfo=FUSO)
    hoje = dia_ref.date()
    dia = "hoje" if d.date() == hoje else "amanhã" if d.date() == hoje + timedelta(days=1) else d.strftime("%d/%m")
    return {"dia": dia, "hora": "dia todo" if todo else d.strftime("%H:%M"),
            "fim": "" if todo else datetime.fromisoformat(fim).astimezone(FUSO).strftime("%H:%M"),
            "titulo": e.get("summary", "(sem título)"), "local": e.get("location", ""), "inicio": d.isoformat()}


def eventos():
    a = agenda()
    agora = datetime.now(FUSO)
    ini = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    cals = [c for c in a.calendarList().list().execute(num_retries=2).get("items", [])
            if not c.get("hidden") and "holiday" not in c["id"] and "#contacts" not in c["id"] and "feriados" not in c.get("summary", "").lower()]

    def buscar(ate):
        evs = []
        for c in cals:
            r = a.events().list(calendarId=c["id"], timeMin=ini.isoformat(), timeMax=ate.isoformat(), singleEvents=True,
                                orderBy="startTime", maxResults=20).execute(num_retries=2)
            evs += [_ev(e, agora) for e in r.get("items", []) if e.get("eventType") != "birthday" and e.get("status") != "cancelled"]
        return sorted(evs, key=lambda x: x["inicio"])
    evs = buscar(ini + timedelta(days=2))
    return evs or buscar(ini + timedelta(days=15))[:3]


# ---------- Drive ----------
EXPORTA = {".gdoc": ("text/plain", ".md"), ".gsheet": ("text/csv", ".csv"), ".gslides": ("text/plain", ".md")}


def exportar_atalho(caminho):
    """Conteúdo de um .gdoc/.gsheet/.gslides do Drive para Desktop (o arquivo local é só um atalho com o doc_id)."""
    ext = Path(caminho).suffix.lower()
    if ext not in EXPORTA:
        return None
    doc_id = json.loads(Path(caminho).read_text()).get("doc_id")
    if not doc_id:
        return None
    dados = drive().files().export(fileId=doc_id, mimeType=EXPORTA[ext][0]).execute(num_retries=2)
    return dados.decode("utf-8", "replace") if isinstance(dados, bytes) else str(dados)
