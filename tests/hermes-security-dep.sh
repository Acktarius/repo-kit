#!/usr/bin/env bash
# Hermes extension dependency: --ext hermes installs the security module (and
# base) through the normal module installer. hermesVPS keeps policy assets in
# its prefix and does not write the security module into an assessment source.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

export HOME="${TMP}/home"
mkdir -p "${HOME}"
unset HERMES_HOME

fail=0
ok() { echo "PASS: $*"; }
bad() { echo "FAIL: $*" >&2; fail=1; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL: missing host command $1" >&2
    exit 1
  }
}
need git
need python3
need cmp
need sha256sum

line_no() {
  local file="$1" pattern="$2"
  grep -n "${pattern}" "${file}" | head -1 | cut -d: -f1 || true
}

assert_module_tree() {
  local target="$1" label="$2"
  local src rel
  while IFS= read -r -d '' src; do
    rel="${src#"${ROOT}/modules/security/files"/}"
    if [[ ! -f "${target}/${rel}" ]]; then
      bad "${label}: missing security module file ${rel}"
    elif ! cmp -s "${src}" "${target}/${rel}"; then
      bad "${label}: security module file differs: ${rel}"
    fi
  done < <(find "${ROOT}/modules/security/files" -type f -print0 | sort -z)
  while IFS= read -r -d '' src; do
    rel="${src#"${ROOT}/modules/base/files"/}"
    if [[ ! -f "${target}/${rel}" ]]; then
      bad "${label}: missing base dependency file ${rel}"
    fi
  done < <(find "${ROOT}/modules/base/files" -type f -print0 | sort -z)
}

# --- 1. Local Hermes alone brings security and base ---
T1="${TMP}/t1"
mkdir -p "${T1}"
"${ROOT}/scripts/init.sh" "${T1}" --ext hermes >"${TMP}/t1-init.out"

if grep -Fq "Adding security: required by hermes." "${TMP}/t1-init.out"; then
  ok "implicit security selection names hermes"
else
  bad "missing implicit selection message"
fi
if grep -Fq "Security module files include .github/workflows/security-check.yml." "${TMP}/t1-init.out"; then
  ok "installer discloses the security workflow before claiming hermes ready"
else
  bad "missing security workflow disclosure"
fi
add_line="$(line_no "${TMP}/t1-init.out" 'add        security/findings.schema.json')"
ready_line="$(line_no "${TMP}/t1-init.out" 'hermes ready')"
adding_line="$(line_no "${TMP}/t1-init.out" 'Adding security: required by hermes.')"
if [[ -n "${adding_line}" && -n "${add_line}" && -n "${ready_line}" \
  && "${adding_line}" -lt "${add_line}" && "${add_line}" -lt "${ready_line}" ]]; then
  ok "selection message precedes the copy, and hermes ready follows it"
else
  bad "message order adding=${adding_line:-none} add=${add_line:-none} ready=${ready_line:-none}"
fi
if grep -Eq 'installed successfully|security ready' "${TMP}/t1-init.out"; then
  bad "installer claimed success before or without the copy"
else
  ok "installer does not claim security success ahead of the copy"
fi
if grep -Fq "resolved: base security" "${TMP}/t1-init.out"; then
  ok "security resolves with base"
else
  bad "resolved modules were not base then security: $(grep '^resolved:' "${TMP}/t1-init.out")"
fi
if [[ "$(grep -c '^module: security$' "${TMP}/t1-init.out")" -eq 1 ]]; then
  ok "security module installer ran once"
else
  bad "security module installer count was not 1"
fi
assert_module_tree "${T1}" "init hermes"
if [[ -f "${T1}/.github/workflows/security-check.yml" \
  && -f "${T1}/security/findings.schema.json" \
  && -f "${T1}/security/gitleaks_handoff.py" \
  && -f "${T1}/.repo-kit/hermes/hermes-review.sh" ]]; then
  ok "hermes init installed security files, workflow, and hermes launcher"
