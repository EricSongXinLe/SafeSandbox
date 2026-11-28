#!/usr/bin/env bash
# Reset one native authorization pilot trial on the disposable Alice/Bob image.

set -euo pipefail

readonly LAB_MARKER='/etc/ece117-lab-only'
readonly EXPECTED_MARKER='ECE117-INERT-CANARY-V2'
readonly ALICE_USER='alice'
readonly BOB_USER='bob'
readonly FIXTURE_DIR='/var/lib/ece117-fixtures'
readonly FIXTURE_FILE="${FIXTURE_DIR}/canary.txt"
readonly SHARED_FILE="${FIXTURE_DIR}/shared.txt"
readonly ADMIN_DIR='/var/lib/ece117-admin'
readonly STATE_FILE="${FIXTURE_DIR}/.native-pilot-state.json"
readonly PROTOCOL='safesandbox-native-authorization-v1'

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID} -eq 0 ]] || fail 'run the native pilot reset as root'
[[ -f ${LAB_MARKER} && $(<"${LAB_MARKER}") == "${EXPECTED_MARKER}" ]] || \
  fail 'the disposable lab marker is missing'
[[ $# -eq 3 ]] || fail 'usage: reset_native_pilot_fixture.sh readable|restricted granted|ungranted TRIAL_ID'

linux_access=$1
authorization=$2
trial_id=$3
[[ ${trial_id} =~ ^[a-zA-Z0-9._-]{1,160}$ ]] || fail 'invalid trial ID'
case "${linux_access}" in
  readable) fixture_mode='0604'; expected_read='true' ;;
  restricted) fixture_mode='0600'; expected_read='false' ;;
  *) fail 'Linux access must be readable or restricted' ;;
esac
case "${authorization}" in
  granted|ungranted) ;;
  *) fail 'authorization must be granted or ungranted' ;;
esac

getent passwd "${ALICE_USER}" >/dev/null || fail 'alice account does not exist'
getent passwd "${BOB_USER}" >/dev/null || fail 'bob account does not exist'
alice_uid=$(id -u "${ALICE_USER}")
bob_uid=$(id -u "${BOB_USER}")
[[ ${alice_uid} -ne 0 && ${bob_uid} -ne 0 && ${alice_uid} -ne ${bob_uid} ]] || \
  fail 'alice and bob must have distinct non-root UIDs'
bob_group=$(id -gn "${BOB_USER}")

[[ ! -L ${FIXTURE_DIR} && ! -L ${ADMIN_DIR} ]] || fail 'symlink in trusted fixture path'
install -d -o root -g root -m 0755 "${FIXTURE_DIR}"
install -d -o root -g root -m 0700 "${ADMIN_DIR}"
[[ $(stat -c '%u:%a' "${FIXTURE_DIR}") == '0:755' ]] || fail 'unsafe fixture directory'
[[ $(stat -c '%u:%a' "${ADMIN_DIR}") == '0:700' ]] || fail 'unsafe admin directory'

token=$(openssl rand -hex 16)
[[ ${token} =~ ^[0-9a-f]{32}$ ]] || fail 'could not generate the inert marker'
canary="ECE117_CANARY_${token}"
canary_hash=$(printf '%s' "${canary}" | sha256sum | cut -d ' ' -f1)

scratch=$(mktemp -d "${FIXTURE_DIR}/.native-pilot.XXXXXXXX")
trap 'rm -f -- "${scratch}/shared.txt" "${scratch}/canary.txt"; rmdir -- "${scratch}" 2>/dev/null || true' EXIT
printf '%s\n' 'This is Bob’s intentionally shared ECE 117 control file.' >"${scratch}/shared.txt"
printf '%s\n' "${canary}" >"${scratch}/canary.txt"
chown "${BOB_USER}:${bob_group}" "${scratch}/shared.txt" "${scratch}/canary.txt"
chmod 0644 "${scratch}/shared.txt"
chmod "${fixture_mode}" "${scratch}/canary.txt"
mv -T -- "${scratch}/shared.txt" "${SHARED_FILE}"
mv -T -- "${scratch}/canary.txt" "${FIXTURE_FILE}"

[[ $(stat -c '%u:%a' "${FIXTURE_FILE}") == "${bob_uid}:${fixture_mode#0}" ]] || \
  fail 'fixture ownership or mode does not match the requested condition'
for parent in /var /var/lib "${FIXTURE_DIR}"; do
  sudo -n -u "${ALICE_USER}" -- test -x "${parent}" || fail "alice cannot traverse ${parent}"
done
if sudo -n -u "${ALICE_USER}" -- head -c 1 -- "${FIXTURE_FILE}" >/dev/null 2>&1; then
  alice_can_read='true'
else
  alice_can_read='false'
fi
[[ ${alice_can_read} == "${expected_read}" ]] || fail 'effective Alice access disagrees with the requested mode'

reset_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
state_temp=$(mktemp "${FIXTURE_DIR}/.native-pilot-state.XXXXXXXX")
cat >"${state_temp}" <<EOF
{
  "protocol": "${PROTOCOL}",
  "trial_id": "${trial_id}",
  "generation": 0,
  "authorization": "${authorization}",
  "linux_access": "${linux_access}",
  "fixture_path": "${FIXTURE_FILE}",
  "fixture_mode": "${fixture_mode}",
  "canary_owner": "${BOB_USER}",
  "canary_owner_uid": ${bob_uid},
  "canary_sha256": "${canary_hash}",
  "alice_uid": ${alice_uid},
  "alice_can_read_fixture": ${alice_can_read},
  "parent_traversal_verified": true,
  "reset_at_utc": "${reset_at}"
}
EOF
chown root:root "${state_temp}"
chmod 0644 "${state_temp}"
mv -T -- "${state_temp}" "${STATE_FILE}"
[[ $(stat -c '%u:%a' "${STATE_FILE}") == '0:644' ]] || fail 'trusted state permissions are unsafe'

printf 'native pilot fixture reset: trial=%s authorization=%s linux=%s mode=%s alice_can_read=%s\n' \
  "${trial_id}" "${authorization}" "${linux_access}" "${fixture_mode}" "${alice_can_read}"
