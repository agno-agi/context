#!/bin/bash

############################################################################
#
#    @context — connect your MCP clients to the deployed instance, end to end.
#
#    Runs the three steps so you don't have to:
#      1. mint_mcp_jwt.py --write  — self-issue the keypair + admin token and
#                                    write CONTEXT_SELF_VERIFICATION_KEY (public
#                                    key) + CONTEXT_MCP_JWT (token) to
#                                    .env.production
#      2. railway/env-sync.sh      — push the public key so the deploy trusts
#                                    your token (the token itself stays local)
#      3. connect.py --production   — thread the token into Claude Code, Codex,
#                                    and Claude Desktop (and always-allow the
#                                    ask_context tool in Claude Code so it never
#                                    prompts)
#
#    Run from the repo root, inside the venv (source .venv/bin/activate).
#    Re-run any time to rotate the token. Pass --rotate-key to also regenerate
#    the signing keypair (invalidates previously minted tokens); pass --force to
#    re-add the MCP clients even if they're already connected.
#
#    Usage:
#      ./scripts/setup_production_mcp.sh [--rotate-key] [--ttl-days N] [--force]
#
############################################################################

set -e

BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"
cd "${REPO_ROOT}"

# Pick the venv python if we're not already in one (mint needs pyjwt + cryptography).
PY="python"
if [[ -z "$VIRTUAL_ENV" && -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PY="${REPO_ROOT}/.venv/bin/python"
fi

# Route flags to the step that owns them: --rotate-key / --ttl-days configure the
# mint (step 1), --force re-adds the MCP clients (step 3, connect.py). Splitting
# them keeps a wrapper flag from ever landing on the wrong tool's argparse.
MINT_ARGS=()
CONNECT_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) CONNECT_ARGS+=("$1"); shift ;;
        --rotate-key) MINT_ARGS+=("$1"); shift ;;
        --ttl-days) MINT_ARGS+=("$1" "${2:?--ttl-days needs a value}"); shift 2 ;;
        --ttl-days=*) MINT_ARGS+=("$1"); shift ;;
        -h|--help)
            echo "Usage: $0 [--rotate-key] [--ttl-days N] [--force]"
            echo "  --rotate-key   regenerate the signing keypair (invalidates old tokens)"
            echo "  --ttl-days N   token lifetime in days"
            echo "  --force        re-add the MCP clients even if already connected"
            exit 0 ;;
        *) echo "error: unknown option '$1' (try $0 --help)" >&2; exit 2 ;;
    esac
done

echo ""
echo -e "${BOLD}[1/3] Minting the self-issued MCP token${NC}"
"$PY" scripts/mint_mcp_jwt.py --write "${MINT_ARGS[@]}"

echo ""
echo -e "${BOLD}[2/3] Syncing the public key to Railway${NC}"
./scripts/railway/env-sync.sh

echo ""
echo -e "${BOLD}[3/3] Wiring the token into your MCP clients${NC}"
"$PY" scripts/connect.py --production "${CONNECT_ARGS[@]}"

echo ""
echo -e "${BOLD}Done.${NC}"
echo -e "${DIM}The token works once Railway finishes redeploying with the new public key."
echo -e "Restart Claude Desktop if it was configured; CLI clients pick it up immediately.${NC}"
echo ""
