#!/bin/bash

############################################################################
#
#    @context Container Entrypoint
#
############################################################################

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

if [[ "$WAIT_FOR_DB" = true || "$WAIT_FOR_DB" = True ]]; then
    echo -e "    ${DIM}Waiting for database at ${DB_HOST}:${DB_PORT}...${NC}"
    dockerize -wait tcp://$DB_HOST:$DB_PORT -timeout 300s
    echo -e "    ${BOLD}Database ready.${NC}"
    echo ""
fi

# Gmail/Calendar OAuth token caches via env — the token files
# don't survive a redeploy on a baked image (Railway), so ship them as base64
# and the entrypoint restores them at startup. Paths mirror the defaults in
# agents/sources.py (GMAIL_TOKEN_FILE / CALENDAR_TOKEN_FILE override them). A
# token already on disk (e.g. mounted in dev via .:/app) wins and isn't touched.
materialize_token() {
    local b64="$1" path="$2" label="$3"
    if [[ -n "$b64" && ! -f "$path" ]]; then
        echo "$b64" | base64 -d > "$path"
        echo -e "    ${DIM}${label} token restored from base64 → ${path}.${NC}"
        echo ""
    fi
}
materialize_token "$GMAIL_TOKEN_JSON_B64" "${GMAIL_TOKEN_FILE:-/app/gmail_token.json}" "Gmail"
materialize_token "$CALENDAR_TOKEN_JSON_B64" "${CALENDAR_TOKEN_FILE:-/app/calendar_token.json}" "Calendar"

case "$1" in
    chill)
        echo -e "    ${DIM}Mode: chill${NC}"
        echo -e "    ${BOLD}Container running.${NC}"
        echo ""
        while true; do sleep 18000; done
        ;;
    *)
        echo -e "    ${DIM}> $@${NC}"
        echo ""
        exec "$@"
        ;;
esac
