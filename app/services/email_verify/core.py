"""通用「邮箱验证码」组件（与框架/ORM 解耦，可直接抄到其他项目用）。

设计思路：
- **算法纯函数化**：生成验证码、判断是否可重发、判断是否过期，都是纯函数 → 好测、无副作用。
- **存储靠接口**：只要求调用方实现 `CodeStore` 那 5 个方法；用 ORM、Redis、SQLite 都行。
- **发信靠回调**：只要求 `callable(to, subject, html) -> bool`；本项目传 mailer.send，
  其他项目传 Flask-Mail / Django send_mail / smtplib 都可以。
- **文案靠配置**：品牌名、主题、有效时长、码长全在 `VerifyConfig` 里，不写死。

快速上手见同目录 README.md。
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, Protocol, runtime_checkable

__all__ = [
    "CodeRecord",
    "CodeStore",
    "MemoryCodeStore",
    "VerifyConfig",
    "VerifyError",
    "EmailVerifier",
    "normalize_email",
    "normalize_code",
    "is_valid_email",
    "render_code_email",
]


# ────────────────────────────── 数据与接口 ──────────────────────────────

@dataclass
class CodeRecord:
    """一次发送留下的记录。字段名刻意保持中性，方便映射到任意存储。"""
    email: str
    code: str
    expires_at: datetime
    last_sent_at: datetime
    id: object = None            # 存储层的主键，可选（内存实现不用）


@runtime_checkable
class CodeStore(Protocol):
    """存储接口：实现这 5 个方法即可接入任意后端。

    语义约定：
    - `latest(email)` 返回该邮箱**最新一条**记录（没有则 None），用于限频与校验。
    - `delete_for(email)` 删除该邮箱所有记录（发新码前清旧码，保证同一时刻只有一个有效码）。
    - `delete_by_id(id)` 删除单条（过期或校验成功后消费）。
    """

    def latest(self, email: str) -> Optional[CodeRecord]: ...
    def add(self, record: CodeRecord) -> None: ...
    def delete_for(self, email: str) -> None: ...
    def delete_by_id(self, record_id: object) -> None: ...


class MemoryCodeStore:
    """内存实现：适合单进程小项目、单元测试或演示。

    ⚠️ 多进程/多机部署请改用共享存储（Redis / MySQL），否则各进程各存一份，
    会出现「A 进程发的码 B 进程校验不过」。生产请用 `sqlalchemy_store.SQLAlchemyCodeStore`
    或自己照此实现一份。
    """

    def __init__(self) -> None:
        self._rows: list[CodeRecord] = []
        self._seq = 0

    def latest(self, email: str) -> Optional[CodeRecord]:
        for r in reversed(self._rows):
            if r.email == email:
                return r
        return None

    def add(self, record: CodeRecord) -> None:
        self._seq += 1
        record.id = self._seq
        self._rows.append(record)

    def delete_for(self, email: str) -> None:
        self._rows = [r for r in self._rows if r.email != email]

    def delete_by_id(self, record_id: object) -> None:
        self._rows = [r for r in self._rows if r.id != record_id]


# ────────────────────────────── 配置 ──────────────────────────────

_HTML_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _esc(s: str) -> str:
    return "".join(_HTML_ESCAPE.get(c, c) for c in str(s))


@dataclass
class VerifyConfig:
    """文案与策略配置：换个项目改这里就行，不用碰算法。"""

    brand: str = "我的应用"                       # 邮件顶部的品牌名
    subject: str = "【{brand}】验证码（{minutes} 分钟内有效）"
    blurb: str = "请在所有需要验证的操作中填写"    # 邮件正文里的一句说明
    title: str = "邮箱验证"                       # 邮件主标题
    tagline: str = "EMAIL VERIFY"                 # 主标题上方的小字
    warn: str = "请勿把验证码告知他人，谨防钓鱼与诈骗。"
    footer: str = "此邮件由系统自动发送·请勿直接回复"
    # 策略
    ttl: timedelta = field(default_factory=lambda: timedelta(minutes=10))
    resend: timedelta = field(default_factory=lambda: timedelta(minutes=1))
    code_length: int = 6
    code_chars: str = "0123456789"
    # 配色（邮件模板用）
    brand_from: str = "#FF7A1A"
    brand_to: str = "#E24B06"
    page_bg: str = "#F4F0E8"
    # 提示文案（都可覆盖：接入已有项目时保持既有文案不变）
    msg_sent: str = "验证码已发送至邮箱"
    msg_invalid_email: str = "邮箱格式不正确"
    msg_exists: str = "该邮箱已注册，请直接登录或更换邮箱"
    msg_too_frequent: str = "发送过于频繁，请 {wait} 秒后重试"
    msg_send_failed: str = "邮件发送失败：请检查 SMTP 配置后重试"

    def subject_text(self) -> str:
        return self.subject.format(brand=self.brand, minutes=int(self.ttl.total_seconds() // 60))


class VerifyError(Exception):
    """带用户可见文案的错误；调用方直接把它展示给用户即可。"""


# ────────────────────────────── 纯函数：算法工具 ──────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str) -> str:
    """邮箱归一化：去首尾空白 + 小写（大多数人邮箱大小写不敏感，统一存小写可避免重复注册）。"""
    return (email or "").strip().lower()


def normalize_code(code: str) -> str:
    """验证码归一化：去掉用户粘贴时可能带入的所有空白。

    历史坑：早期邮件模板用 &nbsp; 分隔验证码，粘贴会带空格；这里统一清除，
    并且不区分大小写（万一你把 code_chars 换成含字母的字符集）。
    """
    return "".join((code or "").split()).upper()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


# ────────────────────────────── 主组件 ──────────────────────────────

class EmailVerifier:
    """邮箱验证码：发送（带限频）、校验（一次性消费）。

    典型用法::

        verifier = EmailVerifier(
            store=SQLAlchemyCodeStore(session_factory, VerificationCode),
            send_mail=mailer.send,              # (to, subject, html) -> bool
            config=VerifyConfig(brand="爱发电铺"),
            exists=my_check_exists,             # 可选：注册前查重
        )
        ok, msg = verifier.send("a@b.com")
        assert verifier.verify("a@b.com", "123456")
    """

    def __init__(
        self,
        store: CodeStore,
        send_mail: Callable[[str, str, str], bool],
        config: Optional[VerifyConfig] = None,
        *,
        exists: Optional[Callable[[str], bool]] = None,
        allow_invalid_email: bool = False,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        """
        :param store: 存储实现（见 CodeStore）
        :param send_mail: 发信回调 `(to, subject, html) -> bool`，返回 False 表示没发出去
        :param config: 文案/策略配置
        :param exists: 可选查重回调，返回 True 表示该邮箱已存在（如已注册），此时拒发验证码
        :param allow_invalid_email: True 时不在组件内做邮箱格式校验（由调用方自己校验）
        :param clock: 时间源，便于测试注入固定时间
        """
        self.store = store
        self.send_mail = send_mail
        self.config = config or VerifyConfig()
        self.exists = exists
        self.allow_invalid_email = allow_invalid_email
        self.clock = clock

    # ── 发送 ──────────────────────────────────────────────
    def send(self, email: str, *, subject: Optional[str] = None,
             blurb: Optional[str] = None) -> tuple[bool, str]:
        """生成并发送验证码。返回 `(ok, message)`，message 可直接展示给用户。"""
        email = normalize_email(email)
        cfg = self.config
        if not self.allow_invalid_email and not is_valid_email(email):
            return False, cfg.msg_invalid_email

        now = self.clock()

        # ① 业务钩子：邮箱已存在（已注册）就不发码，避免给已有账号乱发邮件
        if self.exists is not None and self.exists(email):
            return False, cfg.msg_exists

        # ② 限频：距上次发送不足 resend 就拒，并告诉用户还要等几秒
        row = self.store.latest(email)
        if row is not None:
            elapsed = (now - row.last_sent_at).total_seconds()
            if elapsed < cfg.resend.total_seconds():
                wait = int(cfg.resend.total_seconds() - elapsed) + 1
                return False, cfg.msg_too_frequent.replace("{wait}", str(wait))

        # ③ 生成并落库（先删旧码，保证同一邮箱同一时刻只有一个有效码）
        code = self._gen_code()
        self.store.delete_for(email)
        self.store.add(CodeRecord(
            email=email, code=code,
            expires_at=now + cfg.ttl,
            last_sent_at=now,
        ))

        # ④ 发信：失败就明确回错，不假装成功（否则用户白等）
        ok = self.send_mail(
            email,
            subject or cfg.subject_text(),
            render_code_email(code, cfg, blurb=blurb),
        )
        if not ok:
            return False, cfg.msg_send_failed
        return True, cfg.msg_sent

    # ── 校验 ──────────────────────────────────────────────
    def verify(self, email: str, code: str) -> bool:
        """校验验证码。成功即消费（删除记录），因此同一码不能重复使用。"""
        email = normalize_email(email)
        code = normalize_code(code)
        if not email or not code:
            return False
        now = self.clock()
        row = self.store.latest(email)
        if row is None:
            return False
        # 用常量时间比较，避免按字符逐位试探的时序侧信道
        if not _constant_time_eq(normalize_code(row.code), code):
            return False
        if row.expires_at < now:
            self.store.delete_by_id(row.id)
            return False
        self.store.delete_by_id(row.id)   # 一次性消费
        return True

    # ── 内部 ──────────────────────────────────────────────
    def _gen_code(self) -> str:
        cfg = self.config
        n = max(int(cfg.code_length), 1)
        chars = cfg.code_chars or "0123456789"
        # 用 SystemRandom：不依赖全局 random 种子，避免被预测
        rng = random.SystemRandom()
        return "".join(rng.choice(chars) for _ in range(n))


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ────────────────────────────── 邮件模板 ──────────────────────────────

def render_code_email(code: str, cfg: VerifyConfig, blurb: Optional[str] = None) -> str:
    """渲染验证码邮件 HTML。

    注意：验证码数字之间**不要**用 &nbsp; 分隔（复制会带空格），字距交给 letter-spacing。
    """
    minutes = int(cfg.ttl.total_seconds() // 60)
    desc = blurb if blurb is not None else cfg.blurb
    return f'''<!doctype html><html><body style="margin:0;background:{_esc(cfg.page_bg)};padding:28px 12px;font-family:'PingFang SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="380" cellpadding="0" cellspacing="0" style="width:380px;max-width:380px;background:#FFFFFF;border-radius:16px;overflow:hidden;border:1px solid #ECE6D8;box-shadow:0 14px 34px rgba(84,64,24,.10)">
  <tr><td style="background:linear-gradient(135deg,{_esc(cfg.brand_from)} 0%,#F95D1F 55%,{_esc(cfg.brand_to)} 100%);padding:26px 30px">
      <div style="color:#fff;font-size:15px;font-weight:800">{_esc(cfg.brand)}</div>
      <div style="color:rgba(255,255,255,.82);font-size:10px;letter-spacing:2px;margin-top:3px">{_esc(cfg.tagline)}</div>
      <div style="margin-top:18px;color:#fff;font-size:21px;font-weight:800;letter-spacing:.2px">{_esc(cfg.title)}</div>
      <div style="color:rgba(255,255,255,.86);font-size:13px;line-height:1.7;margin-top:6px">{_esc(desc)}。</div>
  </td></tr>
  <tr><td style="padding:26px 30px 8px;text-align:center">
      <div style="color:#B7AFA0;font-size:11px;font-weight:700;letter-spacing:1px">验证码（{minutes} 分钟内有效）</div>
      <div style="margin:12px 0 0;font-size:34px;font-weight:800;letter-spacing:8px;color:#201D17">{_esc(code)}</div>
      <div style="margin-top:12px;font-size:12px;color:#7E6F3C">{_esc(cfg.warn)}</div>
  </td></tr>
  <tr><td style="padding:16px 30px;border-top:1px dashed #ECE6D8;color:#B4AC99;font-size:11px">{_esc(cfg.footer)}</td></tr>
</table></td></tr></table></body></html>'''
