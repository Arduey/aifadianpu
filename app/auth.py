"""会话 / 密码 / 登录锁定 / 预览通行证"""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta

import jwt
from fastapi import Request
from sqlalchemy import func

from . import config, settings
from .db import LoginLock, PlatformSetting, SessionLocal, User

COOKIE_NAME = "afp_session"


# ── 密码:PBKDF2-SHA256(零依赖) ─────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 120_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 120_000)
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# ── 会话令牌(与 Next 版相同的 HS256 JWT,Cookie/Bearer 双通道) ──
def sign_token(user: User) -> str:
    return jwt.encode(
        {"sub": str(user.id), "role": user.role, "exp": datetime.now() + timedelta(days=7)},
        config.SESSION_SECRET,
        algorithm="HS256",
    )


def _verify_token(raw: str):
    try:
        payload = jwt.decode(raw, config.SESSION_SECRET, algorithms=["HS256"])
        return int(payload["sub"]), str(payload.get("role", "merchant"))
    except Exception:
        return None


def current_user(request: Request):
    """Cookie → Bearer → 预览通行证(?preview=admin|merchant);未登录返回 None"""
    raw = request.cookies.get(COOKIE_NAME)
    claim = _verify_token(raw) if raw else None
    if claim is None:
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            claim = _verify_token(header[7:])
    with SessionLocal() as db:
        if claim:
            user = db.get(User, claim[0])
            if user and user.status == "active":
                return user
        # 预览通行证(生产以 ENABLE_PREVIEW_LOGIN=false 关闭)
        preview = request.query_params.get("preview")
        if preview and settings.enable_preview_login():
            if preview == "admin":
                user = db.query(User).filter(User.role == "admin").order_by(User.id).first()
                if user and user.status == "active":
                    return user
            elif preview == "merchant":
                user = (
                    db.query(User)
                    .filter(User.role == "merchant", User.status == "active")
                    .order_by(User.id)
                    .first()
                )
                if user:
                    return user
    return None


# ── 防爆破:5 分钟内失败 5 次 → 锁定 5 分钟 ──────────────
def lock_remaining(identifier: str) -> int:
    with SessionLocal() as db:
        lock = db.get(LoginLock, identifier)
        if not lock or not lock.locked_until:
            return 0
        left = int(lock.locked_until.timestamp() - time.time())
        return left if left > 0 else 0


def record_fail(identifier: str):
    """返回 (是否锁定, 剩余秒数, 失败次数)"""
    with SessionLocal() as db:
        lock = db.get(LoginLock, identifier)
        now = datetime.now()
        if not lock:
            db.add(LoginLock(identifier=identifier, fail_count=1, window_started_at=now))
            db.commit()
            return False, 0, 1
        window_fresh = (now - lock.window_started_at).total_seconds() > 300
        fails = 1 if window_fresh else lock.fail_count + 1
        if fails >= 5:
            lock.fail_count = 0
            lock.window_started_at = now
            lock.locked_until = now + timedelta(minutes=5)
            db.commit()
            return True, 300, fails
        lock.fail_count = fails
        lock.window_started_at = now if window_fresh else lock.window_started_at
        lock.locked_until = None
        db.commit()
        return False, 0, fails


def clear_lock(identifier: str) -> None:
    with SessionLocal() as db:
        db.query(LoginLock).filter(LoginLock.identifier == identifier).delete()
        db.commit()


def random_token(length: int = 28) -> str:
    return secrets.token_hex((length + 1) // 2)[:length]


def first_admin_email() -> str | None:
    with SessionLocal() as db:
        email = db.query(User.email).filter(User.role == "admin").order_by(User.id).first()
        return email[0] if email else None


def is_installed() -> bool:
    """平台是否已完成安装向导(platform_settings.installed)"""
    try:
        with SessionLocal() as db:
            row = db.query(PlatformSetting).order_by(PlatformSetting.id).first()
            return bool(row and row.installed)
    except Exception:
        # 模型可能含尚未 ALTER 的新列(如 api_fee_cents)导致整个 SELECT 失败;
        # 用原生 SQL 只取 installed 列,缺列也能正确判断。
        try:
            from sqlalchemy import text
            with SessionLocal() as db:
                r = db.execute(text("SELECT installed FROM platform_settings ORDER BY id LIMIT 1")).first()
                return bool(r and r[0])
        except Exception:
            return False
