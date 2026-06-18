# 面向大客户的 MaaS API 接口 — 实施计划

## 一、需求完善

### 1.1 核心功能

| 功能模块 | 描述 |
|---------|------|
| **网关 Key 管理** | 在指定 team 下创建/查看/吊销 gateway key（不可删除，只可吊销） |
| **账单查询** | 查询每个 key 的消费账单（最近7日），数据来源于 ClickHouse (dbt) |
| **消费阈值** | 为 key 设置消费限额，超限时自动 block 该 key |
| **OAuth2 认证** | client_credentials 模式，对接公司自研认证中心 |

### 1.2 需求细化与补充

#### 网关 Key 管理
- 创建 key：指定 team_id，系统生成 key（建议前缀 `sk-maas-` + 随机串，仅展示一次）
- 查看 key 列表：按 team 过滤，分页查询
- 查看 key 详情：key 元信息 + 当前消费状态
- 吊销 key：不可删除，只能将状态改为 revoked（软吊销）
- key 状态机：`active` → `blocked`（超限）/ `revoked`（手动吊销）
- **不提供 DELETE 接口**，key 一旦创建不可删除，保留审计记录

#### 账单查询
- 数据源：ClickHouse (dbt 产出)
- 查询范围：最近7天
- 聚合维度：按 key / 按 key+日期 / 按 key+模型
- 返回字段：key_id, 日期, 模型, 请求次数, token 数(输入/输出), 消费金额

#### 消费阈值（基于 LiteLLM Budget 实时拦截）
- 设置：为 key 配置单日/总额消费阈值，同步写入 LiteLLM key 的 `max_budget` + `budget_duration`
- 检查机制（双层）：
  - **实时拦截**：LiteLLM 网关在请求前检查 `spend >= max_budget`，超限直接拒绝请求（`BudgetExceededError`）
  - **被动兜底**：本服务查询账单时同步检查消费状态，超限则更新 key 状态为 blocked
- Spend 来源：通过 CustomLogger 回调，在每次请求完成后调用本服务 API 获取计费金额（替换 LiteLLM 默认计价），将消费金额写入 LiteLLM 的 DB + Redis 计数器。非 managed_key 走默认策略。
- 告警：超限时可通过 webhook 通知（一期不做，预留 TODO 埋点，后续迭代加）
- 解除 block：手动操作，或重置消费周期

#### OAuth2 认证
- client_credentials 模式：client 拿 client_id + client_secret 换 access_token
  - **client_id = `maas2ss`**（大客户专用，由认证中心预注册）
  - 用户获取 token 参考：hydra console-api-entry 的 OAuth2 封装
- token 验证：本服务作为资源服务器，调用自研认证中心的 introspection 端点验证 token
  - **参考实现**：`lag-proxy` 的 `AuthService`（introspection + TTL 缓存），位于 `app/services/auth.py`
  - 缓存策略：`(introspect_data, expire_at)` 元组，TTL = exp - now - 10s，默认 300s
  - 公共路径白名单：`/health`、`/docs`、`/redoc`、`/openapi.json`
- 权限控制（双层校验）：
  1. **token 中携带 client_id**：从 introspection 响应中提取，与本服务的 `client_user_mapping` 表匹配
  2. **请求 header 携带 `x-user-id`**：必须与 token 中 client_id 对应的 user_id 匹配，否则返回 403
  - 校验逻辑：`client_id → client_user_mapping → user_id == request.headers["x-user-id"]`
- 接口级别：所有 `/api/v1/*` 接口均需认证
- **team_id 规则**：
  - 生产环境：`AI_PRD_` + `[user_id]`
  - 测试环境：`AI_TEST_` + `[user_id]`
  - 从 team_id 反推 user_id 的正则：`^AI_(?:PRD|DEV|TEST)_(.+)$`

### 1.3 非功能性需求
- API 版本：`/api/v1/`
- 日志：结构化日志（JSON），请求级 trace_id
- 错误处理：统一错误响应格式
- 配置管理：环境变量 + `.env` 文件
- 健康检查：`/health` 端点
- **Swagger API 文档**：
  - 基于 FastAPI 自带的 OpenAPI 3.0 自动生成，供用户在线查看和调试接口
  - Swagger UI 路径：`/docs`（可交互测试）
  - ReDoc 路径：`/redoc`（只读，阅读友好）
  - OpenAPI JSON：`/openapi.json`（供第三方工具导入）
  - 环境控制：通过 `ENABLE_DOCS` 环境变量控制是否开启（生产环境可关闭）
  - 认证集成：Swagger UI 内置 Bearer token 输入框，用户可直接在页面上填入 access_token 进行接口调试
  - 公共路径白名单：`/health`、`/docs`、`/redoc`、`/openapi.json` 无需认证即可访问

---

## 二、技术架构

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│   Client     │────▶│  FastAPI Service  │────▶│   MySQL 8    │
│              │     │  (maas-v2-api)    │     │  (key/阈值)   │
└──────────────┘     │                  │     └─────────────┘
                     │  ┌────────────┐  │
                     │  │ OAuth2     │  │     ┌──────────────┐
                     │  │ Middleware │──┼────▶│ 自研认证中心   │
                     │  └────────────┘  │     │ (introspect) │
                     │                  │     └──────────────┘
                     │  ┌────────────┐  │
                     │  │ Billing    │  │     ┌─────────────┐
                     │  │ Service    │──┼────▶│ ClickHouse  │
                     │  └────────────┘  │     │ (dbt 账单)   │
                     │                  │     └─────────────┘
                     │  ┌────────────┐  │
                     │  │ LiteLLM    │  │     ┌──────────────────────────────┐
                     │  │ Sync via   │──┼────▶│  lag-proxy → LiteLLM Gateway │
                     │  │ lag-proxy  │  │     │              (ds-api-gw)     │
                     │  └────────────┘  │     │                              │
                     │                  │     │  ┌────────────────────────┐ │
                     └──────────────────┘     │  │ CustomLogger ★         │ │
                                              │  │ (本仓库开发,部署在GW内) │ │
                                              │  │ 调用本服务API获取计费   │ │
                                              │  └────────────────────────┘ │
                                              │  ┌────────────────────────┐ │
                                              │  │ Budget 检查 (实时拦截)  │ │
                                              │  │ spend >= max_budget    │ │
                                              │  │ → BudgetExceededError  │ │
                                              │  └────────────────────────┘ │
                                              │  ┌────────────────────────┐ │
                                              │  │ Redis 计数器            │ │
                                              │  │ spend:key:{token}      │ │
                                              │  └────────────────────────┘ │
                                              │  ┌────────────────────────┐ │
                                              │  │ PostgreSQL (key/team)  │ │
                                              │  └────────────────────────┘ │
                                              └──────────────────────────────┘
```

### 2.0 核心交互流程：消费阈值实时拦截

```
Client 请求 (sk-xxx)
    │
    ▼
