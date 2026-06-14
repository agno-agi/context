#!/bin/bash

############################################################################
#
#    @context Google Setup — provisions the service-account auth path
#
#    Creates a GCP project + service account + JSON key so @context can
#    read and (with your approval) act on your Gmail and Google Calendar.
#
#    Unlike a read-only Drive bot, @context acts *as you* — so the service
#    account has to impersonate your mailbox/calendar via Google Workspace
#    domain-wide delegation. That last grant lives in the Workspace Admin
#    console, not in GCP, so no script can do it. This script does
#    everything `gcloud` can, then prints the exact Client ID + scopes for
#    you (or your Workspace admin) to paste — the one manual step.
#
#    This is the headless path (best for deploys). For a personal Gmail
#    account with no Workspace, use the OAuth path instead:
#      python scripts/google_mint_tokens.py   (see docs/GOOGLE.md)
#
#    Usage:    ./scripts/google_setup.sh
#    Prereqs:  `gcloud` installed and `gcloud auth login` completed,
#              plus a Google Workspace account (delegation needs one).
#
#    Interactive by default — prompts for the GCP project ID with a smart
#    default derived from your gcloud account (e.g. hello@agno.com →
#    context-agno). For CI / scripting, set CONTEXT_GCP_PROJECT_ID to skip
#    the prompt.
#
#    Overrides (export before running):
#      CONTEXT_GCP_PROJECT_ID    6-30 char globally-unique project ID.
#                                GCP project IDs share one namespace across
#                                all of Google Cloud (like S3 buckets).
#      CONTEXT_GCP_PROJECT_NAME  default: "Context"
#      CONTEXT_SA_NAME           default: context-agent  (6-30 chars)
#      CONTEXT_KEY_PATH          default: <repo>/google-service-account.json
#      CONTEXT_DELEGATED_USER    your email — prefills the printed env block
#
#    The default key path lives at the repo root (gitignored). A repo-relative
#    path resolves the same on the host and inside the container (cwd=/app via
#    the .:/app mount), so docker + CLI both see it.
#
#    Safe to re-run — reuses an existing project / service account if one is
#    already there, and writes a fresh key each time.
#
############################################################################

set -e

CURR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${CURR_DIR}")"

# Colors
ORANGE='\033[38;5;208m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

PROJECT_ID="${CONTEXT_GCP_PROJECT_ID:-}"
PROJECT_NAME="${CONTEXT_GCP_PROJECT_NAME:-Context}"
SA_NAME="${CONTEXT_SA_NAME:-context-agent}"
KEY_PATH="${CONTEXT_KEY_PATH:-${REPO_ROOT}/google-service-account.json}"
DELEGATED_USER="${CONTEXT_DELEGATED_USER:-}"

# The scopes @context's Gmail + Calendar providers use. Mint/delegate exactly
# these — nothing more. Kept in sync with docs/GOOGLE.md and the OAuth scopes
# in scripts/google_mint_tokens.py.
SCOPES=(
    "https://www.googleapis.com/auth/gmail.readonly"
    "https://www.googleapis.com/auth/gmail.modify"
    "https://www.googleapis.com/auth/gmail.compose"
    "https://www.googleapis.com/auth/calendar.readonly"
    "https://www.googleapis.com/auth/calendar"
)
SCOPES_CSV="$(IFS=,; echo "${SCOPES[*]}")"

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
echo -e "    ${DIM}Google Setup — service account for Gmail + Calendar${NC}"
echo ""

# Preflight
if ! command -v gcloud &> /dev/null; then
    echo -e "    ${ORANGE}gcloud CLI not found.${NC}"
    echo -e "    Install: ${DIM}https://cloud.google.com/sdk/docs/install${NC}"
    exit 1
fi

