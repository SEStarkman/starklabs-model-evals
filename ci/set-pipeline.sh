#!/usr/bin/env bash
set -euo pipefail

TARGET="${TARGET:-starklabs}"
PIPELINE="${PIPELINE:-starklabs-model-evals}"
SECRETS_FILE="${SECRETS_FILE:-starklabs-ci/concourse/secrets.yml}"

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Missing secrets file: $SECRETS_FILE" >&2
  exit 1
fi

if ! grep -q "BEGIN OPENSSH PRIVATE KEY\\|BEGIN RSA PRIVATE KEY" "$SECRETS_FILE"; then
  echo "secrets.yml must contain a repo SSH private key for the git resource" >&2
  exit 1
fi

fly -t "$TARGET" validate-pipeline -c ci/pipeline.yml

echo "Pipeline $PIPELINE validated for target $TARGET. This script never sets or unpauses it."