LiteLLM Gateway
    │
    ├─ 1. user_api_key_auth() → 验证 key
    ├─ 2. common_checks() → 读取 Redis 计数器 spend:key:{token}
    │     └─ if spend >= max_budget → 拒绝请求 (429 BudgetExceededError)
    ├─ 3. _reserve_budget_after_common_checks() → 预留估算费用
    ├─ 4. 转发请求到 LLM Provider
    ├─ 5. 响应返回
    ├─ 6. CustomLogger.async_log_success_event() ← 【关键拦截点】
    │     ├─ 用本服务计费逻辑计算实际消费金额（替换 LiteLLM 默认计价）
    │     ├─ increment_spend_counters() → 更新 Redis spend:key:{token}
    │     ├─ DBSpendUpdateWriter → 更新 PostgreSQL VerificationToken.spend
    │     └─ reconcile_budget_reservation() → 调整预留到实际值
    │
    ▼
返回响应给 Client

═════════════════════════════════════════════════════════

阈值管理（本服务 FastAPI）:
    │
    ├─ 创建/修改阈值 → spending_limits 表 + 调用 LiteLLM /key/update 设置 max_budget
    ├─ 查询账单 → ClickHouse + 检查超限 → 更新 managed_keys.status = blocked
    └─ 解除 block → 调用 LiteLLM /key/{key}/reset_spend 重置 spend
```

### 2.1 技术栈
- **语言**：Python 3.13
- **包管理**：uv
- **框架**：FastAPI + Uvicorn
- **ORM**：SQLAlchemy 2.0 (async)
- **数据库**：MySQL 8 (key/阈值/client映射) + ClickHouse (账单查询)
- **数据库迁移**：Alembic
- **认证**：自研 OAuth2 client_credentials → introspection（参考 `lag-proxy` 的 `AuthService`）
- **数据校验**：Pydantic v2
- **日志**：structlog
- **容器化**：Docker + K8s
- **LiteLLM 集成**：通过 `lag-proxy` 调用 LiteLLM 管理 API（key/budget 同步）
- **LiteLLM CustomLogger**：回调替换默认计价（部署在 LiteLLM Gateway 侧）

### 2.1.1 外部服务依赖

| 服务 | 用途 | 调用方式 | 参考项目 |
|------|------|---------|---------|
| **lag-proxy** | LiteLLM 网关的代理层，本服务通过它调用 key/team 管理 API | K8s 内部服务名 | `../lag-proxy` |
| **自研认证中心** | OAuth2 introspection 验证 token | HTTP POST | hydra console-api-entry |
| **ClickHouse (ByteHouse)** | 账单数据查询 | HTTP 接口 | — |

### 2.2 项目结构

```
llm-3rd-api/
├── pyproject.toml              # uv 项目配置
├── uv.lock
├── Dockerfile
├── .env.example
├── .gitignore
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial.py
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app 入口
│   ├── config.py               # 配置管理 (pydantic-settings)
│   ├── database.py             # MySQL 连接
│   ├── clickhouse.py           # ClickHouse 连接
│   ├── dependencies.py         # 通用依赖注入（含 x-user-id 提取、team_id 自动生成）
│   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── managed_key.py
│   │   ├── client_user_mapping.py  # ★ OAuth2 client_id ↔ user_id 映射
│   │   └── spending_limit.py
│   ├── schemas/                # Pydantic 请求/响应模型
│   │   ├── __init__.py
│   │   ├── managed_key.py
│   │   ├── billing.py
│   │   ├── spending_limit.py
│   │   └── common.py          # 分页、错误响应等
│   ├── routers/                # API 路由
│   │   ├── __init__.py
│   │   ├── managed_keys.py
│   │   ├── billing.py
│   │   └── health.py
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── managed_key_service.py
│   │   ├── billing_service.py
│   │   ├── spending_limit_service.py
│   │   └── auth_service.py
│   ├── litellm_integration/    # ★ LiteLLM 网关集成
│   │   ├── __init__.py
│   │   ├── client.py           # LiteLLM 管理 API 客户端（/key/generate, /key/update, /key/{key}/reset_spend）
│   │   ├── custom_logger.py    # ★ CustomLogger 实现：替换默认计价，用本服务计费逻辑
│   │   ├── budget_sync.py      # 阈值→max_budget 同步逻辑
│   │   └── cost_calculator.py  # 调用外部计费服务 API 获取实际消费金额（CNY）
│   ├── middleware/              # 中间件
│   │   ├── __init__.py
│   │   ├── auth.py             # OAuth2 token 验证
│   │   └── logging.py          # 请求日志 + trace_id
│   └── utils/
│       ├── __init__.py
│       └── key_generator.py    # Key 生成工具
├── tests/
│   ├── __init__.py
│   ├── conftest.py             # pytest fixtures
│   ├── test_managed_keys.py
│   ├── test_billing.py
│   ├── test_spending_limits.py
│   ├── test_auth.py
│   └── test_litellm_integration.py  # ★ CustomLogger / budget_sync 测试
└── k8s/
    ├── deployment.yaml
    ├── service.yaml
    └── configmap.yaml
```

---

## 三、API 设计

### 3.1 网关 Key 管理

```
POST   /api/v1/keys                    # 创建 key
GET    /api/v1/keys                    # 列出 key（分页，可按 team 过滤）
GET    /api/v1/keys/{key_id}           # 查看 key 详情
PATCH  /api/v1/keys/{key_id}/revoke    # 吊销 key（不可删除）
PATCH  /api/v1/keys/{key_id}/unblock   # 解除 block
```

### 3.2 消费阈值

```
POST   /api/v1/keys/{key_id}/limits          # 设置消费阈值
GET    /api/v1/keys/{key_id}/limits          # 查看阈值配置
PATCH  /api/v1/keys/{key_id}/limits/{limit_id}  # 修改阈值
DELETE /api/v1/keys/{key_id}/limits/{limit_id}  # 删除阈值
```

### 3.3 账单查询

```
GET    /api/v1/keys/{key_id}/billing        # 查询 key 账单（最近7天）
GET    /api/v1/billing/summary              # 按条件汇总账单
```

### 3.4 系统

```
GET    /health                              # 健康检查
```

### 3.5 统一响应格式

```json
// 成功
{
  "code": 0,
  "data": { ... },
  "message": "success"
}

// 列表（分页）
{
  "code": 0,
  "data": {
    "items": [ ... ],
    "total": 100,
    "page": 1,
    "page_size": 20
  },
  "message": "success"
}

