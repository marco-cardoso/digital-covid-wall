#!/usr/bin/env bash
# Deploys the website to dev, https://dev.covidwall.co.uk.
#
# Tests and builds the frontend, uploads it, a snapshot of the dashboard's API answers (dev has no backend) and the
# stitched wall tiles to the dev bucket, then clears CloudFront's cache. The bucket, CloudFront and the contact form's
# Lambda come from terraform/environments/dev; --infra applies that first (Terraform asks before changing anything).
#
#   scripts/deploy_dev.sh                 test, build and upload
#   scripts/deploy_dev.sh --dry-run       show what would be uploaded; change nothing
#   scripts/deploy_dev.sh --infra         terraform apply for dev first
#   scripts/deploy_dev.sh --skip-wall     leave the wall tiles as they are (783 MB, 13,500 files)
#   scripts/deploy_dev.sh --skip-tests    skip the frontend tests and lint
#
# Uses whatever AWS credentials the shell has (AWS_PROFILE etc.). Never uploads public/pictures, the source photos.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/terraform/environments/dev"
FRONTEND="$ROOT/frontend"
SITE_URL="https://dev.covidwall.co.uk"

DRY_RUN=0 INFRA=0 SKIP_WALL=0 SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --infra) INFRA=1 ;;
    --skip-wall) SKIP_WALL=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    -h | --help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { echo "Error: $*" >&2; exit 1; }

for tool in aws terraform npm; do
  command -v "$tool" >/dev/null || die "$tool is not installed."
done
[ -d "$ENV_DIR" ] || die "$ENV_DIR is missing (the Terraform environments are kept on disk, not in git)."

step "AWS account"
aws sts get-caller-identity --query '[Account, Arn]' --output text || die "no AWS credentials; set AWS_PROFILE or log in."

if [ "$INFRA" = 1 ]; then
  [ "$DRY_RUN" = 1 ] && die "--infra and --dry-run together: run 'terraform plan' in $ENV_DIR to preview instead."
  step "Infrastructure (terraform apply, dev)"
  terraform -chdir="$ENV_DIR" init -input=false >/dev/null
  terraform -chdir="$ENV_DIR" apply
fi

BUCKET="$(terraform -chdir="$ENV_DIR" output -raw site_bucket)"
DISTRIBUTION="$(terraform -chdir="$ENV_DIR" output -raw site_distribution_id)"
echo "Bucket: $BUCKET   Distribution: $DISTRIBUTION"

if ! terraform -chdir="$ENV_DIR" output -raw contact_table >/dev/null 2>&1; then
  echo "Note: the contact form's Lambda is not deployed yet, so messages sent on dev will fail. Run with --infra."
fi

step "Frontend build"
cd "$FRONTEND"
[ -d node_modules ] || npm ci
if [ "$SKIP_TESTS" = 0 ]; then
  npm test
  npm run lint
fi
rm -rf dist
COPY_PUBLIC_DIR=0 npm run build

# Dev has no backend, so the dashboard's read-only API answers are saved from the local data and served as files
# at the same paths (/api/stats, /api/insights, /api/tributes). /api/feedback still goes to the Lambda.
step "API snapshot for the dashboard"
PYTHON="$ROOT/backend/.venv/bin/python"
[ -x "$PYTHON" ] || die "backend/.venv is missing; set up the backend first (README: Running locally)."
SNAPSHOT="$(mktemp -d)"
trap 'rm -rf "$SNAPSHOT"' EXIT
"$PYTHON" "$ROOT/scripts/snapshot_api.py" "$SNAPSHOT"

# The known-good list for the tamper monitor: everything the bucket will hold after this deploy, local wall tiles
# included (with --skip-wall the bucket's tiles are expected to match them). It is recorded twice: before the
# upload, marked as a deploy under way, so the monitor expects files to be missing or old for a while; and once
# CloudFront serves the new site, as final.
step "Known-good list"
INTEGRITY="$(terraform -chdir="$ENV_DIR" output -raw integrity_bucket 2>/dev/null || true)"
"$PYTHON" "$ROOT/scripts/site_manifest.py" --site dev --url "$SITE_URL" --out "$SNAPSHOT/manifest.json" \
  --map dist/index.html=index.html --map dist/assets=assets \
  --map public/favicon.svg=favicon.svg --map public/icons.svg=icons.svg \
  --map "$SNAPSHOT/api=api" --map public/wall=wall --exclude ".DS_Store"
