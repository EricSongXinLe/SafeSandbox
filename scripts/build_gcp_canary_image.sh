#!/usr/bin/env bash
# Run from Cloud Shell against a dedicated Ubuntu builder.
set -euo pipefail

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

ensure_alice_has_no_sudo() {
  local listing
  local denied='^User alice is not allowed to run sudo on [[:alnum:]_.-]+\.$'
  # sudo may return success for the list operation even when it lists no grants.
  # Query as root in the C locale and accept only the explicit denial.
  listing=$(sudo -n env LC_ALL=C sudo -n -l -U alice 2>&1) || true
  printf '%s\n' "$listing"
  [[ $listing =~ $denied ]] ||
    fail 'Cannot verify that Alice has no sudo privileges. Review the sudo listing above.'
}

guest_prepare() {
  local sha=$1 stage install_dir alice_row bob_row
  cd "$HOME"
  printf '%s  %s\n' "$sha" ece117-canary-v2.tar.gz | sha256sum -c -
  if sudo -n test -e /opt/ece117 || sudo -n test -L /opt/ece117; then
    sudo -n test ! -L /opt/ece117 || fail '/opt/ece117 is a symlink'
    printf '%s  %s\n' "$sha" ece117-canary-v2.tar.gz |
      sudo -n cmp -s - /opt/ece117/BUNDLE.sha256 ||
      fail '/opt/ece117 contains a different bundle. Use a clean builder.'
    ensure_alice_has_no_sudo
    printf 'The same bundle is already installed.\n'
    return
  fi

  sudo -n apt-get -o APT::Update::Error-Mode=any \
    -o Acquire::Retries=0 -o Acquire::http::Timeout=10 -o Acquire::https::Timeout=10 update ||
    fail 'apt update failed. Check approved outbound access to the Ubuntu mirrors from this VM.'
  sudo -n apt-get -o Acquire::Retries=0 -o Acquire::http::Timeout=10 \
    -o Acquire::https::Timeout=10 install -y acl openssl python3 sudo

  stage=$(mktemp -d "$HOME/ece117-stage.XXXXXX")
  tar -xzf "$HOME/ece117-canary-v2.tar.gz" -C "$stage"
  (
    cd "$stage"
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
    bash -n scripts/vm/reset_fixture.sh
    if [[ -f scripts/vm/reset_native_pilot_fixture.sh ]]; then
      bash -n scripts/vm/reset_native_pilot_fixture.sh
    fi
  )

  if ! getent passwd alice >/dev/null; then
    sudo -n useradd --create-home --shell /bin/bash alice
  fi
  if ! getent passwd bob >/dev/null; then
    sudo -n useradd --system --no-create-home --shell /usr/sbin/nologin bob
  fi
  alice_row=$(getent passwd alice)
  bob_row=$(getent passwd bob)
  [[ $alice_row == *:/home/alice:/bin/bash && $(id -u alice) != 0 ]] ||
    fail 'Alice must be an unprivileged account with /home/alice and Bash'
  [[ $bob_row == *:/usr/sbin/nologin && $(id -u bob) != 0 && $(id -u bob) != "$(id -u alice)" ]] ||
    fail 'Bob must have a separate unprivileged UID and a nologin shell'
  ensure_alice_has_no_sudo
  sudo -n install -d -o alice -g "$(id -gn alice)" -m 0700 \
    /home/alice/experiment /home/alice/ece117-results
  sudo -n install -d -o root -g root -m 0700 \
    /var/lib/ece117-admin /var/lib/ece117-admin/canary-trials
  printf '%s\n' ECE117-INERT-CANARY-V2 > "$stage/lab-marker"
  sudo -n install -o root -g root -m 0644 "$stage/lab-marker" /etc/ece117-lab-only

  install_dir=$(sudo -n mktemp -d /opt/ece117-install.XXXXXX)
  sudo -n cp -R "$stage/scripts" "$stage/prompts" "$install_dir/"
  sudo -n chown -R root:root "$install_dir"
  sudo -n chmod -R go-w "$install_dir"
  sudo -n chmod 0755 "$install_dir" "$install_dir/scripts/vm/reset_fixture.sh"
  if [[ -f "$stage/scripts/vm/reset_native_pilot_fixture.sh" ]]; then
    sudo -n chmod 0755 "$install_dir/scripts/vm/reset_native_pilot_fixture.sh"
  fi
  printf '%s  %s\n' "$sha" ece117-canary-v2.tar.gz > "$stage/BUNDLE.sha256"
  sudo -n install -o root -g root -m 0644 "$stage/BUNDLE.sha256" "$install_dir/BUNDLE.sha256"
  sudo -n mv -nT "$install_dir" /opt/ece117
  sudo -n test ! -e "$install_dir" || fail '/opt/ece117 appeared during setup'
  printf 'Installed the verified bundle in /opt/ece117.\n'
}

guest_check_image() {
  local sha=$1 scope=${2:-both}
  printf '%s  %s\n' "$sha" ece117-canary-v2.tar.gz |
    sudo -n cmp -s - /opt/ece117/BUNDLE.sha256 ||
    fail 'installed bundle checksum differs. Run prepare on a clean builder.'
  ensure_alice_has_no_sudo
  if [[ $scope == trusted ]]; then
    sudo -n -iu alice -- python3 --version || fail 'Python is missing or cannot run as Alice'
    return
  fi
  sudo -n -iu alice -- codex --version || fail 'Codex CLI is missing or cannot run as Alice'
  if [[ $scope == both ]]; then
    sudo -n -iu alice -- claude --version || fail 'Claude Code CLI is missing or cannot run as Alice'
  fi
}

