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

# Google service account via env — for platforms with no secret-file mounts
# (Railway). Base64 the JSON key into GOOGLE_SERVICE_ACCOUNT_JSON_B64 and the
# entrypoint materializes it; an explicit GOOGLE_SERVICE_ACCOUNT_FILE wins.
if [[ -n "$GOOGLE_SERVICE_ACCOUNT_JSON_B64" && -z "$GOOGLE_SERVICE_ACCOUNT_FILE" ]]; then
    echo "$GOOGLE_SERVICE_ACCOUNT_JSON_B64" | base64 -d > /app/google-service-account.json
    export GOOGLE_SERVICE_ACCOUNT_FILE=/app/google-service-account.json
    echo -e "    ${DIM}Google service account written from GOOGLE_SERVICE_ACCOUNT_JSON_B64.${NC}"
    echo ""
fi

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
