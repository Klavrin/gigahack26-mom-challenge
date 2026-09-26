#!/bin/sh
# Tries to open a connection to the internet from inside every container.
# Expected in sealed mode: every line says BLOCKED.
PY='import socket,sys
try:
    socket.create_connection(("1.1.1.1", 443), 3); print("OPEN")
except OSError:
    print("BLOCKED")'
NODE='const s=require("net").connect(443,"1.1.1.1");s.on("connect",()=>{console.log("OPEN");process.exit()});s.on("error",()=>{console.log("BLOCKED");process.exit()});setTimeout(()=>{console.log("BLOCKED");process.exit()},3000)'

check() { printf '%-8s %s\n' "$1" "$(docker compose exec -T "$1" "$@" 2>/dev/null | tail -1)"; }
running() { docker compose ps --services --status running | grep -qx "$1"; }

running api     && check api python -c "$PY"
running nemo    && check nemo python -c "$PY"
running n8n     && check n8n node -e "$NODE"
running ollama  && check ollama bash -c 'timeout 3 bash -c "</dev/tcp/1.1.1.1/443" 2>/dev/null && echo OPEN || echo BLOCKED'
running mailpit && check mailpit sh -c 'nc -z -w 3 1.1.1.1 443 2>/dev/null && echo OPEN || echo BLOCKED'
