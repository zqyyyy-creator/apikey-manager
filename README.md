# MaaS v2 Client API

MaaS v2 Client API 用于管理 MaaS 托管的 LiteLLM Key、消费阈值、账单查询，以及供 LiteLLM CustomLogger 调用的内部同步接口。

本项目实现以 `PLAN.md` 和 `API_SPEC.md` 为准。

## 服务职责

- 通过 OAuth2 introspection 和 `x-user-id` 校验用户请求。
- 通过 `lag-proxy` 创建、查询、更新、吊销、解封托管 LiteLLM Key。
- 在 MySQL 中保存 managed key 元数据。
- 查询 ByteHouse/ClickHouse 账单数据，提供单 Key 和 Team 汇总账单 API。
- 管理 spending limits，并同步预算配置到 LiteLLM。
- 提供 LiteLLM CustomLogger 使用的内部接口：

  ```text
  GET /api/v1/internal/keys/{key_hash_id}/managed
  GET /api/v1/internal/keys/{key_hash_id}/cost
  GET /api/v1/internal/budget-sync/keys
  ```

- 在本仓库维护 CustomLogger 实现：

  ```text
  app/litellm_integration/custom_logger.py
  ```

## 关键设计

- `key_hash_id` 是 managed key 的主标识。
- raw key 只在创建时返回一次，MaaS 不落库存储 raw key。
- managed key 不提供删除接口；如需停用，只能调用 revoke，并保留审计记录。
- `team_id` 由服务端根据 `user_id` 生成：
  - 测试环境：`AI_TEST_{user_id}`
  - 生产环境：`AI_PRD_{user_id}`
- 账单金额和预算金额统一按 CNY 处理。
- LiteLLM budget 只做数值比较，不做 USD/CNY 换算。
- 当前 ClickHouse 账单表统一使用：

  ```text
  dws_para_statements_changelog
  ```

  对应配置：

  ```env
  CH_DBT_BILLING_TABLE=dws_para_statements_changelog
  ```

  早期 PLAN 中部分段落提到过 `dws_para_statements`；当前实现和本地/dev 配置以 `dws_para_statements_changelog` 为准，并在聚合前对 changelog 行做去重。

## 主要接口

- `GET /health`
- `GET /api/v1/debug/auth`（默认仅 `ENV_MODE!=prod` 时启用）
- `POST /api/v1/keys`
- `GET /api/v1/keys`
- `GET /api/v1/keys/{key_id}`
- `PATCH /api/v1/keys/{key_id}/revoke`
- `PATCH /api/v1/keys/{key_id}/unblock`
- `POST /api/v1/keys/{key_id}/limits`
- `GET /api/v1/keys/{key_id}/limits`
- `PATCH /api/v1/keys/{key_id}/limits/{limit_id}`
- `DELETE /api/v1/keys/{key_id}/limits/{limit_id}`
- `GET /api/v1/keys/{key_id}/billing`
- `GET /api/v1/billing/summary`
- `GET /api/v1/internal/keys/{key_hash_id}/cost`
- `GET /api/v1/internal/budget-sync/keys`

当 `ENABLE_DOCS=true` 时，本地 API 文档地址为：

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
http://127.0.0.1:8000/openapi.json
```

## 环境变量

复制 `.env.example` 为 `.env`，并按当前环境填写配置。

核心配置示例：

```env
ENV_MODE=test
DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/maas_v2

CH_DBT_SCHEME=https
CH_DBT_HOST=bytehouse.example.com
CH_DBT_PORT=8123
CH_DBT_USER=user
CH_DBT_PASSWORD=password
CH_DBT_DATABASE=dev_dbt_data
CH_DBT_BILLING_TABLE=dws_para_statements_changelog

LAG_PROXY_URL=http://localhost:8001
LAG_PROXY_TIMEOUT=30.0

OAUTH2_INTROSPECT_URL=https://auth.example.com/oauth/introspect
OAUTH2_INTROSPECT_TIMEOUT=5.0
OAUTH2_TOKEN_CACHE_MAX=1000
OAUTH2_TOKEN_CACHE_DEFAULT_TTL=300
DEFAULT_CLIENT_ID=maas2ss

ENABLE_DOCS=true
ENABLE_DEBUG_ROUTES=

INTERNAL_API_KEY=change-me

COST_CACHE_MANAGED_TTL=300
COST_CACHE_RATE_TTL=600
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
BILLING_SERVICE_TIMEOUT=5.0
```

默认方案下，Gateway 插件不依赖 `BILLING_SERVICE_URL` 做实时计费，managed key 的 spend 以 ClickHouse/ByteHouse budget sync 结果为准。`BILLING_SERVICE_URL` 仅在开启 `MAAS_V2_REALTIME_COST_ENABLED=true` 时用于可选实时 cost API。

## 本地启动

执行目录：

```bash
cd /home/qyz/apikey-manager/maas-v2-client-api
```

启动命令：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

预期输出：

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete
```

健康检查：

```bash
curl -i "http://127.0.0.1:8000/health"
```

## 认证

大多数对外 API 需要：

```http
Authorization: Bearer <access_token>
x-user-id: <user_id>
```

服务会通过 `OAUTH2_INTROSPECT_URL` introspect token，并通过 `client_user_mapping` 校验 token 对应的用户是否等于请求头中的 `x-user-id`。

CustomLogger 内部接口需要：

```http
x-internal-api-key: <INTERNAL_API_KEY>
```

内部接口不走用户 OAuth2，只允许 Gateway / 内部网络用
`x-internal-api-key` 调用。

## 账单查询

账单接口查询 ClickHouse/ByteHouse，单次查询日期范围最大 7 天。

当前表名：

```text
{CH_DBT_DATABASE}.dws_para_statements_changelog
```

