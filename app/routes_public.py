"""公开路由:主页/注册、登录、忘记密码、店铺页、下单轮询、公开小接口"""
import json
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import auth, config, settings
from .db import FeeLedger, Order, PasswordReset, PlatformSetting, Product, ProductCategory, SessionLocal, User, platform_settings
from .render import render
from .services import afdian, afd_login, afd_live, delivery, mailer, email_templates, pipeline, verification
from .utils import shop_name_ok, valid_email, valid_shop_name

router = APIRouter()


def err(message: str, status: int = 400):
    return JSONResponse({"ok": False, "message": message}, status_code=status)


def _client_ip(request: Request) -> str:
    """获取客户端 IP(经 Nginx 反代读取 X-Forwarded-For),用于登录锁定"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


# ── 主页 + 注册(注册即商户,送 ¥0.20;管理员由安装向导创建) ──
@router.get("/")
def home(request: Request):
    _plogo = ""
    try:
        with SessionLocal() as db:
            _plogo = platform_settings(db).platform_logo_url or ""
    except Exception:  # noqa: BLE001
        _plogo = ""
    return render(request, "index.html", {"error": "", "form": {"email": "", "shop_name": ""}, "platformLogo": _plogo})


@router.post("/api/verification/send")
async def send_verification(request: Request):
    """注册邮箱验证码:发送前 1 分钟限次(由 verification 服务控制)"""
    try:
        b = await request.json()
    except Exception:
        b = await request.form()
    email = str(b.get("email", "")).strip().lower()
    if not valid_email(email):
        return err("邮箱格式不正确,仅支持 QQ / 163 邮箱")
    ok_re, msg = verification.send_code(email)
    if ok_re:
        return {"ok": True, "message": msg}
    return err(msg)


@router.post("/")
async def register(request: Request):
    """注册。AJAX(带 X-Requested-With: fetch / JSON body)返回 JSON;否则按原 HTML 渲染。"""
    is_ajax = False
    body = None
    try:
        body = await request.json()
    except Exception:
        pass
    if body is not None:
        is_ajax = True
        email = str(body.get("email", "")).strip().lower()
        shop_name = str(body.get("shop_name", "")).strip()
        password = str(body.get("password", ""))
        confirm = str(body.get("confirm", ""))
        code = str(body.get("code", "")).strip()
    else:
        f = await request.form()
        is_ajax = str(request.headers.get("x-requested-with", "")).lower() == "fetch"
        email = str(f.get("email", "")).strip().lower()
        shop_name = str(f.get("shop_name", "")).strip()
        password = str(f.get("password", ""))
        confirm = str(f.get("confirm", ""))
        code = str(f.get("code", "")).strip()

    form = {"email": email, "shop_name": shop_name}
    error = ""
    _dom = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    _allowed_domains = settings.allowed_email_domains()
    if _allowed_domains and _dom not in _allowed_domains:
        error = "该邮箱域名不在允许注册列表(由平台管理员在个人中心配置): " + " / ".join(_allowed_domains)
    elif not valid_email(email):
        error = "邮箱格式不正确,仅支持 QQ / 163 邮箱"
    elif not shop_name_ok(shop_name):
        error = "店铺名仅支持中文/字母/数字,不含特殊符号;汉字按2字符,最长折合12字符"
    elif len(password) < 8 or len(password) > 20:
        error = "密码须为 8~20 位"
    elif password != confirm:
        error = "两次输入的密码不一致"
    elif not code:
        error = "请输入邮箱验证码"
    elif not verification.verify_code(email, code):
        error = "验证码错误或已失效"
    elif _has_registered(email, shop_name):
        error = "该邮箱已注册,或店铺名已被占用"

    if error:
        if is_ajax:
            return JSONResponse({"ok": False, "message": error, "form": form})
        return render(request, "index.html", {"error": error, "form": form})

    _grant = settings.api_fee_cents()  # 注册赠送=单次API费用(管理台可调)
    with SessionLocal() as db:
        user = User(
            email=email, shop_name=shop_name,
            password_hash=auth.hash_password(password),
            role="merchant", api_balance_cents=_grant,  # 注册即送单次费用
            email_notify=True, balance_notify=True,     # 新注册默认开启:订单邮件通知 + API 余额不足提醒
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        # 注册赠送,记为"赠送"流水
        db.add(FeeLedger(
            merchant_id=user.id, delta_cents=_grant, balance_after_cents=_grant,
            reason="signup_grant", note="注册赠送",
            created_at=datetime.now(),
        ))
        db.commit()
        # 新注册商户自动创建一个默认分类 + 默认测试商品,便于立即体验
        _dc = ProductCategory(merchant_id=user.id, name="默认分类", icon_url="",
                              sort_order=0, created_at=datetime.now(), updated_at=datetime.now())
        db.add(_dc)
        db.flush()
        db.add(Product(
            merchant_id=user.id, category_id=_dc.id,
            title="测试商品", sku_name="默认SKU",
            price=5, is_recharge=False, recharge_grant_cents=0, sort_order=0,
            created_at=datetime.now(), updated_at=datetime.now(),
        ))
        db.commit()
        token = auth.sign_token(user)
    resp = JSONResponse({"ok": True, "redirect": "/console/dashboard"})
    resp.set_cookie(
        auth.COOKIE_NAME, token, max_age=7 * 86400, httponly=True,
        samesite="none" if config.APP_SECURE else "lax", secure=config.APP_SECURE,
    )
    return resp


def _has_registered(email: str, shop_name: str) -> bool:
    with SessionLocal() as db:
        return bool(db.query(User).filter((User.email == email) | (User.shop_name == shop_name)).first())


# ── 安装向导(管理员账号不通过注册,由本向导创建) ──
def _bool3(v: str | None):
    """三态布尔:空/None→None(跟随 .env),'1'/'true'→True,'0'/'false'→False"""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return None


# ── 安装向导(管理员账号不通过注册,由本向导创建;配置全部网页填写,自动写 .env) ──
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _db_ready() -> bool:
    """当前进程的 DB 引擎能否连通(即 .env 已配好并已重启加载)"""
    try:
        from sqlalchemy import text
        from .db import engine
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _env_has_db() -> bool:
    """.env 文件里是否已写入数据库配置(用于区分 待重启 步骤)"""
    try:
        if not os.path.exists(ENV_PATH):
            return False
        with open(ENV_PATH, "r", encoding="utf-8") as fh:
            content = fh.read()
        pwd = ""
        for line in content.splitlines():
            if line.strip().startswith("DB_PASSWORD="):
                pwd = line.split("=", 1)[1].strip()
        return bool(pwd) and "请改为" not in pwd and pwd != "DB_PASSWORD"
    except Exception:
        return False


def _write_env(host, port, user, pwd, name, app_secure=True) -> None:
    """将数据库/会话等运维配置写入项目 .env(由网页向导生成,无需用户手编)"""
    import secrets
    lines = [
        "# 本文件由安装向导自动生成,请勿手改;换机/迁移时随项目一起带走。",
        "DB_HOST=" + str(host or "127.0.0.1"),
        "DB_PORT=" + str(port or "3306"),
        "DB_USER=" + str(user or ""),
        "DB_PASSWORD=" + str(pwd or ""),
        "DB_NAME=" + str(name or ""),
        "SESSION_SECRET=" + secrets.token_hex(32),
        "APP_SECURE=" + ("true" if app_secure else "false"),
    ]
    with open(ENV_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


@router.get("/install")
def install_page(request: Request):
    if auth.is_installed():
        return RedirectResponse("/", status_code=302)
    if _db_ready():
        # DB 已可连 → 第 2 步:管理员 + 业务配置
        return render(request, "install.html", {"step": "step2", "error": "", "form": {}})
    if _env_has_db():
        # 已写好 .env 但尚未重启生效 → 提示重启
        return render(request, "install.html", {"step": "restart", "error": "", "form": {}})
    # 尚未配置 → 第 1 步:数据库连接 + 会话密钥
    return render(request, "install.html", {"step": "step1", "error": "", "form": {}})


@router.post("/install")
async def install_submit(request: Request):
    """安装向导 第1步:填写数据库连接并写入 .env(会话密钥自动生成)"""
    if auth.is_installed():
        return RedirectResponse("/", status_code=302)
    if _db_ready():
        return RedirectResponse("/install", status_code=302)  # 已进入第2步
    f = await request.form()
    host = str(f.get("DB_HOST", "")).strip()
    port = str(f.get("DB_PORT", "3306")).strip()
    name = str(f.get("DB_NAME", "")).strip()
    user = str(f.get("DB_USER", "")).strip()
    pwd = str(f.get("DB_PASSWORD", ""))
    error = ""
    if not (host and name and user and pwd):
        error = "请填写数据库连接的全部字段"
    if not error:
        try:
            import pymysql
            port_i = int(port or "3306")
            conn = pymysql.connect(host=host, port=port_i, user=user, password=pwd,
                                   database=name, connect_timeout=6)
            conn.close()
        except Exception as e:  # noqa: BLE001
            error = f"数据库连接测试失败: {e}"
    if error:
        return render(request, "install.html", {"step": "step1", "error": error,
                                                "form": {"DB_HOST": host, "DB_PORT": port,
                                                         "DB_NAME": name, "DB_USER": user}})
    try:
        _write_env(host, port, user, pwd, name)
    except Exception as e:  # noqa: BLE001
        return render(request, "install.html", {"step": "step1", "error": f"写入配置失败: {e}",
                                                "form": {"DB_HOST": host, "DB_PORT": port,
                                                         "DB_NAME": name, "DB_USER": user}})
    return render(request, "install.html", {"step": "restart", "error": "", "form": {}})


@router.post("/install/finish")
async def install_finish(request: Request):
    """安装向导 第2步:创建管理员 + 写业务配置 + 置 installed"""
    if auth.is_installed():
        return RedirectResponse("/", status_code=302)
    if not _db_ready():
        return render(request, "install.html", {"step": "restart", "error": "数据库尚未就绪,请先完成第1步并重启", "form": {}})
    f = await request.form()
    email = str(f.get("admin_email", "")).strip().lower()
    shop_name = str(f.get("admin_shop", "")).strip()
    password = str(f.get("admin_pwd", ""))
    confirm = str(f.get("admin_confirm", ""))
    form = {
        "email": email, "shop_name": shop_name,
        "app_base_url": str(f.get("app_base_url", "")).strip(),
        "consumer_account": str(f.get("consumer_account", "")).strip(),
        "platform_logo_url": str(f.get("platform_logo_url", "")).strip(),
        "smtp_host": str(f.get("smtp_host", "")).strip(),
        "smtp_port": str(f.get("smtp_port", "")).strip(),
        "smtp_user": str(f.get("smtp_user", "")).strip(),
        "smtp_from": str(f.get("smtp_from", "爱发电铺")).strip(),
    }
    error = ""
    if not valid_email(email):
        error = "邮箱格式不正确,仅支持 QQ / 163 邮箱"
    elif not valid_shop_name(shop_name):
        error = "店铺名仅支持中文/字母/数字,不含特殊符号,最长 12 字符"
    elif len(password) < 8:
        error = "管理员密码至少 8 位"
    elif password != confirm:
        error = "两次输入的密码不一致"
    if not error:
        # 写库前确保表结构就绪(从头开始自动建表)
        try:
            from .db import init_db
            init_db()
        except Exception as e:  # noqa: BLE001
            return render(request, "install.html", {"step": "step2", "error": f"数据库表初始化失败: {e}", "form": form})
        try:
            with SessionLocal() as db:
                if db.query(User).filter((User.email == email) | (User.shop_name == shop_name)).first():
                    error = "该邮箱或店铺名已被占用"
                else:
                    admin = User(
                        email=email, shop_name=shop_name,
                        password_hash=auth.hash_password(password),
                        role="admin", api_balance_cents=0,
                    )
                    db.add(admin)
                    db.commit()
                    db.refresh(admin)
                    # 管理员默认充值商品:标题「充值倍率」,SKU「1：1」,售价 10 元 → 到账 10 元(=1000 分)
                    try:
                        _ac = ProductCategory(merchant_id=admin.id, name="API充值",
                                              icon_url="", sort_order=0)
                        db.add(_ac)
                        db.flush()
                        db.add(Product(
                            merchant_id=admin.id, category_id=_ac.id,
                            title="充值倍率", sku_name="1：1", price=10,
                            is_recharge=True, recharge_grant_cents=1000, sort_order=0,
                        ))
                        db.commit()
                    except Exception:  # noqa: BLE001
                        db.rollback()
                    ps = platform_settings(db)
                    ps.installed = True
                    ps.app_base_url = str(f.get("app_base_url", "")).strip()
                    ps.afdian_live = _bool3(f.get("afdian_live"))  # ⚠️遗留字段:当前代码不读取,恒为 None
                    ps.consumer_account = str(f.get("consumer_account", "")).strip()
                    ps.consumer_password = str(f.get("consumer_password", "")).strip()
                    ps.platform_logo_url = str(f.get("platform_logo_url", "")).strip()
                    ps.smtp_host = str(f.get("smtp_host", "")).strip()
                    if str(f.get("smtp_port", "")).strip().isdigit():
                        ps.smtp_port = int(str(f.get("smtp_port", "")).strip())
                    ps.smtp_user = str(f.get("smtp_user", "")).strip()
                    ps.smtp_pass = str(f.get("smtp_pass", "")).strip()
                    ps.smtp_from = str(f.get("smtp_from", "爱发电铺")).strip()
                    db.commit()
                    token = auth.sign_token(admin)
                    resp = RedirectResponse("/console/dashboard", status_code=302)
                    resp.set_cookie(
                        auth.COOKIE_NAME, token, max_age=7 * 86400, httponly=True,
                        samesite="none" if config.APP_SECURE else "lax", secure=config.APP_SECURE,
                    )
                    return resp
        except Exception as e:  # noqa: BLE001
            error = f"写入失败: {type(e).__name__}: {e}"
    return render(request, "install.html", {"step": "step2", "error": error, "form": form})



@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", {"error": ""})


@router.post("/login")
async def login(request: Request):
    f = await request.form()
    account = str(f.get("account", "")).strip()
    password = str(f.get("password", ""))
    if not account or not password:
        return render(request, "login.html", {"error": "请输入账号和密码"})

    identifier = _client_ip(request)  # 登录失败锁定:按客户端 IP,而非账号
    left = auth.lock_remaining(identifier)
    if left > 0:
        return render(request, "login.html", {"error": f"登录失败次数过多,请 {left} 秒后重试"})

    with SessionLocal() as db:
        user = (
            db.query(User)
            .filter((User.email == account.lower()) | (User.shop_name == account))
            .first()
        )
    if not user or not auth.verify_password(password, user.password_hash):
        locked, sec, fails = auth.record_fail(identifier)
        error = f"登录失败次数过多,已锁定 {sec} 秒" if locked else f"账号或密码错误({fails}/5,5 分钟内失败 5 次将锁定 5 分钟)"
        return render(request, "login.html", {"error": error})
    if user.status != "active":
        return render(request, "login.html", {"error": "该账号已注销停用,无法登录;请联系管理员启用"})

    auth.clear_lock(identifier)
    token = auth.sign_token(user)
    resp = RedirectResponse("/console/dashboard", status_code=302)
    resp.set_cookie(
        auth.COOKIE_NAME, token, max_age=7 * 86400, httponly=True,
        samesite="none" if config.APP_SECURE else "lax", secure=config.APP_SECURE,
    )
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ── 忘记密码 / 重置 ──
@router.get("/forgot")
def forgot_page(request: Request):
    return render(request, "forgot.html", {"sent": False, "demoUrl": "", "email": "", "error": ""})


@router.post("/forgot")
async def forgot(request: Request):
    f = await request.form()
    email = str(f.get("email", "")).strip().lower()
    if not valid_email(email):
        return render(request, "forgot.html", {"sent": False, "demoUrl": "", "email": email, "error": "仅支持 QQ / 163 邮箱"})
    demo_url = ""
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return render(request, "forgot.html", {"sent": False, "demoUrl": "", "email": email, "error": "该邮箱未注册,请检查后重试"})
        db.query(PasswordReset).filter(PasswordReset.email == email).delete()  # 旧链接立即失效
        token = auth.random_token()
        db.add(PasswordReset(email=email, token=token, expires_at=datetime.now() + timedelta(minutes=10)))
        db.commit()
        url = f"{settings.app_base_url()}/reset/{token}"
        mailer.send(email, "【爱发电铺】重置密码链接(10分钟有效)", email_templates.reset_password_html(email, url))
        if mailer.demo_mode():
            demo_url = url
    return render(request, "forgot.html", {"sent": True, "demoUrl": demo_url, "email": email, "error": ""})


@router.get("/reset/{token}")
def reset_page(request: Request, token: str):
    return render(request, "reset.html", {"token": token, "error": "", "done": False})


@router.post("/reset/{token}")
async def reset(request: Request, token: str):
    f = await request.form()
    password = str(f.get("password", ""))
    confirm = str(f.get("confirm", ""))
    if len(password) < 8:
        return render(request, "reset.html", {"token": token, "error": "新密码至少 8 位", "done": False})
    if password != confirm:
        return render(request, "reset.html", {"token": token, "error": "两次输入的密码不一致", "done": False})
    with SessionLocal() as db:
        row = db.query(PasswordReset).filter(PasswordReset.token == token).first()
        if not row or row.expires_at < datetime.now():
            return render(request, "reset.html", {"token": token, "error": "重置链接已失效,请重新申请(链接 10 分钟有效)", "done": False})
        user = db.query(User).filter(User.email == row.email).first()
        if not user:
            return render(request, "reset.html", {"token": token, "error": "账号不存在", "done": False})
        user.password_hash = auth.hash_password(password)
        db.query(PasswordReset).filter(PasswordReset.id == row.id).delete()
        db.commit()
        new_token = auth.sign_token(user)  # 提交即已登录
    resp = render(request, "reset.html", {"token": token, "error": "", "done": True})
    resp.set_cookie(
        auth.COOKIE_NAME, new_token, max_age=7 * 86400, httponly=True,
        samesite="none" if config.APP_SECURE else "lax", secure=config.APP_SECURE,
    )
    return resp


# ── 使用说明 / 开放接口 / 公开小接口 ──
# 注意:FastAPI 框架内置 /docs(OpenAPI Swagger)、/redoc、/openapi.json,勿占用这些路径。
@router.get("/mail-preview/verify")
async def mail_preview_verify_public():
    """验证码邮件模板在线预览(仅返回固定样例 HTML,不含任何私密信息)"""
    from fastapi.responses import HTMLResponse as _h
    html = verification._html("123456", "请在需要验证邮箱的操作中填写;如非本人操作可忽略")
    return _h(content=html)


@router.get("/guide")
def guide(request: Request):
    admin_email = auth.first_admin_email() or ""
    preview_uid = ""
    try:
        with SessionLocal() as db:
            adm = db.query(User).filter(User.role == "admin").order_by(User.id).first()
            if adm:
                preview_uid = (adm.afdian_user_id or "").strip()
    except Exception:
        preview_uid = ""
    return render(request, "docs.html", {"adminEmail": admin_email, "previewShopUid": preview_uid})


@router.get("/api-docs")
def api_docs(request: Request):
    return render(request, "openapi.html", {"api_base": settings.app_base_url() or str(request.base_url).rstrip("/")})


# ── 自助提货(无需登录)──────────────────────────────────────
# 仅凭订单号查询;3 QPS/IP 限流;同一订单始终返回同一份内容(幂等)。
_pickup_hits: dict[str, list] = {}


def _pickup_rate_ok(ip: str, limit: int = 3, window: float = 1.0) -> bool:
    """简单滑动窗口限流:每 window 秒最多 limit 次"""
    import time as _t
    now = _t.time()
    arr = [x for x in _pickup_hits.get(ip, []) if now - x < window]
    if len(arr) >= limit:
        _pickup_hits[ip] = arr
        return False
    arr.append(now)
    _pickup_hits[ip] = arr
    if len(_pickup_hits) > 5000:  # 防止字典无限增长
        _pickup_hits.clear()
    return True


@router.get("/pickup")
def pickup_page(request: Request):
    """自助提货页(无需登录)。返回按钮默认指向管理员店铺,查询成功后由前端改为订单所属店铺。"""
    fallback = "/"
    try:
        with SessionLocal() as db:
            adm = db.query(User).filter(User.role == "admin").order_by(User.id).first()
            if adm and (adm.afdian_user_id or "").strip():
                fallback = "/shop/" + adm.afdian_user_id.strip()
    except Exception:  # noqa: BLE001
        fallback = "/"
    return render(request, "pickup.html", {"fallback_shop_url": fallback})


@router.get("/api/pickup")
def api_pickup(request: Request):
    """提货查询:GET /api/pickup?order_no=xxx  (无需登录)"""
    ip = _client_ip(request)
    if not _pickup_rate_ok(ip):
        return err("查询过于频繁,请稍后再试", 429)
    order_no = (request.query_params.get("order_no") or "").strip()
    if not order_no:
        return err("请填写订单号")
    if len(order_no) > 64:
        return err("订单号格式不正确")
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.order_no == order_no).first()
        if not order:
            return err("订单号不存在,请核对后重试", 404)
        if order.status != "paid":
            return err("该订单尚未支付,支付成功后即可提货", 403)
        info = delivery.ensure_delivery(db, order)
        db.commit()
        merchant = db.get(User, order.merchant_id)
        return {
            "ok": True,
            "order": {
                "order_no": order.order_no,
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
                "paid_at": order.paid_at.strftime("%Y-%m-%d %H:%M:%S") if order.paid_at else "",
                "category": order.category,
                "title": order.title,
                "sku": order.sku,
                "total": order.total,
                "channel": "微信" if order.channel == "wechat" else "支付宝",
                "shop_name": merchant.shop_name if merchant else "",
                "shop_uid": (merchant.afdian_user_id if merchant else "") or "",
            },
            "delivery": {
                "kind": info.get("kind") or "",
                "content": info.get("content") or "",
                "tip": info.get("tip") or "",
                "needs_manual": bool(info.get("needs_manual")),
            },
            "contact": (auth.first_admin_email() or ""),
            "merchant_email": (merchant.email if merchant else "") or "",
        }


@router.get("/api/order/query")
def api_order_query(request: Request):
    """商户查询订单数据(供外部程序发放权益):传 商户邮箱 + 订单号,仅返回已支付订单。
    返回 {ok, data:{order_id, creat_time, type, title, sku, total, seller}}。"""
    email = (request.query_params.get("email") or "").strip().lower()
    order_no = (request.query_params.get("order_no") or "").strip()
    if not email or not order_no:
        return err("缺少参数 email / order_no")
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            return err("商户不存在", 404)
        order = db.query(Order).filter(Order.order_no == order_no, Order.merchant_id == u.id).first()
        if not order:
            return err("订单不存在", 404)
        if order.status != "paid":
            return err("订单未支付", 403)
        _paid = ""
        if order.paid_at:
            _paid = order.paid_at.strftime("%Y-%m-%d %H:%M:%S")
        elif order.created_at:
            _paid = order.created_at.strftime("%Y-%m-%d %H:%M:%S")
        data = {
            "order_id": order.order_no,
            "creat_time": _paid,
            "type": order.category,
            "title": order.title,
            "sku": order.sku,
            "total": order.total,
            "seller": u.afdian_user_id or str(u.id),
        }
    return {"ok": True, "data": data}


@router.get("/api/support")
def support():
    return {"ok": True, "email": auth.first_admin_email()}


@router.get("/api/shops")
def shops():
    with SessionLocal() as db:
        rows = (
            db.query(User)
            .filter(User.status == "active", User.afdian_user_id != "")
            .order_by(User.id)
            .all()
        )
        out = []
        for u in rows:
            count = db.query(Product.id).filter(Product.merchant_id == u.id, Product.is_recharge == False).count()  # noqa: E712
            out.append({
                "shop_name": u.shop_name, "shop_logo_url": u.shop_logo_url,
                "bio": u.bio, "afdian_user_id": u.afdian_user_id, "product_count": count,
            })
    return {"ok": True, "shops": out}


@router.get("/api/products")
def api_products(request: Request):
    """商户在售商品列表(供外部程序获取 product_id)。传 uid(爱发电 user_id) / shop(店铺名) / email(商户邮箱) 三选一。
    返回 {ok, shop_name, afdian_user_id, products:[{id, category, title, sku_name, price}]}。"""
    uid = (request.query_params.get("uid") or "").strip()
    shop = (request.query_params.get("shop") or "").strip()
    email = (request.query_params.get("email") or "").strip().lower()
    if not uid and not shop and not email:
        return err("缺少参数: uid(爱发电 user_id) / shop(店铺名) / email(商户邮箱),三选一")
    with SessionLocal() as db:
        q = db.query(User).filter(User.status == "active")
        if uid:
            q = q.filter(User.afdian_user_id == uid)
        elif shop:
            q = q.filter(User.shop_name == shop)
        else:
            q = q.filter(User.email == email)
        u = q.first()
        if not u:
            return err("未找到该店铺(需已绑定爱发电且状态正常)", 404)
        rows = (
            db.query(Product, ProductCategory)
            .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
            .filter(Product.merchant_id == u.id, Product.is_recharge == False)  # noqa: E712
            .order_by(ProductCategory.sort_order, Product.sort_order, Product.id)
            .all()
        )
        items = [
            {"id": p.id, "category": (c.name if c else ""), "title": p.title,
             "sku_name": p.sku_name, "price": p.price}
            for p, c in rows
        ]
    return {"ok": True, "shop_name": u.shop_name, "afdian_user_id": u.afdian_user_id, "products": items}


# ── 消费者店铺页 ──
@router.get("/shop/{uid}")
def shop_page(request: Request, uid: str):
    with SessionLocal() as db:
        merchant = db.query(User).filter(User.afdian_user_id == uid).first()
        if not merchant:
            return render(request, "shop.html", {"notFound": True})
        s = platform_settings(db)
        _me = getattr(request.state, "me", None)
        _admin_email = auth.first_admin_email() or ""
        ctx = {
            "notFound": False,
            "shop": merchant,
            "isOwner": bool(_me and _me.id == merchant.id),
            "adminEmail": _admin_email,
            "shop_logo_ok": bool((merchant.shop_logo_url or "").strip()),
            "disabled": merchant.status != "active",
            "platformLogo": s.platform_logo_url,
            "payMethods": {
                "wechat": {"enabled": bool(s.wechat_enabled), "note": s.wechat_disabled_note},
                "alipay": {"enabled": bool(s.alipay_enabled), "note": s.alipay_disabled_note},
            },
            "groups": [],
        }
        if merchant.status == "active":
            _cat_rows = (
                db.query(ProductCategory)
                .filter(ProductCategory.merchant_id == merchant.id)
                .order_by(ProductCategory.sort_order, ProductCategory.id)
                .all()
            )
            goods = (
                db.query(Product, ProductCategory)
                .outerjoin(ProductCategory, ProductCategory.id == Product.category_id)
                .filter(Product.merchant_id == merchant.id, Product.is_recharge == False)  # noqa: E712
                .order_by(ProductCategory.sort_order, Product.sort_order, Product.id)
                .all()
            )
            grouped: dict[str, list] = {}
            _lim_products = []
            for g, c in goods:
                _cname = c.name if c else ""
                _is_card = delivery.is_card_type(g)
                if delivery.is_limited(g):
                    _lim_products.append(g)
                grouped.setdefault(_cname, []).append({
                    "id": g.id, "category": _cname, "title": g.title,
                    "sku_name": g.sku_name, "price": g.price,
                    "delivery_kind": (g.delivery_kind if g.delivery_type == "platform" else "") or "",
                    "is_card": _is_card,
                    "is_limited": bool(delivery.is_limited(g)),
                    "stock": 0,  # 下面按需填充
                    "_sort": g.sort_order,
                })
            # 卡密型 SKU:批量取可售库存(0 则前台显示缺货、不可购买)
            _card_ids = [x["id"] for _c, lst in grouped.items() for x in lst if x.get("is_card")]
            if _card_ids:
                _smap = delivery.stock_map(db, _card_ids)
                for _c, lst in grouped.items():
                    for x in lst:
                        if x.get("is_card"):
                            x["stock"] = int(_smap.get(x["id"], 0))
            # 限购类(商户发货/链接发货设了上限):批量算剩余可售量
            if _lim_products:
                _lmap = delivery.limited_left_map(db, _lim_products)
                for _c, lst in grouped.items():
                    for x in lst:
                        if x.get("is_limited"):
                            x["stock"] = int(_lmap.get(x["id"], 0))
            # 分类顺序已由 SQL 按 product_categories.sort_order 排好(保持插入顺序)
            _items = list(grouped.items())
            for _lst in grouped.values():
                for _x in _lst:
                    _x.pop("_sort", None)
            ctx["groups"] = _items
            # 分类图标(前台分类目录用)
            ctx["cat_icon"] = {c.name: (c.icon_url or "") for c in _cat_rows}
    from .auth import current_user as _shop_user
    _cu = None
    try:
        _cu = _shop_user(request)
    except Exception:  # noqa: BLE001
        _cu = None
    ctx["shop_is_admin"] = bool(_cu is not None and getattr(_cu, "role", "") == "admin")
    return render(request, "shop.html", ctx)


@router.post("/shop/buy")
async def shop_buy(request: Request):
    body = await request.json()
    product_id = int(body.get("product_id", 0))
    channel = body.get("channel", "")
    buyer_email = str(body.get("buyer_email", "") or "").strip().lower()[:120]
    if not product_id:
        return err("请选择商品")
    if channel not in ("wechat", "alipay"):
        return err("请选择付款方式(微信/支付宝)")
    if buyer_email and not valid_email(buyer_email):
        return err("收货邮箱格式不正确")

    with SessionLocal() as db:
        s = platform_settings(db)
        if channel == "wechat" and not s.wechat_enabled:
            return err(s.wechat_disabled_note or "微信支付暂不可用", 403)
        if channel == "alipay" and not s.alipay_enabled:
            return err(s.alipay_disabled_note or "支付宝暂不可用", 403)
        if not s.consumer_account or not s.consumer_password:
            return err("平台尚未配置爱发电(消费者)账号,暂无法创建订单", 503)

        product = db.get(Product, product_id)
        if not product or product.is_recharge:
            return err("商品不存在", 404)
        _cat_row = db.get(ProductCategory, product.category_id)
        _cat_name = _cat_row.name if _cat_row else ""
        merchant = db.get(User, product.merchant_id)
        if not merchant or merchant.status != "active":
            return err("店铺已停用", 403)
        if not merchant.is_afdian_configured():
            return err("商户尚未完成爱发电绑定,暂无法下单", 503)

        # 余额检查:<单次API费用 拦截并邮件提醒;<阈值 仅提醒
        if merchant.api_balance_cents < settings.api_fee_cents():
            notified = pipeline.notify_low_balance(merchant.id)
            return err(
                "该店铺 API 费用余额不足,暂无法下单(已邮件提醒商户充值)" if notified
                else "该店铺 API 费用余额不足,暂无法下单", 403,
            )
        if merchant.api_balance_cents < merchant.balance_threshold_cents:
            pipeline.notify_low_balance(merchant.id)

        # 平台发货·卡密:下单前先看库存,为 0 直接拒(前台已置灰,此处双保险)
        _card_delivery = delivery.is_card_type(product)
        if _card_delivery and delivery.stock_count(db, product.id) <= 0:
            return err("该商品已缺货,暂无法购买", 409)
        # 商户发货/链接发货的「限购总量」:卖完(已付款数达上限)即拒
        if delivery.is_limited(product) and delivery.limited_left(db, product) <= 0:
            return err("该商品已售罄,暂无法购买", 409)

        remark = f"{_cat_name}&{product.title}&{product.sku_name}&{product.price}"
        # 无人自动化下单:自动取/续登消费者 token;token 失效会自动重登再试
        pay_type = (afd_live.PAY_TYPES.get(channel) or {}).get("py_type", "wpy_qr")
        r = afd_live.live_create_auto(merchant.afdian_user_id, product.price, remark, pay_type)
        if not r.get("ok"):
            return err(f"下单失败: {r.get('message') or '未知错误'}", 503 if r.get("source") == "fail" else 500)
        _d = r.get("data") or {}
        order_no = str(_d.get("out_trade_no") or "")
        qr = _d.get("redirect_url") or ""
        if not order_no:
            return err("下单失败:爱发电未返回订单号", 500)
        db.add(Order(
            order_no=order_no, product_id=product.id, merchant_id=merchant.id,
            category=_cat_name, title=product.title, sku=product.sku_name,
            total=product.price, channel=channel, remark=remark,
            buyer_account=s.consumer_account, buyer_email=buyer_email,
            status="pending", created_at=datetime.now(),
        ))
        # 平台发货·卡密:下单即锁定一个卡密(未付款 3 小时后清单时释放回库存)
        if _card_delivery and not delivery.lock_card(db, product.id, order_no):
            db.rollback()
            return err("该商品已缺货,暂无法购买", 409)
        db.commit()
        # 统计:创建订单数(独立累计,不会因过期未付单被清理而减少)
        try:
            pipeline.bump_order_stat(merchant.id, created=1)
        except Exception:  # noqa: BLE001
            pass
        # 惰性清理:每次创建订单顺带删一次过期未付,不放定时器
        try:
            pipeline.gc_stale_pending()
        except Exception:  # noqa: BLE001
            pass
    return JSONResponse({"ok": True, "orderNo": order_no, "qrPayload": qr, "total": product.price}, status_code=201)


@router.get("/shop/poll/{order_no}")
def shop_poll(order_no: str):
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        return err("订单不存在", 404)
    if order.status == "paid":
        return {"ok": True, "status": "paid", "paidAt": str(order.paid_at or "")}
    # 无人工单:自动取/续登消费者 token,失效自动重登
    r = afd_live.live_check_auto(order_no)
    if r.get("ok") and r.get("paid"):
        pipeline.mark_order_paid(order_no)
        return {"ok": True, "status": "paid",
                "paidAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return {"ok": True, "status": "pending"}


# ── 爱发电 Webhook 回调(页面无关收单)────────────────────────────
# 你方在爱发电开发者后台把「Webhook URL」配成下面地址(真实部署域名随之拼):
#   https://你的域名/api/afdian/webhook
# 爱发电推送任何“订单支付”都会 POST 到这里;按订单 out_trade_no 复用幂等
# pipeline.mark_order_paid -> 自动写库/扣 API 费/发商户 Webhook 与邮件,防重复。
# 消费者页面关闭/刷新/离开都不影响本收单(前端轮询无论先到后到都幂等)。

def _webhook_find_order_no(payload) -> str:
    """递归在回调 JSON 中找订单号(out_trade_no/order_no),优先键名最长的 out_trade_no。"""
    found = []
    stack = [payload]
    visited = set()
    while stack:
        cur = stack.pop()
        if id(cur) in visited:
            continue
        visited.add(id(cur))
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in ("out_trade_no", "trade_no", "order_no", "orderId") and isinstance(v, str) and v.strip():
                    found.append(str(v).strip())
                elif isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            for it in cur:
                stack.append(it)
    if not found:
        return ""
    # 官方字段为 out_trade_no,优先;其次任意出现的最早
    for p in ("out_trade_no", "trade_no", "order_no", "orderId"):
        for v in found:
            if p == "out_trade_no":
                return v
    return found[0]


@router.post("/api/afdian/webhook")
async def afdian_webhook(request: Request):
    """接受爱发电订单支付回调(push),先记一条调试日志,再把它翻成幂等 mark。"""
    raw = {}
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        try:
            form = await request.form()
            raw = dict(form)
        except Exception:  # noqa: BLE001
            raw = {}
    order_no = _webhook_find_order_no(raw)
    # 调试日志:原始推送 + 命中与否(开发者要在「哪里看回调」就是看这里)
    import json as _json
    from . import db as _db
    try:
        with SessionLocal() as xdb:
            exists = xdb.query(_db.Order).filter(_db.Order.order_no == order_no).first() if order_no else None
            xdb.add(_db.AfdianWebhookLog(
                body_text=_json.dumps(raw, ensure_ascii=False)[:12000] if raw is not None else "",
                order_no=order_no or "",
                matched=bool(exists),
            ))
            xdb.commit()
    except Exception:  # noqa: BLE001
        pass
    # 惰性清理:收到回调便顺手删一次过期未付款(不等待/不做定时器)
    try:
        pipeline.gc_stale_pending()
    except Exception:  # noqa: BLE001
        pass
    if not order_no:
        # 持续回 ec=200 防平台重推(记录仍在,方便你比对「空的测试事件」)
        return JSONResponse({"ec": 200, "em": "ack(空事件)"})
    # 幂等:已 paid 会直接早退;未 paid 会写成交并触发商户回调通知一次
    pipeline.mark_order_paid(order_no)
    return JSONResponse({"ec": 200, "em": "ok"})
