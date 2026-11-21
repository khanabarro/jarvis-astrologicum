"""Ponte entre o grafo do graphify e o cluster.

- resumo(): conceitos (estrelas pequenas), comunidades (regiões) e ligações, já ligados às
  estrelas de arquivo pelo nome do arquivo no corpus (que termina com o id da estrela).
- tocados(texto): quais estrelas e conceitos aparecem num resultado de ferramenta, para o
  cluster mostrar o caminho do raciocínio.
"""
import json
import re
from pathlib import Path

import indexador

GRAFO = indexador.CACHE / "grafo" / "graphify-out" / "graph.json"
ID_ESTRELA = re.compile(r"-([nskca][0-9a-f]{11})\.md\b")
_cache = {"mtime": None, "dados": None}


def _estrela_de(source_file):
    m = ID_ESTRELA.search(source_file or "")
    return m.group(1) if m else None


def _carregar():
    try:
        mt = GRAFO.stat().st_mtime
    except OSError:
        return None
    if _cache["mtime"] == mt:
        return _cache["dados"]
    g = json.loads(GRAFO.read_text())
    nos, links = g.get("nodes", []), g.get("links", g.get("edges", []))
    rotulos = {}
    for k in ("community_labels", "communities_labels"):
        if isinstance(g.get(k), dict):
            rotulos = g[k]
    lab_arq = GRAFO.parent / ".graphify_labels.json"
    if not rotulos and lab_arq.exists():
        try:
            rotulos = json.loads(lab_arq.read_text())
        except ValueError:
            pass

    grau = {}
    for l in links:
        for k in ("source", "target"):
            grau[l[k]] = grau.get(l[k], 0) + 1

    conceitos, por_no = [], {}
    for n in nos:
        rot = (n.get("label") or str(n["id"])).strip()
        estrela = _estrela_de(n.get("source_file"))
        # o nó do próprio arquivo já é a estrela grande; os outros viram conceitos
        if estrela and ID_ESTRELA.search(rot + ".md" if not rot.endswith(".md") else rot):
            por_no[n["id"]] = ("e", estrela)
            continue
        c = {"id": "g" + str(len(conceitos)), "rot": rot[:60], "com": n.get("community"),
             "grau": grau.get(n["id"], 0), "estrela": estrela}
        por_no[n["id"]] = ("c", c["id"])
        conceitos.append(c)

    ligacoes = []
    for l in links:
        a, b = por_no.get(l["source"]), por_no.get(l["target"])
        if a and b and a != b:
            ligacoes.append([a[1], b[1]])

    comunidades = {}
    for c in conceitos:
        if c["com"] is not None:
            k = str(c["com"])
            comunidades.setdefault(k, {"id": k, "nome": rotulos.get(k) or rotulos.get(int(k)) if isinstance(rotulos, dict) else None, "n": 0})
            comunidades[k]["n"] += 1
    rot_busca = sorted(((c["rot"].lower(), c["id"]) for c in conceitos if len(c["rot"]) >= 4),
                       key=lambda x: -len(x[0]))[:4000]
    dados = {"conceitos": conceitos, "ligacoes": ligacoes[:6000], "comunidades": list(comunidades.values()),
             "_busca": rot_busca, "_estrela_conceitos": {}}
    for c in conceitos:
        if c["estrela"]:
            dados["_estrela_conceitos"].setdefault(c["estrela"], []).append(c["id"])
    _cache.update(mtime=mt, dados=dados)
    return dados


def resumo():
    d = _carregar()
    if not d:
        return {"conceitos": [], "ligacoes": [], "comunidades": [], "pronto": False}
    return {"conceitos": d["conceitos"], "ligacoes": d["ligacoes"], "comunidades": d["comunidades"], "pronto": True}


def tocados(texto, caminhos_estrelas=None):
    """Estrelas (por id no nome do arquivo ou por caminho) e conceitos (por rótulo) citados no texto."""
    if not texto:
        return [], []
    estrelas = list(dict.fromkeys(ID_ESTRELA.findall(texto)))
    for caminho, eid in (caminhos_estrelas or {}).items():
        if caminho in texto and eid not in estrelas:
            estrelas.append(eid)
    conceitos = []
    d = _carregar()
    if d:
        baixo = texto.lower()
        for rot, cid in d["_busca"]:
            if rot in baixo:
                conceitos.append(cid)
                if len(conceitos) >= 40:
                    break
    return estrelas[:40], conceitos
