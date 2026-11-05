#!/bin/sh
# Deploys the dashboard and its data to Vercel. Run this after a backend run to publish new results.
# It uploads from a temporary copy holding only the files below, so .env can never be included.
set -e

ROOT=$(cd "$(dirname "$0")" && pwd)
BUILD=$(mktemp -d)
trap 'rm -rf "${BUILD:?}"' EXIT

cp -R "$ROOT/pipeline" "$ROOT/dashboard" "$ROOT/data" "$ROOT/index.py" "$ROOT/requirements.txt" "$BUILD/"

vercel link --yes --project frc-scouting --cwd "$BUILD"
vercel deploy --prod --yes --cwd "$BUILD"
