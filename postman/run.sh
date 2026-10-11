#!/usr/bin/env bash
# Run the SearXNG integration collection against the local instance
# (container/docker-compose.yml). No credentials: SearXNG has no authentication.
#
#   ./postman/run.sh                                        # everything
#   ./postman/run.sh --folder "News category search"
#   SEARXNG_URL=http://127.0.0.1:8080 ./postman/run.sh      # another address
#
# Bare SearXNG only: nothing here needs the firecrawl stack. The Firecrawl-backed
# scrapes (learn-answer, bankier.pl) live in the firecrawl project's collection,
# folder "External sources (Firecrawl scrape)", because those sources render
# client-side and cannot be fetched over plain HTTP.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

args=()
[[ -z "${SEARXNG_URL:-}" ]] || args+=(--env-var "searxngUrl=$SEARXNG_URL")

exec newman run \
  "$here/searxng-integration-test.postman_collection.json" \
  -e "$here/searxng-integration-test.postman_environment.json" \
  "${args[@]}" \
  "$@"