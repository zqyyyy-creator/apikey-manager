# MaaS v2 Client API Test Checklist

This checklist summarizes the local/dev validation status against `PLAN.md` and
`API_SPEC.md`.

## Environment

- User ID:
  `SELF-TeRR3Kt9lmHuY5fXoQ_tiz_RhSXzXta8kNmHpUutbII`
- Team ID:
  `AI_TEST_SELF-TeRR3Kt9lmHuY5fXoQ_tiz_RhSXzXta8kNmHpUutbII`
- Main managed key hash:
  `a75c3c13aab0268d3333a942e117091225acb5c4434fc2bcedf869527d570571`
- ClickHouse billing table:
  `dev_dbt_data.dws_para_statements_changelog`

## Passed

- MySQL connectivity passed.
- ClickHouse connectivity passed.
- OAuth access token and user mapping validation passed.
- Managed key create/list/detail flow passed.
- Raw key is returned only at creation time and is not stored by MaaS.
- Key billing API returned `200 OK`.
- Key detail `usage_summary` returns `today_cost` and `total_cost_7d`.
- Internal cost API works for managed and non-managed keys in local tests.
- LiteLLM CustomLogger local chain passed with mock billing service:
  `ds-api-gateway -> CustomLogger -> MaaS internal cost API -> mock billing`.
- CustomLogger success path logged `maas_custom_logger_managed_cost_synced`.
- Non-managed/missing key paths were validated.
- `unblock` now calls LiteLLM reset spend before marking the key active.
- Route tests no longer hang on TestClient; ASGI test helper is used.
- Full automated test suite passed.

## Blocked

- Real external billing service integration is blocked.
  - Current configured base URL: `BILLING_SERVICE_URL=http://localhost:8080`
  - Local check failed because no service is listening on port `8080`.
  - Need billing service repository, startup command, final API path, request
    schema, response schema, and authentication requirements.

- Spending limit automatic block real integration is blocked by test data.
  - Current team billing summary for `2026-06-23` through `2026-06-29` returned
    no items and `total_cost = 0`.
  - The API accepts two-decimal limit amounts, so a real positive bill of at
    least `0.01 CNY` is needed to trigger `cost >= limit.amount`.

## Needs Follow-Up

- Run internal cost API against the real billing service after the service
  contract is confirmed.
- Run the full Gateway chain again with the real billing service replacing the
  mock billing service.
- Run spending limit automatic block with a key that has real ClickHouse cost
  `>= 0.01 CNY`.
- Run unblock/reset spend positive integration when a real blocked key exists.
- Confirm final ds-api-gateway deployment config for `custom_callbacks.py` and
  MaaS environment variables.
- Keep ClickHouse table naming aligned on
  `dws_para_statements_changelog`.

## Useful Commands

Check billing summary for the current dev team:

```bash
curl -s "http://127.0.0.1:8000/api/v1/billing/summary?start_date=2026-06-23&end_date=2026-06-29&group_by=key&page=1&page_size=100" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "x-user-id: ${USER_ID}" \
  | python -m json.tool
```

Check internal cost API:

```bash
curl -i \
  -H "x-internal-api-key: ${MAAS_V2_INTERNAL_API_KEY}" \
  "http://127.0.0.1:8000/api/v1/internal/keys/${KEY_HASH_ID}/cost?model=deepseek-v3&input_tokens=1000&output_tokens=200&cache_tokens=500"
```

Run automated tests:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --frozen pytest -vv
```
