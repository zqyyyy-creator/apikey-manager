# LiteLLM CustomLogger Deployment

This document describes how to deploy the MaaS CustomLogger into
`ds-api-gateway` / `lag-proxy`.

## Scope

The CustomLogger is required by PLAN Phase 6:

- Managed MaaS keys use MaaS CNY cost instead of LiteLLM default pricing.
- Non-managed keys are skipped and continue using LiteLLM default spend logic.
- The managed-key cost delta is written to LiteLLM DB and Redis spend counters.
- LiteLLM budget enforcement can continue checking `spend >= max_budget`.

## Files

Source of truth:

```text
maas-v2-client-api/app/litellm_integration/custom_logger.py
```

Gateway deployment target:

```text
ds-api-gateway/custom_callbacks.py
```

Local-only test helper:

```text
ds-api-gateway/mock_openai_server.py
```

Do not deploy `mock_openai_server.py` or a `maas-local-mock` model to real
Gateway environments.

## Gateway Environment Variables

Set these in the LiteLLM Gateway process:

```env
MAAS_V2_API_URL=http://maas-v2-client-api:8000
MAAS_V2_INTERNAL_API_KEY=<same value as maas-v2-client-api INTERNAL_API_KEY>
MAAS_V2_API_TIMEOUT=3.0
```

Use the in-cluster MaaS API service URL for `MAAS_V2_API_URL` in Kubernetes.

## Gateway Config

Add the MaaS callback to LiteLLM Gateway config:

```yaml
litellm_settings:
  callbacks: custom_callbacks.maas_custom_logger
  success_callback: ["prometheus"]
  failure_callback: ["custom_callbacks.maas_custom_logger"]
```

If the real Gateway already has callback settings, merge them. Do not remove
unrelated existing callbacks.

Example with an existing success callback:

```yaml
litellm_settings:
  callbacks: custom_callbacks.maas_custom_logger
  success_callback: ["prometheus", "langfuse"]
  failure_callback: ["custom_callbacks.maas_custom_logger"]
```

## Deployment Steps

1. Copy the maintained logger into the Gateway repo:

   ```bash
   cp maas-v2-client-api/app/litellm_integration/custom_logger.py \
      ds-api-gateway/custom_callbacks.py
   ```

2. Add the Gateway environment variables.

3. Update the LiteLLM config as shown above.

4. Restart the LiteLLM Gateway process.

5. Check startup logs. You should see the custom callback initialized.

## Verification

Use a real managed key created by MaaS API and send one successful model request
through the Gateway.

Expected Gateway log:

```text
maas_custom_logger_managed_cost_synced
```

For local callback-to-MaaS connectivity checks with the mock model, the request
can include `_encrypted_content_affinity_pinned=true` to bypass this Gateway
branch's Router Redis prediction path. Full budget/spend verification should use
the Gateway's normal Redis configuration.

This means:

```text
LiteLLM success callback
-> MaaS internal cost API
-> managed=true
-> delta = maas_cost - litellm_default_cost
-> LiteLLM DB spend update
-> LiteLLM Redis spend counter update
```

For a non-managed key, expected log:

```text
maas_custom_logger_non_managed_key
```

That means the request is intentionally left on LiteLLM default spend handling.

## Troubleshooting

`maas_custom_logger_not_configured`

The Gateway process is missing `MAAS_V2_API_URL` or
`MAAS_V2_INTERNAL_API_KEY`.

`maas_custom_logger_skip_missing_key`

LiteLLM did not provide a key hash in callback metadata. Verify the request is
using a LiteLLM virtual key, not only a local master key.

`maas_custom_logger_cost_lookup_failed`

The Gateway could not call MaaS internal cost API. Check service URL, network,
and internal API key.

`maas_custom_logger_skip_missing_cost`

LiteLLM did not calculate a default `response_cost`, so the delta cannot be
computed. Verify the model has LiteLLM pricing or custom pricing configured.

`maas_custom_logger_skip_missing_litellm_token`

MaaS cost was calculated, but LiteLLM did not provide the token hash needed for
DB/Redis spend updates. Real virtual-key requests should include it.

`maas_custom_logger_spend_sync_failed`

MaaS cost was calculated, but updating LiteLLM DB or Redis spend counters
failed. Check Gateway DB/Redis connectivity and traceback.

## Rollback

Remove the MaaS callback from Gateway config and restart Gateway:

```yaml
litellm_settings:
  success_callback: ["prometheus"]
```

After rollback, managed keys will go back to LiteLLM default pricing and spend
tracking.
