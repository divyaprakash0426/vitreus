#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
skip_all_pulls=0
skip_large_pull=0
usage() {
  echo "Usage: scripts/setup_arch.sh [--skip-31b] [--no-pull]"
  echo "--skip-31b skips only gemma4:31b; --no-pull skips all Ollama pulls."
}
while (($#)); do
  case "$1" in
    --skip-31b) skip_large_pull=1 ;;
    --no-pull) skip_all_pulls=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done
packages=()
command -v uv >/dev/null 2>&1 || packages+=(uv)
command -v soffice >/dev/null 2>&1 || packages+=(libreoffice-fresh)
if ! command -v ollama >/dev/null 2>&1; then
  ollama_package="ollama"
  if command -v nvidia-smi >/dev/null 2>&1; then
    ollama_package="ollama-cuda"
  elif command -v rocminfo >/dev/null 2>&1 || [[ -d /opt/rocm ]]; then
    ollama_package="ollama-rocm"
  fi
  if [[ "$ollama_package" != "ollama" ]] && ! pacman -Si "$ollama_package" >/dev/null 2>&1; then
    echo "Package '$ollama_package' is unavailable; using plain ollama." >&2
    ollama_package="ollama"
  fi
  packages+=("$ollama_package")
fi
if ((${#packages[@]})); then
  sudo pacman -S --needed --noconfirm "${packages[@]}"
else
  echo "System packages already installed."
fi
echo "Enabling and starting ollama.service..."
sudo systemctl enable --now ollama.service
ollama_ready=0
for _ in {1..30}; do
  ollama list >/dev/null 2>&1 && { ollama_ready=1; break; }
  sleep 1
done
if ((ollama_ready == 0)); then
  echo "Ollama did not become ready within 30 seconds." >&2
  exit 1
fi
cd "$REPO_ROOT"
uv sync
model_present() {
  ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "$1"
}
pull_model() {
  local model="$1"
  if model_present "$model"; then
    echo "Ollama model already present: $model"
  else
    ollama pull "$model"
  fi
}
if ((skip_all_pulls)); then
  echo "Skipping all Ollama model pulls because --no-pull was passed."
else
  [[ "$skip_large_pull" == "1" ]] && echo "Skipping gemma4:31b because --skip-31b was passed." || pull_model "gemma4:31b"
  pull_model "gemma4:e4b"
fi
cat <<'MSG'

Optional backend API keys:
  export GEMINI_API_KEY=...          # Google AI Studio
  export OPENROUTER_API_KEY=...      # OpenRouter
  export OPENAI_API_KEY=...          # OpenAI-compatible servers
  export OPENAI_BASE_URL=...         # e.g. http://localhost:1234/v1

Running Vitreus doctor...
MSG
uv run vitreus doctor
