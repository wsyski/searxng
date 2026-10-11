#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later

# The `searxng` skill is authored HERE, in this repo, and mirrored into the
# user skill hub at ~/.agents/skills/searxng so Claude Code, OpenCode and
# Hermes can load it.
#
# This is the inverse of the hub's own rule - "~/.agents is the sole source of
# truth for user-scoped shared capability" - and it was adopted deliberately,
# because the skill documents an instance this repo owns: its port, its
# categories, and three engines that exist only in searx/engines/. A skill that
# describes a deployment belongs next to the deployment.
#
# The cost is two copies and a sync step, and a sync step nobody runs is a
# silent divergence. So the sync is a target rather than a habit, and there is a
# check that reports drift instead of hiding it. The skill is a LISTED skill:
# the model never loads it unprompted, so a stale copy is invisible until
# someone types /searxng and gets the old text.
#
#   make skill.sync    copy skills/<name>/ -> $SKILL_HUB/<name>/
#   make skill.check   fail if the two trees differ (skips if the hub is absent)

# The logic lives in skills/sync.sh, byte-identical to the copy in
# /opt/playground/firecrawl; these targets only delegate to it. It mirrors every
# skills/<name>/ that holds a SKILL.md, and SKILL_HUB still overrides the hub.

skill.help() {
    cat <<EOF
  skill.:
    sync   : copy each skills/<name>/ -> \${SKILL_HUB:-~/.agents/skills}/<name>/
    check  : verify the hub copies match; non-zero on drift, skip if no hub
EOF
}

skill.sync() {
    "${REPO_ROOT}/skills/sync.sh" sync
}

skill.check() {
    "${REPO_ROOT}/skills/sync.sh" check
}
