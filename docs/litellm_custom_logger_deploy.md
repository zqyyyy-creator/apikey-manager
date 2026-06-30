# LiteLLM CustomLogger Deployment

This document describes how to deploy the MaaS CustomLogger into
`ds-api-gateway` / `lag-proxy`.

## Scope

The CustomLogger supports two deployment modes. The current default mode is the
CK-driven budget sync strategy:

- Managed MaaS keys neutralize LiteLLM default realtime cost.
- CK/ByteHouse budget sync writes the authoritative spend into LiteLLM DB and
  Redis counters.
- Non-managed keys are skipped and continue using LiteLLM default spend logic.
- LiteLLM budget enforcement can continue checking `spend >= max_budget`.

Optional realtime cost replacement can be enabled with
`MAAS_V2_REALTIME_COST_ENABLED=true`.

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
MAAS_V2_REALTIME_COST_ENABLED=false
MAAS_V2_BUDGET_SYNC_ENABLED=true
MAAS_V2_BUDGET_SYNC_INTERVAL_SECONDS=3600
```

Use the in-cluster MaaS API service URL for `MAAS_V2_API_URL` in Kubernetes.
The budget sync job runs inside the Gateway callback process. It starts during
callback initialization when LiteLLM loads the module inside a running event
loop, and falls back to starting on the first successful request if the callback
was imported earlier. It calls MaaS internal API, reads CK-derived spend, then
updates LiteLLM key spend, `max_budget`, `budget_duration`, `budget_limits`,
and Redis spend counters.

## Optional MaaS API Billing Service Environment Variables

The default CK sync strategy does not require billing service configuration.
Set these in the MaaS API process only when
`MAAS_V2_REALTIME_COST_ENABLED=true`:

```env
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
BILLING_SERVICE_TIMEOUT=5.0
```

`BILLING_SERVICE_URL` is an optional external service dependency. It is not
provided or started by this repository.

The current MaaS implementation posts this JSON to:

```text
{BILLING_SERVICE_URL}{BILLING_SERVICE_COST_PATH}
```

```json
{
  "model": "deepseek-v3",
  "input_tokens": 1000,
  "output_tokens": 200,
  "cache_tokens": 500
}
```

MaaS accepts either a direct cost response:

```json
{
  "data": {
    "cost": "0.052",
    "charge_detail": {
      "input_cost": "0.040",
      "output_cost": "0.010",
      "cache_cost": "0.002"
    }
  }
}
```

or a model rate response:

```json
{
  "data": {
    "input_rate": "0.000001",
    "output_rate": "0.000002",
    "cache_rate": "0.0000002"
  }
}
```

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
maas_custom_logger_realtime_cost_skipped_for_managed_key
maas_budget_sync_completed
```

For local callback-to-MaaS connectivity checks with the mock model, the request
can include `_encrypted_content_affinity_pinned=true` to bypass this Gateway
branch's Router Redis prediction path. Full budget/spend verification should use
the Gateway's normal Redis configuration.

This means:

```text
LiteLLM success callback
-> MaaS internal managed API
-> managed=true
-> delta = 0 - litellm_default_cost
-> neutralize LiteLLM default realtime spend
```

Budget sync flow:

```text
LiteLLM Gateway background callback task, every 3600s
-> MaaS internal budget-sync API
-> ClickHouse dws_para_statements_changelog spend aggregation
-> LiteLLM_VerificationToken spend / budget fields update
-> Redis spend:key:{token} and spend:key:{token}:window:{duration} update
```

For optional realtime cost replacement only, verify the external billing service
is listening from the MaaS API host:

```bash
curl -i "http://localhost:8080"
```

Then verify MaaS internal cost lookup directly:

```bash
curl -i \
  -H "x-internal-api-key: ${MAAS_V2_INTERNAL_API_KEY}" \
  "http://127.0.0.1:8000/api/v1/internal/keys/${KEY_HASH_ID}/cost?model=deepseek-v3&input_tokens=1000&output_tokens=200&cache_tokens=500"
```

Expected result:

```json
{
  "code": 0,
  "data": {
    "managed": true,
    "cost": "...",
    "currency": "CNY",
    "charge_detail": {
      "input_cost": "...",
      "output_cost": "...",
      "cache_cost": "..."
    }
  },
  "message": "success"
}
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

Only applies when `MAAS_V2_REALTIME_COST_ENABLED=true`. The Gateway could not
call MaaS internal cost API. Check service URL, network, and internal API key.

MaaS internal cost API returns `500` or logs an external billing service error.

Check that `BILLING_SERVICE_URL` is reachable from the MaaS API process:

```bash
curl -i "http://localhost:8080"
```

If the billing service is running but the internal cost API still fails, check
`BILLING_SERVICE_COST_PATH`, the request schema, response schema, and any
required billing-service authentication headers.

`maas_custom_logger_managed_lookup_failed`

The Gateway could not call MaaS internal managed API. Check `MAAS_V2_API_URL`,
network connectivity, and `MAAS_V2_INTERNAL_API_KEY`.

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