核心字段映射：

- `service_user_id`：用户/Team 账单过滤字段
- `resource_uuid`：Key/资源标识
- `resource_scale`：模型名称
- `resource_used_count`：token/request 数量
- `used_value`：分 charge type 的金额
- `real_price`：实际 CNY 消费金额
- `billing_date`：账单日期

查询示例：

```bash
curl -s "http://127.0.0.1:8000/api/v1/billing/summary?start_date=2026-06-23&end_date=2026-06-29&group_by=key&page=1&page_size=100" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "x-user-id: ${USER_ID}" \
  | python -m json.tool
```

## LiteLLM CustomLogger 集成

CustomLogger 代码维护在：

```text
app/litellm_integration/custom_logger.py
```

部署时复制到 `ds-api-gateway`，由 LiteLLM Gateway 加载。CustomLogger 会调用 MaaS 内部接口：

```text
GET /api/v1/internal/keys/{key_hash_id}/managed
GET /api/v1/internal/keys/{key_hash_id}/cost?model=...&input_tokens=...&output_tokens=...&cache_tokens=...
GET /api/v1/internal/budget-sync/keys
```

CustomLogger 当前包含两条链路：

1. 默认方案 A：请求成功后，调用 managed API 判断是否为 managed key。managed key 不做实时 billing service 计费，并抵消 LiteLLM 默认实时 cost；非 managed key 不受影响，继续走 LiteLLM 默认 spend 逻辑。
2. 启用 budget sync 后，Gateway 后台任务定时调用 budget-sync API。插件在 Gateway callback 初始化时优先启动后台任务；如果 LiteLLM 加载 callback 时还没有可用事件循环，则在第一次成功请求后兜底启动。MaaS API 基于 ClickHouse changelog 账单计算 spend，并返回 key 级 `max_budget`、`budget_duration`、`budget_limits` 和窗口 spend。插件将这些值写回 LiteLLM `LiteLLM_VerificationToken` 和 Redis counter。
3. 可选实时计费：如果设置 `MAAS_V2_REALTIME_COST_ENABLED=true`，请求成功后会调用 cost API，再由 MaaS API 调外部 billing service，用 MaaS CNY 成本替换 LiteLLM 默认成本。

Gateway 侧环境变量示例：

```env
MAAS_V2_API_URL=http://maas-v2-client-api:8000
MAAS_V2_INTERNAL_API_KEY=<same value as MaaS INTERNAL_API_KEY>
MAAS_V2_API_TIMEOUT=3.0
MAAS_V2_REALTIME_COST_ENABLED=false
MAAS_V2_BUDGET_SYNC_ENABLED=true
MAAS_V2_BUDGET_SYNC_INTERVAL_SECONDS=3600
```

仅当 `MAAS_V2_REALTIME_COST_ENABLED=true` 时，MaaS API 的 cost API 会再调用外部 billing service：

```env
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
```

详细部署说明：

```text
docs/litellm_custom_logger_deploy.md
app/litellm_integration/README.md
```

可选实时计费模式的本地 mock billing service 启动命令：

```bash
cd /home/qyz/apikey-manager/maas-v2-client-api
.venv/bin/python tools/mock_billing_service.py
```

## 测试

自动化测试：

```bash
cd /home/qyz/apikey-manager/maas-v2-client-api
UV_CACHE_DIR=/tmp/uv-cache uv run --frozen pytest -vv
```

当前已知结果：

```text
60 passed
```

手动联调和验收状态记录在：

```text
docs/final_test_checklist.md
```

## Docker / K8s 部署模板

本仓库提供基础容器和 K8s 模板：

```text
Dockerfile
k8s/configmap.yaml
k8s/secret.example.yaml
k8s/deployment.yaml
k8s/service.yaml
```

构建镜像示例：

```bash
cd /home/qyz/apikey-manager/maas-v2-client-api
docker build -t maas-v2-client-api:latest .
```

K8s 模板说明：

- `k8s/configmap.yaml`：非敏感环境变量示例。
- `k8s/secret.example.yaml`：敏感环境变量示例，不能直接用于生产。
- `k8s/deployment.yaml`：MaaS API Deployment 模板。
- `k8s/service.yaml`：ClusterIP Service 模板。

部署前需要按实际环境替换：

- 镜像地址和 tag
- MySQL `DATABASE_URL`
- ClickHouse/ByteHouse 用户名和密码
- `INTERNAL_API_KEY`
- `LAG_PROXY_URL`
- `OAUTH2_INTROSPECT_URL`
- `BILLING_SERVICE_URL`（仅可选实时计费模式需要）

## 当前已知阻塞项

- 可选实时外部 billing service 联调暂时阻塞。默认方案 A 不依赖该服务；如后续开启 `MAAS_V2_REALTIME_COST_ENABLED=true`，还需要确认 billing service 仓库、启动命令、真实 path、请求/响应 schema 和鉴权要求。
- `resource_uuid -> key_hash_id` 的真实映射表/来源还未接入。当前实现将 `resource_uuid` 暂按 `key_hash_id` 处理，真实联调前必须确认账单资源标识与 managed key 的对应关系。
- LiteLLM budget sync 已在本地 Gateway 触发并出现 `maas_budget_sync_completed` 日志，但还未用真实 managed key 验证 LiteLLM Postgres 表和 Redis counter 的最终写入结果。
- spending limit 自动 block 真实联调暂时阻塞。需要一把真实 ClickHouse 消费金额达到阈值的 managed key，验证 LiteLLM 请求前拦截效果。

## 相关文档

- `PLAN.md`
- `API_SPEC.md`
- `docs/litellm_custom_logger_deploy.md`
- `docs/final_test_checklist.md`
- `app/litellm_integration/README.md`
