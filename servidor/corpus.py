"""Monta o corpus que o graphify lê: servidor/cache/corpus/.

Notas e skills entram como links físicos (nada é copiado). Conversas, que são .jsonl,
viram um .md só com o texto trocado (sem ferramentas). Artefatos ficam de fora por enquanto:
PDFs e imagens custam caro para extrair.

Também grava corpus/mapa.json: caminho no corpus -> id da estrela, para ligar conceitos a estrelas.
"""
import json
import os
import re
import shutil
from pathlib import Path

import config
import indexador

CORPUS = indexador.CACHE / "corpus"
LIMITE = 60_000          # caracteres por conversa exportada (o começo e o fim, se passar)


def _nome(s):
    return re.sub(r"[^\w\-]+", "-", s, flags=re.U).strip("-")[:60] or "sem-nome"


def pasta_de(e):
    p = CORPUS / (e["tipo"] + "s")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _exportar(caminho):
    try:
        import google_api
        return google_api.exportar_atalho(caminho) if google_api.estado()["conectado"] else None
    except Exception:  # noqa: BLE001 — sem API ou sem acesso: fica só como estrela
        return None


def montar(estrelas=None):
    estrelas = estrelas or indexador.indexar()
    if CORPUS.exists():
        shutil.rmtree(CORPUS)        # apaga só os links e as exportações; os originais ficam
    mapa = {}
    for e in estrelas:
        if e["tipo"] not in ("nota", "skill", "conversa"):
            continue
        if e["tipo"] == "nota" and e["caminho"].lower().endswith((".gdoc", ".gsheet", ".gslides")):
            txt = _exportar(e["caminho"])     # docs do Google: com a API conectada, o conteúdo entra no grafo
            if txt:
                destino = pasta_de(e) / f"{_nome(e['titulo'])}-{e['id']}.md"
                destino.write_text(f"# {e['titulo']}\n\nDocumento do Google Drive ({e.get('fonte')}).\n\n{txt[:LIMITE]}")
                mapa[str(destino.relative_to(CORPUS))] = e["id"]
            continue
        if e["tipo"] == "nota" and not e["caminho"].lower().endswith((".md", ".txt")):
            continue          # .docx: o graphify não lê; fica só como estrela
        pasta = CORPUS / (e["tipo"] + "s")
        pasta.mkdir(parents=True, exist_ok=True)
        destino = pasta / f"{_nome(e['titulo'])}-{e['id']}.md"
        if e["tipo"] == "conversa":
            msgs = indexador.conversa_mensagens(e["caminho"], limite=400)
            txt = f"# {e['titulo']}\n\nConversa do projeto {e.get('fonte')}.\n\n" + "\n\n".join(
                (f"**{config.NOME}:** " if m["eu"] else "**Claude:** ") + m["texto"] for m in msgs)
            if len(txt) > LIMITE:
                txt = txt[: LIMITE // 2] + "\n\n[…]\n\n" + txt[-LIMITE // 2:]
            destino.write_text(txt)
        else:
            # link físico: o graphify vê um arquivo comum dentro do corpus, sem duplicar os dados
            # (link simbólico ele trata como fora do escopo). Em outro disco, copia.
            try:
                os.link(e["caminho"], destino)
            except OSError:
                shutil.copyfile(e["caminho"], destino)
        mapa[str(destino.relative_to(CORPUS))] = e["id"]
    (CORPUS / "mapa.json").write_text(json.dumps(mapa, ensure_ascii=False))
    return mapa


if __name__ == "__main__":
    m = montar()
    total = sum((CORPUS / k).resolve().stat().st_size for k in m)
    print(len(m), "arquivos,", round(total / 1024), "KB")
