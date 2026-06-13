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

count=0
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

    if [[ "$SKIP_KEYS" == *" ${current_key} "* ]]; then
        echo -e "${DIM}  Skipping ${current_key} (managed by up.sh)${NC}"
        current_key=""
        current_value=""
        continue
    fi

    echo -e "${DIM}  Setting ${current_key}${NC}"
    railway variables --set "${current_key}=${current_value}" --service agent-os 2>/dev/null
    count=$((count + 1))

    current_key=""
    current_value=""
done < "$ENV_FILE"

echo ""
echo -e "${BOLD}Done.${NC} Synced ${count} variable(s) to Railway."
echo -e "${DIM}Railway will auto-redeploy if values changed.${NC}"
echo ""