// 错误
{
  "code": 40001,
  "data": null,
  "message": "Key not found"
}
```

---

## 四、数据库设计

### 4.1 MySQL 8 — managed_keys 表

> **设计决策**：maas-v2-backend 的 `key_team` 表是 litellm 同步的映射关系表，与本项目"受管控 key 的生命周期管理"职责不同。
> `key_team` 侧重 key→team 的映射和别名，而 `managed_keys` 侧重 key 的创建/吊销/阻断/阈值等完整生命周期。
> 两者通过 `key_hash_id` 关联，但表结构独立，避免跨服务耦合。
> 表名 `managed_keys` 而非 `gateway_keys`，强调这些是"受管控的 key"——只有大客户或有阈值管理需求的 key 才会存入此表。

| 字段 | 类型 | 说明 |
|------|------|------|
| key_hash_id | VARCHAR(100) PK | key 的 SHA-256 哈希，主键（与 key_team.key_hash_id 对齐） |
| team_id | VARCHAR(100) | 所属团队 (litellm team_id) |
| name | VARCHAR(128) | key 名称/备注 |
| key_alias | VARCHAR(64) | key 别名（透传 LiteLLM 的 key_alias，用于展示识别） |
| description | VARCHAR(512) | key 用途描述（透传 LiteLLM 的 metadata.description） |
| status | ENUM('active','blocked','revoked') | key 状态 |
| blocked_reason | VARCHAR(256) | block 原因 |
| created_at | DATETIME | 创建时间 |
| revoked_at | DATETIME | 吊销时间 |
| blocked_at | DATETIME | block 时间 |

**与原设计的变化**：
- ~~PostgreSQL → MySQL 8~~
- ~~`id UUID` 自增主键 → `key_hash_id VARCHAR(100)` 自然主键~~（一个 key 一条记录，key_hash_id 天然唯一，与 key_team / billing_record / billing_usage_window / key_profile 关联链路一致）
- ~~`key_prefix` → `key_alias`~~，透传 LiteLLM 的 `key_alias` 字段（最长 64）
- ~~`key_hash VARCHAR(128)` → `key_hash_id VARCHAR(100)`~~（对齐 maas-v2-backend 命名）
- 新增 `description`（透传 LiteLLM `metadata.description`）

### 4.2 MySQL 8 — client_user_mapping 表

> **新建**：存储 OAuth2 client_id 与用户 user_id 的对应关系。
> 认证时需校验请求中的 `x-user-id` 与 token 中 client_id 绑定的 user_id 是否一致。
> 用户只需传 `x-user-id`，`team_id` 由服务端根据 user_id + 环境自动拼接，无需用户关心。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO_INCREMENT | 主键 |
| client_id | VARCHAR(100) UNIQUE | OAuth2 客户端 ID（如 `maas2ss`） |
| user_id | VARCHAR(100) NOT NULL | 对应的用户 ID |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

**team_id 生成规则**（服务端自动，不存表）：
- 生产环境：`team_id = "AI_PRD_" + user_id`
- 测试环境：`team_id = "AI_TEST_" + user_id`
- 环境区分通过配置项 `ENV_MODE=prod|test` 控制
- 从 team_id 反推 user_id 的正则：`^AI_(?:PRD|DEV|TEST)_(.+)$`

**认证校验流程**：
```
请求 → AuthMiddleware 校验 Bearer token
  │
  ├─ 1. AuthService.validate_token(token) → introspection → 获取 client_id
  ├─ 2. 查询 client_user_mapping 表：client_id → user_id
  ├─ 3. 比对 request.headers["x-user-id"] == mapped_user_id
  │     └─ 不匹配 → 403 Forbidden
  └─ 4. 通过 → 注入 user_id 到请求上下文
           → 服务端自动生成 team_id = f"AI_{ENV_PREFIX}_{user_id}"
```

**初始数据**：
```sql
INSERT INTO client_user_mapping (client_id, user_id)
VALUES ('maas2ss', '{user_id}');
```

### 4.3 MySQL 8 — spending_limits 表

> maas-v2-backend 中无此表，需要新建。后续可迁移到 maas-v2-backend。
> spending_limits 是本服务的阈值配置存储，会同步到 LiteLLM key 的 budget 字段实现实时拦截。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO_INCREMENT | 主键 |
| key_hash_id | VARCHAR(100) (FK → managed_keys.key_hash_id) | 关联 key |
| limit_type | ENUM('daily','total') | 阈值类型：单日/累计总额 |
| amount | DECIMAL(12,4) | 阈值金额 |
| currency | VARCHAR(8) | 币种，默认 CNY |
| enabled | BOOLEAN | 是否启用，默认 TRUE |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

**与 LiteLLM Budget 的映射关系**：

| spending_limits 字段 | LiteLLM Key 字段 | 映射逻辑 |
|---------------------|------------------|---------|
| `limit_type='daily'` + `amount` | `max_budget` + `budget_duration='1d'` | 单日限额 → LiteLLM 每日重置的 max_budget |
| `limit_type='total'` + `amount` | `max_budget`（无 budget_duration） | 累计总额 → LiteLLM 硬性 max_budget |
| `enabled=TRUE` | 同步设置 | 启用/禁用阈值 |
| `enabled=FALSE` | `max_budget=null` | 禁用 → 清除 LiteLLM 的 max_budget |

> ⚠️ 若同一 key 同时有 daily 和 total 限额，优先使用 total 的金额作为 `max_budget`（取较小值），
> 或使用 LiteLLM 的 `budget_limits` 多窗口预算特性同时支持两个限额。

**与原设计的变化**：
- ~~PostgreSQL → MySQL 8~~
- ~~`id UUID` → `id BIGINT AUTO_INCREMENT`~~
- ~~`key_id UUID (FK)` → `key_hash_id VARCHAR(100) (FK → managed_keys.key_hash_id)`~~（与 managed_keys 主键对齐，迁移到 maas-v2-backend 后可直接关联 key_team / billing_record 等）
- ~~`limit_type VARCHAR(16)` → `limit_type ENUM('daily','total')`~~
- ~~`currency 默认 USD` → `currency 默认 CNY`~~（对齐 maas-v2-backend 币种规范）

### 4.4 ClickHouse — 账单查询（dbt 已有表）

> **已确认**：表名 `dws_para_statements`，Distributed 引擎。
> - **生产库**：`prod_litellm_dbt_data.dws_para_statements`
> - **测试库**：`dev_dbt_data.dws_para_statements`
> - 通过配置项 `CLICKHOUSE_DB` 切换环境

**实际 DDL**：

```sql
CREATE TABLE prod_litellm_dbt_data.dws_para_statements
(
    `cluster_id`            Int64       COMMENT '集群id',
    `region_id`             Int64       COMMENT '地域id',
    `zone_id`               Int64       COMMENT '可用区id',
    `resource_type`         String      COMMENT '资源类型（固定 API_TOKEN）',
    `charge_detail_status`  String      COMMENT '账单状态',
    `start_time`            Int64       COMMENT '账单开始时间（毫秒时间戳）',
    `periodic_end_time`     Int64       COMMENT '账单结束时间（毫秒时间戳）',
    `user_id`               Int64       COMMENT '用户id',
    `billing_type`          String      COMMENT '计费方式（固定 PostPaid）',
    `periodic_start_time`   Int64       COMMENT '账单开始时间（同 start_time）',
    `sub_resource_type`     String      COMMENT '子资源类型（已废弃，ETL 置空）',
    `resource_uuid`         String      COMMENT '资源UUID',
    `resource_scale`        String      COMMENT '模型名称（来自 dim_model_registry.model）',
    `parent_resource_uuid`  String      COMMENT '父资源UUID',
    `used_value`            String      COMMENT '使用量',
    `resource_id`           Nullable(Int64)  COMMENT '资源id',
    `price_id`              Nullable(Int64)  COMMENT '定价策略id',
    `charge_type`           String      COMMENT '计费类型（INPUT/OUTPUT/CACHE/COUNT/VIDEO/AUDIO）',
    `paratera_uuid`         String      COMMENT 'Paratera UUID',
    `service_user_id`       String      COMMENT '服务用户ID（team_id 去掉 AI_PRD_ 前缀）',
    `statement_resource`    String      COMMENT '账单来源（固定 LLM_USAGE）',
    `resource_used_count`   String      COMMENT '资源使用量（token/request count）',
    `paratera_price`        Decimal(15,5) COMMENT '应收金额',
    `cost_price`            Decimal(15,5) COMMENT '成本价',
    `real_price`            Decimal(15,5) COMMENT '实收金额',
    `coupon_price`          Decimal(15,5) COMMENT '优惠券金额',
    `owed_price`            Decimal(15,5) COMMENT '欠费金额',
    `ai_price`              Decimal(15,5) COMMENT 'AI 价格',
    `ai_real_price`         Decimal(15,5) COMMENT 'AI 实收价格',
    `ai_coupon_price`       Decimal(15,5) COMMENT 'AI 优惠券价格',
    `ai_owed_price`         Decimal(15,5) COMMENT 'AI 欠费金额',
    `gratis_price`          Decimal(9,8)  COMMENT '赠送金额',
    `is_backfill`           UInt8       COMMENT '0=全量账单, 1=补采记录',
    `created_time`          DateTime    COMMENT '记录创建时间',
    `updated_time`          DateTime    COMMENT '记录更新时间',
    `billing_date`          Date        COMMENT '账单日期',
    `_etl_time`             DateTime    COMMENT 'ETL 处理时间'
)
ENGINE = Distributed('bytehouse_llm_cluster', 'prod_litellm_dbt_data',
    'local_dws_para_statements', cityHash64(user_id, billing_date))
