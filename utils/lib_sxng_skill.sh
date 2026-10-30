#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later

# The `searxng` skill is authored HERE, in this repo, and mirrored into the
# user skill hub at ~/.agents/skills/searxng so Claude Code, OpenCode and
# Hermes can load it.
#
# This is the inverse of the hub's own rule - "~/.agents is the sole source of
# truth for user-scoped shared capability" - and it was adopted deliberately,
# because the skill documents an instance this repo owns: its port, its
# categories, and six finance engines that exist only in searx/engines/. A skill
# that describes a deployment belongs next to the deployment.
#
# The cost is two copies and a sync step, and a sync step nobody runs is a
# silent divergence. So the sync is a target rather than a habit, and there is a
# check that reports drift instead of hiding it. The skill is a LISTED skill:
# the model never loads it unprompted, so a stale copy is invisible until
# someone types /searxng and gets the old text.
#
#   make skill.sync    copy skills/<name>/ -> $SKILL_HUB/<name>/
#   make skill.check   fail if the two trees differ (skips if the hub is absent)
#   make skill.test    run the skill's own stdlib unittest suite

# The logic lives in skills/sync.sh, byte-identical to the copy in
# /opt/playground/firecrawl; these targets only delegate to it. It mirrors every
# skills/<name>/ that holds a SKILL.md, and SKILL_HUB still overrides the hub.

# The linter the IDE plugin runs over the agent configs (see .agnix.toml). uvx
# fetches it — a wheel with a prebuilt binary — so nothing is compiled and
# nothing has to be on PATH. A host with no network and no uvx cache SKIPS, the
# same call skill.check makes when the hub is absent; .github/workflows/skills.yml
# turns a skip back into a failure, because a validator that skipped validated
# nothing.
SKILL_AGNIX="agnix==0.57.0"

skill.help() {
    cat <<EOF
  skill.:
    sync     : copy each skills/<name>/ -> \${SKILL_HUB:-~/.agents/skills}/<name>/
    check    : verify the hub copies match; non-zero on drift, skip if no hub
    validate : lint every SKILL.md with agnix; non-zero on an error, skip if no uvx
    test     : run skills/*/tests with stdlib unittest; non-zero on a failure
EOF
}

skill.sync() {
    "${REPO_ROOT}/skills/sync.sh" sync
}

skill.check() {
    "${REPO_ROOT}/skills/sync.sh" check
}

# Found rather than listed, for the same reason skill.validate does it: a glob
# that no longer matches would leave the step passing over everything.
skill.test() {
    build_msg TEST "[skill] unittest"
    local dir
    local dirs=()
    for dir in "${REPO_ROOT}"/skills/*/tests; do
        if [ -d "$dir" ]; then
            dirs+=("$dir")
        fi
    done
    if [ "${#dirs[@]}" -eq 0 ]; then
        err_msg "no skills/*/tests directory - the glob is wrong"
        return 1
    fi
    for dir in "${dirs[@]}"; do
        # Deliberately NOT ./manage pyenv.cmd: sxq is stdlib-only and must keep
        # working on a host with no venv, so its tests have to as well. The venv
        # is dropped from PATH for the same reason - the tests then run on the
        # same interpreter sxq itself would use standalone, which is the one
        # thing worth asserting about them. That also makes the step behave
        # identically whether or not `make install` has run: the skills.yml job
        # has no venv, this host does. A failing suite returns immediately
        # rather than being counted and summarised - a green step here has to
        # mean the tests ran.
        PATH="${PATH#"${PY_ENV_BIN}":}" python3 -m unittest discover -s "$dir" -v || return 1
    done
    build_msg TEST "[skill] unittest OK - ${#dirs[@]} suite(s)"
}

# agnix's JSON report on stdout; non-zero when it cannot be run or parsed. The
# exit code is not a verdict: agnix exits 1 whenever it has anything to report,
# so the caller reads the body, not the status.
_skill.agnix() {
    local repo="$1"
    shift
    local out
    out="$(cd "$repo" && uvx "$SKILL_AGNIX" "$@" --format json 2>/dev/null)" || true
    if ! jq -e . >/dev/null 2>&1 <<<"$out"; then
        return 1
    fi
    printf '%s' "$out"
}

