#!/usr/bin/env bash
# Resolve Bedrock model IDs for the configured account and region.
#
# Model IDs are never hardcoded from memory: some models reject their own base
# model ID with "on-demand throughput isn't supported" and require the
# cross-region inference profile ID (the "us."-prefixed variant) instead. This
# prints what the account actually exposes so .env can be filled from evidence.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"

echo "== Amazon foundation models in ${REGION} =="
aws bedrock list-foundation-models --region "$REGION" --by-provider Amazon \
  --query 'modelSummaries[?contains(modelId,`nova`)].[modelId,inferenceTypesSupported[0]]' \
  --output table

echo
echo "== Active inference profiles (preferred over bare model IDs) =="
aws bedrock list-inference-profiles --region "$REGION" \
  --query 'inferenceProfileSummaries[?status==`ACTIVE`].[inferenceProfileId]' \
  --output text | sort

echo
echo "Smoke-test one before committing it to .env:"
echo "  aws bedrock-runtime converse --region ${REGION} --model-id <id> \\"
echo "    --messages '[{\"role\":\"user\",\"content\":[{\"text\":\"Reply with exactly: OK\"}]}]' \\"
echo "    --inference-config '{\"maxTokens\":16,\"temperature\":0}'"
