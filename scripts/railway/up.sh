#!/bin/bash

############################################################################
#
#    @context Railway Setup (first-time provisioning)
#
#    Usage:     ./scripts/railway/up.sh
#    Redeploy:  ./scripts/railway/redeploy.sh
#    Sync env:  ./scripts/railway/env-sync.sh
#
#    Provisions Postgres + the agent-os service, creates the public domain,
#    and deploys — forwarding everything set in .env.production, including
#    OWNER_ID and the multi-line JWT_VERIFICATION_KEY. If the JWT key isn't
#    set yet, the script pauses after printing your domain so you can mint
#    it at os.agno.com — so the first deploy comes up serving.
#
#    Prerequisites:
#      - Railway CLI installed
#      - Logged in via `railway login`
#      - OPENAI_API_KEY set in environment (or .env / .env.production)
#
############################################################################

set -e

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo ""
GRADIENT=(220 214 208 202 166 130)
i=0
while IFS= read -r line; do
    printf '\033[38;5;%dm%s\033[0m\n' "${GRADIENT[$i]}" "$line"
    i=$((i+1))
done << 'BANNER'
     █████╗  ██████╗ ███╗   ██╗ ██████╗
    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
    ███████║██║  ███╗██╔██╗ ██║██║   ██║
    ██╔══██║██║   ██║██║╚██╗██║██║   ██║
    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝
BANNER
echo ""
echo -e "    ${DIM}@context · Built on Agno.${NC}"
echo ""

# Load env file — .env.production preferred for Railway, .env as fallback.
# Parsed line-by-line (not `source`d) so an unquoted multi-line PEM
# JWT_VERIFICATION_KEY isn't interpreted as shell. Mirrors the parser in
# env-sync.sh so both scripts read .env files identically. A function so
# the JWT pause below can re-read the file after the user edits it.
load_env_file() {
    local line current_key="" current_value=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ -z "$current_key" ]]; then
            [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        fi

        if [[ -z "$current_key" ]]; then
            current_key="${line%%=*}"
            current_value="${line#*=}"
        else
            current_value="${current_value}
${line}"
        fi

        # Still inside a PEM block — keep accumulating lines.
        if [[ "$current_value" == *"-----BEGIN"* && "$current_value" != *"-----END"* ]]; then
            continue
        fi

        # Strip surrounding quotes if present
        current_value="${current_value#\"}"
        current_value="${current_value%\"}"
        current_value="${current_value#\'}"
        current_value="${current_value%\'}"

        export "${current_key}=${current_value}"

        current_key=""
        current_value=""
    done < "$1"
}

# Persist a resolved value back into the env file so it stays a faithful record
# of the deploy (and env-sync.sh keeps managing it). Replaces an existing
# commented-or-uncommented `KEY=` line in place; appends if the key is absent.
# Rewrites via the original file (not `mv`) so a secrets file keeps its inode +
# permissions. The `|` sed delimiter avoids clashing with URL slashes. No-op
# when the file is missing.
persist_env_var() {
    local key="$1" value="$2" file="$3" tmp
    [[ -z "$file" || ! -f "$file" ]] && return
    if grep -qE "^[#[:space:]]*${key}=" "$file"; then
        tmp="$(mktemp)"
        if sed -E "s|^[#[:space:]]*${key}=.*|${key}=${value}|" "$file" > "$tmp"; then
            cat "$tmp" > "$file"
        fi
        rm -f "$tmp"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$file"
    fi
}

ENV_FILE=""
[[ -f .env.production ]] && ENV_FILE=".env.production"
[[ -z "$ENV_FILE" && -f .env ]] && ENV_FILE=".env"

if [[ -n "$ENV_FILE" ]]; then
    load_env_file "$ENV_FILE"
    echo -e "${DIM}Loaded ${ENV_FILE}${NC}"
fi

# Preflight
if ! command -v railway &> /dev/null; then
    echo "Railway CLI not found. Install: https://docs.railway.app/guides/cli"
    exit 1
fi

if [[ -z "$OPENAI_API_KEY" ]]; then
    echo "OPENAI_API_KEY not set. Add to .env (or .env.production) or export it."
    exit 1
fi

if [[ -z "$OWNER_ID" ]]; then
    echo -e "${BOLD}Warning:${NC} OWNER_ID not set — @context deploys capture-only (nobody is the owner)."
    echo -e "${DIM}Set it in .env.production (Slack email and/or JWT sub), or sync later with env-sync.sh.${NC}"
    echo ""
fi

# railway.json ships 2 replicas. Without a shared scheduler token each replica
# auto-generates its own, and a scheduler trigger authenticated by one replica
# is rejected by the other (~half the time). Pin one now so it's forwarded
# below; respects an explicit value if the env file already set it.
INTERNAL_SERVICE_TOKEN="${INTERNAL_SERVICE_TOKEN:-$(openssl rand -hex 32)}"
export INTERNAL_SERVICE_TOKEN

echo -e "${BOLD}Initializing project...${NC}"
echo ""
railway init -n "agent-platform"

echo ""
echo -e "${BOLD}Deploying PgVector database...${NC}"
echo ""
railway add -s pgvector -i agnohq/pgvector:18 \
    -v "POSTGRES_USER=${DB_USER:-context}" \
    -v "POSTGRES_PASSWORD=${DB_PASS:-context}" \
    -v "POSTGRES_DB=${DB_DATABASE:-context}"

echo ""
echo -e "${BOLD}Adding database volume...${NC}"
railway service link pgvector
railway volume add -m /var/lib/postgresql 2>/dev/null || echo -e "${DIM}Volume already exists or skipped${NC}"

echo ""
echo -e "${DIM}Waiting 15s for database...${NC}"
sleep 15

