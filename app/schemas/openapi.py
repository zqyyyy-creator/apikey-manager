COMMON_ERROR_RESPONSES = {
    400: {
        "description": "请求参数错误",
        "content": {
            "application/json": {
                "example": {
                    "code": 40000,
                    "data": {
                        "errors": [
                            {
                                "type": "missing",
                                "loc": ["header", "x-user-id"],
                                "msg": "Field required",
                            }
                        ]
                    },
                    "message": "Request parameter error",
                }
            }
        },
    },
    401: {
        "description": "未认证或 token 无效",
        "content": {
            "application/json": {
                "example": {
                    "code": 40100,
                    "data": None,
                    "message": "Missing bearer token",
                }
            }
        },
    },
    403: {
        "description": "无权限或内部 API key 无效",
        "content": {
            "application/json": {
                "example": {
                    "code": 40300,
                    "data": None,
                    "message": "Invalid internal API key",
                }
            }
        },
    },
    404: {
        "description": "资源不存在",
        "content": {
            "application/json": {
                "example": {
                    "code": 40400,
                    "data": None,
                    "message": "Key not found",
                }
            }
        },
    },
    500: {
        "description": "服务内部错误",
        "content": {
            "application/json": {
                "example": {
                    "code": 50000,
                    "data": None,
                    "message": "Internal server error",
                }
            }
        },
    },
}


CONFLICT_RESPONSE = {
    409: {
        "description": "资源状态冲突",
        "content": {
            "application/json": {
                "example": {
                    "code": 40900,
                    "data": None,
                    "message": "Key already revoked",
                }
            }
        },
    },
}


UPSTREAM_ERROR_RESPONSE = {
    502: {
        "description": "上游 lag-proxy 或 LiteLLM 调用失败",
        "content": {
            "application/json": {
                "example": {
                    "code": 50000,
                    "data": None,
                    "message": "Failed to sync spending limit to LiteLLM",
                }
            }
        },
    },
}
