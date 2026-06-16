#!/bin/bash

############################################################################
#
#    @context — turnkey: reset, deploy to production, wire every MCP client.
#
#    THE single command to (re)connect your MCP clients to the deployed
#    @context — full reset + redeploy by default, or `--no-redeploy` for the
#    lightweight "just rotate the token and rewire clients" path. Runs, in order:
#
#      0. Preflight        — venv python, Railway CLI, `railway login`, project link
#      1. Reset clients    — connect.py --remove (clear any stale `context` entries)
#      2. Mint fresh token — mint_mcp_jwt.py --rotate-key --write (new keypair +
#                            admin token → .env.production; old tokens invalidated)
#      3. Sync public key  — railway/env-sync.sh (deploy trusts the new token;
#                            the token itself stays local)
#      4. Push to prod     — railway up (redeploys, applying numReplicas:1 from
#                            railway.json — the single-replica fix that makes the
#                            remote MCP session reliable; see docs/SCALING.md).
#                            Skipped with --no-redeploy.
#      5. Wire clients     — connect.py --production --force into Claude Code,
#                            Codex, Claude Desktop, and Cursor (with the new token)
#      6. Wait (optional)  — poll the deploy's /health so it can tell you when the
#                            new build is live (skip with --no-wait)
#
#    Then it stops and tells you to restart your apps when you're ready — it does
#    NOT restart anything for you, and it never touches your Postgres / data.
#
#    Run from the repo root. The venv is auto-detected (or `source .venv/bin/activate`).
#
#    Usage:
#      ./scripts/setup_context.sh [--no-redeploy] [--no-rotate-key] [--no-wait]
#                                 [--ttl-days N] [--clients "claude-code codex …"]
#
#      --no-redeploy     skip the `railway up` redeploy — just rotate the token
#                        and rewire clients (the lightweight path)
#      --no-rotate-key   reuse the existing signing key (just re-mint the token +
#                        rewire); default is a full key rotation (clean slate)
#      --no-wait         don't poll /health after the redeploy; exit immediately
#      --ttl-days N      token lifetime in days (passed to the mint step)
#      --clients "..."   limit which MCP clients get wired (default: all four)
#
############################################################################

set -euo pipefail

BOLD='\033[1m'
DIM='\033[2m'
ORANGE='\033[38;5;208m'
GREEN='\033[32m'
RED='\033[31m'
NC='\033[0m'

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
cd "${REPO_ROOT}"

# ---- args -----------------------------------------------------------------
ROTATE_KEY=1
WAIT_FOR_HEALTH=1
REDEPLOY=1
TTL_ARGS=()
CLIENTS_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-redeploy) REDEPLOY=0; shift ;;
        --no-rotate-key) ROTATE_KEY=0; shift ;;
        --no-wait) WAIT_FOR_HEALTH=0; shift ;;
        --ttl-days) TTL_ARGS+=(--ttl-days "${2:?--ttl-days needs a value}"); shift 2 ;;
        --ttl-days=*) TTL_ARGS+=("$1"); shift ;;
        --clients) CLIENTS_ARG="${2:?--clients needs a value}"; shift 2 ;;
        --clients=*) CLIENTS_ARG="${1#*=}"; shift ;;
        -h|--help)
            cat <<'USAGE'
@context — connect every MCP client to the deployed instance (one command).

Usage: ./scripts/setup_context.sh [options]

  Default (full setup): railway login check -> reset stale client entries ->
  mint a fresh token (rotating the signing key) -> push the public key ->
  `railway up` redeploy (applies railway.json, e.g. numReplicas) -> wire
  Claude Code, Codex, Claude Desktop, Cursor -> wait for /health -> tell you
  to restart your apps. Never restarts apps for you; never touches Postgres.

  --no-redeploy    skip the `railway up` redeploy — just rotate the token and
                   rewire clients (env-sync still redeploys if the key changed)
  --no-rotate-key  reuse the existing signing key instead of rotating it
  --no-wait        don't poll /health after deploying; exit immediately
  --ttl-days N     token lifetime in days (passed to the mint step)
  --clients "..."  limit which clients get wired
                   (default: claude-code codex claude-desktop cursor)
