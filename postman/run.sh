#!/usr/bin/env bash
# Run the SearXNG integration collection against the local instance
# (container/docker-compose.yml). No credentials: SearXNG has no authentication.
#
#   ./postman/run.sh                                        # everything
#   ./postman/run.sh --folder "Direct JSON search"
#   SEARXNG_URL=http://127.0.0.1:8080 ./postman/run.sh      # another address
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

args=()
[[ -z "${SEARXNG_URL:-}" ]] || args+=(--env-var "searxngUrl=$SEARXNG_URL")

exec newman run \
  "$here/searxng-integration-test.postman_collection.json" \
  -e "$here/searxng-integration-test.postman_environment.json" \
  "${args[@]}" \
  "$@"
