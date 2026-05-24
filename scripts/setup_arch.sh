#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it with: pacman -S uv" >&2
  exit 1
fi

uv sync --extra dev

cat <<'MSG'
Vitreus development environment is ready.

Optional runtime integrations:
- LibreOffice Calc with UNO socket support:
  libreoffice --calc --accept='socket,host=localhost,port=2002;urp;StarOffice.ComponentContext'
- Ollama with Gemma 4 31B Dense:
  ollama pull gemma4:31b
MSG