USAGE
            exit 0 ;;
        *) echo "error: unknown option '$1' (try $0 --help)" >&2; exit 2 ;;
    esac
done

# connect.py takes --clients as space-separated values; default to all four.
CLIENTS_VALUES=(claude-code codex claude-desktop cursor)
[[ -n "$CLIENTS_ARG" ]] && read -r -a CLIENTS_VALUES <<< "$CLIENTS_ARG"

# Pick the venv python if we're not already in one (mint needs pyjwt + cryptography).
PY="python"
if [[ -z "${VIRTUAL_ENV:-}" && -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PY="${REPO_ROOT}/.venv/bin/python"
fi

step() { echo ""; echo -e "${BOLD}$1${NC}"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${ORANGE}!${NC} $1"; }

# ---- banner ---------------------------------------------------------------
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
echo -e "    ${DIM}@context · connect every MCP client to production.${NC}"

# ---- 0. preflight ---------------------------------------------------------
step "[0/6] Preflight"

if [[ ! -f .env.production ]]; then
    echo -e "  ${RED}✗${NC} .env.production not found. Provision first: ./scripts/railway/up.sh" >&2
    exit 1
fi
ok ".env.production present"

if ! command -v railway &> /dev/null; then
    echo -e "  ${RED}✗${NC} Railway CLI not found. Install: https://docs.railway.app/guides/cli" >&2
    exit 1
fi

# Log in if needed (interactive — opens a browser).
if railway whoami &> /dev/null; then
    ok "Railway: logged in as $(railway whoami 2>/dev/null | sed -E 's/.*as //; s/ .*//')"
else
    warn "Railway: not logged in — launching \`railway login\` (a browser will open)…"
    railway login
fi

if ! railway status &> /dev/null; then
    echo -e "  ${RED}✗${NC} Not linked to a Railway project. Run ./scripts/railway/up.sh first (it provisions + links)." >&2
    exit 1
fi
ok "Railway: linked to $(railway status 2>/dev/null | sed -nE 's/^Project: //p' | head -1)"

# Report the replica count we're about to deploy (1 = reliable remote MCP).
REPLICAS="$(grep -oE '"numReplicas"[[:space:]]*:[[:space:]]*[0-9]+' railway.json | grep -oE '[0-9]+' | head -1 || echo '?')"
if [[ "$REPLICAS" == "1" ]]; then
    ok "railway.json: numReplicas=1 (single replica → reliable MCP sessions)"
else
    warn "railway.json: numReplicas=${REPLICAS}. Remote MCP needs 1 replica to be reliable"
    warn "(no session affinity across replicas → 'Session not found'/502). Set it to 1 in railway.json."
fi

# ---- 1. reset clients -----------------------------------------------------
step "[1/6] Resetting MCP client entries (clean slate)"
# Match by name, so this clears any stale 'context' entry (local or prod) before
# we re-wire. Non-fatal: a client with nothing to remove is fine.
"$PY" scripts/connect.py --remove --clients "${CLIENTS_VALUES[@]}" || true

# ---- 2. mint fresh token --------------------------------------------------
step "[2/6] Minting the self-issued MCP token"
MINT_ARGS=(--write)
[[ "$ROTATE_KEY" == "1" ]] && MINT_ARGS+=(--rotate-key)
# Length-guard the append: macOS ships bash 3.2, where "${empty[@]}" under
# `set -u` is an "unbound variable" error, not an empty expansion.
[[ ${#TTL_ARGS[@]} -gt 0 ]] && MINT_ARGS+=("${TTL_ARGS[@]}")
"$PY" scripts/mint_mcp_jwt.py "${MINT_ARGS[@]}"

# ---- 3. sync public key to Railway ---------------------------------------
step "[3/6] Syncing the public key to Railway"
./scripts/railway/env-sync.sh

# ---- 4. push to production ------------------------------------------------
if [[ "$REDEPLOY" == "1" ]]; then
    step "[4/6] Pushing to production (applies numReplicas from railway.json)"
    railway up --service agent-os -d
else
    step "[4/6] Skipping \`railway up\` (--no-redeploy)"
    echo -e "  ${DIM}Just rotating the token + rewiring clients. (env-sync above still redeploys${NC}"
    echo -e "  ${DIM}when the signing key changed, so the new token takes effect either way.)${NC}"
fi

# ---- 5. wire clients ------------------------------------------------------
step "[5/6] Wiring the token into your MCP clients"
"$PY" scripts/connect.py --production --force --clients "${CLIENTS_VALUES[@]}"

# ---- 6. wait for the deploy (optional) ------------------------------------
# `|| true`: a missing AGENTOS_URL must not exit the script under `set -e` /
# `pipefail` — the wait below already degrades gracefully on an empty value.
AGENTOS_URL="$(grep -E '^AGENTOS_URL=' .env.production | head -1 | cut -d= -f2- || true)"
AGENTOS_URL="${AGENTOS_URL%\"}"; AGENTOS_URL="${AGENTOS_URL#\"}"     # strip surrounding "…"
AGENTOS_URL="${AGENTOS_URL%\'}"; AGENTOS_URL="${AGENTOS_URL#\'}"     # strip surrounding '…'
if [[ "$WAIT_FOR_HEALTH" == "1" && -n "$AGENTOS_URL" ]]; then
    step "[6/6] Waiting for the new build to come up (Ctrl-C to skip — clients are already wired)"
    echo -e "  ${DIM}Polling ${AGENTOS_URL}/health … a single replica has a brief swap window.${NC}"
    start=$(date +%s); deadline=$(( start + 300 )); seen_down=0; settled=0   # up to 5 minutes
    while [[ $(date +%s) -lt $deadline ]]; do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "${AGENTOS_URL}/health" 2>/dev/null || echo 000)"
        now=$(date +%s)
        if [[ "$code" == "200" ]]; then
            if [[ "$seen_down" == "1" ]]; then
                echo ""; ok "Deploy is live again (${AGENTOS_URL}/health → 200). New token + 1 replica are serving."
                settled=1; break
            elif (( now - start >= 60 )); then
                # Never caught a restart blip — either the rollout finished between
                # polls or hasn't started. Healthy for 60s is good enough to stop.
                echo ""; ok "Server healthy at ${AGENTOS_URL}/health. If Railway is still rolling out, give it a minute and confirm it's green before restarting clients."
                settled=1; break
            fi
            printf '  .'
        else
            seen_down=1   # caught the rollout swap; the next 200 is the new build
            printf '  .'
        fi
        sleep 5
    done
    [[ "$settled" == "0" ]] && { echo ""; warn "Still deploying after 5 min — check \`railway logs --service agent-os\`. Clients are wired; just restart once it's up."; }
else
    step "[6/6] Skipping health wait"
    echo -e "  ${DIM}The deploy is building on Railway (~3–5 min). Check: railway logs --service agent-os${NC}"
fi

# ---- done -----------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}Done.${NC} @context is deployed and your clients are wired."
echo ""
echo -e "${BOLD}Restart these whenever you're ready${NC} (no rush — the config is already saved):"
echo -e "  • ${BOLD}Claude Code${NC}    — quit & relaunch (or it reconnects on next run)"
echo -e "  • ${BOLD}Claude Desktop${NC} — fully quit (⌘Q) and reopen"
echo -e "  • ${BOLD}Cursor${NC}         — fully quit (⌘Q) and reopen"
if printf '%s\n' "${CLIENTS_VALUES[@]}" | grep -qx codex; then
    echo -e "  • ${BOLD}Codex${NC}          — add ${DIM}export CONTEXT_JWT=\$(grep '^CONTEXT_MCP_JWT=' .env.production | cut -d= -f2-)${NC} to your shell, then restart your shell"
fi
echo ""
echo -e "${DIM}ChatGPT can't be auto-wired (remote-connector only) — add ${AGENTOS_URL:-https://<domain>}/mcp"
echo -e "manually under Settings → Connectors with header 'Authorization: Bearer <token>' if you want it.${NC}"
echo ""