COMMENT '全量账单表 v2 distributed（查询用）';
```

**关键字段映射**（ClickHouse → API 响应）：

| ClickHouse 字段 | 含义 | API 响应字段 | 说明 |
|-----------------|------|-------------|------|
| `service_user_id` | 服务用户ID | 查询过滤条件 | team_id 去掉 `AI_PRD_` 前缀 = user_id，**用此字段过滤用户** |
| `resource_scale` | 模型名称 | `model` | 来自 `dim_model_registry.model` |
| `charge_type` | 计费类型 | — | `INPUT` / `OUTPUT` / `CACHE` / `COUNT` / `VIDEO` / `AUDIO` |
| `resource_used_count` | 资源使用量（token/request count） | `input_tokens` / `output_tokens` / `cache_tokens` | 根据 `charge_type` 分别汇总，互不扣减 |
| `used_value` | 使用量对应金额 | `input_cost` / `output_cost` / `cache_cost` | **金额**（非 token 数），根据 `charge_type` 分别汇总，互不扣减 |
| `real_price` | 实收金额 | `cost` | 实际消费金额（CNY），各 charge_type 独立计费 |
| `billing_date` | 账单日期 | `date` | Date 类型 |
| `resource_uuid` | 资源UUID | 查询过滤条件 | 对应 key 的标识 |

> ⚠️ **重要**：`used_value` 和 `real_price` 都是**金额**（CNY），不是 token 数量。
> token 数量应从 `resource_used_count` 获取。
> - `resource_used_count`：token/request 数量（按 `charge_type` 区分 INPUT/OUTPUT/CACHE）
> - `used_value`：对应的使用量金额
> - `real_price`：实收金额

**⚠️ 缓存费用说明**：

当同一请求同时存在 `charge_type = 'INPUT'` 和 `charge_type = 'CACHE'` 的记录时：
- `input_tokens` = `INPUT.resource_used_count`（直接取值，不扣减缓存）
- `cache_tokens` = `CACHE.resource_used_count`（缓存命中量，独立展示）
- `input_cost` = `INPUT.used_value`（输入金额，直接取值，不扣减缓存）
- `cache_cost` = `CACHE.used_value`（缓存金额，独立展示）
- 两者各自独立计费，`INPUT` 和 `CACHE` 的 `real_price` 分别是各自的实收金额

```
请求: 1000 input tokens (其中 600 命中缓存)

ClickHouse 记录:
  charge_type=INPUT, resource_used_count=1000, used_value=1.00, real_price=1.00  ← 输入
  charge_type=CACHE, resource_used_count=600,  used_value=0.06, real_price=0.06  ← 缓存折扣

展示:
  input_tokens  = 1000    ← 直接取 INPUT.resource_used_count
  cache_tokens  = 600     ← 直接取 CACHE.resource_used_count
  input_cost    = 1.00    ← INPUT.used_value
  cache_cost    = 0.06    ← CACHE.used_value
  output_tokens = (同 charge_type=OUTPUT 的 resource_used_count)
  output_cost   = (同 charge_type=OUTPUT 的 used_value)
```

**查询示例**（按 key + 日期 + 模型聚合）：
```sql
SELECT
    resource_uuid          AS key_id,
    billing_date           AS date,
    resource_scale         AS model,
    count()                AS request_count,
    -- token 数量（从 resource_used_count 取值）
    sumIf(toFloat64OrZero(resource_used_count), charge_type = 'INPUT')   AS input_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type = 'CACHE')   AS cache_tokens,
    sumIf(toFloat64OrZero(resource_used_count), charge_type = 'OUTPUT')  AS output_tokens,
    -- 各 charge_type 的使用量金额（从 used_value 取值）
    sumIf(toFloat64OrZero(used_value), charge_type = 'INPUT')   AS input_cost,
    sumIf(toFloat64OrZero(used_value), charge_type = 'CACHE')   AS cache_cost,
    sumIf(toFloat64OrZero(used_value), charge_type = 'OUTPUT')  AS output_cost,
    -- 总实收金额
    sum(real_price)        AS cost
FROM {clickhouse_db}.dws_para_statements
WHERE service_user_id = '{user_id}'          -- 用 x-user-id 过滤
  AND billing_date >= toDate('{start_date}')
  AND billing_date <= toDate('{end_date}')
  AND statement_resource = 'LLM_USAGE'
  AND is_backfill = 0
