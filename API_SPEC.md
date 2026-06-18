# MaaS API 接口说明文档

> **版本**：v1
> **Base URL**：`https://{host}/api/v1`
> **认证方式**：OAuth2 client_credentials

---

## 目录

1. [概述](#1-概述)
2. [认证说明](#2-认证说明)
3. [通用约定](#3-通用约定)
4. [接口一览](#4-接口一览)
5. [网关 Key 管理](#5-网关-key-管理)
6. [消费阈值管理](#6-消费阈值管理)
7. [账单查询](#7-账单查询)
8. [系统接口](#8-系统接口)
9. [错误码一览](#9-错误码一览)
10. [常见问题](#10-常见问题)

---

## 1. 概述

本 API 为大客户提供 MaaS（Model as a Service）网关 Key 的管理能力，核心功能包括：

- **网关 Key 生命周期管理**：创建、查看、吊销 Key
- **消费控制**：为 Key 设置消费阈值，超限自动阻断
- **账单查询**：查看每个 Key 的消费明细，支持最近 7 天

### 关键约束

| 项目 | 说明 |
|------|------|
| Key 不可删除 | Key 一旦创建只能吊销（revoke），不可删除，保留完整审计记录 |
| 账单查询范围 | 仅支持查询最近 7 天的消费数据 |
| 账单更新频率 | 每 10 分钟生成一次账单（由外部系统产出） |
| 阈值检查时机 | 查询账单时同步检查消费是否超限 |
| 权限隔离 | 每个 Team 只能操作属于自己的 Key 和数据 |

---

## 2. 认证说明

### 2.1 OAuth2 client_credentials 模式

所有 `/api/v1/*` 接口均需认证，使用 OAuth2 client_credentials 模式获取 access_token。

#### 获取 Token

```
POST https://{auth-center-host}/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id={your_client_id}&client_secret={your_client_secret}
```

#### 响应

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

#### 使用 Token

在所有 API 请求的 Header 中携带：

```
Authorization: Bearer {access_token}
```

### 2.2 权限说明

- Token 中绑定 `team_id`，所有操作仅限该 Team 下的资源
- 试图操作其他 Team 的资源将返回 `403 Forbidden`

---

## 3. 通用约定

### 3.1 请求头

| Header | 必填 | 说明 |
|--------|------|------|
| `Authorization` | 是 | `Bearer {access_token}` |
| `Content-Type` | 是（写操作） | `application/json` |

### 3.2 统一响应格式

**成功响应**

```json
{
  "code": 0,
  "data": { ... },
  "message": "success"
}
```

**列表响应（分页）**

```json
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
```

**错误响应**

```json
{
  "code": 40001,
  "data": null,
  "message": "Key not found"
}
```

### 3.3 分页参数

所有列表接口支持以下查询参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码，从 1 开始 |
| `page_size` | int | 20 | 每页条数，最大 100 |

### 3.4 时间格式

所有时间字段使用 ISO 8601 格式：`2025-06-17T10:30:00Z`

---

## 4. 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/keys` | 创建网关 Key |
| GET | `/api/v1/keys` | 列出 Key（分页） |
| GET | `/api/v1/keys/{key_id}` | 查看 Key 详情 |
| PATCH | `/api/v1/keys/{key_id}/revoke` | 吊销 Key |
| PATCH | `/api/v1/keys/{key_id}/unblock` | 解除 Key 阻断 |
| POST | `/api/v1/keys/{key_id}/limits` | 设置消费阈值 |
| GET | `/api/v1/keys/{key_id}/limits` | 查看消费阈值 |
| PATCH | `/api/v1/keys/{key_id}/limits/{limit_id}` | 修改消费阈值 |
| DELETE | `/api/v1/keys/{key_id}/limits/{limit_id}` | 删除消费阈值 |
| GET | `/api/v1/keys/{key_id}/billing` | 查询 Key 账单 |
| GET | `/api/v1/billing/summary` | 汇总账单查询 |
| GET | `/health` | 健康检查 |

---

## 5. 网关 Key 管理

### 5.1 创建 Key

创建一个新的网关 Key。Key 值**仅在创建时返回一次**，后续无法再次查看，请妥善保存。

```
POST /api/v1/keys
```

**请求体**

```json
{
  "name": "production-api-key",
  "team_id": "team-abc123"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 否 | Key 名称/备注，最长 128 字符 |
| `team_id` | string | 是 | 所属 Team ID |

**响应** `201 Created`

```json
{
  "code": 0,
  "data": {
    "id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
    "name": "production-api-key",
    "team_id": "team-abc123",
    "key": "sk-maas-000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9g7h8i9j0k1l2m3n4o5p6",
    "key_alias": "sk...o5p6",
    "status": "active",
    "created_at": "2025-06-17T10:00:00Z"
  },
  "message": "success"
}
```

> ⚠️ **重要**：`key` 字段仅在本次响应中出现，后续查询不会再返回完整 Key 值，仅返回 `key_alias`（格式 `sk...xxxx`）用于识别。

---

### 5.2 列出 Key

分页列出当前 Team 下的所有 Key。

```
GET /api/v1/keys?page=1&page_size=20&status=active
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 100 |
| `status` | string | 否 | 按状态过滤：`active` / `blocked` / `revoked` |
| `name` | string | 否 | 按名称模糊搜索 |

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
        "name": "production-api-key",
        "team_id": "team-abc123",
        "key_alias": "sk...a1b2",
        "status": "active",
        "created_at": "2025-06-17T10:00:00Z",
        "blocked_reason": null,
        "blocked_at": null,
        "revoked_at": null
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "message": "success"
}
```

---

### 5.3 查看 Key 详情

查看指定 Key 的详细信息和当前消费状态。

```
GET /api/v1/keys/{key_id}
```

**路径参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `key_id` | string | Key 的 key_hash_id |

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
    "name": "production-api-key",
    "team_id": "team-abc123",
    "key_alias": "sk...a1b2",
    "status": "active",
    "created_at": "2025-06-17T10:00:00Z",
    "blocked_reason": null,
    "blocked_at": null,
    "revoked_at": null,
    "spending_limits": [
      {
        "id": 101,
        "limit_type": "daily",
        "amount": 100.00,
        "currency": "CNY",
        "enabled": true
      }
    ],
    "usage_summary": {
      "today_cost": 23.45,
      "total_cost_7d": 156.78
    }
  },
  "message": "success"
}
```

---

### 5.4 吊销 Key

将 Key 状态设为 `revoked`，吊销后该 Key 将立即失效，不可恢复。

> ⚠️ Key 一旦吊销**不可恢复**，不可删除。如需继续使用，请新建 Key。

```
PATCH /api/v1/keys/{key_id}/revoke
```

**请求体**

```json
{
  "reason": "Key compromised, rotating to new key"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reason` | string | 否 | 吊销原因，最长 256 字符 |

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
    "status": "revoked",
    "revoked_at": "2025-06-17T15:30:00Z"
  },
  "message": "success"
}
```

**错误场景**

| 错误码 | 说明 |
|--------|------|
| 40401 | Key 不存在 |
| 40901 | Key 已处于 revoked 状态，无法重复吊销 |

---

### 5.5 解除 Key 阻断

当 Key 因消费超限被自动 block 后，可手动解除阻断使其恢复使用。

```
PATCH /api/v1/keys/{key_id}/unblock
```

**请求体**

```json
{
  "reason": "Approved by admin after review"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reason` | string | 否 | 解除阻断原因 |

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
    "status": "active",
    "blocked_reason": null,
    "blocked_at": null
  },
  "message": "success"
}
```

**错误场景**

| 错误码 | 说明 |
|--------|------|
| 40401 | Key 不存在 |
| 40902 | Key 状态非 blocked，无法解除阻断 |
| 40903 | Key 已 revoked，无法解除阻断 |

---

### 5.6 Key 状态流转

```
                    ┌──────────────┐
         创建 ────▶ │    active    │ ◀──── 手动解除阻断
                    └──────┬───────┘
                           │
                    消费超限（自动）
                           │
                           ▼
                    ┌──────────────┐
                    │   blocked    │
                    └──────┬───────┘
                           │
                    手动吊销 / 不可恢复
                           │
                           ▼
                    ┌──────────────┐
                    │   revoked    │  ← 也可从 active 直接吊销
                    └──────────────┘    （终态，不可恢复）
```

| 状态 | 说明 | 可转换到 |
|------|------|---------|
| `active` | 正常可用 | `blocked` / `revoked` |
| `blocked` | 因消费超限被阻断，不可调用 | `active`（手动解除）/ `revoked` |
| `revoked` | 已吊销，永久失效 | 无（终态） |

---

## 6. 消费阈值管理

为指定 Key 设置消费阈值，当消费达到阈值时 Key 将被自动阻断。

### 6.1 设置消费阈值

```
POST /api/v1/keys/{key_id}/limits
```

**请求体**

```json
{
  "limit_type": "daily",
  "amount": 100.00,
  "currency": "CNY",
  "enabled": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `limit_type` | string | 是 | 阈值类型：`daily`（单日限额）/ `total`（累计总额限额） |
| `amount` | number | 是 | 阈值金额，必须大于 0，最多 2 位小数 |
| `currency` | string | 否 | 币种，默认 `USD` |
| `enabled` | boolean | 否 | 是否启用，默认 `true` |

**响应** `201 Created`

```json
{
  "code": 0,
  "data": {
    "id": 101,
    "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
    "limit_type": "daily",
    "amount": 100.00,
    "currency": "CNY",
    "enabled": true,
    "created_at": "2025-06-17T10:00:00Z"
  },
  "message": "success"
}
```

> 💡 同一 Key 可以同时设置 `daily` 和 `total` 两种阈值，任一超限都会触发阻断。

**错误场景**

| 错误码 | 说明 |
|--------|------|
| 40401 | Key 不存在 |
| 40904 | 该 limit_type 的阈值已存在，请用 PATCH 修改 |

---

### 6.2 查看消费阈值

查看指定 Key 的所有消费阈值配置。

```
GET /api/v1/keys/{key_id}/limits
```

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": 101,
        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
        "limit_type": "daily",
        "amount": 100.00,
        "currency": "CNY",
        "enabled": true,
        "created_at": "2025-06-17T10:00:00Z",
        "updated_at": "2025-06-17T10:00:00Z"
      },
      {
        "id": 102,
        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
        "limit_type": "total",
        "amount": 1000.00,
        "currency": "CNY",
        "enabled": true,
        "created_at": "2025-06-17T10:05:00Z",
        "updated_at": "2025-06-17T10:05:00Z"
      }
    ]
  },
  "message": "success"
}
```

---

### 6.3 修改消费阈值

```
PATCH /api/v1/keys/{key_id}/limits/{limit_id}
```

**请求体**

```json
{
  "amount": 200.00,
  "enabled": true
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `amount` | number | 否 | 新的阈值金额 |
| `enabled` | boolean | 否 | 是否启用 |

> 至少需要提供一个字段。

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "id": 101,
    "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
    "limit_type": "daily",
    "amount": 200.00,
    "currency": "CNY",
    "enabled": true,
    "created_at": "2025-06-17T10:00:00Z",
    "updated_at": "2025-06-17T12:00:00Z"
  },
  "message": "success"
}
```

---

### 6.4 删除消费阈值

删除指定的消费阈值配置。

```
DELETE /api/v1/keys/{key_id}/limits/{limit_id}
```

**响应** `200 OK`

```json
{
  "code": 0,
  "data": null,
  "message": "success"
}
```

---

## 7. 账单查询

### 7.1 查询 Key 账单

查询指定 Key 的消费明细，支持最近 7 天的数据。

> 💡 查询账单时，系统会同步检查消费阈值，如超限将自动阻断 Key。

```
GET /api/v1/keys/{key_id}/billing?start_date=2025-06-10&end_date=2025-06-17&group_by=model&page=1&page_size=20
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` | string (date) | 否 | 起始日期，格式 `YYYY-MM-DD`，默认 7 天前 |
| `end_date` | string (date) | 否 | 截止日期，格式 `YYYY-MM-DD`，默认今天 |
| `group_by` | string | 否 | 聚合维度：`date`（按日）/ `model`（按模型）/ `date_model`（按日+模型），默认 `date` |
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 100 |

> ⚠️ 查询范围最大 7 天，超出范围将返回错误。

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
        "date": "2025-06-17",
        "model": "deepseek-v3",
        "request_count": 1250,
        "input_tokens": 1000000,
        "cache_tokens": 600000,
        "output_tokens": 250000,
        "input_cost": 10.00,
        "cache_cost": 0.60,
        "output_cost": 1.90,
        "cost": 12.50
      },
      {
        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
        "date": "2025-06-17",
        "model": "deepseek-r1",
        "request_count": 300,
        "input_tokens": 150000,
        "cache_tokens": 0,
        "output_tokens": 100000,
        "input_cost": 6.00,
        "cache_cost": 0,
        "output_cost": 2.75,
        "cost": 8.75
      }
    ],
    "total": 2,
    "page": 1,
    "page_size": 20,
    "summary": {
      "total_request_count": 1550,
      "total_input_tokens": 1150000,
      "total_cache_tokens": 600000,
      "total_output_tokens": 350000,
      "total_input_cost": 16.00,
      "total_cache_cost": 0.60,
      "total_output_cost": 4.65,
      "total_cost": 21.25
    }
  },
  "message": "success"
}
```

> 💡 **字段说明**：`input_tokens` / `cache_tokens` / `output_tokens` 为 token 数量（来自 `resource_used_count`），`input_cost` / `cache_cost` / `output_cost` 为对应金额（来自 `used_value`，CNY），`cost` 为实收总额（来自 `real_price`）。

---

### 7.2 汇总账单查询

查询当前 Team 下所有 Key 的消费汇总，支持按 Key、日期、模型等维度聚合。

```
GET /api/v1/billing/summary?start_date=2025-06-10&end_date=2025-06-17&group_by=key&page=1&page_size=20
```

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `start_date` | string (date) | 否 | 起始日期，默认 7 天前 |
| `end_date` | string (date) | 否 | 截止日期，默认今天 |
| `group_by` | string | 否 | 聚合维度：`key`（按Key）/ `key_date`（按Key+日期）/ `key_model`（按Key+模型），默认 `key` |
| `key_id` | string | 否 | 指定 Key 的 key_hash_id 过滤 |
| `page` | int | 否 | 页码，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 100 |

**响应** `200 OK`

```json
{
  "code": 0,
  "data": {
    "items": [
      {
        "key_id": "000129d9bfb397ab07534c35efd6a617cba8e00910e67bb63c2d49a68bff87f9",
        "key_name": "production-api-key",
        "key_alias": "sk...a1b2",
        "total_request_count": 15000,
        "total_input_tokens": 5000000,
        "total_cache_tokens": 1200000,
        "total_output_tokens": 2500000,
        "total_input_cost": 125.00,
        "total_cache_cost": 1.20,
        "total_output_cost": 30.58,
        "total_cost": 156.78
      },
      {
        "key_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2",
        "key_name": "staging-key",
        "key_alias": "sk...x9y8",
        "total_request_count": 2300,
        "total_input_tokens": 800000,
        "total_cache_tokens": 0,
        "total_output_tokens": 400000,
        "total_input_cost": 24.00,
        "total_cache_cost": 0,
        "total_output_cost": 8.15,
        "total_cost": 32.15
      }
    ],
    "total": 2,
    "page": 1,
    "page_size": 20,
    "summary": {
      "total_request_count": 17300,
      "total_input_tokens": 5800000,
      "total_cache_tokens": 1200000,
      "total_output_tokens": 2900000,
      "total_input_cost": 149.00,
      "total_cache_cost": 1.20,
      "total_output_cost": 38.73,
      "total_cost": 188.93
    }
  },
  "message": "success"
}
```

---

## 8. 系统接口

### 8.1 健康检查

无需认证。

```
GET /health
```

**响应** `200 OK`

```json
{
  "status": "healthy",
  "services": {
    "mysql": "up",
    "clickhouse": "up"
  }
}
```

---

## 9. 错误码一览

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| 0 | 200 | 成功 |
| 40000 | 400 | 请求参数错误 |
| 40100 | 401 | 未认证（缺少或无效的 Token） |
| 40300 | 403 | 无权限（操作其他 Team 的资源） |

### Key 相关错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| 40401 | 404 | Key 不存在 |
| 40901 | 409 | Key 已吊销，无法重复操作 |
| 40902 | 409 | Key 状态非 blocked，无法解除阻断 |
| 40903 | 409 | Key 已吊销，无法解除阻断 |

### 阈值相关错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| 40402 | 404 | 阈值配置不存在 |
| 40904 | 409 | 该类型的阈值已存在 |
| 40001 | 400 | 阈值金额必须大于 0 |

### 账单相关错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| 40002 | 400 | 查询日期范围超过 7 天 |
| 40003 | 400 | 日期格式错误 |

### 服务端错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| 50000 | 500 | 服务内部错误 |
| 50001 | 500 | 数据库查询失败 |
| 50002 | 502 | 认证中心不可用 |
| 50003 | 502 | 账单数据源不可用 |

---

## 10. 常见问题

### Q: Key 创建后能否再次查看完整的 Key 值？

**不能。** Key 值仅在创建时返回一次，系统仅存储 Key 的哈希值用于校验。如遗失 Key，请吊销旧 Key 并创建新 Key。

### Q: 被阻断（blocked）的 Key 如何恢复？

调用 `PATCH /api/v1/keys/{key_id}/unblock` 接口手动解除阻断。解除后 Key 恢复为 `active` 状态，可继续使用。

### Q: Key 为什么不能删除？

出于审计和安全追溯的需要，Key 一旦创建将永久保留记录，只能吊销（revoke）。吊销后 Key 立即失效，等同于"删除"的效果，但记录不会丢失。

### Q: 消费阈值超限后多久会被阻断？

阈值检查在查询账单时同步触发。如果消费已超限，查询账单的响应中将包含超限提示，同时 Key 会被自动阻断。

### Q: 账单数据的延迟是多少？

账单由外部系统每 10 分钟生成一次，因此最新账单数据可能有最多 10 分钟的延迟。

### Q: 同一个 Key 可以设置多个消费阈值吗？

可以。每个 Key 最多设置两个阈值：一个 `daily`（单日限额）和一个 `total`（累计总额限额），任一超限都会触发阻断。

### Q: 解除阻断后，之前累积的消费金额会重置吗？

不会。`total` 类型的阈值基于累计消费，解除阻断不会重置。如果需要重置累计金额，建议删除旧阈值并重新创建。`daily` 类型的阈值按自然日重置。

### Q: 吊销的 Key 能否恢复？

**不能。** revoked 是终态，不可恢复。如需重新使用，请新建 Key。