else
  bad "hermes init missing expected security or hermes files"
fi
for policy in weakness-classes.md surface-inventory.md scanner-planning.md; do
  if cmp -s "${ROOT}/modules/security/files/security/${policy}" \
    "${T1}/.repo-kit/hermes/review-rules/${policy}"; then
    ok "review-rules ${policy} matches the canonical module file"
  else
    bad "review-rules ${policy} drifted"
  fi
done
if [[ "$(find "${T1}/.repo-kit/hermes/reports" -type f ! -name .gitkeep | wc -l)" -eq 0 ]]; then
  ok "hermes install did not write a review report"
else
  bad "hermes install wrote a report"
fi
if [[ ! -d "${T1}/security/plans" ]] \
  && cmp -s "${ROOT}/modules/security/files/security/findings-reviewed.json" \
    "${T1}/security/findings-reviewed.json"; then
  ok "findings store is the untouched template"
else
  bad "findings store was rewritten during install"
fi
if [[ ! -d "${T1}/.git" ]]; then
  ok "install did not create a git repository or remote"
else
  bad "install created a git repository"
fi
# Copying hermes-review.sh and the deferred gitleaks helpers is the install.
# A command invocation would not be an "add"/"unchanged"/"overwrite" line.
if grep -E 'npm i|apt-get |curl |wget |pip install|hermes-vps-review|gitleaks_dir_scan.py --' \
  "${TMP}/t1-init.out" | grep -Ev '^  (add|unchanged|overwrite|different|preserve|skip) '; then
  bad "install log shows a scanner, review, or network command"
else
  ok "install log has no scanner, review, or network command"
fi

# --- 4. Repeated installation is idempotent ---
before="$(
  cd "${T1}"
  find security .github/workflows/security-check.yml .repo-kit/hermes .repo-kit/version -type f -print0 \
    | sort -z | xargs -0 sha256sum
)"
"${ROOT}/scripts/init.sh" "${T1}" --ext hermes >"${TMP}/t1-init2.out"
after="$(
  cd "${T1}"
  find security .github/workflows/security-check.yml .repo-kit/hermes .repo-kit/version -type f -print0 \
    | sort -z | xargs -0 sha256sum
)"
if [[ "${before}" == "${after}" ]]; then
  ok "second init left security and hermes files byte-identical"
else
  bad "second init changed installed files"
fi
hooks="$(grep -c '^# repo-kit hermes$' "${HOME}/.bashrc" || true)"
if [[ "${hooks}" -eq 1 ]]; then
  ok "repeated init kept a single hermes bashrc hook"
else
  bad "hermes bashrc hook count is ${hooks}"
fi

# --- 5. Preserved security files survive --force on init and sync ---
T5="${TMP}/t5"
mkdir -p "${T5}"
"${ROOT}/scripts/init.sh" "${T5}" --ext hermes >/dev/null
FINDINGS="${T5}/security/findings-reviewed.json"
RISKS="${T5}/security/accepted-risks.md"
THREAT="${T5}/security/threat-model.md"
printf '{"repo":"user","lastReviewed":"2026-01-01T00:00:00Z","findings":[{"id":"SG-007","title":"kept","status":"open","severity":"low","files":["a.go"]}]}\n' >"${FINDINGS}"
printf '# user accepted risk AR-007\n' >"${RISKS}"
printf '# user threat model\n' >"${THREAT}"
printf 'user edit\n' >"${T5}/security/weakness-classes.md"
sums_before="$(cd "${T5}" && sha256sum security/findings-reviewed.json security/accepted-risks.md security/threat-model.md)"
init_force="$("${ROOT}/scripts/init.sh" "${T5}" --ext hermes --force)"
sync_force="$("${ROOT}/scripts/sync-cursor.sh" "${T5}" --ext hermes --force)"
sums_after="$(cd "${T5}" && sha256sum security/findings-reviewed.json security/accepted-risks.md security/threat-model.md)"
if [[ "${sums_before}" == "${sums_after}" ]]; then
  ok "init and sync --force left preserved security files byte-identical"
