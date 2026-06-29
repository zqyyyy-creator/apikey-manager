# MaaS v2 Client API

MaaS v2 Client API 用于管理 MaaS 托管的 LiteLLM Key、消费阈值、账单查询，以及供 LiteLLM CustomLogger 调用的内部计费接口。

本项目实现以 `PLAN.md` 和 `API_SPEC.md` 为准。

## 服务职责

- 通过 OAuth2 introspection 和 `x-user-id` 校验用户请求。
- 通过 `lag-proxy` 创建、查询、更新、吊销、解封托管 LiteLLM Key。
- 在 MySQL 中保存 managed key 元数据。
- 查询 ByteHouse/ClickHouse 账单数据，提供单 Key 和 Team 汇总账单 API。
- 管理 spending limits，并同步预算配置到 LiteLLM。
- 提供 LiteLLM CustomLogger 使用的内部 cost API：

  ```text
  GET /api/v1/internal/keys/{key_hash_id}/cost
  ```

- 在本仓库维护 CustomLogger 实现：

  ```text
  app/litellm_integration/custom_logger.py
  ```

## 关键设计

- `key_hash_id` 是 managed key 的主标识。
- raw key 只在创建时返回一次，MaaS 不落库存储 raw key。
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
- `GET /api/v1/debug/auth`
- `POST /api/v1/keys`
- `GET /api/v1/keys`
- `GET /api/v1/keys/{key_id}`
- `PATCH /api/v1/keys/{key_id}`
- `DELETE /api/v1/keys/{key_id}`
- `PATCH /api/v1/keys/{key_id}/unblock`
- `POST /api/v1/keys/{key_id}/limits`
- `GET /api/v1/keys/{key_id}/limits`
- `PATCH /api/v1/keys/{key_id}/limits/{limit_id}`
- `DELETE /api/v1/keys/{key_id}/limits/{limit_id}`
- `GET /api/v1/keys/{key_id}/billing`
- `GET /api/v1/billing/summary`
- `GET /api/v1/internal/keys/{key_hash_id}/cost`

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

INTERNAL_API_KEY=change-me

COST_CACHE_MANAGED_TTL=300
COST_CACHE_RATE_TTL=600
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
BILLING_SERVICE_TIMEOUT=5.0
```

`BILLING_SERVICE_URL` 是外部 billing service 依赖。本仓库不会启动真实 billing service。

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

## CustomLogger 集成

CustomLogger 代码维护在：

```text
app/litellm_integration/custom_logger.py
```

部署时复制到 `ds-api-gateway`，由 LiteLLM Gateway 加载。CustomLogger 会调用 MaaS 内部接口：

```text
GET /api/v1/internal/keys/{key_hash_id}/cost?model=...&input_tokens=...&output_tokens=...&cache_tokens=...
```

MaaS API 再调用外部 billing service：

```env
BILLING_SERVICE_URL=http://localhost:8080
BILLING_SERVICE_COST_PATH=/api/v1/cost/calculate
```

详细部署说明：

```text
docs/litellm_custom_logger_deploy.md
app/litellm_integration/README.md
```

本地 mock billing service 启动命令：

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
54 passed
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
- `BILLING_SERVICE_URL`

## 当前已知阻塞项

- 真实外部 billing service 联调暂时阻塞。还需要确认 billing service 仓库、启动命令、真实 path、请求/响应 schema 和鉴权要求。
- spending limit 自动 block 真实联调暂时阻塞。当前 dev team 在 ClickHouse 中最近 7 天没有可用账单数据，`total_cost = 0`，需要一把真实 ClickHouse 消费金额 `>= 0.01 CNY` 的 Key 才能触发 block。

## 相关文档

- `PLAN.md`
- `API_SPEC.md`
- `docs/litellm_custom_logger_deploy.md`
- `docs/final_test_checklist.md`
- `app/litellm_integration/README.md`
