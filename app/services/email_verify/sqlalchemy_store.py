"""SQLAlchemy 版 `CodeStore` 参考实现（本项目自用，也可抄到自己项目改表名）。

要求传入的模型至少有这五个字段（名字可通过构造参数改）：
    email: str, code: str, expires_at: datetime, last_sent_at: datetime, id: 主键

用法::

    from app.db import SessionLocal, VerificationCode
    from app.services.email_verify import SQLAlchemyCodeStore

    store = SQLAlchemyCodeStore(SessionLocal, VerificationCode)
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from .core import CodeRecord


class SQLAlchemyCodeStore:
    """把验证码记录存到 SQLAlchemy 模型里。

    每次操作都新开一个 session（与项目现有的 `with SessionLocal() as db:` 风格一致），
    避免把长事务带进「校验 → 建用户」的注册流程。
    """

    def __init__(
        self,
        session_factory: Callable,
        model,
        *,
        order_field: str = "id",
    ) -> None:
        self.session_factory = session_factory
        self.model = model
        self.order_field = order_field

    def _to_record(self, row) -> CodeRecord:
        return CodeRecord(
            email=row.email,
            code=row.code,
            expires_at=row.expires_at,
            last_sent_at=row.last_sent_at,
            id=row.id,
        )

    def latest(self, email: str) -> Optional[CodeRecord]:
        m = self.model
        with self.session_factory() as db:
            row = (
                db.query(m)
                .filter(m.email == email)
                .order_by(getattr(m, self.order_field).desc())
                .first()
            )
            return self._to_record(row) if row is not None else None

    def add(self, record: CodeRecord) -> None:
        m = self.model
        with self.session_factory() as db:
            db.add(m(
                email=record.email,
                code=record.code,
                expires_at=record.expires_at,
                last_sent_at=record.last_sent_at,
            ))
            db.commit()

    def delete_for(self, email: str) -> None:
        m = self.model
        with self.session_factory() as db:
            db.query(m).filter(m.email == email).delete()
            db.commit()

    def delete_by_id(self, record_id: object) -> None:
        m = self.model
        with self.session_factory() as db:
            db.query(m).filter(m.id == record_id).delete()
            db.commit()


def purge_expired(store: "SQLAlchemyCodeStore", now: Optional[datetime] = None) -> int:
    """顺带提供的清理助手：删掉所有已过期的验证码（可挂到定时任务里）。返回删除条数。"""
    m = store.model
    now = now or datetime.now()
    with store.session_factory() as db:
        n = db.query(m).filter(m.expires_at < now).delete()
        db.commit()
        return int(n or 0)
