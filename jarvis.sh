#!/usr/bin/env bash
# Liga o servidor do JARVIS (se ainda não estiver ligado) e abre a galáxia no navegador.
cd "$(dirname "$0")"
PORTA=$(python3 -c 'import json;print(json.load(open("jarvis.config.json")).get("porta",8742))' 2>/dev/null || echo 8742)
URL="http://127.0.0.1:$PORTA"
if ! curl -s -o /dev/null "$URL/api/saude"; then
  echo "Ligando o JARVIS…"
  PY=servidor/.venv/bin/python; [ -x "$PY" ] || PY=python3
  "$PY" servidor/servidor.py &
  for i in $(seq 1 30); do sleep 0.2; curl -s -o /dev/null "$URL/api/saude" && break; done
fi
(command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || echo "Abra $URL"
echo "JARVIS em $URL. Feche este terminal para desligar."
wait