ACTIVE_ACCOUNT=$(gcloud config get-value account 2>/dev/null || true)
if [[ -z "$ACTIVE_ACCOUNT" ]] || [[ "$ACTIVE_ACCOUNT" == "(unset)" ]]; then
    echo -e "    ${ORANGE}gcloud is not authenticated.${NC}"
    echo -e "    Run: ${DIM}gcloud auth login${NC}"
    exit 1
fi

# Derive a sensible default project ID from the gcloud account:
#   enterprise email (e.g. hello@agno.com) → context-agno
#   personal email (gmail/icloud/etc.)     → context-<username>
DOMAIN_SLUG=$(echo "${ACTIVE_ACCOUNT}" | awk -F@ 'NF==2{print $2}' | awk -F. 'NF>=2{print $1}' | tr -cd 'a-z0-9-')
case "${DOMAIN_SLUG}" in
    gmail|googlemail|yahoo|ymail|hotmail|outlook|live|msn|icloud|me|mac|protonmail|proton|pm|aol|fastmail|zoho|tutanota|gmx|mail)
        DOMAIN_SLUG=""
        ;;
esac
if [[ -n "${DOMAIN_SLUG}" ]]; then
    DEFAULT_PROJECT_ID="context-${DOMAIN_SLUG}"
else
    USER_SLUG=$(whoami | tr '[:upper:]_' '[:lower:]-' | tr -cd 'a-z0-9-')
    DEFAULT_PROJECT_ID="context-${USER_SLUG:-agent}"