GROUP BY resource_uuid, billing_date, resource_scale
ORDER BY billing_date DESC, cost DESC
```

> 💡 **费用计算逻辑**：总费用 = `sum(real_price)`，即所有 charge_type 的实收金额之和。
> INPUT、CACHE、OUTPUT 各自独立计费，不做扣减。

> ⚠️ `used_value` 和 `resource_used_count` 在 ClickHouse 中是 String 类型，查询时需 `toFloat64OrZero()` 转换。
> `service_user_id` 是 team_id 去掉 `AI_PRD_` 前缀的结果，即 user_id。

### 4.4 与 maas-v2-backend / LiteLLM 表的复用关系

| 表 | 本项目 | maas-v2-backend | LiteLLM Gateway | 复用/交互策略 |
|----|--------|-----------------|-----------------|-------------|
| `key_team` | ❌ 不建 | ✅ 已有 | — | 通过 `key_hash_id` 关联查询，不重复建表 |
| `managed_keys` | ✅ 新建 | ❌ 无 | — | 本项目独有，后续可迁移 |
| `client_user_mapping` | ✅ 新建 | ❌ 无 | — | OAuth2 client_id ↔ user_id 映射，认证校验用 |
| `spending_limits` | ✅ 新建 | ❌ 无 | — | 本项目独有，后续可迁移 |
| `LiteLLM_VerificationToken` | ❌ 不建 | — | ✅ 已有 | 通过 /key/update API 同步 max_budget/spend |
| `LiteLLM_SpendLogs` | ❌ 不建 | — | ✅ 已有 | CustomLogger 写入消费日志，按需查询 |

---

## 五、实施步骤

### Phase 1: 项目骨架 (Day 1)
1. **初始化项目**
   - `uv init` + 配置 `pyproject.toml`（Python 3.13）
   - 安装依赖：fastapi, uvicorn, sqlalchemy, aiomysql, clickhouse-driver, pydantic-settings, structlog, httpx, alembic, litellm
   - 配置 `.gitignore`, `.env.example`
   - **关键环境变量**：

     | 变量 | 说明 | 示例 |
     |------|------|------|
     | `ENV_MODE` | 环境模式：`prod` / `test`，决定 team_id 前缀和 ClickHouse 库名 | `prod` |
     | `DATABASE_URL` | MySQL 连接串 | `mysql+aiomysql://user:pass@host:3306/maas_v2` |
     | `CLICKHOUSE_URL` | ClickHouse HTTP 接口地址 | `http://bytehouse:8123` |
     | `CLICKHOUSE_DB` | ClickHouse 数据库名 | `prod_litellm_dbt_data` / `dev_dbt_data` |
     | `LAG_PROXY_URL` | lag-proxy 服务地址（K8s 内部） | `http://lag-proxy:8000` |
     | `LAG_PROXY_TIMEOUT` | lag-proxy 请求超时（秒） | `30.0` |
     | `OAUTH2_INTROSPECT_URL` | 自研认证中心 introspection 端点 | `https://auth.example.com/oauth/introspect` |
     | `OAUTH2_INTROSPECT_TIMEOUT` | introspection 超时（秒） | `5.0` |
     | `OAUTH2_TOKEN_CACHE_MAX` | token 缓存上限 | `1000` |
     | `OAUTH2_TOKEN_CACHE_DEFAULT_TTL` | token 缓存默认 TTL（秒） | `300` |
     | `DEFAULT_CLIENT_ID` | 默认 OAuth2 client_id | `maas2ss` |
     | `ENABLE_DOCS` | 是否开启 Swagger/ReDoc 文档（`true`/`false`） | `true` |
     | `INTERNAL_API_KEY` | 内部接口 API Key（供 CustomLogger 调用） | `xxx` |
     | `COST_CACHE_MANAGED_TTL` | managed 状态缓存 TTL（秒） | `300` |
     | `COST_CACHE_RATE_TTL` | 模型费率缓存 TTL（秒），与账单10分钟周期对齐 | `600` |
     | `BILLING_SERVICE_URL` | 外部计费服务 API 地址 | `http://billing-service:8080` |

2. **搭建 FastAPI 应用框架**
   - `app/main.py`：创建 FastAPI 实例，注册路由、中间件
   - `app/config.py`：基于 pydantic-settings 的配置类（含 LiteLLM 网关地址、admin key 等配置）
   - `app/database.py`：MySQL async engine + session
   - `app/clickhouse.py`：ClickHouse 连接客户端

3. **健康检查端点**
   - `GET /health`：返回 MySQL + CH 连接状态

