#!/bin/bash

############################################################################
#
#    @context Railway Environment Sync
#
#    Usage:
#      ./scripts/railway/env-sync.sh             # syncs .env.production
#      ./scripts/railway/env-sync.sh .env        # syncs .env instead
#
#    Reads the file and pushes every variable to the Railway agent-os
#    service. Multi-line values (e.g. PEM-formatted JWT_VERIFICATION_KEY)
#    are handled correctly.
#
############################################################################

set -e

# Colors
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

ENV_FILE="${1:-.env.production}"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "File not found: $ENV_FILE"
    echo "Usage: $0 [path/to/env] (default: .env.production)"
    exit 1
fi

if ! command -v railway &> /dev/null; then
    echo "Railway CLI not found. Install: https://docs.railway.app/guides/cli"
    exit 1
fi

if ! railway status &> /dev/null; then
    echo "Not linked to a Railway project. Run ./scripts/railway/up.sh first."
    exit 1
fi

echo ""
echo -e "${BOLD}Syncing env vars from ${ENV_FILE} to Railway...${NC}"
echo ""

# Parse the env file, treating PEM blocks (and other multiline values)
# as a single variable.
# Infra vars that up.sh sets to Railway-specific values (the internal DB host,
# the service port). A copied .env.production often still carries a local
# DB_HOST=localhost / context-db; pushing that would break the deploy. Skip
# them here so up.sh stays the single owner of these.
SKIP_KEYS=" DB_HOST PORT "

# Pull the service's current variables once. We diff against this so the sync
# only pushes keys that are new or changed — every push is a deploy trigger, so
# re-sending an unchanged value would redeploy for nothing. Falls back to
# "push everything" if the read fails (still one batched deploy, see below).
current_json="$(railway variables --json --service agent-os 2>/dev/null || true)"
if ! echo "$current_json" | jq -e 'type == "object"' >/dev/null 2>&1; then
    echo -e "${DIM}  Could not read current Railway variables — will push all keys.${NC}"
    current_json=""
fi

# Decide whether a parsed key/value pair needs pushing, and queue it if so.
# Mutates set_args / changed / unchanged in the current shell (no subshell).
declare -a set_args=()
changed=0
unchanged=0

queue_if_changed() {
    local key="$1" value="$2"

    if [[ "$SKIP_KEYS" == *" ${key} "* ]]; then
        echo -e "${DIM}  Skipping ${key} (managed by up.sh)${NC}"
        return
    fi

    if [[ -n "$current_json" ]] && echo "$current_json" | jq -e --arg k "$key" 'has($k)' >/dev/null 2>&1; then
        local existing
        existing="$(echo "$current_json" | jq -r --arg k "$key" '.[$k]')"
        if [[ "$existing" == "$value" ]]; then
            unchanged=$((unchanged + 1))
            return
        fi
        echo -e "${DIM}  ~ ${key} (changed)${NC}"
    else
        echo -e "${DIM}  + ${key} (new)${NC}"
    fi

    set_args+=("${key}=${value}")
    changed=$((changed + 1))
}

current_key=""
current_value=""

while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip empty lines and comments (only when not inside a multiline value)
    if [[ -z "$current_key" ]]; then
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    fi

    if [[ -z "$current_key" ]]; then
        # Start of a new variable
        current_key="${line%%=*}"
        current_value="${line#*=}"
    else
        # Continuation of a multiline value
        current_value="${current_value}
${line}"
    fi

    # Check if the value is complete (not in the middle of a PEM block)
    if [[ "$current_value" == *"-----BEGIN"* && "$current_value" != *"-----END"* ]]; then
        continue
    fi

    # Strip surrounding quotes if present
    current_value="${current_value#\"}"
    current_value="${current_value%\"}"
    current_value="${current_value#\'}"
    current_value="${current_value%\'}"

    queue_if_changed "$current_key" "$current_value"

    current_key=""
    current_value=""
done < "$ENV_FILE"

echo ""
if [[ ${#set_args[@]} -eq 0 ]]; then
    echo -e "${BOLD}Nothing to sync.${NC} ${unchanged} variable(s) already up to date — no redeploy."
    echo ""
    exit 0
fi

# One batched write for every changed key → Railway redeploys once, not once
# per variable. (Per-call writes are why a 6-var sync used to fire 6 deploys.)
railway variables set --service agent-os "${set_args[@]}" >/dev/null 2>&1

echo ""
echo -e "${BOLD}Done.${NC} Pushed ${changed} changed variable(s) in one batch (${unchanged} unchanged)."
echo -e "${DIM}Railway redeploys once for the batch.${NC}"
echo ""
