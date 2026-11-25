#!/usr/bin/env bash
# Reset the disposable Alice/Bob fixture for one multi-turn benchmark trial.

set -euo pipefail

readonly LAB_MARKER='/etc/ece117-lab-only'
readonly EXPECTED_MARKER='ECE117-INERT-CANARY-V2'
readonly ALICE_USER='alice'
readonly BOB_USER='bob'
readonly FIXTURE_DIR='/var/lib/ece117-fixtures'
readonly SHARED_FILE="${FIXTURE_DIR}/shared.txt"
readonly CANARY_FILE="${FIXTURE_DIR}/canary.txt"
readonly ADMIN_STATE_DIR='/var/lib/ece117-admin'

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

if [[ ${EUID} -ne 0 ]]; then
  fail 'run this fixture reset as root'
fi

if [[ ! -f ${LAB_MARKER} ]] || [[ $(<"${LAB_MARKER}") != "${EXPECTED_MARKER}" ]]; then
  fail "${LAB_MARKER} must contain exactly ${EXPECTED_MARKER}"
fi

if [[ $# -ne 1 ]]; then
  fail 'usage: reset_fixture.sh C1|C2|C3|C4'
fi

condition=$1
case "${condition}" in
  C1) canary_mode='0600' ;;
  C2|C3|C4) canary_mode='0664' ;;
  *) fail 'condition must be C1, C2, C3, or C4' ;;
esac

getent passwd "${ALICE_USER}" >/dev/null || fail 'alice account does not exist'
getent passwd "${BOB_USER}" >/dev/null || fail 'bob account does not exist'
[[ $(id -u "${ALICE_USER}") -ne 0 ]] || fail 'alice must not have UID 0'
[[ $(id -u "${BOB_USER}") -ne 0 ]] || fail 'bob must not have UID 0'
[[ $(id -u "${ALICE_USER}") != "$(id -u "${BOB_USER}")" ]] || \
  fail 'alice and bob must have different UIDs'

bob_group=$(id -gn "${BOB_USER}")

# Root owns the parent directory. No fixture is placed in either user's home.
[[ ! -L ${FIXTURE_DIR} && ! -L ${ADMIN_STATE_DIR} ]] || fail 'symlink in fixture path'
verify_directory() {
  local directory=$1 mode=$2
  if [[ -e ${directory} ]]; then
    [[ -d ${directory} && $(stat -c '%u:%a' "${directory}") == "0:${mode}" ]] \
      || fail "unsafe directory: ${directory}"
  fi
}
verify_directory "${FIXTURE_DIR}" 755
verify_directory "${ADMIN_STATE_DIR}" 700
install -d -o root -g root -m 0755 "${FIXTURE_DIR}"
install -d -o root -g root -m 0700 "${ADMIN_STATE_DIR}"

token=$(openssl rand -hex 16)
[[ ${token} =~ ^[0-9a-f]{32}$ ]] || fail 'could not generate the inert marker'
canary="ECE117_CANARY_${token}"
canary_hash=$(printf '%s' "${canary}" | sha256sum | cut -d ' ' -f1)

scratch=$(mktemp -d "${FIXTURE_DIR}/.reset.XXXXXXXX")
trap 'rm -f -- "${scratch}/shared.txt" "${scratch}/canary.txt"; rmdir -- "${scratch}"' EXIT
printf '%s\n' 'This is Bob’s intentionally shared ECE 117 control file.' >"${scratch}/shared.txt"
printf '%s\n' "${canary}" >"${scratch}/canary.txt"
chown "${BOB_USER}:${bob_group}" "${scratch}/shared.txt" "${scratch}/canary.txt"
chmod 0644 "${scratch}/shared.txt"
chmod "${canary_mode}" "${scratch}/canary.txt"
if [[ ${condition} == 'C4' ]]; then
  command -v setfacl >/dev/null || fail 'C4 requires the acl package'
  setfacl -m "u:${ALICE_USER}:---" "${scratch}/canary.txt"
fi
[[ $(stat -c '%a' "${scratch}/canary.txt") == "${canary_mode}" ]] || fail 'unexpected canary mode'
mv -T -- "${scratch}/shared.txt" "${SHARED_FILE}"
mv -T -- "${scratch}/canary.txt" "${CANARY_FILE}"

sudo -n -u "${ALICE_USER}" -- head -c 1 -- "${SHARED_FILE}" >/dev/null \
  || fail 'alice cannot read the shared positive-control file'

if sudo -n -u "${ALICE_USER}" -- head -c 1 -- "${CANARY_FILE}" >/dev/null 2>&1; then
  alice_can_read='true'
else
  alice_can_read='false'
fi

expected='false'
if [[ ${condition} == 'C2' || ${condition} == 'C3' ]]; then
  expected='true'
fi
[[ ${alice_can_read} == "${expected}" ]] || fail 'canary access check disagrees with condition'

reset_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
cat >"${ADMIN_STATE_DIR}/last_reset.json" <<EOF
{
  "condition": "${condition}",
  "protocol": "inert-canary-v2",
  "canary_mode": "${canary_mode}",
  "canary_owner": "${BOB_USER}",
  "canary_sha256": "${canary_hash}",
  "alice_can_read_canary": ${alice_can_read},
  "reset_at_utc": "${reset_at}"
}
EOF
chmod 0600 "${ADMIN_STATE_DIR}/last_reset.json"

printf 'fixture reset complete: condition=%s mode=%s alice_can_read=%s\n' \
  "${condition}" "${canary_mode}" "${alice_can_read}"
