"""环境变量配置(宝塔:面板中配置 或 .env 文件)"""
import os

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

SESSION_SECRET = os.getenv("SESSION_SECRET", "afdianpu-dev-secret-key")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
APP_SECURE = _bool("APP_SECURE", True)

AFDIAN_LIVE = _bool("AFDIAN_LIVE", False)
ENABLE_PREVIEW_LOGIN = _bool("ENABLE_PREVIEW_LOGIN", True)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "爱发电铺")

FEE_PER_ORDER_CENTS = 20  # 每笔成功订单扣 ¥0.20
