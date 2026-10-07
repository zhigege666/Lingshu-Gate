#!/usr/bin/env bash
# Exercise env:// key signing against an isolated loopback OCI registry.
# Synthetic keys and signatures never reach a public registry/transparency log.
set -euo pipefail
umask 077
: "${RUNNER_TEMP:?CI temporary directory is required}"
: "${LINGSHU_GATE_COSIGN_SMOKE_REGISTRY_IMAGE:?Pinned registry image is required}"
: "${LINGSHU_GATE_RELEASE_PYTHON_BASE_IMAGE:?Pinned fixture image is required}"

fixture_root=$(mktemp -d "$RUNNER_TEMP/gate-cosign.XXXXXX")
registry_name="gate-cosign-smoke-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
trap 'docker rm --force "$registry_name" >/dev/null 2>&1 || true; rm -rf "$fixture_root"' EXIT
docker run --detach --name "$registry_name" --publish 127.0.0.1::5000 \
  "$LINGSHU_GATE_COSIGN_SMOKE_REGISTRY_IMAGE" >/dev/null
port=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "5000/tcp") 0).HostPort}}' "$registry_name")
ready=false
for ((attempt=0; attempt<30; attempt++)); do
  if curl --silent --fail "http://127.0.0.1:$port/v2/" >/dev/null; then ready=true; break; fi
  sleep 1
done
test "$ready" = true

fixture="localhost:$port/gate/cosign-fixture"
docker pull "$LINGSHU_GATE_RELEASE_PYTHON_BASE_IMAGE" >/dev/null
docker tag "$LINGSHU_GATE_RELEASE_PYTHON_BASE_IMAGE" "$fixture:synthetic"
docker push "$fixture:synthetic" >/dev/null
reference=$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$fixture:synthetic" \
  | awk -v prefix="$fixture@" 'index($0, prefix) == 1 { print }')
[[ "$reference" =~ @sha256:[0-9a-f]{64}$ ]]

export COSIGN_PASSWORD=synthetic-fixture-password
cosign generate-key-pair --output-key-prefix "$fixture_root/signing" >/dev/null
# Keep Cosign 3's signing-config API, with no public CA/OIDC/tlog/TSA endpoints.
cosign signing-config create --out "$fixture_root/signing-config.json" \
  --no-default-fulcio --no-default-oidc --no-default-rekor --no-default-tsa
COSIGN_PRIVATE_KEY=$(cat "$fixture_root/signing.key") \
  cosign sign --yes --key env://COSIGN_PRIVATE_KEY \
    --signing-config "$fixture_root/signing-config.json" --allow-http-registry "$reference"
cosign verify --key "$fixture_root/signing.pub" --insecure-ignore-tlog \
  --allow-http-registry "$reference" > "$fixture_root/verified.json"
cosign generate-key-pair --output-key-prefix "$fixture_root/wrong" >/dev/null
if cosign verify --key "$fixture_root/wrong.pub" --insecure-ignore-tlog \
  --allow-http-registry "$reference" >/dev/null 2>&1; then
  echo "A different public key must not verify the fixture signature"
  exit 1
fi
echo "Synthetic OCI env-key signature verified; mismatched key rejected"
