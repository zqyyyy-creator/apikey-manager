# 面向大客户的maas api接口

## 功能
- 提供网关key的创建接口，只能是在某个team下的创建
- 返回每个key的账单信息， 每10分钟会出一个账单
- 可以在key配消费阈值，如超限，则将key block住
- 账单信息从dbt库中查询，只提供查询最近7日的

## 技术要求
- 接口通过oauth2认证：client_credentials 模式
- uv管理python， python = 3.13
- fastapi restful接口
