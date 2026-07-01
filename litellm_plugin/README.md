# LiteLLM Gateway Plugin

This directory contains the MaaS LiteLLM Gateway callback file that can be
copied into `ds-api-gateway` for local or deployment testing.

## Files

```text
custom_callbacks.py
```

The file defines:

```python
maas_custom_logger = MaasCustomLogger()
proxy_handler_instance = maas_custom_logger
```

LiteLLM Gateway loads this object from `proxy_server_config.yaml`.

## Default Billing Mode

The default mode is CK/ByteHouse budget sync:

```env
MAAS_V2_REALTIME_COST_ENABLED=false
MAAS_V2_BUDGET_SYNC_ENABLED=true
MAAS_V2_BUDGET_SYNC_INTERVAL_SECONDS=3600
```

In this mode, managed keys do not use LiteLLM default realtime cost as the
authoritative spend. The callback neutralizes LiteLLM default realtime cost for
managed keys, and the background sync loop writes CK-derived spend into LiteLLM
DB and Redis counters.

Optional realtime billing-service mode is still available:

```env
MAAS_V2_REALTIME_COST_ENABLED=true
```

Only this optional mode requires MaaS API `BILLING_SERVICE_URL`.

## Copy To Gateway

From `/home/qyz/apikey-manager`:

```bash
cp maas-v2-client-api/litellm_plugin/custom_callbacks.py \
   ds-api-gateway/litellm/integrations/maas_custom_logger.py
```

Then make sure `ds-api-gateway/proxy_server_config.yaml` contains the callback:

```yaml
litellm_settings:
  callbacks: litellm.integrations.maas_custom_logger.maas_custom_logger
  success_callback: ["prometheus"]
  failure_callback: ["litellm.integrations.maas_custom_logger.maas_custom_logger"]
```

If the Gateway config already has callbacks, merge this callback instead of
replacing unrelated existing entries.

## Required Gateway Environment Variables

```env
MAAS_V2_API_URL=http://maas-v2-client-api:8000
MAAS_V2_INTERNAL_API_KEY=<same value as MaaS INTERNAL_API_KEY>
MAAS_V2_API_TIMEOUT=3.0
MAAS_V2_REALTIME_COST_ENABLED=false
MAAS_V2_BUDGET_SYNC_ENABLED=true
MAAS_V2_BUDGET_SYNC_INTERVAL_SECONDS=3600
```
