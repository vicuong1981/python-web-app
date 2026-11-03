#!/usr/bin/env bash
# Create this app's feature flags in Cloudflare Flagship.
#
# Needs Node.js. Log in first with `npx wrangler login`, or set
# CLOUDFLARE_API_TOKEN to a token with the Flagship write permission.
#
# Usage:
#   ./scripts/create_flags.sh              # creates the Flagship app, then the flags
#   ./scripts/create_flags.sh <APP_ID>     # adds the flags to an existing app
set -euo pipefail

WRANGLER="npx --yes wrangler@latest"
APP_ID="${1:-}"

if [ -z "$APP_ID" ]; then
  echo "Creating Flagship app 'python-web-app'..."
  APP_ID=$($WRANGLER flagship apps create python-web-app --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
fi
echo "Flagship app ID: $APP_ID"

# Redesigned homepage: off by default, rolled out to 25% of users (sticky per user).
$WRANGLER flagship flags create "$APP_ID" new-homepage \
  -V on=true -V off=false --default off --type boolean \
  --description "Show the redesigned homepage" \
  --rule "serve=on; rollout=25%@targetingKey"

# Kill switch for the notes API: on by default; turn off to return 503s.
$WRANGLER flagship flags create "$APP_ID" notes-api \
  -V on=true -V off=false --default on --type boolean \
  --description "Kill switch for the notes API"

# Max note length: 500 for everyone, 2000 for the pro plan.
$WRANGLER flagship flags create "$APP_ID" max-note-length \
  -V standard=500 -V pro=2000 --default standard --type number \
  --description "Maximum characters per note" \
  --rule "serve=pro; when=plan equals pro"

cat <<EOF

Done. To use these flags, set these environment variables for the app:
  FLAGSHIP_APP_ID=$APP_ID
  CLOUDFLARE_ACCOUNT_ID=<your Cloudflare account ID>
  FLAGSHIP_API_TOKEN=<a token with the Flagship Evaluate permission>
EOF