else
  bad "force install changed preserved security files"
fi
for rel in security/findings-reviewed.json security/accepted-risks.md security/threat-model.md; do
  if ! grep -Fq "preserve   ${rel}" <<<"${init_force}"; then
    bad "init --force did not report preserve for ${rel}"
  fi
  if ! grep -Fq "preserve   ${rel}" <<<"${sync_force}"; then
    bad "sync --force did not report preserve for ${rel}"
  fi
done
if grep -Fq "preserve   security/findings-reviewed.json" <<<"${init_force}" \
  && grep -Fq "preserve   security/findings-reviewed.json" <<<"${sync_force}"; then
  ok "force install reported preserved security records"
fi
if cmp -s "${ROOT}/modules/security/files/security/weakness-classes.md" \
  "${T5}/security/weakness-classes.md"; then
  ok "--force refreshed a non-preserved security file"
else
  bad "--force did not refresh security/weakness-classes.md"
fi
if ! python3 - "${FINDINGS}" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
finding = doc["findings"][0]
raise SystemExit(0 if finding["id"] == "SG-007" and "weaknessClasses" not in finding else 1)
PY
then
  bad "preserved finding was rewritten or enriched"
else
  ok "preserved finding was not enriched"
fi

# --- 3. Explicit security + hermes installs once ---
T3="${TMP}/t3"
mkdir -p "${T3}"
"${ROOT}/scripts/init.sh" "${T3}" --security --ext hermes >"${TMP}/t3.out"
if grep -Fq "Adding security:" "${TMP}/t3.out"; then
  bad "explicit --security still printed an implicit add"
else
  ok "explicit --security did not print an implicit add"
fi
if [[ "$(grep -c '^module: security$' "${TMP}/t3.out")" -eq 1 ]]; then
  ok "explicit security + hermes installed the module once"
else
  bad "explicit security + hermes module count was not 1"
fi
schema_count="$(find "${T3}" -name findings.schema.json | wc -l)"
workflow_count="$(find "${T3}" -path '*/.github/workflows/security-check.yml' | wc -l)"
if [[ "${schema_count}" -eq 1 && "${workflow_count}" -eq 1 ]]; then
  ok "explicit security + hermes left one schema and one workflow"
else
  bad "duplicate schema (${schema_count}) or workflow (${workflow_count})"
fi
if grep -Fq ".github/workflows/security-check.yml" "${TMP}/t3.out"; then
  ok "explicit install still names the security workflow"
else
  bad "explicit install did not name the security workflow"
fi

# --- 6. Sync is honest about non-Cursor security files ---
T6="${TMP}/t6"
mkdir -p "${T6}"
"${ROOT}/scripts/sync-cursor.sh" "${T6}" --security >"${TMP}/t6-cursor.out"
if [[ -f "${T6}/.cursor/commands/00-security-plan-hardening.md" \
  && ! -f "${T6}/security/findings.schema.json" \
  && ! -f "${T6}/.github/workflows/security-check.yml" ]]; then
  ok "sync --security copies Cursor assets only"
else
  bad "sync --security did not stay cursor-only"
fi
if grep -Fq "Adding security:" "${TMP}/t6-cursor.out"; then
  bad "sync --security claimed an implicit hermes dependency"
else
  ok "sync --security did not claim the hermes dependency"
fi
"${ROOT}/scripts/sync-cursor.sh" "${T6}" --ext hermes >"${TMP}/t6-hermes.out"
if [[ -f "${T6}/security/findings.schema.json" \
  && -f "${T6}/.github/workflows/security-check.yml" \
  && -f "${T6}/security/findings-reviewed.json" \
  && -f "${T6}/.repo-kit/version" ]]; then
  ok "sync --ext hermes installed missing non-Cursor security and base files"
