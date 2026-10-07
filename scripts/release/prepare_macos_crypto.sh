#!/usr/bin/env bash
# Build the same OpenSSL release used by cryptography's 50.0.2 wheels.
# Intel macOS has no upstream wheel; static linkage avoids Homebrew dylib drift.
set -euo pipefail

test "$(uname -s)" = Darwin
test "$(uname -m)" = x86_64
: "${RUNNER_TEMP:?RUNNER_TEMP must identify the CI temporary directory}"
: "${GITHUB_ENV:?GITHUB_ENV must identify the CI environment file}"

openssl_version=4.0.3
openssl_sha256=325b5c806167c13b40b1ffeadfe0248197c00eccc4cf123ec1e28d2d2fd216d9
crypto_build_dir=$(mktemp -d "$RUNNER_TEMP/gate-crypto.XXXXXX")
archive="$crypto_build_dir/openssl-$openssl_version.tar.gz"
prefix="$crypto_build_dir/install"

curl --fail --location --proto '=https' --tlsv1.2 \
  "https://github.com/openssl/openssl/releases/download/openssl-$openssl_version/openssl-$openssl_version.tar.gz" \
  --output "$archive"
printf '%s  %s\n' "$openssl_sha256" "$archive" | shasum -a 256 --check
tar -xzf "$archive" -C "$crypto_build_dir"
(
  cd "$crypto_build_dir/openssl-$openssl_version"
  ./Configure darwin64-x86_64-cc no-shared -fPIC --prefix="$prefix" --libdir=lib
  make -j2
  make test
  make install_sw
)

# Exact Rust input, above cryptography's documented 1.83.0 minimum.
rustup toolchain install 1.90.0 --profile minimal
printf 'OPENSSL_DIR=%s\nOPENSSL_STATIC=1\nRUSTUP_TOOLCHAIN=1.90.0\n' "$prefix" >> "$GITHUB_ENV"
