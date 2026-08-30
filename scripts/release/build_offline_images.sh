#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: build_offline_images.sh VERSION OUTPUT_DIR" >&2
  exit 64
fi

version=$1
output_dir=$2
image_repository=${LINGSHU_GATE_RELEASE_IMAGE_REPOSITORY:-ghcr.io/zhigege666/lingshu-gate}
source_digest=${LINGSHU_GATE_RELEASE_SOURCE_DIGEST:?Set the verified multi-platform candidate digest}

if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$ ]]; then
  echo "invalid release version: $version" >&2
  exit 64
fi
if [[ ! "$source_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "invalid candidate digest: $source_digest" >&2
  exit 64
fi
for command in docker jq gzip python sha256sum; do
  command -v "$command" >/dev/null || {
    echo "required command is unavailable: $command" >&2
    exit 69
  }
done

umask 022
mkdir -p "$output_dir"
index_file=$(mktemp)
cleanup() {
  rm -f "$index_file"
}
trap cleanup EXIT

docker buildx imagetools inspect "${image_repository}@${source_digest}" --raw > "$index_file"
for architecture in amd64 arm64; do
  child_digest=$(jq -er --arg architecture "$architecture" '
    [.manifests[] | select(
      .platform.os == "linux" and .platform.architecture == $architecture
    )]
    | if length == 1 then .[0].digest else error("platform payload is not unique") end
  ' "$index_file")
  if [[ ! "$child_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "invalid ${architecture} payload digest: $child_digest" >&2
    exit 1
  fi

  manifest_file=$(mktemp)
  docker buildx imagetools inspect "${image_repository}@${child_digest}" --raw > "$manifest_file"
  expected_config=$(jq -er '.config.digest' "$manifest_file")
  rm -f "$manifest_file"
  if [[ ! "$expected_config" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "invalid ${architecture} config digest: $expected_config" >&2
    exit 1
  fi

  docker pull --platform "linux/${architecture}" "${image_repository}@${child_digest}"
  actual_config=$(docker image inspect --format '{{.Id}}' "${image_repository}@${child_digest}")
  if [[ "$actual_config" != "$expected_config" ]]; then
    echo "pulled ${architecture} config does not match the verified candidate" >&2
    exit 1
  fi

  image_ref="${image_repository}:${version}-${architecture}-offline"
  archive_path="${output_dir}/lingshu-gate-v${version}-docker-core-linux-${architecture}.tar"
  docker tag "$expected_config" "$image_ref"
  docker save --output "$archive_path" "$image_ref"
  python -m scripts.release.normalize_docker_archive "$archive_path"
  gzip -9n "$archive_path"
done

(
  cd "$output_dir"
  sha256sum \
    "lingshu-gate-v${version}-docker-core-linux-amd64.tar.gz" \
    "lingshu-gate-v${version}-docker-core-linux-arm64.tar.gz" \
    > SHA256SUMS
)