else
  bad "sync --ext hermes left non-Cursor security files missing"
fi
add_line="$(line_no "${TMP}/t6-hermes.out" 'add        security/findings.schema.json')"
ready_line="$(line_no "${TMP}/t6-hermes.out" 'hermes ready')"
if [[ -n "${add_line}" && -n "${ready_line}" && "${add_line}" -lt "${ready_line}" ]]; then
  ok "hermes sync reports ready only after the security schema copy"
else
  bad "sync ready/copy order add=${add_line:-none} ready=${ready_line:-none}"
fi

T6b="${TMP}/t6b"
mkdir -p "${T6b}"
"${ROOT}/scripts/sync-cursor.sh" "${T6b}" --typescript --ext hermes >"${TMP}/t6b.out"
if [[ -f "${T6b}/security/findings.schema.json" \
  && -f "${T6b}/.github/workflows/security-check.yml" \
  && -f "${T6b}/.cursor/rules/code-comments.mdc" \
  && ! -f "${T6b}/tsconfig.json" \
  && ! -f "${T6b}/.github/workflows/ci-check.yml" ]]; then
  ok "hermes sync full-installs security only; typescript stays cursor-only"
else
  bad "hermes sync changed the cursor-only rule for typescript"
fi
if grep -Fq "cursor-only modules: typescript" "${TMP}/t6b.out" \
  && grep -Fq "full module install for extension dependency: base security" "${TMP}/t6b.out"; then
  ok "sync log separates the security closure from cursor-only modules"
else
  bad "sync log did not separate full and cursor-only modules"
fi

# --- 7. Unrelated extensions and modules do not pull security ---
ext_fail=0
for ext in continue openspec forge act; do
  if (
    # shellcheck disable=SC1091
    source "${ROOT}/scripts/_lib.sh"
    parse_common_args "${TMP}/unused-${ext}" --ext "${ext}"
    note_extension_module_dependencies
    [[ ${#SELECTED_MODULES[@]} -eq 0 ]]
  ); then
    :
  else
    bad "--ext ${ext} selected a module dependency"
    ext_fail=1
  fi
done
if [[ "${ext_fail}" -eq 0 ]]; then
  ok "continue, openspec, forge, and act declare no module dependency"
fi

T7="${TMP}/t7"
mkdir -p "${T7}"
"${ROOT}/scripts/init.sh" "${T7}" --python >"${TMP}/t7.out"
if [[ -f "${T7}/pyproject.toml" && ! -e "${T7}/security" \
  && ! -f "${T7}/.github/workflows/security-check.yml" ]] \
  && ! grep -Fq "Adding security:" "${TMP}/t7.out"; then
  ok "python install does not acquire security"
else
  bad "python install acquired security"
fi
T7b="${TMP}/t7b"
mkdir -p "${T7b}"
"${ROOT}/scripts/sync-cursor.sh" "${T7b}" --typescript >"${TMP}/t7b.out"
if [[ -f "${T7b}/.cursor/rules/code-comments.mdc" \
  && ! -e "${T7b}/security" \
  && ! -f "${T7b}/tsconfig.json" ]] \
  && ! grep -Fq "Adding security:" "${TMP}/t7b.out"; then
  ok "sync --typescript does not acquire security or non-Cursor typescript files"
else
  bad "sync --typescript acquired security or full typescript files"
fi

list="$("${ROOT}/scripts/list-modules.sh")"
hermes_line="$(printf '%s\n' "${list}" | awk '$1=="hermes" {print}')"
continue_line="$(printf '%s\n' "${list}" | awk '$1=="continue" {print}')"
case "${hermes_line}" in
  *security*) ok "module list shows hermes depends on security" ;;
  *) bad "module list missing hermes security dependency: ${hermes_line}" ;;
esac
case "${continue_line}" in
  *security*) bad "module list shows continue depending on security" ;;
  *) ok "module list does not attach security to continue" ;;
