# LiteLLM Gateway Integration

`custom_logger.py` is maintained in this repository and deployed into the
LiteLLM Gateway process.

The CustomLogger replaces LiteLLM default pricing for MaaS managed keys:

1. Extract the hashed key id from LiteLLM callback metadata.
2. Call MaaS internal API:
   `GET /api/v1/internal/keys/{key_hash_id}/cost`.
3. If the key is not managed, skip and let LiteLLM default spend tracking run.
4. If the key is managed, calculate:
   `delta = maas_cost - litellm_default_cost`.
5. Write the delta into LiteLLM DB and Redis spend counters so final spend is
   equal to the MaaS CNY cost.

Required environment variables in the Gateway process:

```env
MAAS_V2_API_URL=http://maas-v2-client-api:8000
MAAS_V2_INTERNAL_API_KEY=<same value as maas-v2-client-api INTERNAL_API_KEY>
MAAS_V2_API_TIMEOUT=3.0
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

## MaaS API Billing Service Dependency

The Gateway callback does not call the external billing service directly. The
request flow is:

```text
LiteLLM Gateway
-> MaaS internal cost API
-> external billing service configured by BILLING_SERVICE_URL
```

The MaaS API process must have these environment variables:

```env
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
BILLING_SERVICE_TIMEOUT=5.0
```

`BILLING_SERVICE_URL` is the external billing service base URL. The service is
not started by this repository. PLAN requires this integration, but the real
billing service repository, startup command, path, request schema, response
schema, and authentication requirements must be confirmed with the billing
service owner.

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

Before running Gateway-to-MaaS tests, verify the billing service is listening:

```bash
curl -i "http://localhost:8080"
```

If this returns `Failed to connect`, the billing service is not running and
MaaS internal cost lookup for managed keys will fail.