echo ""
echo -e "${BOLD}Creating application service...${NC}"
echo ""
# Forward everything the first deploy needs so it comes up serving on the
# first try. Optional keys ride along only when set — Railway CLI rejects
# empty values. JWT_VERIFICATION_KEY is multi-line, so it's set separately
# below via `railway variables --set` (the same path env-sync.sh uses).
RAILWAY_VARS=(
    -v "DB_USER=${DB_USER:-context}"
    -v "DB_PASS=${DB_PASS:-context}"
    -v "DB_HOST=pgvector.railway.internal"
    -v "DB_PORT=${DB_PORT:-5432}"
    -v "DB_DATABASE=${DB_DATABASE:-context}"
    -v "DB_DRIVER=postgresql+psycopg"
    -v "WAIT_FOR_DB=True"
    -v "PORT=8000"
    -v "OPENAI_API_KEY=${OPENAI_API_KEY}"
)
for key in OWNER_ID OWNER_NAME RUNTIME_ENV AGENTOS_URL AGNO_DEBUG PARALLEL_API_KEY \
           INTERNAL_SERVICE_TOKEN \
           SLACK_BOT_TOKEN SLACK_SIGNING_SECRET \
           GMAIL_TOKEN_JSON_B64 CALENDAR_TOKEN_JSON_B64 GMAIL_TOKEN_FILE CALENDAR_TOKEN_FILE \
           GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_PROJECT_ID \
           KNOWLEDGE_REPO_URL KNOWLEDGE_GITHUB_TOKEN KNOWLEDGE_BRANCH KNOWLEDGE_LOCAL_PATH; do
    [[ -n "${!key}" ]] && RAILWAY_VARS+=(-v "${key}=${!key}")
done

railway add -s agent-os "${RAILWAY_VARS[@]}"

# Domain before deploy — os.agno.com needs it to mint JWT_VERIFICATION_KEY,
# and the app needs that key to serve traffic in prd.
echo ""
echo -e "${BOLD}Creating domain...${NC}"
echo ""
DOMAIN_OUTPUT="$(railway domain --service agent-os 2>&1 || true)"
echo "$DOMAIN_OUTPUT"
APP_URL="$(grep -oE 'https://[A-Za-z0-9.-]+|[A-Za-z0-9-]+\.up\.railway\.app' <<< "$DOMAIN_OUTPUT" | head -1)"
[[ -n "$APP_URL" && "$APP_URL" != https://* ]] && APP_URL="https://${APP_URL}"

# The scheduler reaches AgentOS over its public URL — default it to the
# fresh domain unless the env file pinned one (forwarded above). Write it back
# into the env file too, so .env.production stays a faithful record of the
# deploy and env-sync.sh keeps managing it (rather than the value living only
# in Railway, while the file's commented localhost default invites a footgun).
AGENTOS_URL_PERSISTED=""
if [[ -z "$AGENTOS_URL" && -n "$APP_URL" ]]; then
    railway variables --set "AGENTOS_URL=${APP_URL}" --service agent-os > /dev/null
    persist_env_var AGENTOS_URL "$APP_URL" "$ENV_FILE"
    [[ -n "$ENV_FILE" ]] && AGENTOS_URL_PERSISTED=1
    echo -e "${DIM}Set AGENTOS_URL=${APP_URL} (Railway${AGENTOS_URL_PERSISTED:+ + ${ENV_FILE}})${NC}"
fi

# JWT auth is on in prd and the app refuses to serve without the key. Now
# that the domain exists, the user can mint it — pause, then re-read the
# env file so the first deploy comes up serving.
if [[ -z "$JWT_VERIFICATION_KEY" && -t 0 ]]; then
    echo ""
    echo -e "${BOLD}JWT_VERIFICATION_KEY not set${NC} — @context won't serve traffic without it."
    echo -e "  1. Open ${BOLD}os.agno.com${NC} → Add OS → Live → enter ${APP_URL:-your Railway domain}"
    echo -e "  2. Enable ${BOLD}Token Based Authorization${NC} and copy the public key"
    echo -e "  3. Paste it into ${ENV_FILE:-.env.production} (full PEM block, no quotes)"
    [[ -n "$AGENTOS_URL_PERSISTED" ]] && echo -e "  ${DIM}(AGENTOS_URL was already written to ${ENV_FILE} for you.)${NC}"
    echo ""
    read -r -p "  Press Enter when saved (or to deploy without it and env-sync later) " || true
    [[ -f .env.production ]] && ENV_FILE=".env.production"
    [[ -z "$ENV_FILE" && -f .env ]] && ENV_FILE=".env"
    [[ -n "$ENV_FILE" ]] && load_env_file "$ENV_FILE"
fi

if [[ -n "$JWT_VERIFICATION_KEY" ]]; then
    echo ""
    echo -e "${DIM}Setting JWT_VERIFICATION_KEY${NC}"
    railway variables --set "JWT_VERIFICATION_KEY=${JWT_VERIFICATION_KEY}" --service agent-os > /dev/null
else
    echo ""
    echo -e "${DIM}Deploying without JWT_VERIFICATION_KEY — the app will refuse traffic until${NC}"
    echo -e "${DIM}you add it to ${ENV_FILE:-.env.production} and run ./scripts/railway/env-sync.sh.${NC}"
fi

echo ""
echo -e "${BOLD}Deploying application...${NC}"
echo ""
railway up --service agent-os -d

echo ""
echo -e "${BOLD}Done.${NC} The app is building — give it a few minutes."
[[ -n "$APP_URL" ]] && echo -e "${DIM}URL:          ${APP_URL}${NC}"
echo -e "${DIM}Logs:         railway logs --service agent-os${NC}"
echo -e "${DIM}Env changes:  ./scripts/railway/env-sync.sh  (defaults to .env.production)${NC}"
echo ""
