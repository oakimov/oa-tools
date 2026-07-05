#!/bin/bash
# Read all of stdin into a variable
input=$(cat)

echo "$input" > "$HOME/.claude/status.json"

MODEL_ID=$(echo "$input" | jq -r '.model.id // ""')
MODEL=$(echo "$input" | jq -r '.model.display_name // "unknown"')

# Map unknown models to their actual context window sizes
get_context_window() {
  local model="$1"
  case "$model" in
    *codestral*)                      echo 32000     ;;
    *deepseek-v4-flash-free*)         echo 1000000   ;;
    *deepseek-v4-flash*)              echo 1048576   ;;
    *deepseek-v4-pro*)                echo 1048576   ;;
    *devstral-2-123b*)                echo 262144    ;;
    *gemma-4-31b-it*)                 echo 262144    ;;
    *gpt-5.4-mini*)                   echo 400000    ;;
    *gpt-5.4*)                        echo 1050000   ;;
    *gpt-5.5*)                        echo 1050000   ;;
    *gpt-5.3-codex*)                  echo 400000    ;;
    *gpt-5.2*)                        echo 400000    ;;
    *gpt-oss-120b*)                   echo 131072    ;;
    *kimi-k2.5*)                      echo 262144    ;;
    *kimi-k2.6*)                      echo 262144    ;;
    *llama-3.3-70b*)                  echo 128000    ;;
    *minimax-m2.5-free*)              echo 196608    ;;
    *minimax-m2.5*)                   echo 196608    ;;
    *minimax-m2.7*)                   echo 196608    ;;
    *mimo-v2.5-pro*)                  echo 1000000   ;;
    *mimo-v2.5*)                      echo 1000000   ;;
    *mistral-small-3.2*)              echo 131072    ;;
    *nemotron-3-super-free*)          echo 1000000   ;;
    *qwen3.5-397b*)                   echo 262144    ;;
    *qwen3-coder-30b*)                echo 262144    ;;
    *qwen3.5-plus*)                   echo 1000000   ;;
    *qwen3.6-plus-free*)              echo 1000000   ;;
    *ring-2.6-1t-free*)               echo 262144    ;;
    *sonar-pro*)                      echo 200000    ;;
    *sonar*)                          echo 128000    ;;
    *trinity-large-preview-free*)     echo 131072    ;;
    *codex-auto-review*)              echo 258000    ;;
    *GLM-4.5-Air*)                    echo 128000    ;;
    *GLM-4.5*)                        echo 128000    ;;
    *GLM-4.6*)                        echo 200000    ;;
    *GLM-4.7*)                        echo 200000    ;;
    *GLM-5-Turbo*)                    echo 200000    ;;
    *GLM-5.1*)                        echo 200000    ;;
    *GLM-5*)                          echo 200000    ;;
    *)                                echo 200000    ;;
  esac
}

# Extract fields with jq, "// 0" provides fallback for null
MODEL=$(echo "$input" | jq -r '.model.display_name')
NATIVE_SIZE=$(echo "$input" | jq -r '.context_window.context_window_size // 0')
USED_TOKENS=$(echo "$input" | jq -r '
  (.context_window.current_usage.input_tokens // 0) +
  (.context_window.current_usage.cache_creation_input_tokens // 0) +
  (.context_window.current_usage.cache_read_input_tokens // 0)
')

KNOWN_SIZE=$(get_context_window "$MODEL_ID")

# If Claude Code's size matches our known size, trust its percentage.
# Otherwise recalculate against the correct denominator.
if [ "$NATIVE_SIZE" -eq "$KNOWN_SIZE" ] 2>/dev/null; then
  PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
else
  PCT=$(( USED_TOKENS * 100 / KNOWN_SIZE ))
fi

# Build progress bar: printf -v creates a run of spaces, then
# ${var// /▓} replaces each space with a block character
BAR_WIDTH=10
FILLED=$((PCT * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
[ "$FILLED" -gt 0 ] && printf -v FILL "%${FILLED}s" && BAR="${FILL// /▓}"
[ "$EMPTY" -gt 0 ] && printf -v PAD "%${EMPTY}s" && BAR="${BAR}${PAD// /░}"

echo "[$MODEL] $BAR $PCT%"