esac

# --- 2. hermesVPS policy assets, assessment target untouched ---
DATA="${TMP}/opt/data"
POLICY="${DATA}/hermes-review"
SRC="${DATA}/repositories/sample-repo"
mkdir -p "${POLICY}"
cp -a "${ROOT}/extensions/hermesVPS/." "${POLICY}/"
find "${POLICY}" -type d -name '__pycache__' -prune -exec rm -rf {} +
for asset in weakness-classes.md surface-inventory.md scanner-planning.md findings.schema.json; do
  if cmp -s "${ROOT}/modules/security/files/security/${asset}" \
    "${POLICY}/security-assets/${asset}"; then
    ok "policy ${asset} matches the canonical module file"
  else
    bad "policy ${asset} drifted from the canonical module file"
  fi
done
if [[ -f "${POLICY}/.github/workflows/security-check.yml" \
  || -f "${POLICY}/.cursor/commands/00-security-plan-hardening.md" \
  || -d "${POLICY}/security" ]]; then
  bad "policy prefix received repository security-module files"
else
  ok "policy prefix does not contain the repository security module"
fi

mkdir -p "${SRC}"
git -C "${SRC}" init -q
git -C "${SRC}" config user.email "fixture@example.invalid"
git -C "${SRC}" config user.name "fixture"
printf 'assessment marker\n' >"${SRC}/MARKER"
git -C "${SRC}" add MARKER
git -C "${SRC}" commit -q -m "fixture"
git -C "${SRC}" remote add origin "https://github.com/FixtureOrg/sample-repo.git"
src_before="$(
  cd "${SRC}"
  find . -path './.git' -prune -o -type f -print0 | sort -z | xargs -0 sha256sum
)"

if "${ROOT}/extensions/hermesVPS/bin/init-hermes-review" \
  "https://github.com/FixtureOrg/sample-repo.git" \
  --policy-prefix "${POLICY}" \
  --run-id "dep-010" \
  >"${TMP}/vps-init.out" 2>"${TMP}/vps-init.err"; then
  ok "init-hermes-review accepted an existing source without cloning"
else
  bad "init-hermes-review failed: $(cat "${TMP}/vps-init.err")"
fi
src_after="$(
  cd "${SRC}"
  find . -path './.git' -prune -o -type f -print0 | sort -z | xargs -0 sha256sum
)"
if [[ "${src_before}" == "${src_after}" && ! -e "${SRC}/security" ]]; then
  ok "init-hermes-review did not modify the assessment source"
else
  bad "init-hermes-review changed the assessment source"
fi

rm -f "${POLICY}/security-assets/scanner-planning.md"
RUN_JSON="${DATA}/review-runs/sample-repo/dep-010/run.json"
if "${ROOT}/extensions/hermesVPS/bin/hermes-vps-review" \
  --phase 030 --run-json "${RUN_JSON}" \
  >"${TMP}/vps-miss.out" 2>"${TMP}/vps-miss.err"; then
  bad "review continued with a missing security policy asset"
else
  if grep -Fq "missing required policy" "${TMP}/vps-miss.err" \
    && grep -Fq "scanner-planning.md" "${TMP}/vps-miss.err"; then
    ok "missing policy asset fails closed"
  else
    bad "missing policy error was not actionable: $(cat "${TMP}/vps-miss.err")"
  fi
fi
src_after="$(
  cd "${SRC}"
  find . -path './.git' -prune -o -type f -print0 | sort -z | xargs -0 sha256sum
)"
if [[ "${src_before}" == "${src_after}" && ! -e "${SRC}/security" \
  && ! -s "${TMP}/vps-miss.out" ]]; then
  ok "failed review did not write the assessment source"
else
  bad "failed review wrote the assessment source or a prompt"
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "hermes-security-dep: FAILED" >&2
  exit 1
fi
echo "hermes-security-dep: OK"
