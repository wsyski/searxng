#!/usr/bin/env bash
# deploy-docker.sh — redeploy this fork's local SearXNG to Docker: recreate the containers
# from the current compose files and env, pulling the pinned image first.
#
# The deployment is mount-based: container/docker-compose.yml runs the pinned upstream
# image, and container/docker-compose.override.yml bind-mounts the fork's engines and three
# core files over it. A mount is only read at container start, and PYTHONPYCACHEPREFIX takes
# effect the same way — so "the latest version" means RECREATE, not just `up` on running
# containers. That is the one thing this script does that a bare `docker compose up -d`
# silently skips.
#
#   bin/deploy-docker.sh             print the plan: compose files, image pin, running set
#   bin/deploy-docker.sh --apply     pull and recreate
#
# NO FLAG IS THE DRY RUN, like the sibling deploy-skills.sh. There is no --check: Docker
# reports its own state (`docker compose ps`) and there is no file tree to diff.
#
# Exit: 0 dry run printed or deployed, 1 a docker failure, 2 usage.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
COMPOSE_DIR="$REPO/container"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
# THE OVERRIDE IS NAMED EXPLICITLY. Compose loads `<file>.override.yml` automatically only
# for its default discovery; with an explicit --file it does not, and the deployment then
# starts the PINNED IMAGE with none of the fork's mounts, env or PYTHONPYCACHEPREFIX —
# measured 2026-10-31: `up` without this second --file crash-looped on
# "server.secret_key is not changed" because .env.prod arrived via the override only.
COMPOSE_OVERRIDE="$COMPOSE_DIR/docker-compose.override.yml"
SERVICE=core
PROJECT=searxng
APPLY=0
PULL=1

usage() {
cat <<'USAGE'
bin/deploy-docker.sh [--apply] [--no-pull]

  (no flag)   the dry run: the compose files, the image pin, the container set, nothing done
  --apply     pull the pinned image and recreate the containers
  --no-pull   with --apply: recreate from the image already on this host (no network)
  -h, --help  this text

Compose project: searxng, from container/docker-compose.yml plus the override it loads
automatically. Env: container/.env (committed) and container/.env.prod (gitignored).

Run it after ANY of: a change under searx/ (the override bind-mounts those files), a change
to container/, or a new SEARXNG_VERSION in container/.env. A running container keeps the
mounts and the environment it started with, so nothing changes until it is recreated.

Exit: 0 dry run printed or deployed, 1 a docker failure, 2 usage.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --no-pull) PULL=0; shift ;;
    --dry-run) shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "deploy-docker.sh: unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || { echo "deploy-docker.sh: no 'docker' on PATH" >&2; exit 2; }
[ -f "$COMPOSE_FILE" ] || { echo "deploy-docker.sh: no $COMPOSE_FILE" >&2; exit 1; }
[ -f "$COMPOSE_DIR/.env" ] || { echo "deploy-docker.sh: no $COMPOSE_DIR/.env" >&2; exit 1; }

compose() { docker compose --project-name "$PROJECT" \
  --file "$COMPOSE_FILE" --file "$COMPOSE_OVERRIDE" "$@"; }

# The config must parse before anything is printed as a plan: a refused manifest looks
# exactly like a plan followed by a deploy that recreated nothing.
if ! config="$(compose config 2>&1)"; then
  echo "deploy-docker.sh: container/docker-compose.yml does not resolve:" >&2
  printf '%s\n' "$config" >&2
  exit 1
fi
pin="$(sed -n 's/^SEARXNG_VERSION=//p' "$COMPOSE_DIR/.env" | tail -1)"

echo "deploy plan"
echo "  repo     $REPO"
echo "  compose  $COMPOSE_FILE (+ container/docker-compose.override.yml)"
echo "  project  $PROJECT"
echo "  image    ${pin:-unset in container/.env}"
echo "  command  docker compose up -d --force-recreate --remove-orphans $SERVICE$([ "$PULL" = 1 ] && printf ' --pull always' || printf ' --pull never')"
echo ""
echo "now running"
docker ps --filter "label=com.docker.compose.project=$PROJECT" \
          --format '  {{.Label "com.docker.compose.service"}}\t{{.Image}}\t{{.Status}}' 2>/dev/null || true

if [ "$APPLY" = 0 ]; then
  echo ""
  echo "dry run — nothing recreated. Re-run with --apply."
  exit 0
fi

echo ""
echo "redeploying"
if [ "$PULL" = 1 ]; then
  compose pull "$SERVICE" || { echo "deploy-docker.sh: pull failed" >&2; exit 1; }
fi
compose up -d --force-recreate --remove-orphans "$SERVICE" \
  || { echo "deploy-docker.sh: up failed" >&2; exit 1; }

echo ""
echo "deployed:"
compose ps
echo ""
host="$(sed -n 's/^SEARXNG_HOST=//p' "$COMPOSE_DIR/.env" | tail -1)"
port="$(sed -n 's/^SEARXNG_PORT=//p' "$COMPOSE_DIR/.env" | tail -1)"
echo "check: curl -s -o /dev/null -w '%{http_code}\\n' http://${host:-127.0.0.1}:${port:-8080}/healthz"
