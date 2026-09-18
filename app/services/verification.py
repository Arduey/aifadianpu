"""注册/操作 邮箱验证码:发送、重发间隔、校验(1分钟限发,10分钟有效)"""
import random
import string
from datetime import datetime, timedelta

from ..db import SessionLocal, User, VerificationCode
from . import mailer

CODE_TTL = timedelta(minutes=10)     # 验证码有效时长
RESEND = timedelta(minutes=1)        # 重发最小间隔

VALID_CHARS = "0123456789"


def _gen_code() -> str:
    return "".join(random.choice(VALID_CHARS) for _ in range(6))


def send_code(email: str):
    """发送验证码到邮箱。返回 (ok, message)。
    - 距上次发送不足1分钟 → 返回剩余秒数
    - 成功 → ok=True, '验证码已发送'
    - 邮件为演示模式 → ok=True 附带提示(仅测试环境)
    """
    email = email.strip().lower()
    now = datetime.now()
    blurb = "请在所有需要验证(如注册/改密)时填写"

    with SessionLocal() as db:
        # 注册前校验:邮箱已注册则不发验证码,直接提示(避免给已注册邮箱发码)
        if db.query(User.id).filter(User.email == email).first():
            return False, "该邮箱已注册,请直接登录或更换邮箱"
        row = (
            db.query(VerificationCode)
            .filter(VerificationCode.email == email)
            .order_by(VerificationCode.id.desc())
            .first()
        )
        if row:
            elapsed = (now - row.last_sent_at).total_seconds()
            if elapsed < RESEND.total_seconds():
                wait = int(RESEND.total_seconds() - elapsed) + 1
                return False, f"发送过于频繁,请 {wait} 秒后重试"
        # 生成并入库
        code = _gen_code()
        db.query(VerificationCode).filter(VerificationCode.email == email).delete()
        db.add(VerificationCode(
            email=email, code=code,
            expires_at=now + CODE_TTL,
            last_sent_at=now,
        ))
        db.commit()

    # 发送邮件;未配置 SMTP 时明确失败,不降级为演示
    ok_mail = mailer.send(email, "【爱发电铺】验证码(10分钟内有效)", _html(code, blurb))
    if not ok_mail:
        return False, "邮件发送失败:未配置有效的 SMTP,无法发送验证码"
    return True, "验证码已发送至邮箱"


def verify_code(email: str, code: str) -> bool:
    """校验验证码。成功消费(删除该邮箱记录),失败返回 False。"""
    email = email.strip().lower()
    # 容错:去掉用户粘贴时可能带入的所有空白(旧邮件用 &nbsp; 分隔会带上空格)
    code = "".join((code or "").split())
    now = datetime.now()
    with SessionLocal() as db:
        row = (
            db.query(VerificationCode)
            .filter(VerificationCode.email == email)
            .order_by(VerificationCode.id.desc())
            .first()
        )
        if not row or row.code != code:
            return False
        if row.expires_at < now:
            db.query(VerificationCode).filter(VerificationCode.id == row.id).delete()
            db.commit()
            return False
        # 一次性使用
        db.query(VerificationCode).filter(VerificationCode.id == row.id).delete()
        db.commit()
        return True


def _html(code: str, blurb: str) -> str:
    # 不再用 &nbsp; 分隔验证码:复制时会带上空格影响粘贴。字间距交给 letter-spacing 呈现。
    return f'''<!doctype html><html><body style="margin:0;background:#F4F0E8;padding:28px 12px;font-family:'PingFang SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="380" cellpadding="0" cellspacing="0" style="width:380px;max-width:380px;background:#FFFFFF;border-radius:16px;overflow:hidden;border:1px solid #ECE6D8;box-shadow:0 14px 34px rgba(84,64,24,.10)">
  <tr><td style="background:linear-gradient(135deg,#FF7A1A 0%,#F95D1F 55%,#E24B06 100%);padding:26px 30px">
      <div style="color:#fff;font-size:15px;font-weight:800">爱发电铺</div>
      <div style="color:rgba(255,255,255,.82);font-size:10px;letter-spacing:2px;margin-top:3px">EMAIL VERIFY</div>
      <div style="margin-top:18px;color:#fff;font-size:21px;font-weight:800;letter-spacing:.2px">邮箱验证</div>
      <div style="color:rgba(255,255,255,.86);font-size:13px;line-height:1.7;margin-top:6px">{blurb}。</div>
  </td></tr>
  <tr><td style="padding:26px 30px 8px;text-align:center">
      <div style="color:#B7AFA0;font-size:11px;font-weight:700;letter-spacing:1px">验证码（10 分钟内有效）</div>
      <div style="margin:12px 0 0;font-size:34px;font-weight:800;letter-spacing:8px;color:#201D17">{code}</div>
      <div style="margin-top:12px;font-size:12px;color:#7E6F3C">请勿把验证码告知他人,谨防钓鱼与转账诈骗。</div>
  </td></tr>
  <tr><td style="padding:16px 30px;border-top:1px dashed #ECE6D8;color:#B4AC99;font-size:11px">此邮件由系统自动发送·请勿直接回复</td></tr>
</table></td></tr></table></body></html>'''