"$PYTHON" -c 'import json, sys
from datetime import datetime, timedelta, timezone
m = json.load(open(sys.argv[1]))
m["deploying_until"] = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
json.dump(m, open(sys.argv[2], "w"), separators=(",", ":"))' "$SNAPSHOT/manifest.json" "$SNAPSHOT/manifest-deploying.json"
[ -n "$INTEGRITY" ] || echo "Note: the tamper monitor is not deployed yet (no integrity bucket); the list is not recorded."

# A dry run lists every file it would upload; a real one reports only problems.
DRY=() QUIET=(--only-show-errors)
[ "$DRY_RUN" = 1 ] && DRY=(--dryrun) QUIET=()
S3="s3://$BUCKET"

if [ -n "$INTEGRITY" ] && [ "$DRY_RUN" = 0 ]; then
  aws s3 cp "$SNAPSHOT/manifest-deploying.json" "s3://$INTEGRITY/manifest.json" --only-show-errors \
    --content-type "application/json"
  echo "Recorded: deploy under way."
fi

step "Upload: the app"
# Bundles have hashed names, so they can be cached for good. Old ones are removed, so the bucket holds exactly what
# the known-good list says.
aws s3 sync dist/assets "$S3/assets" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} --delete \
  --cache-control "public, max-age=31536000, immutable"
# The few unhashed files the page links to.
aws s3 sync public "$S3" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} \
  --exclude "*" --include "favicon.svg" --include "icons.svg" \
  --cache-control "public, max-age=86400"
# The API snapshot: JSON under extension-less names, rechecked on every visit like the live API would be.
aws s3 sync "$SNAPSHOT/api" "$S3/api" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} \
  --content-type "application/json" --cache-control "no-cache"

if [ "$SKIP_WALL" = 0 ]; then
  [ -f public/wall/wall.json ] || die "no wall tiles in frontend/public/wall (they are not in git); use --skip-wall."
  step "Upload: the wall tiles (only what changed)"
  # Like nginx.conf: tiles keep a week; wall.json, which names the current build, is always checked.
  aws s3 sync public/wall "$S3/wall" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} --delete \
    --exclude "wall.json" --exclude "*.dzi" --exclude "*.DS_Store" \
    --cache-control "public, max-age=604800"
  aws s3 sync public/wall "$S3/wall" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} \
    --exclude "*" --include "*.dzi" \
    --content-type "application/xml" --cache-control "public, max-age=604800"
  aws s3 cp public/wall/wall.json "$S3/wall/wall.json" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} \
    --content-type "application/json" --cache-control "no-cache"
fi

step "Upload: index.html, last, so it only points at files that are there"
aws s3 cp dist/index.html "$S3/index.html" ${DRY[@]+"${DRY[@]}"} ${QUIET[@]+"${QUIET[@]}"} \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache"

if [ "$DRY_RUN" = 1 ]; then
  step "Dry run: nothing was uploaded, and CloudFront's cache was left alone"
  exit 0
fi

step "Clear CloudFront's cache"
INVALIDATION="$(aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths "/*" \
  --query Invalidation.Id --output text)"
echo "Invalidation $INVALIDATION started; waiting for it (a minute or two)."
aws cloudfront wait invalidation-completed --distribution-id "$DISTRIBUTION" --id "$INVALIDATION"

if [ -n "$INTEGRITY" ]; then
  step "Known-good list: final"
  aws s3 cp "$SNAPSHOT/manifest.json" "s3://$INTEGRITY/manifest.json" --only-show-errors \
    --content-type "application/json"
  echo "Recorded. The monitor now checks the site against this deploy."
fi

step "Deployed: $SITE_URL"