usage() {
  cat <<'EOF'
Usage: bash build_gcp_canary_image.sh prepare|image|build [--create-builder]

Required environment: PROJECT, ZONE, SUBNET, BUILDER, BUNDLE_SHA
Required for image/build: IMAGE
Optional: BUNDLE (defaults to $HOME/ece117-canary-v2.tar.gz)

prepare uploads, installs, and tests on a running dedicated builder.
image verifies the install and selected runtime, stops the builder, and creates IMAGE.
build combines prepare and image. ECE117_TRIAL_AGENTS selects both, codex, or trusted.
--create-builder creates a billable stock Ubuntu builder for prepare or build.
An IAP-enabled subnet with approved outbound access is a prerequisite.
EOF
}

case "${1:-}" in
  _guest_prepare) guest_prepare "$2"; exit ;;
  _guest_check_image) guest_check_image "$2" "${3:-both}"; exit ;;
  -h|--help) usage; exit ;;
  prepare|image|build) mode=$1 ;;
  *) usage >&2; exit 2 ;;
esac

create_builder=false
if [[ ${2:-} == --create-builder && $mode != image ]]; then
  create_builder=true
elif [[ $# -gt 1 ]]; then
  fail 'expected only a mode and optional --create-builder for prepare or build'
fi
[[ $# -le 2 ]] || fail 'unexpected arguments'
: "${PROJECT:?Set PROJECT}" "${ZONE:?Set ZONE}" "${SUBNET:?Set SUBNET}"
: "${BUILDER:?Set BUILDER}" "${BUNDLE_SHA:?Set BUNDLE_SHA}"
[[ $BUNDLE_SHA =~ ^[0-9a-f]{64}$ ]] || fail 'BUNDLE_SHA must be 64 lowercase hex digits'
if [[ $mode != prepare ]]; then
  : "${IMAGE:?Set IMAGE}"
fi

scope=(--project="$PROJECT" --zone="$ZONE")
ssh=(gcloud compute ssh "$BUILDER" "${scope[@]}" --tunnel-through-iap)
script_file=$0
bundle=${BUNDLE:-"$HOME/ece117-canary-v2.tar.gz"}
if [[ $mode != image ]]; then
  printf '%s  %s\n' "$BUNDLE_SHA" "$bundle" | sha256sum -c -
fi
if [[ $create_builder == true ]]; then
  gcloud compute instances create "$BUILDER" "${scope[@]}" --subnet="$SUBNET" \
    --machine-type=e2-small --image-family=ubuntu-2404-lts-amd64 \
    --image-project=ubuntu-os-cloud --no-address --no-service-account --no-scopes
fi
printf 'Checking IAP SSH for %s in %s/%s.\n' "$BUILDER" "$PROJECT" "$ZONE"
for ((attempt=1; attempt<=8; attempt++)); do
  if "${ssh[@]}" --ssh-flag=-oConnectTimeout=10 --command=true </dev/null; then
    break
  fi
  [[ $attempt -lt 8 ]] || fail "IAP SSH is unavailable. Run gcloud compute ssh $BUILDER --troubleshoot --tunnel-through-iap with the same project and zone."
  sleep 5
done

if [[ $mode != image ]]; then
  gcloud compute scp "$bundle" "${BUILDER}:~/ece117-canary-v2.tar.gz" \
    "${scope[@]}" --tunnel-through-iap
  "${ssh[@]}" --ssh-flag=-T --command="bash -s -- _guest_prepare $BUNDLE_SHA" < "$script_file"
fi

if [[ $mode != prepare ]]; then
  trial_agents=${ECE117_TRIAL_AGENTS:-both}
  [[ $trial_agents == both || $trial_agents == codex || $trial_agents == trusted ]] ||
    fail 'invalid ECE117_TRIAL_AGENTS'
  "${ssh[@]}" --ssh-flag=-T --command="bash -s -- _guest_check_image $BUNDLE_SHA $trial_agents" < "$script_file"
  boot_disk=$(
    gcloud compute instances describe "$BUILDER" "${scope[@]}" --format=json |
      python3 -c '
import json
import sys

disks = [disk for disk in json.load(sys.stdin).get("disks", []) if disk.get("boot") is True]
if len(disks) != 1 or not disks[0].get("source"):
    sys.exit("could not identify exactly one boot disk")
print(disks[0]["source"].rsplit("/", 1)[-1])
'
  )
  [[ $boot_disk =~ ^[a-z][a-z0-9-]*$ ]] || fail 'could not identify exactly one boot disk'
  gcloud compute instances stop "$BUILDER" "${scope[@]}"
  gcloud compute images create "$IMAGE" --project="$PROJECT" \
    --source-disk="$boot_disk" --source-disk-zone="$ZONE" \
    --description="ECE117 inert-canary bundle SHA-256 $BUNDLE_SHA"
  gcloud compute images describe "$IMAGE" --project="$PROJECT" --format='table(name,id,status)'
fi
