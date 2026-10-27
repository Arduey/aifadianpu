"""通用邮箱验证码组件。

按需导入即可，`__init__` 不导入 SQLAlchemy 等重依赖，
所以把整个 `email_verify/` 目录抄到 Flask/Django 项目里也能直接用（只用内存存储或自写存储）。
"""
from .core import (
    CodeRecord,
    CodeStore,
    EmailVerifier,
    MemoryCodeStore,
    VerifyConfig,
    VerifyError,
    is_valid_email,
    normalize_code,
    normalize_email,
    render_code_email,
)

__all__ = [
    "CodeRecord",
    "CodeStore",
    "EmailVerifier",
    "MemoryCodeStore",
    "VerifyConfig",
    "VerifyError",
    "is_valid_email",
    "normalize_code",
    "normalize_email",
    "render_code_email",
    "SQLAlchemyCodeStore",
]


def __getattr__(name):
    """懒加载 SQLAlchemy 实现：只有真的用到它才需要装 SQLAlchemy。"""
    if name == "SQLAlchemyCodeStore":
        from .sqlalchemy_store import SQLAlchemyCodeStore
        return SQLAlchemyCodeStore
    raise AttributeError(name)
