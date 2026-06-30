# LiteLLM Gateway Integration

`custom_logger.py` is maintained in this repository and deployed into the
LiteLLM Gateway process.

By default, the CustomLogger uses the CK-driven budget sync strategy for MaaS
managed keys:

1. Extract the hashed key id from LiteLLM callback metadata.
2. Call MaaS internal API:
   `GET /api/v1/internal/keys/{key_hash_id}/managed`.
3. If the key is not managed, skip and let LiteLLM default spend tracking run.
4. If the key is managed, neutralize LiteLLM default realtime cost for that
   request.
5. Let the background budget sync loop write CK-derived spend into LiteLLM DB
   and Redis budget counters.

Optional realtime cost replacement is still available by setting
`MAAS_V2_REALTIME_COST_ENABLED=true`. In that mode, the callback calls
`GET /api/v1/internal/keys/{key_hash_id}/cost` and writes
`delta = maas_cost - litellm_default_cost` into LiteLLM spend counters.

Required environment variables in the Gateway process:

```env
MAAS_V2_API_URL=http://maas-v2-client-api:8000
MAAS_V2_INTERNAL_API_KEY=<same value as maas-v2-client-api INTERNAL_API_KEY>
MAAS_V2_API_TIMEOUT=3.0
MAAS_V2_REALTIME_COST_ENABLED=false
MAAS_V2_BUDGET_SYNC_ENABLED=true
MAAS_V2_BUDGET_SYNC_INTERVAL_SECONDS=3600
```

Example LiteLLM Gateway config:

```yaml
litellm_settings:
  callbacks: custom_callbacks.maas_custom_logger
  success_callback: ["prometheus"]
  failure_callback: ["custom_callbacks.maas_custom_logger"]
```

If the real Gateway already has callbacks, merge the MaaS callback into the
existing config instead of replacing unrelated callbacks.

When `MAAS_V2_BUDGET_SYNC_ENABLED=true`, the callback also starts a background
sync loop in the Gateway process. It starts during callback initialization when
LiteLLM loads the module inside a running event loop, and falls back to starting
on the first successful request if the callback was imported earlier. The loop
pulls CK-derived spend from MaaS internal API and writes the values into LiteLLM
key spend, budget fields, and Redis budget counters.

## Optional MaaS API Billing Service Dependency

The default CK sync strategy does not require an external billing service.
Only enable the following realtime request flow when
`MAAS_V2_REALTIME_COST_ENABLED=true`:

```text
LiteLLM Gateway
-> MaaS internal cost API
-> external billing service configured by BILLING_SERVICE_URL
```

The MaaS API process must have these environment variables for realtime cost
replacement:

```env
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
BILLING_SERVICE_TIMEOUT=5.0
```

`BILLING_SERVICE_URL` is the optional external billing service base URL. The
service is not started by this repository.

The current MaaS implementation sends:

```json
{
  "model": "deepseek-v3",
  "input_tokens": 1000,
  "output_tokens": 200,
  "cache_tokens": 500
}
```

The current MaaS implementation accepts either a direct cost response:

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

or a rate response, which MaaS caches by model and multiplies by token count:

```json
{
  "data": {
    "input_rate": "0.000001",
    "output_rate": "0.000002",
    "cache_rate": "0.0000002"
  }
}
```

Before running optional realtime-cost Gateway-to-MaaS tests, verify the billing
service is listening:

```bash
curl -i "http://localhost:8080"
```

If this returns `Failed to connect`, the optional realtime cost lookup for
managed keys will fail. The default CK budget sync mode does not require this
service.
