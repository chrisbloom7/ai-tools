#!/usr/bin/env bash
# PostToolUse hook: validate an edited plugin.json, marketplace.json or SKILL.md.
# JSON files get `jq empty`; SKILL.md must open with a frontmatter block that has name and description.
# Skips quietly when jq is missing, so it never blocks a contributor without it.
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0

file="$(jq -r '.tool_input.file_path // empty')"
[ -f "${file}" ] || exit 0

case "${file}" in
  */plugin.json | */marketplace.json)
    if ! output="$(jq empty "${file}" 2>&1)"; then
      printf 'Invalid JSON in %s:\n%s\n' "${file}" "${output}" >&2
      exit 2
    fi ;;
  */SKILL.md)
    if [ "$(head -n 1 "${file}")" != "---" ]; then
      printf 'Missing frontmatter in %s: the file must start with a --- line.\n' "${file}" >&2
      exit 2
    fi
    frontmatter="$(awk 'NR == 1 { next } /^---[[:space:]]*$/ { found = 1; exit } { print }' "${file}")"
    if ! awk 'NR == 1 { next } /^---[[:space:]]*$/ { found = 1 } END { exit !found }' "${file}"; then
      printf 'Unterminated frontmatter in %s: no closing --- line.\n' "${file}" >&2
      exit 2
    fi
    for key in name description; do
      if ! printf '%s\n' "${frontmatter}" | grep -Eq "^${key}:[[:space:]]*[^[:space:]]"; then
        printf 'Frontmatter in %s is missing "%s".\n' "${file}" "${key}" >&2
        exit 2
      fi
    done ;;
  *) exit 0 ;;
esac
exit 0
