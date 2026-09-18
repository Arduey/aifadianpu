"""邮件发送:SMTP(来自安装向导/后台配置或 .env)时真实发送,否则演示模式(仅日志)"""
import logging
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from .. import settings

log = logging.getLogger("afdianpu.mail")


def configured() -> bool:
    s = settings.smtp()
    return bool(s["host"] and s["user"] and s["pass"])


def demo_mode() -> bool:
    return not configured()


def send(to: str, subject: str, html: str) -> bool:
    s = settings.smtp()
    if not (s["host"] and s["user"] and s["pass"]):
        log.info("[mailer:demo] → %s | %s", to, subject)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        # 发件地址:优先用已认证的 SMTP 邮箱本身(防伪造/满足 DKIM-SPF 对齐,QQ/163 易因此拒信550);
        # 仅当账号不是邮箱时才用 APP_BASE_URL 域拼 no-reply
        sent_from = s["user"]
        display = s["from"] or "爱发电铺"
        if "@" not in sent_from:
            try:
                _host = settings.app_base_url()
                if "//" in _host:
                    _host = _host.split("//")[-1].split("/")[0]
            except Exception:
                _host = ""
            if not (_host and "." in _host) or _host.lower().startswith("localhost"):
                _host = ""
            sent_from = f"no-reply@{_host}" if _host else s["user"]
        msg["From"] = formataddr((display, sent_from))
        msg["To"] = to
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP_SSL(s["host"], s["port"], timeout=10) as server:
            server.login(s["user"], s["pass"])
            server.sendmail(s["user"], [to], msg.as_string())
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("[mailer] 发送失败: %s", e)
        return False