fi
# GCP requires 6-30 chars; safety pad / truncate.
while (( ${#DEFAULT_PROJECT_ID} < 6 )); do
    DEFAULT_PROJECT_ID="${DEFAULT_PROJECT_ID}x"
done
if (( ${#DEFAULT_PROJECT_ID} > 30 )); then
    DEFAULT_PROJECT_ID="${DEFAULT_PROJECT_ID:0:30}"
    DEFAULT_PROJECT_ID="${DEFAULT_PROJECT_ID%-}"
fi

if [[ -z "${PROJECT_ID}" ]]; then
    if [[ -t 0 ]]; then
        echo -e "    ${DIM}GCP project IDs are globally unique across all of Google Cloud${NC}"
        echo -e "    ${DIM}(like S3 bucket names). Something org-scoped works best.${NC}"
        echo ""
        read -r -p "    GCP Project ID [${DEFAULT_PROJECT_ID}]: " PROJECT_ID
        PROJECT_ID="${PROJECT_ID:-$DEFAULT_PROJECT_ID}"
        echo ""
    else
        echo -e "    ${ORANGE}CONTEXT_GCP_PROJECT_ID is required in non-interactive mode.${NC}"
        echo ""
        echo -e "    Example:"
        echo -e "      ${DIM}CONTEXT_GCP_PROJECT_ID=${DEFAULT_PROJECT_ID} ./scripts/google_setup.sh${NC}"
        exit 1
    fi
fi

# GCP requires 6-30 chars for both project IDs and service account names.
validate_length() {
    local value="$1" label="$2" len=${#1}
    if (( len < 6 || len > 30 )); then
        echo -e "    ${ORANGE}${label} must be 6-30 chars, got ${len}: '${value}'${NC}"
        exit 1
    fi
}
validate_length "${PROJECT_ID}" "CONTEXT_GCP_PROJECT_ID"
validate_length "${SA_NAME}"    "CONTEXT_SA_NAME"

echo -e "    ${DIM}Authenticated as ${ACTIVE_ACCOUNT}${NC}"
echo -e "    ${DIM}Project ID:     ${PROJECT_ID}${NC}"
echo -e "    ${DIM}Service acct:   ${SA_NAME}${NC}"
echo -e "    ${DIM}Key path:       ${KEY_PATH}${NC}"
echo ""

# Step 1 — project
echo -e "    ${DIM}[1/4] Creating GCP project...${NC}"
if gcloud projects describe "${PROJECT_ID}" &> /dev/null; then
    echo -e "    ${DIM}      project already exists, reusing${NC}"
else
    gcloud projects create "${PROJECT_ID}" --name="${PROJECT_NAME}" --quiet
    echo -e "    ${DIM}      created ${PROJECT_ID}${NC}"
fi
gcloud config set project "${PROJECT_ID}" --quiet 2>/dev/null

# Step 2 — enable APIs
#   gmail.googleapis.com         : the Gmail provider
#   calendar-json.googleapis.com : the Calendar provider (Calendar API's
#                                  service name is calendar-json, not calendar)
#   orgpolicy.googleapis.com     : lets step 4 auto-override the SA-key org
#                                  policy when enterprise orgs block key
#                                  creation. Without this, v2 org policies
#                                  aren't consulted and the override no-ops.
echo -e "    ${DIM}[2/4] Enabling APIs (Gmail + Calendar + Org Policy)...${NC}"
gcloud services enable \
    gmail.googleapis.com \
    calendar-json.googleapis.com \
    orgpolicy.googleapis.com \
    --project="${PROJECT_ID}" --quiet

# Step 3 — service account
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
echo -e "    ${DIM}[3/4] Creating service account...${NC}"
if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &> /dev/null; then
    echo -e "    ${DIM}      service account already exists, reusing${NC}"
else
    gcloud iam service-accounts create "${SA_NAME}" \
        --display-name="Context Agent" \
        --project="${PROJECT_ID}" \
        --quiet
    echo -e "    ${DIM}      created ${SA_EMAIL}${NC}"
fi

# Step 4 — key
echo -e "    ${DIM}[4/4] Generating JSON key...${NC}"
mkdir -p "$(dirname "${KEY_PATH}")"

create_key() {
    gcloud iam service-accounts keys create "${KEY_PATH}" \
        --iam-account="${SA_EMAIL}" \
        --project="${PROJECT_ID}" \
        --quiet 2>&1
}

KEY_OK=0
if KEY_ERR=$(create_key); then
    KEY_OK=1
fi

# Enterprise orgs commonly block SA key creation via
# constraints/iam.disableServiceAccountKeyCreation. If that's the specific
# blocker and the caller has policy-admin rights, apply a project-scoped
# override and retry. Requires roles/orgpolicy.policyAdmin on the org (or on
# the project via inheritance).
if [[ $KEY_OK -eq 0 ]] && echo "${KEY_ERR}" | grep -q "iam.disableServiceAccountKeyCreation"; then
    echo -e "    ${DIM}      org policy blocks key creation; applying project override...${NC}"
    if OVERRIDE_ERR=$(gcloud resource-manager org-policies disable-enforce \
        constraints/iam.disableServiceAccountKeyCreation \
        --project="${PROJECT_ID}" --quiet 2>&1); then
        sleep 2  # brief propagation window
        echo -e "    ${DIM}      override applied, retrying key creation...${NC}"
        if KEY_ERR=$(create_key); then
            KEY_OK=1
        fi
    else
        echo -e "    ${DIM}      override failed:${NC}"
        while IFS= read -r line; do
            echo -e "    ${DIM}      ${line}${NC}"
        done <<< "${OVERRIDE_ERR}"
    fi
fi

if [[ $KEY_OK -eq 0 ]]; then
    echo ""
    echo -e "    ${ORANGE}Key creation failed.${NC}"
    echo -e "    ${DIM}${KEY_ERR}${NC}"
    echo ""
    if echo "${KEY_ERR}" | grep -q "iam.disableServiceAccountKeyCreation"; then
        echo -e "    ${BOLD}This is a GCP org policy, not a script bug.${NC}"
        echo -e "    Your org blocks downloadable SA keys, and the script"
        echo -e "    tried to auto-apply a project-scoped override but you"
        echo -e "    don't have ${DIM}roles/orgpolicy.policyAdmin${NC}."
        echo ""
        echo -e "    ${BOLD}Fix:${NC} ask a GCP org admin to run:"
        echo ""
        echo "    gcloud resource-manager org-policies disable-enforce constraints/iam.disableServiceAccountKeyCreation --project=${PROJECT_ID}"
        echo ""
        echo -e "    Then rerun this script."
    fi
    exit 1
fi

chmod 600 "${KEY_PATH}"
echo -e "    ${DIM}      wrote ${KEY_PATH}${NC}"

# The numeric OAuth2 client ID of the service account — this is what the
# Workspace Admin console wants for the domain-wide delegation grant (not the
# SA email). Pull it from the SA itself so it's correct even on reruns.
SA_CLIENT_ID=$(gcloud iam service-accounts describe "${SA_EMAIL}" \
    --project="${PROJECT_ID}" --format="value(oauth2ClientId)" 2>/dev/null || true)

# Copy the client ID to the clipboard — it's the first thing you paste.
CLIPBOARD_MSG=""
if [[ -n "${SA_CLIENT_ID}" ]]; then
    if command -v pbcopy &> /dev/null; then
        echo -n "${SA_CLIENT_ID}" | pbcopy
        CLIPBOARD_MSG="(copied to clipboard)"
    elif command -v xclip &> /dev/null; then
        echo -n "${SA_CLIENT_ID}" | xclip -selection clipboard
        CLIPBOARD_MSG="(copied to clipboard)"
    fi
fi

# Prefer a repo-relative path for the env var if the key is under REPO_ROOT.
# Relative paths resolve the same on the host (cwd=repo root) and in the
# container (cwd=/app via .:/app mount), so docker + CLI both work.
if [[ "${KEY_PATH}" == "${REPO_ROOT}/"* ]]; then
    ENV_VALUE="${KEY_PATH#${REPO_ROOT}/}"
else
    ENV_VALUE="${KEY_PATH}"
fi
DELEGATED_VALUE="${DELEGATED_USER:-you@yourdomain.com}"

echo ""
echo -e "    ${BOLD}Done.${NC} @context's identity: ${BOLD}${SA_EMAIL}${NC}"
echo ""
echo -e "    ${BOLD}Next — two steps:${NC}"
echo ""
echo -e "    ${BOLD}1. Grant domain-wide delegation${NC} ${DIM}(Workspace admin, one-time)${NC}"
echo -e "       The one step gcloud can't do — it lives in the Workspace admin"
echo -e "       console. Go to ${DIM}admin.google.com${NC} → Security → Access and"
echo -e "       data control → API controls → Manage Domain Wide Delegation →"
echo -e "       ${BOLD}Add new${NC}, and paste:"
echo ""
echo -e "       Client ID:  ${BOLD}${SA_CLIENT_ID:-<run: gcloud iam service-accounts describe ${SA_EMAIL} --format='value(oauth2ClientId)'>}${NC} ${DIM}${CLIPBOARD_MSG}${NC}"
echo -e "       OAuth scopes (comma-separated):"
echo -e "       ${DIM}${SCOPES_CSV}${NC}"
echo ""
echo -e "    ${BOLD}2. Point @context at the key${NC} — add to ${DIM}${REPO_ROOT}/.env${NC}:"
echo -e "       ${DIM}GOOGLE_SERVICE_ACCOUNT_FILE=${ENV_VALUE}${NC}"
echo -e "       ${DIM}GOOGLE_DELEGATED_USER=${DELEGATED_VALUE}${NC}   ${DIM}# the mailbox/calendar to act as${NC}"
echo ""
echo -e "       Then restart: ${DIM}docker compose up -d${NC}"
echo ""
echo -e "    ${DIM}Deploying to Railway (no secret-file mounts)? Ship the key as${NC}"
echo -e "    ${DIM}base64 instead of a file — the entrypoint materializes it:${NC}"
echo -e "       ${DIM}echo \"GOOGLE_SERVICE_ACCOUNT_JSON_B64=\$(base64 < ${ENV_VALUE})\" >> .env.production${NC}"
echo ""
