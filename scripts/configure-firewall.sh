#!/bin/bash
set -euo pipefail

PLUGIN_ID="io.github.ctl0v0.omasonos"
PORT=1499
ACTION="${1:-add}"
[[ $# -eq 0 ]] || shift
STATE_HOME="${XDG_STATE_HOME:-${HOME}/.local/state}"
STATE_FILE="${STATE_HOME}/${PLUGIN_ID}/state.json"

if [[ $ACTION != add && $ACTION != remove ]]; then
  echo "Usage: $0 [add|remove]" >&2
  exit 2
fi
for command in ufw; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Missing required command: $command" >&2
    exit 1
  }
done
hosts=("$@")
if ((${#hosts[@]} == 0)); then
  command -v jq >/dev/null 2>&1 || {
    echo "Missing required command: jq" >&2
    exit 1
  }
  [[ -r $STATE_FILE ]] || {
    echo "No OmaSonos discovery state found. Open the plugin once, then retry." >&2
    exit 1
  }
  mapfile -t hosts < <(jq -r '.cachedHosts[]? | select(test("^[0-9]+(\\.[0-9]+){3}$"))' "$STATE_FILE")
fi
((${#hosts[@]} > 0)) || {
  echo "No discovered Sonos addresses found. Open the plugin and refresh first." >&2
  exit 1
}

runner=()
if ((EUID != 0)); then
  command -v sudo >/dev/null 2>&1 || {
    echo "Missing required command: sudo" >&2
    exit 1
  }
  runner=(sudo)
fi

if [[ $ACTION == add ]]; then
  for host in "${hosts[@]}"; do
    "${runner[@]}" ufw allow from "$host" to any port "$PORT" proto tcp comment OmaSonos
  done
  echo "Allowed TCP $PORT from ${#hosts[@]} discovered Sonos speaker address(es)."
else
  for host in "${hosts[@]}"; do
    "${runner[@]}" ufw --force delete allow from "$host" to any port "$PORT" proto tcp
  done
  echo "Removed OmaSonos TCP $PORT rules for ${#hosts[@]} speaker address(es)."
fi
