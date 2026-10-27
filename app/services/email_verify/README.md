# email_verify —— 通用邮箱验证码组件

一套与框架、ORM、邮件服务都无关的邮箱验证码实现。**整个目录可以直接复制到别的项目**（Flask / Django / FastAPI / 纯脚本都行）。

## 特性

- **算法与业务解耦**：只负责「生成验证码、限频、有效期、一次性校验」这几件事
- **存储可换**：实现 5 个方法的 `CodeStore` 即可（自带内存版 + SQLAlchemy 版）
- **发信可换**：只要求一个 `(to, subject, html) -> bool` 的回调
- **文案可配**：品牌名、邮件标题、正文说明、有效时长、码长、配色全部走 `VerifyConfig`
- **默认自带的安全措施**：
  - 用 `random.SystemRandom` 生成验证码（不受全局随机种子影响）
  - `hmac.compare_digest` 常量时间比较（防时序侧信道）
  - 过期即删 + 校验成功即消费（同一个码不能重复用）
  - 同一邮箱发新码前先删旧码（任意时刻只有一个有效码）
  - 校验码前自动去掉用户粘贴带入的空白（历史坑：`&nbsp;` 会带空格）

## 行为约定

| 项 | 默认值 | 改法 |
| --- | --- | --- |
| 有效期 | 10 分钟 | `VerifyConfig(ttl=timedelta(minutes=5))` |
| 重发间隔 | 1 分钟 | `VerifyConfig(resend=timedelta(seconds=30))` |
| 验证码长度 | 6 位 | `VerifyConfig(code_length=4)` |
| 验证码字符集 | 纯数字 | `VerifyConfig(code_chars="0123456789ABCDEF")` |
| 校验时大小写 | 不敏感 | 固定行为 |

`send()` 返回 `(ok, message)`，`message` 可以直接展示给用户：

| 情况 | ok | message |
| --- | --- | --- |
| 成功 | `True` | `验证码已发送至邮箱` |
| 邮箱格式不对 | `False` | `邮箱格式不正确` |
| 已注册（传了 `exists`） | `False` | `该邮箱已注册，请直接登录或更换邮箱` |
| 一分钟内重复发 | `False` | `发送过于频繁，请 N 秒后重试` |
| 发信失败 | `False` | `邮件发送失败：请检查 SMTP 配置后重试` |

---

## 快速上手（内存存储，适合单进程小项目 / 测试）

```python
from email_verify import EmailVerifier, MemoryCodeStore, VerifyConfig

def send_mail(to, subject, html) -> bool:
    # 换成你自己的发信实现；返回 False 表示没发出去
    print(to, subject)
    return True

verifier = EmailVerifier(
    store=MemoryCodeStore(),
    send_mail=send_mail,
    config=VerifyConfig(brand="我的应用"),
)

ok, msg = verifier.send("a@b.com")
print(ok, msg)                      # True 验证码已发送至邮箱

print(verifier.verify("a@b.com", "123456"))   # True / False，成功即消费
```

> ⚠️ `MemoryCodeStore` 只存在进程内存里：**多进程（gunicorn/uwsgi 多 worker）或多机部署会失效**——A 进程发的码，B 进程校验不到。生产请用共享存储。

---

## FastAPI + SQLAlchemy（本项目用法）

### 1. 建表（模型字段名固定这五个）

```python
class VerificationCode(Base):
    __tablename__ = "verification_codes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(120), nullable=False, index=True)
    code = Column(String(8), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=False, default=datetime.now)
```

### 2. 组装

```python
from app.db import SessionLocal, User, VerificationCode
from app.services import mailer
from app.services.email_verify import EmailVerifier, SQLAlchemyCodeStore, VerifyConfig

def _exists(email: str) -> bool:            # 可选：注册前查重
    with SessionLocal() as db:
        return db.query(User.id).filter(User.email == email).first() is not None

verifier = EmailVerifier(
    store=SQLAlchemyCodeStore(SessionLocal, VerificationCode),
    send_mail=mailer.send,                  # (to, subject, html) -> bool
    config=VerifyConfig(brand="爱发电铺"),
    exists=_exists,
)
```

### 3. 路由

```python
@router.post("/api/verification/send")
async def send_verification(request: Request):
    body = await request.json()
    email = str(body.get("email", ""))
    ok, msg = verifier.send(email)
    if ok:
        return {"ok": True, "message": msg}
    return JSONResponse({"ok": False, "message": msg}, status_code=400)

# 注册时
if not verifier.verify(email, code):
    return {"ok": False, "message": "验证码错误或已失效"}
```

