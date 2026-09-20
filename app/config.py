"""环境变量配置(宝塔:面板中配置 或 .env 文件)"""
import os
import secrets

from dotenv import load_dotenv

# 固定从项目根加载 .env(不依赖当前工作目录)。安装向导会把配置写入
# 项目根 .env,这里显式指向它,保证无论从哪个目录启动都能读到。
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BASE, ".env"))


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "afdianpu")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "afdianpu")

# 会话签名密钥(HS256 JWT):必须由 .env 提供。未配置时随机生成,避免沿用公开的固定值
# 导致任何人可伪造登录 cookie;随机值只在"尚未走向导"阶段生效,该阶段没有真实会话。
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
# 对外访问域名:留空表示未配置,由使用处以当前请求域名兜底(不再写死 localhost)
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")
APP_SECURE = _bool("APP_SECURE", True)

# ⚠️ 遗留配置:当前业务代码已不读取(下单/查单固定走 app/services/afd_live.py 的真实接口)。
# 保留仅为兼容旧 .env 与旧数据库列,新部署无需设置。
AFDIAN_LIVE = _bool("AFDIAN_LIVE", False)
ENABLE_PREVIEW_LOGIN = _bool("ENABLE_PREVIEW_LOGIN", True)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "爱发电铺")

FEE_PER_ORDER_CENTS = 20  # 每笔成功订单扣 ¥0.20