4. **Swagger API 文档配置**
   - FastAPI 实例配置 Swagger UI + ReDoc：
     ```python
     app = FastAPI(
         title="MaaS API",
         version="1.0.0",
         description="面向大客户的 MaaS 网关 Key 管理 API\n\n"
                     "所有 `/api/v1/*` 接口需通过 OAuth2 Bearer token 认证，\n"
                     "并在请求 header 中携带 `x-user-id`。",
         docs_url="/docs" if enable_docs else None,
         redoc_url="/redoc" if enable_docs else None,
         openapi_url="/openapi.json" if enable_docs else None,
         swagger_ui_parameters={"persistAuthorization": True},
     )
     ```
   - 集成 Bearer token 安全方案，Swagger UI 内置 Authorization 输入框：
     ```python
     from fastapi.security import HTTPBearer
     app.swagger_security = [HTTPBearer()]
     ```
   - `x-user-id` 作为自定义 header 在接口文档中标注为必填
   - `ENABLE_DOCS` 环境变量控制文档开关（生产环境建议关闭）

### Phase 2: 认证模块 (Day 2)
4. **OAuth2 认证中间件**
   - `app/middleware/auth.py`：从 Authorization header 取 token
   - `app/services/auth_service.py`：调用自研认证中心 introspection 端点
     - **参考实现**：`lag-proxy` 的 `app/services/auth.py`（introspection + TTL 缓存）
     - client_id = `maas2ss`
   - 从 introspection 响应中提取 client_id
   - **双层校验**：
     1. 查询 `client_user_mapping` 表：`client_id → user_id`
     2. 比对 `request.headers["x-user-id"] == mapped_user_id`，不匹配返回 403
   - **team_id 自动生成**：认证通过后，服务端根据 `user_id` + 环境配置自动拼接
     - 生产：`f"AI_PRD_{user_id}"`
     - 测试：`f"AI_TEST_{user_id}"`
     - 环境前缀通过配置项 `ENV_MODE` 控制
   - 挂载为 FastAPI 依赖，保护所有 `/api/v1/*` 路由

5. **请求日志中间件**
   - `app/middleware/logging.py`：trace_id、请求耗时、状态码

### Phase 3: Key 管理 (Day 3-4)
6. **数据模型 + 迁移**
   - `app/models/managed_key.py`：SQLAlchemy 模型
   - Alembic 初始化 + 001_initial migration
   - `app/models/spending_limit.py`

7. **Key CRUD 接口**
   - `POST /api/v1/keys`：创建 key → 调用 LiteLLM `/key/generate` 生成 key + 写入 managed_keys 表

     **⚠️ Key 原值安全处理（关键约束）**：
     - key 原值（如 `sk-xxxx...`）**仅**在创建响应中原样返回给用户，**不可在本服务中持久化存储**
     - 本服务只存储 `key_hash_id`（SHA-256 哈希）和 `key_alias`（脱敏别名，如 LiteLLM 返回的 `sk...xxxx`）
     - key 原值**不可写入日志**（structlog 需过滤敏感字段）
     - key 原值**不可写入数据库**（managed_keys 表无明文字段）
     - 流程：LiteLLM `/key/generate` 返回 key 原值 → 本服务从响应中提取 `key_hash_id`（哈希）和 `key_alias`（脱敏）存库 → 将 key 原值透传给用户响应 → 丢弃，不落任何持久化存储

     ```
     LiteLLM /key/generate 响应
       │
       ├─ key 原值: "sk-abc123..."     ──▶ 透传给用户响应（仅此一次）
       ├─ key_hash_id: SHA256(key)     ──▶ 存入 managed_keys 表
       └─ key_alias: "sk...c123"       ──▶ 存入 managed_keys 表

     ⛔ 禁止：key 原值写入 DB / 日志 / 缓存 / 任何持久化存储
     ```

   - `GET /api/v1/keys`：分页列表，支持 team_id 过滤
   - `GET /api/v1/keys/{key_id}`：详情
   - `PATCH /api/v1/keys/{key_id}/revoke`：吊销 key → 调用 LiteLLM `/key/update` 设 blocked + 更新 managed_keys 状态
   - 权限校验：只能操作 token 所属 team 的 key

8. **LiteLLM 管理客户端**（通过 lag-proxy 调用）
   - `app/litellm_integration/client.py`：封装 lag-proxy 的 key/team 管理 API
     - `generate_key(team_id, max_budget, budget_duration, ...)` → POST lag-proxy/key/generate
     - `update_key(key, max_budget, ...)` → POST lag-proxy/key/update
     - `block_key(key)` → POST lag-proxy/key/block
     - `unblock_key(key)` → POST lag-proxy/key/unblock
     - `get_key_info(key)` → GET lag-proxy/key/info
   - ⚠️ 调用 lag-proxy 时需携带 `x-user-id` header（参考 `lag-proxy` 的 `app/dependencies.py`）

### Phase 4: 账单查询 (Day 5)
9. **账单查询服务**
   - `app/services/billing_service.py`：查询 ClickHouse
   - `GET /api/v1/keys/{key_id}/billing`：单 key 账单
   - `GET /api/v1/billing/summary`：汇总账单
   - 限制查询范围为最近7天
   - 查询账单时同步检查消费阈值（被动兜底）

### Phase 5: 消费阈值 + LiteLLM Budget 集成 (Day 6-7)
10. **消费阈值管理**
    - `POST /api/v1/keys/{key_id}/limits`：设置阈值 → 写入 spending_limits 表 + 同步 LiteLLM key 的 max_budget/budget_duration
    - `GET /api/v1/keys/{key_id}/limits`：查看阈值
    - `PATCH /api/v1/keys/{key_id}/limits/{limit_id}`：修改 → 同步更新 LiteLLM budget
    - `DELETE /api/v1/keys/{key_id}/limits/{limit_id}`：删除 → 清除 LiteLLM 对应 budget

11. **阈值→Budget 同步逻辑**
    - `app/litellm_integration/budget_sync.py`：
      - `sync_limit_to_budget(key_hash_id, limits)`：将 spending_limits 转换为 LiteLLM budget 参数并同步
      - `daily limit` → `max_budget=amount, budget_duration='1d'`
      - `total limit` → `max_budget=amount`（无 budget_duration）
      - `daily + total 同时存在` → 使用 `budget_limits` 多窗口：`[{"budget_duration":"1d","max_budget":daily_amount}, {"budget_duration":"30d","max_budget":total_amount}]`
      - `enabled=FALSE` → `max_budget=null`

12. **超限 Block/Unblock 逻辑**
    - 被动检查：查询账单时触发阈值检查，超限 → 更新 managed_keys.status = blocked
    - TODO: block 后 webhook/通知（一期不做，预留 `_notify_key_blocked(key_id, reason)` 埋点）
    - 实时拦截：LiteLLM budget 检查已在前置拦截（spend >= max_budget → 429）
    - `PATCH /api/v1/keys/{key_id}/unblock`：手动解除 → 调用 LiteLLM `/key/{key}/reset_spend` 重置 spend + 更新 managed_keys 状态

### Phase 6: CustomLogger — 替换默认计价 (Day 7-8) ★

> **⚠️ 架构关键点**：CustomLogger 代码运行在 LiteLLM Gateway（ds-api-gw）进程内，不在本服务（maas-v2-client-api）进程中。
> CustomLogger 通过 HTTP 调用本服务的 RESTful 接口获取 managed_key 的消费金额，替换 LiteLLM 默认计价。
> **非 managed_key 的 key 不受影响**，继续走 LiteLLM 原有的 budget 策略。
> 部署方式：CustomLogger 作为一个 Python 文件放入 ds-api-gateway，环境变量配置本服务地址即可，无需 pip 安装。

13. **CustomLogger 实现**
    - 代码位置：`app/litellm_integration/custom_logger.py`（在本服务仓库中开发维护，部署时复制到 ds-api-gateway）
    - 继承 `litellm.CustomLogger`
    - 实现 `async_log_success_event()`：
      1. 从 kwargs 提取 key (token)、model、prompt_tokens、completion_tokens
      2. 调用本服务 API：`GET /api/v1/internal/keys/{key_hash_id}/cost` 查询该 key 是否为 managed_key
         - **是 managed_key**：用本服务返回的消费金额替换 LiteLLM 默认计价
         - **非 managed_key**：跳过，走 LiteLLM 默认 budget 策略
      3. 调用 LiteLLM 内部 API 更新 spend：`increment_spend_counters()` + `DBSpendUpdateWriter`
      4. 确保 Redis 计数器和 DB 的 spend 都使用本服务返回的计费金额
    - 实现 `async_log_failure_event()`：释放预算预留

14. **CustomLogger 部署方式**

    ```yaml
    # ds-api-gateway 环境变量
    MAAS_V2_API_URL: "http://maas-v2-client-api:8000"  # 本服务地址

    # ds-api-gateway 的 proxy_server_config.yaml
    litellm_settings:
      success_callback: ["maas_custom_logger"]
      failure_callback: ["maas_custom_logger"]
    ```

    **部署流程**：
    ```
    maas-v2-client-api 仓库（开发维护）          ds-api-gateway（运行时）
    ┌──────────────────────────────┐           ┌─────────────────────────────┐
    │ app/litellm_integration/     │  ──CI──▶  │ custom_callbacks/           │
    │   custom_logger.py           │  复制到    │   maas_custom_logger.py     │
    └──────────────────────────────┘           └─────────────────────────────┘
                                                │
                                                │ env: MAAS_V2_API_URL
                                                │ config.yaml 注册
                                                ▼
                                              LiteLLM Gateway 进程
                                              运行时加载 CustomLogger
    ```

    - CustomLogger 通过环境变量 `MAAS_V2_API_URL` 获取本服务地址
    - 仅需一个 Python 文件，放入 ds-api-gateway 的 callbacks 目录，PYTHONPATH 可达即可
    - **无需 pip 安装**，无需打包

15. **本服务新增内部接口**（供 CustomLogger 调用）

    > 这些接口不对外暴露，仅供 LiteLLM Gateway 的 CustomLogger 内部调用，可走 K8s 内部网络。

    ```
    GET /api/v1/internal/keys/{key_hash_id}/cost?model=xxx&input_tokens=xxx&output_tokens=xxx&cache_tokens=xxx
    ```

    - 判断 key_hash_id 是否在 managed_keys 表中
    - 若是：调用外部计费服务 API 计算消费金额，返回 CNY
    - 若否：返回 `{"managed": false}`，CustomLogger 据此走默认逻辑
    - 该接口不走 OAuth2 认证，走 K8s 内部网络或 API Key 认证

    **缓存策略**（两层缓存，避免每次请求都查表或调外部接口）：

    | 缓存层 | Key | Value | TTL | 说明 |
    |--------|-----|-------|-----|------|
    | **L1: 内存缓存** | `managed:{key_hash_id}` | `true` / `false` | 5 min | 判断 key 是否 managed，避免每次查 managed_keys 表 |
    | **L2: 费率缓存** | `rate:{model}` | `{input_rate, output_rate, cache_rate}` | 10 min | 模型单价缓存，与账单产出周期对齐 |

    缓存命中时的流程：
    ```
    请求 → L1 缓存查 managed?
      ├─ 未命中 → 查 managed_keys 表 → 写入 L1 缓存
      └─ 命中 →
           ├─ managed=false → 返回 {"managed": false}
           └─ managed=true → 计算 cost
                ├─ L2 缓存查 model 费率
                │   ├─ 未命中 → 调外部计费 API → 写入 L2 缓存
                │   └─ 命中 → 直接用缓存的费率
                └─ cost = input_rate × input_tokens + output_rate × output_tokens + cache_rate × cache_tokens
                    → 返回 {"managed": true, "cost": ..., ...}
    ```

    缓存失效：
    - key 状态变更（吊销/block/unblock）时主动清除当前实例 L1 缓存
    - 阈值变更时无需清除（只影响 max_budget，不影响计费）
    - 外部计费服务费率变更时，等 L2 自然过期（10min，与账单产出周期对齐）或手动清除

    **多实例部署说明**：
    - 采用内存缓存（`cachetools.TTLCache`），不引入 Redis
    - L1（managed 状态）多实例间最多 5 分钟不一致，可接受：key 的吊销/block 由 LiteLLM Gateway 侧执行，本服务只改表状态，L1 仅决定计费逻辑分支
    - L2（模型费率）所有实例从同一外部计费 API 取值，结果一致，独立缓存无问题

    **响应**：
    ```json
    // managed key
    {
      "managed": true,
      "cost": 0.052,           // CNY
      "currency": "CNY",
      "charge_detail": {
        "input_cost": 0.040,
        "output_cost": 0.010,
        "cache_cost": 0.002
      }
    }

    // non-managed key
    {
      "managed": false
    }
    ```

16. **外部计费逻辑**
    - `app/litellm_integration/cost_calculator.py`：
      - 调用外部计费服务 API 获取实际消费金额（方案 C）
      - 传入：模型、token 数量、请求类型等参数
      - 返回 CNY 金额，budget 金额统一存 CNY，LiteLLM 仅做数值比较不关心币种

    **整体交互时序**：
    ```
    Client 请求 ──▶ LiteLLM Gateway
                      │
                      ├─ 1. key 验证 + budget 检查（spend >= max_budget → 429）
                      ├─ 2. 转发请求到 LLM Provider
                      ├─ 3. 响应返回
                      └─ 4. CustomLogger.async_log_success_event()
                            │
                            ├─ 4a. GET maas-v2-api/internal/keys/{hash}/cost
                            │       ├─ managed_key → 返回外部计费金额 (CNY)
                            │       └─ non-managed → 返回 {"managed": false}
                            │
                            ├─ 4b. if managed: 用返回金额替换默认计价
                            │   if not managed: 走 LiteLLM 默认 budget 策略
                            │
                            ├─ 4c. increment_spend_counters() → 更新 Redis
                            └─ 4d. DBSpendUpdateWriter → 更新 PostgreSQL

    ══════════════════════════════════════════

    maas-v2-client-api（本服务，独立部署）
      │
      ├─ 对外：管理 key 生命周期 → 通过 lag-proxy 调用 LiteLLM API
      ├─ 对外：管理 spending_limits → 同步 max_budget 到 LiteLLM key
      ├─ 对外：查询账单 → ClickHouse dbt
      └─ 对内：提供 /internal/keys/{hash}/cost 接口 → 供 CustomLogger 调用
    ```

### Phase 7: 测试 + 容器化 (Day 9-10)
15. **单元测试 + 集成测试**
    - conftest.py：测试数据库
    - Key CRUD 测试（含 LiteLLM API mock）
    - 账单查询测试（mock ClickHouse）
    - 阈值 + budget 同步测试
    - CustomLogger 单元测试
    - 认证中间件测试

16. **Docker + K8s**
    - Dockerfile：多阶段构建
    - k8s/deployment.yaml
    - k8s/service.yaml
    - k8s/configmap.yaml
    - CustomLogger 部署配置（一个 .py 文件复制到 ds-api-gateway callbacks 目录，环境变量配本服务地址，config.yaml 注册）

17. **文档收尾**
    - README.md：项目说明、本地启动、环境变量
    - Swagger API 文档完善：
      - 确保所有接口的 `summary`、`description`、`response_model` 完整
      - 每个 Pydantic schema 添加 `json_schema_extra` 示例（Example），方便用户在 Swagger UI 中看到请求/响应样例
      - 自定义 header `x-user-id` 在文档中标注说明
      - 错误响应示例（在各接口的 `responses` 参数中声明 4xx/5xx 的 schema）
      - 验证 Swagger UI（`/docs`）和 ReDoc（`/redoc`）可正常访问和交互
      - 验证 Bearer token 掓取后，Swagger UI 的 "Try it out" 可正常调试
    - LiteLLM 集成说明：CustomLogger 部署、配置、调试

---

## 六、工时评估

| 阶段 | 任务 | 预估工时 | 备注 |
|------|------|---------|------|
| **Phase 1** | 项目骨架搭建 | **1 天** | 依赖配置、框架搭建、健康检查 |
| **Phase 2** | OAuth2 认证模块 | **1 天** | 需确认自研认证中心的 introspection 接口文档 |
| **Phase 3** | Key 管理 CRUD + LiteLLM 客户端 | **2 天** | 含数据模型、迁移、接口、权限校验、LiteLLM API 集成 |
| **Phase 4** | 账单查询 | **1 天** | ClickHouse 查询、7天限制、mock 数据 |
| **Phase 5** | 消费阈值 + Budget 同步 | **2 天** | 阈值 CRUD、LiteLLM budget 双向同步、block/unblock |
| **Phase 6** | CustomLogger 替换计价 ★ | **2 天** | CustomLogger 实现、外部计费逻辑、Redis/DB spend 更新、币种处理 |
| **Phase 7** | 测试 + 容器化 | **2 天** | 测试用例、Dockerfile、K8s YAML、CustomLogger 部署 |
| | **总计** | **11 个工作日** | |

### 风险与依赖
| 风险项 | 影响 | 缓解措施 |
|--------|------|---------|
| 自研认证中心 introspection 接口文档不明确 | 可能阻塞 Phase 2 | 先用 mock 实现，后续对接 |
| ClickHouse dbt 表结构未确认 | 影响 Phase 4 账单查询 | 先按假设结构开发，预留适配层 |
| Python 3.13 兼容性 | 极少数库可能尚未适配 | 开发初期验证所有依赖兼容性 |
| LiteLLM CustomLogger 与内部 API 耦合 | CustomLogger 依赖 LiteLLM 内部函数（increment_spend_counters 等），版本升级可能 breaking | 封装适配层，锁定 LiteLLM 版本，关注 changelog |
| 币种不一致（CNY vs USD） | LiteLLM budget 系统以 USD 计价，本服务以 CNY 计费 | budget 金额存 CNY，LiteLLM 仅做数值比较不关心币种（已确认方案 A） |
| CustomLogger 部署位置 | CustomLogger 运行在 LiteLLM Gateway 进程内，代码在本仓库维护 | 一个 Python 文件复制到 ds-api-gateway，环境变量 `MAAS_V2_API_URL` 配置本服务地址，config.yaml 注册 |
| 消费阈值检查时机 | 仅被动查询时检查有滞后 | 实时拦截由 LiteLLM budget 保证，被动检查作为兜底 |

---

## 七、关键决策

### ✅ 已确认

| # | 决策项 | 结论 |
|---|--------|------|
| 1 | ClickHouse 账单表 | 表名 `dws_para_statements`；生产库 `prod_litellm_dbt_data`，测试库 `dev_dbt_data`；金额字段 `used_value`/`real_price`；用户字段 `service_user_id` |
| 2 | OAuth2 client_id | `maas2ss` |
| 3 | 认证实现参考 | `lag-proxy` 的 `AuthService`（introspection + TTL 缓存） |
| 4 | 用户标识方式 | 请求 header 携带 `x-user-id`，与 token 中 client_id 对应的 user_id 比对 |
| 5 | team_id 规则 | 服务端根据 user_id 自动拼接：生产 `AI_PRD_{user_id}`，测试 `AI_TEST_{user_id}`；用户无需传 team_id |
| 6 | client_id ↔ user_id 映射 | 新建 `client_user_mapping` 表存储 |
| 7 | LiteLLM 网关调用方式 | 通过 `lag-proxy` 代理调用，调用时携带 `x-user-id` header |
| 8 | introspection 接口规范 | 参考 `lag-proxy` 的 `AuthService` 实现；URL 由 `OAUTH2_INTROSPECT_URL` 环境变量配置；请求方式 POST `data={"token": token}`；响应中按 OAuth2 标准取 `client_id` 字段 |
| 9 | 消费阈值粒度 | 不支持按模型分别设限，阈值以 key 为粒度（daily / total） |
| 10 | block 后 webhook/通知 | 一期不做，预留 TODO 埋点，后续迭代加 |
| 11 | 币种策略 | 方案 A：budget 金额存 CNY，LiteLLM 仅做数值比较（`spend >= max_budget`），不关心币种 |
| 12 | 外部计费逻辑数据源 | 方案 C：调用外部计费服务的 API（实时但增加延迟），CustomLogger 不内置定价规则 |
| 13 | CustomLogger 部署方式 | 一个 Python 文件放入 ds-api-gateway，环境变量 `MAAS_V2_API_URL` 配置本服务地址，无需 pip 安装 |
| 14 | CustomLogger 与本服务交互 | CustomLogger 调用本服务 `/api/v1/internal/keys/{hash}/cost` 接口获取消费金额；非 managed_key 走 LiteLLM 默认策略 |

### ❓ 待确认

---

## 八、LiteLLM Budget 机制参考

> 以下是对 LiteLLM 网关 budget 机制的源码分析总结，供实施参考。

### 8.1 Budget 配置层级

LiteLLM 支持多层级 budget 配置：

| 层级 | 字段 | 说明 |
|------|------|------|
| Key | `max_budget`, `budget_duration`, `budget_reset_at` | 单个 API Key 的额度 |
| Team | `max_budget`, `budget_duration` | 团队额度 |
| Team Member | `team_member_budget` | 团队内成员额度 |
| User | `max_budget`, `budget_duration` | 用户额度 |
| Organization | `organization_max_budget` | 组织额度 |
| BudgetTable | 可复用的 budget 模板 | 多 key/team 共享 |
| BudgetLimits | `budget_limits` 多窗口 | 同时设日限额+月限额 |

### 8.2 请求生命周期中的 Budget 检查

```
请求 → user_api_key_auth() → common_checks()
  ├─ Team max budget check (Redis: spend:team:{team_id})
  ├─ Team multi-window budgets (Redis: spend:team:{team_id}:window:{duration})
  ├─ Key multi-window budgets (Redis: spend:key:{token}:window:{duration})
  ├─ Organization budget (Redis: spend:org:{org_id})
  ├─ Tag budget (Redis: spend:tag:{tag_name})
  ├─ User budget (Redis: spend:user:{user_id})
  ├─ Team member budget (Redis: spend:team_member:{user_id}:{team_id})
  └─ End user budget
  ↓
_reserve_budget_after_common_checks() → 预留估算费用
  ↓
请求转发 → 响应 → _PROXY_track_cost_callback()
  ├─ increment_spend_counters() → 更新 Redis 计数器
  ├─ reconcile_budget_reservation() → 调整预留到实际
  └─ DBSpendUpdateWriter → 更新 DB
```

### 8.3 Spend 存储双层架构

| 存储层 | Key 格式 | 用途 | 更新方式 |
|--------|---------|------|---------|
| **Redis** | `spend:key:{hashed_token}` | 实时预算检查 | `increment_spend_counters()` 递增 |
| **PostgreSQL** | `LiteLLM_VerificationToken.spend` | 持久化展示 | `DBSpendUpdateWriter` 更新 |

Fallback 链：`Redis → 内存 → DB reseed → fallback`

### 8.4 Budget 重置机制

`ResetBudgetJob` 后台定时任务：
1. 查找 `budget_reset_at <= now` 的 key/team/user
2. 设置 `spend = 0`，计算新 `budget_reset_at = now + budget_duration`
3. 清除 Redis 计数器 + 使缓存失效

`budget_duration` 格式：`Ns`(秒), `Nm`(分), `Nh`(时), `Nd`(天), `Nw`(周), `Nmo`(月)

### 8.5 可用的 LiteLLM 管理 API

| API | 用途 | 关键参数 |
|-----|------|---------|
| `POST /key/generate` | 创建 key | `team_id`, `max_budget`, `budget_duration`, `key_alias` |
| `POST /key/update` | 更新 key | `key`, `max_budget`, `spend`, `budget_duration` |
| `POST /key/{key}/reset_spend` | 重置 spend | `reset_to`（必须 ≤ 当前 spend） |
| `GET /key/info` | 查看 key 详情 | `key` |
| `POST /global/spend/reset` | 全局重置 | —（重置所有 key/team spend 为 0） |

### 8.6 CustomLogger 接口

```python
class CustomLogger:
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        """请求成功后回调 — 替换默认计价的关键拦截点"""
        pass

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        """请求失败后回调 — 释放预算预留"""
        pass
```

kwargs 中可获取：`model`, `messages`, `stream`, `api_key`, `user_api_key_dict`, `start_time`, `end_time`, `response_cost` 等。

在 `config.yaml` 中注册：
```yaml
litellm_settings:
  success_callback: ["maas_custom_logger"]
  failure_callback: ["maas_custom_logger"]
```
