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

# Where the hub keeps skills. Overridable so this works on a machine whose hub
# lives elsewhere, and so a test can point it at a scratch directory.
SKILL_HUB="${SKILL_HUB:-$HOME/.agents/skills}"

# One skill is mirrored. Named rather than globbed: a blanket copy would sweep
# in anything else that ever lands under skills/, including scratch files.
skill.name() {
    echo "searxng"
}

skill.src() {
    echo "${REPO_ROOT}/skills/$(skill.name)"
}

skill.dst() {
    echo "${SKILL_HUB}/$(skill.name)"
}

skill.help() {
    cat <<EOF
  skill.:
    sync   : copy skills/$(skill.name)/ -> ${SKILL_HUB}/$(skill.name)/
    check  : verify the hub copy matches; non-zero on drift, skip if no hub
EOF
}

skill.sync() {
    local src dst
    src="$(skill.src)"
    dst="$(skill.dst)"

    if [ ! -d "$src" ]; then
        err_msg "no such directory: $src"
        return 1
    fi

    build_msg SKILL "sync $(skill.name) -> ${dst}"

    mkdir -p "$dst"
    # --delete so a file removed here does not survive in the hub, which is
    # how a stale copy outlives the thing that replaced it.
    # --delete-excluded, not just --exclude: an excluded path is skipped by the
    # transfer AND left alone by --delete, so __pycache__ would sit in the hub
    # forever. The hub copy is read by path, Python will drop one there, and
    # every later sync would refuse to remove it.
    if command -v rsync >/dev/null; then
        rsync -a --delete --delete-excluded --exclude='__pycache__' "$src/" "$dst/"
    else
        rm -rf "$dst"
        mkdir -p "$dst"
        (cd "$src" && find . -name '__pycache__' -prune -o -type f -print) |
            while read -r f; do
                mkdir -p "$dst/$(dirname "$f")"
                cp "$src/$f" "$dst/$f"
            done
    fi
}

skill.check() {
    local src dst
    src="$(skill.src)"
    dst="$(skill.dst)"

    if [ ! -d "$src" ]; then
        err_msg "no such directory: $src"
        return 1
    fi

    # Not an error. CI and any other checkout do not have the hub, and a build
    # that fails because ~/.agents is missing teaches people to ignore it.
    if [ ! -d "$dst" ]; then
        build_msg SKILL "check $(skill.name) - no hub copy at ${dst}, skipping"
        return 0
    fi

    # Compare content, not metadata: a copy is not a clone, and mtimes differ
    # on every copy for reasons that have nothing to do with the skill.
    local out
    out="$(diff -r -x '__pycache__' "$src" "$dst" 2>&1)"
    if [ -z "$out" ]; then
        build_msg SKILL "check $(skill.name) - hub copy is in sync"
        return 0
    fi

    err_msg "hub copy of $(skill.name) differs from the repo:"
    echo "$out" >&2
    err_msg "run: make skill.sync"
    return 1
}