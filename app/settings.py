"""运行时业务配置:优先取 platform_settings(安装向导/后台可改),空则回退 .env"""
from . import config
from .db import PlatformSetting, SessionLocal


def _row():
    with SessionLocal() as db:
        return db.query(PlatformSetting).order_by(PlatformSetting.id).first()


def allowed_email_domains() -> list:
    """注册允许的邮箱域名(分号;分隔,空/不可用 = 不限制)。返回小写、无 @ 列表。"""
    domains = []
    try:
        r = _row()
        if r is not None and getattr(r, "allowed_email_domains", None):
            raw = str(r.allowed_email_domains)
            domains = [x.strip().lower().lstrip("@") for x in raw.replace("，", ";").replace(",", ";").split(";") if x.strip()]
    except Exception:
        domains = []
    return domains


def app_base_url() -> str:
    """对外访问地址(重置链接前缀):DB 已填则用 DB,否则 .env"""
    try:
        r = _row()
        if r and r.app_base_url:
            return r.app_base_url.rstrip("/")
    except Exception:
        pass
    return config.APP_BASE_URL


def afdian_live() -> bool:
    try:
        r = _row()
        if r is not None and r.afdian_live is not None:
            return bool(r.afdian_live)
    except Exception:
        pass
    return config.AFDIAN_LIVE


def enable_preview_login() -> bool:
    try:
        r = _row()
        if r is not None and r.enable_preview_login is not None:
            return bool(r.enable_preview_login)
    except Exception:
        pass
    return config.ENABLE_PREVIEW_LOGIN


def smtp() -> dict:
    """SMTP 配置:DB 有 smtp_host 则用 DB,否则回退 .env"""
    try:
        r = _row()
        if r and r.smtp_host:
            return {
                "host": r.smtp_host,
                "port": r.smtp_port or config.SMTP_PORT,
                "user": r.smtp_user,
                "pass": r.smtp_pass,
                "from": r.smtp_from or config.SMTP_FROM,
            }
    except Exception:
        pass
    return {
        "host": config.SMTP_HOST,
        "port": config.SMTP_PORT,
        "user": config.SMTP_USER,
        "pass": config.SMTP_PASS,
        "from": config.SMTP_FROM,
    }


def api_fee_cents() -> int:
    """单次 API 费用(分):DB 可调(管理台),否则 .env 默认"""
    try:
        r = _row()
        if r is not None and getattr(r, "api_fee_cents", None) is not None:
            return int(r.api_fee_cents)
    except Exception:
        pass
    return int(config.FEE_PER_ORDER_CENTS)
