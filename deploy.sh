#!/bin/sh
# Deploys the dashboard to Vercel as plain static files: web/ plus a fresh data/processed/dashboard.json.
# Git pushes never deploy (see vercel.json): the data is not in git, so this script is the only way to publish.
# It uploads from a temporary copy holding only those files, so .env and the CSVs are never included.
set -e

ROOT=$(cd "$(dirname "$0")" && pwd)
BUILD=$(mktemp -d)
trap 'rm -rf "${BUILD:?}"' EXIT

# Rebuild the JSON first so the deploy always matches the latest pipeline output
(cd "$ROOT" && python -m pipeline.export)

mkdir -p "$BUILD/data/processed"
cp -R "$ROOT/web" "$BUILD/"
cp "$ROOT/data/processed/dashboard.json" "$BUILD/data/processed/"

# No build step, just serve the files. The page lives at /web/, so send the bare URL there.
cat > "$BUILD/vercel.json" <<'JSON'
{ "framework": null, "redirects": [{ "source": "/", "destination": "/web/" }] }
JSON

vercel link --yes --project frc-scouting --cwd "$BUILD"
vercel deploy --prod --yes --cwd "$BUILD"