# The premise behind targeting claude-code instead of the generic spec: nested
# metadata.hermes is an error there and accepted here. Asserted, because agnix
# may change either behaviour and a stale premise is how the config quietly stops
# being the reason the repo is clean. Run in a temp dir with NO .agnix.toml: the
# config's runtime overrides --target, so comparing targets inside the repo would
# compare claude-code with claude-code.
_skill.validate_premise() {
    local dir generic claude
    dir="$(mktemp -d)"
    printf -- '%s\n' \
        '---' \
        'name: zz-agnix-probe' \
        'description: A probe carrying Hermes nested metadata.' \
        'metadata:' \
        '  hermes:' \
        '    requires_tools:' \
        '      - __manual_command_only__' \
        '---' \
        'body' >"${dir}/SKILL.md"

    generic="$(_skill.agnix "$dir" . --target generic)" || true
    claude="$(_skill.agnix "$dir" . --target claude-code)" || true
    rm -rf "$dir"

    if ! jq -e '[.diagnostics[] | select(.level == "error")] | length > 0' \
        >/dev/null 2>&1 <<<"$generic"; then
        err_msg "the universal target accepts nested metadata.hermes - the premise of the claude-code target has changed"
        return 1
    fi
    if ! jq -e '[.diagnostics[] | select(.level == "error")] | length == 0' \
        >/dev/null 2>&1 <<<"$claude"; then
        err_msg "claude-code rejects nested metadata.hermes too - choosing the target cannot be what makes this skill valid"
        return 1
    fi
}

# Every SKILL.md validates under the same linter the IDE plugin runs. A file
# that will not parse is a skill that will not load, and because the skill is
# mirrored to the hub (see skill.check) the broken copy would be the one three
# harnesses read. Skips when uvx or jq is absent; CI treats that as a failure.
skill.validate() {
    build_msg TEST "[skill] agnix ${SKILL_AGNIX}"

    if ! command -v uvx >/dev/null 2>&1; then
        echo "SKILL_VALIDATE_SKIPPED: uvx is not installed"
        return 0
    fi
    if ! command -v jq >/dev/null 2>&1; then
        echo "SKILL_VALIDATE_SKIPPED: jq is not installed"
        return 0
    fi

    # Found rather than listed, because a skill added anywhere else would then
    # be silently unvalidated.
    local file
    local skills=()
    for file in "${REPO_ROOT}"/skills/*/SKILL.md \
        "${REPO_ROOT}"/.claude/skills/*/SKILL.md; do
        if [ -f "$file" ]; then
            skills+=("$file")
        fi
    done
    if [ "${#skills[@]}" -eq 0 ]; then
        err_msg "no SKILL.md found - the globs are wrong"
        return 1
    fi

    local report
    if ! report="$(_skill.agnix "$REPO_ROOT" .)"; then
        err_msg "agnix produced no readable report; is .agnix.toml valid?"
        return 1
    fi

    local errors
    errors="$(jq '[.diagnostics[] | select(.level == "error")] | length' <<<"$report")"
    if [ "$errors" -ne 0 ]; then
        jq -r '.diagnostics[] | select(.level == "error") | "  \(.rule) \(.file):\(.line)  \(.message)"' <<<"$report"
        err_msg "${errors} agnix error(s) - fix the config or the files it names"
        return 1
    fi

    # Every skill was actually LOOKED AT: agnix walks the tree, so a skill it
    # never read would leave no finding and the check above would pass over it.
    local checked
    checked="$(jq '.files_checked // 0' <<<"$report")"
    if [ "$checked" -lt "${#skills[@]}" ]; then
        err_msg "agnix examined ${checked} file(s) but this repo holds ${#skills[@]} SKILL.md - it is reading a different tree"
        return 1
    fi

    # A deliberate break IS caught, so the check above is known to be able to
    # fail. Handed to agnix EXPLICITLY: its walk skips dot-directories, so a
    # probe under .agnix-probe/ is invisible to a bare '.' scan. The committed
    # config still resolves from the repo root, which pins it to a runtime rather
    # than a suppression - an unquoted-colon description is caught under every
    # target, so a config that disabled AS-016 would leave this silent.
    local probe="${REPO_ROOT}/.agnix-probe" broke
    mkdir -p "${probe}/skills/zz-agnix-probe"
    printf -- '%s\n' \
        '---' \
        'name: zz-agnix-probe' \
        'description: deliberately broken: an unquoted colon' \
        '---' \
        'body' >"${probe}/skills/zz-agnix-probe/SKILL.md"
    broke="$(_skill.agnix "$REPO_ROOT" .agnix-probe)" || true
    rm -rf "$probe"
    if ! jq -e '[.diagnostics[] | select(.level == "error")] | length > 0' \
        >/dev/null 2>&1 <<<"$broke"; then
        err_msg "agnix reports no error for a SKILL.md whose frontmatter cannot parse - the check above cannot fail and proves nothing"
        return 1
    fi

    _skill.validate_premise || return 1

    build_msg TEST "[skill] agnix OK - ${#skills[@]} SKILL.md, ${checked} files"
}