---

## Flask 用法

```python
from flask import Flask, request, jsonify
from flask_mail import Mail, Message
from email_verify import EmailVerifier, MemoryCodeStore, VerifyConfig
# 生产请换成 Redis/MySQL 存储，见下一节

app = Flask(__name__)
mail = Mail(app)

def send_mail(to: str, subject: str, html: str) -> bool:
    try:
        mail.send(Message(subject=subject, recipients=[to], html=html))
        return True
    except Exception:
        return False

verifier = EmailVerifier(
    store=MemoryCodeStore(),
    send_mail=send_mail,
    config=VerifyConfig(brand="我的站点", ttl=timedelta(minutes=5)),
)

@app.post("/api/code/send")
def code_send():
    ok, msg = verifier.send(request.json["email"])
    return jsonify(ok=ok, message=msg), (200 if ok else 400)

@app.post("/api/code/check")
def code_check():
    return jsonify(ok=verifier.verify(request.json["email"], request.json["code"]))
```

---

## Django 用法

```python
# settings.py 里已有 EMAIL_* 配置
from django.core.mail import send_mail as dj_send_mail
from email_verify import EmailVerifier, VerifyConfig
from .store import DjangoCodeStore        # 见下方自定义存储示例

def send_mail(to, subject, html) -> bool:
    try:
        dj_send_mail(subject, "", None, [to], html_message=html)
        return True
    except Exception:
        return False

verifier = EmailVerifier(
    store=DjangoCodeStore(),
    send_mail=send_mail,
    config=VerifyConfig(brand="我的后台"),
)
```

---

## 自己写存储（Redis 示例）

只要实现 `CodeStore` 的 4 个方法，语义如下：

| 方法 | 语义 |
| --- | --- |
| `latest(email)` | 返回该邮箱**最新一条**记录，没有返回 `None`；限频和校验都用它 |
| `add(record)` | 存一条新记录（`record.id` 可留给存储层回填） |
| `delete_for(email)` | 删掉该邮箱**所有**记录（发新码前调用） |
| `delete_by_id(id)` | 删一条（过期或校验成功后调用） |

```python
import json
from datetime import datetime
from email_verify import CodeRecord

class RedisCodeStore:
    """key: verify:{email} → json；天然带 TTL，无需额外清理任务。"""

    def __init__(self, redis, ttl_seconds=600):
        self.r = redis
        self.ttl = ttl_seconds
        self._key = lambda email: f"verify:{email}"

    def latest(self, email):
        raw = self.r.get(self._key(email))
        if not raw:
            return None
        d = json.loads(raw)
        return CodeRecord(
            email=email,
            code=d["code"],
            expires_at=datetime.fromisoformat(d["expires_at"]),
            last_sent_at=datetime.fromisoformat(d["last_sent_at"]),
            id=email,                       # Redis 版用 email 当"主键"
        )

    def add(self, record):
        self.r.set(self._key(record.email), json.dumps({
            "code": record.code,
            "expires_at": record.expires_at.isoformat(),
            "last_sent_at": record.last_sent_at.isoformat(),
        }), ex=self.ttl)

    def delete_for(self, email):
        self.r.delete(self._key(email))

    def delete_by_id(self, record_id):
        self.r.delete(self._key(record_id))
```

---

## 常见坑（都踩过）

1. **多 worker 部署用内存存储** → 换个进程就校验失败。用 Redis / 数据库。
2. **验证码里加 `&nbsp;` 分隔** → 用户复制会带空格，校验失败。本组件已用 `normalize_code` 去掉所有空白，字距靠邮件的 `letter-spacing` 实现。
3. **发送成功就删旧码**、**校验成功才删码** —— 顺序别反，否则并发时会留下多个有效码。
4. **SMTP 没配置时不要假装成功**：`send_mail` 返回 `False`，本组件会明确报错，避免用户白等。
5. **限频只按邮箱**：如果你还要按 IP 限频，请在路由层加（组件不管 HTTP 层）。
6. **`exists` 钩子会让"该邮箱是否注册"暴露给任何人**：介意邮箱枚举的话，把它换成通用文案（例如统一回「验证码已发送」），或加图形验证码。

## 文件结构

```
email_verify/
├── __init__.py            # 对外导出（不依赖 SQLAlchemy）
├── core.py                # 协议 + 配置 + 算法 + 邮件模板（零依赖）
├── sqlalchemy_store.py    # SQLAlchemy 存储参考实现
└── README.md
```
