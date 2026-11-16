#!/usr/bin/env bash
# Validate the plugin marketplace: manifests parse, every SKILL.md has name and description
# frontmatter, and plugin.json lists exactly the skill directories that exist on disk.
# Run from the repo root: .github/scripts/validate-plugins.sh [root]
set -uo pipefail

root="${1:-.}"
cd "${root}" || exit 1
errors=0

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  errors=$((errors + 1))
}

# 1. Every manifest is valid JSON.
manifests=()
while IFS= read -r file; do manifests+=("${file}"); done < <(
  find . -type f \( -name plugin.json -o -name marketplace.json \) -not -path './.git/*' | sort
)
[ "${#manifests[@]}" -gt 0 ] || fail "no plugin.json or marketplace.json found"
for file in "${manifests[@]}"; do
  if ! output="$(jq empty "${file}" 2>&1)"; then
    fail "invalid JSON in ${file}: ${output}"
  fi
done

# 2. Every SKILL.md opens with frontmatter that has name and description.
while IFS= read -r file; do
  if [ "$(head -n 1 "${file}")" != "---" ]; then
    fail "${file}: must start with a --- line"
    continue
  fi
  frontmatter="$(awk 'NR == 1 { next } /^---[[:space:]]*$/ { exit } { print }' "${file}")"
  if ! awk 'NR > 1 && /^---[[:space:]]*$/ { found = 1 } END { exit !found }' "${file}"; then
    fail "${file}: frontmatter has no closing --- line"
    continue
  fi
  for key in name description; do
    printf '%s\n' "${frontmatter}" | grep -Eq "^${key}:[[:space:]]*[^[:space:]]" \
      || fail "${file}: frontmatter is missing \"${key}\""
  done
done < <(find . -type f -name SKILL.md -not -path './.git/*' | sort)

# 3. Each plugin.json lists every skill directory on disk, and every listed skill exists.
for file in "${manifests[@]}"; do
  [ "$(basename "${file}")" = "plugin.json" ] || continue
  jq empty "${file}" >/dev/null 2>&1 || continue
  plugin_dir="$(dirname "$(dirname "${file}")")" # plugin.json lives in <plugin>/.claude-plugin/
  listed="$(jq -r '.skills // [] | .[]' "${file}" | sed 's|^\./||; s|/$||' | sort)"

  for skill in ${listed}; do
    [ -f "${plugin_dir}/${skill}/SKILL.md" ] \
      || fail "${file}: lists ${skill} but ${plugin_dir}/${skill}/SKILL.md does not exist"
  done

  on_disk="$(cd "${plugin_dir}" && find skills -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null \
    | sed 's|/SKILL.md$||' | sort)"
  for skill in ${on_disk}; do
    printf '%s\n' "${listed}" | grep -qx "${skill}" \
      || fail "${plugin_dir}/${skill} exists on disk but is not listed in ${file}"
  done
done

if [ "${errors}" -gt 0 ]; then
  printf '%d problem(s) found.\n' "${errors}" >&2
  exit 1
fi
echo "Plugin manifests and skills are valid."
