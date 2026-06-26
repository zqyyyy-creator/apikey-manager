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
