def add_error_responses(result, generator, request, public):
    """Document the shared error envelope for every API operation."""
    result["components"]["schemas"]["ErrorResponse"] = {
        "type": "object",
        "required": ["error"],
        "properties": {
            "error": {
                "type": "object",
                "required": ["code", "message", "details", "request_id"],
                "properties": {
                    "code": {"type": "string", "example": "validation_error"},
                    "message": {"type": "string"},
                    "details": {
                        "description": "Field errors, a list of errors, or a detail message."
                    },
                    "request_id": {"type": "string", "nullable": True},
                },
            }
        },
    }
    for path, operations in result["paths"].items():
        if path == "/health/":
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            codes = {
                "400": "Invalid request",
                "401": "Authentication required",
                "403": "Permission denied",
                "404": "Not found",
                "500": "Internal error",
            }
            if method in {"post", "put", "patch", "delete"}:
                codes["409"] = "Resource state or relationship conflict"
            if path == "/api/auth/login/":
                codes["429"] = "Login rate limit exceeded"
            for code, description in codes.items():
                operation["responses"].setdefault(
                    code,
                    {
                        "description": description,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                            }
                        },
                    },
                )
    return result
