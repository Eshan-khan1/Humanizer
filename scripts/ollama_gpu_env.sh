# shellcheck shell=bash
# GPU / Metal settings for Ollama on Apple Silicon (sourced by start_server.sh).
# OLLAMA_GPU_MEMORY_FRACTION is a project convention; Ollama maps it to
# OLLAMA_GPU_OVERHEAD (bytes reserved for the system) on macOS unified memory.

ollama_configure_gpu() {
  # Fraction of unified RAM for the model (Metal). Default 75%; lower if the Mac feels sluggish.
  export OLLAMA_GPU_MEMORY_FRACTION="${OLLAMA_GPU_MEMORY_FRACTION:-0.75}"
  export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"
  export OLLAMA_LLM_LIBRARY="${OLLAMA_LLM_LIBRARY:-metal}"
  # Keep mistral loaded longer to avoid reload cost during grammar/training bursts.
  export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}"

  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 0
  fi

  local total_mem fraction overhead_mb
  total_mem="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
  fraction="${OLLAMA_GPU_MEMORY_FRACTION}"

  if [[ "${total_mem}" -gt 0 ]]; then
    # Reserve the rest of RAM so Ollama does not consume all unified memory.
    export OLLAMA_GPU_OVERHEAD="$(
      awk "BEGIN { printf \"%.0f\", ${total_mem} * (1 - ${fraction}) }"
    )"
    overhead_mb=$((OLLAMA_GPU_OVERHEAD / 1024 / 1024))
    total_mb=$((total_mem / 1024 / 1024))
    target_mb="$(awk "BEGIN { printf \"%.0f\", ${total_mb} * ${fraction} }")"
    echo "Ollama GPU (Metal): ~${target_mb}MB target (${OLLAMA_GPU_MEMORY_FRACTION} of ${total_mb}MB unified), ${overhead_mb}MB reserved for system"
  else
    echo "Ollama GPU (Metal): fraction=${OLLAMA_GPU_MEMORY_FRACTION}, flash attention on"
  fi
}

ollama_binary() {
  if [[ -x "/Applications/Ollama.app/Contents/Resources/ollama" ]]; then
    echo "/Applications/Ollama.app/Contents/Resources/ollama"
  elif command -v ollama >/dev/null 2>&1; then
    command -v ollama
  else
    return 1
  fi
}

# Start or restart `ollama serve` with GPU env applied (optional).
ollama_ensure_serve() {
  local bin
  bin="$(ollama_binary)" || return 0

  ollama_configure_gpu

  if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    if [[ "${OLLAMA_RELOAD:-}" == "1" ]]; then
      echo "Restarting Ollama to apply GPU settings..."
      if lsof -ti:11434 >/dev/null 2>&1; then
        lsof -ti:11434 | xargs kill 2>/dev/null || true
        sleep 2
      fi
    else
      echo "Ollama already running on :11434 (set OLLAMA_RELOAD=1 to restart with GPU settings)"
      return 0
    fi
  fi

  echo "Starting Ollama serve (Metal)..."
  nohup env \
    OLLAMA_GPU_MEMORY_FRACTION="${OLLAMA_GPU_MEMORY_FRACTION}" \
    OLLAMA_GPU_OVERHEAD="${OLLAMA_GPU_OVERHEAD:-0}" \
    OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION}" \
    OLLAMA_LLM_LIBRARY="${OLLAMA_LLM_LIBRARY}" \
    OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:-30m}" \
    "${bin}" serve >/dev/null 2>&1 &

  for _ in $(seq 1 30); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "WARNING: Ollama did not become ready on :11434" >&2
}
