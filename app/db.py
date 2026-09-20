"""SQLAlchemy 引擎与数据表"""
import json
from datetime import datetime

from sqlalchemy import (Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

DATABASE_URL = (
    f"mysql+pymysql://{config.DB_USER}:{config.DB_PASSWORD}"
    f"@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}?charset=utf8mb4"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(120), unique=True, nullable=False)
    shop_name = Column(String(36), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False, default="merchant")  # admin|merchant
    status = Column(String(16), nullable=False, default="active")  # active|disabled
    afdian_user_id = Column(String(120), nullable=False, default="")
    afdian_token = Column(String(255), nullable=False, default="")
    shop_logo_url = Column(String(500), nullable=False, default="")
    bio = Column(String(600), nullable=False, default="")
    qq = Column(String(40), nullable=False, default="")       # 商家 QQ(前台店铺展示)
    wechat = Column(String(60), nullable=False, default="")   # 商家微信(前台店铺展示)
    webhook_url = Column(String(500), nullable=False, default="")
    webhook_method = Column(String(8), nullable=False, default="post")  # post|get
    webhook_encode = Column(String(12), nullable=False, default="raw")  # raw|form|field
    webhook_headers = Column(String(1000), nullable=False, default="")  # 自定义请求头,多行 k: v
    webhook_params = Column(String(500), nullable=False, default="")  # 自定义查询参数,多行 k=v
    webhook_body = Column(String(2000), nullable=False, default="")  # 附加自定义字段 JSON(并入订单 payload)即自定义请求体(GET/POST 附加到 URL)
    email_notify = Column(Boolean, nullable=False, default=True)
    balance_notify = Column(Boolean, nullable=False, default=True)
    api_balance_cents = Column(Integer, nullable=False, default=0)
    balance_threshold_cents = Column(Integer, nullable=False, default=100)
    last_balance_notify_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    def is_afdian_configured(self) -> bool:
        return bool(self.afdian_user_id and self.afdian_token)


class PasswordReset(Base):
    __tablename__ = "password_resets"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(120), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class VerificationCode(Base):
    __tablename__ = "verification_codes"
    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(120), nullable=False, index=True)
    code = Column(String(8), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    last_sent_at = Column(DateTime, nullable=False, default=datetime.now)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class LoginLock(Base):
    __tablename__ = "login_locks"
    identifier = Column(String(120), primary_key=True)
    fail_count = Column(Integer, nullable=False, default=0)
    window_started_at = Column(DateTime, nullable=False, default=datetime.now)
    locked_until = Column(DateTime, nullable=True)


class ProductCategory(Base):
    """店铺分类(独立表,与 SKU 解耦)。

    分类的「名称/图标/排序」都在本表;商品用 products.category_id 关联本表 id,
    因此改名/换图标只需改这一行,不必触碰商品行。
    服务层见 app/services/categories.py。
    """
    __tablename__ = "product_categories"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    name = Column(String(60), nullable=False)               # 分类名(与 Product.category 对应)
    icon_url = Column(String(500), nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    # 分类改为外键关联 product_categories.id(不再存分类名字符串与图标)
    category_id = Column(Integer, nullable=False, default=0, index=True)
    title = Column(String(180), nullable=False)
    sku_name = Column(String(180), nullable=False)
    price = Column(Integer, nullable=False)  # 元,≥5
    is_recharge = Column(Boolean, nullable=False, default=False)
    recharge_grant_cents = Column(Integer, nullable=False, default=0)
    sort_order = Column(Integer, nullable=False, default=0)  # 后台拖拽排序(同分类内/全局)
    # 发货方式(SKU 级):merchant=商户自行发货(默认) | platform=平台发货
    delivery_type = Column(String(16), nullable=False, default="merchant")
    # 平台发货时的类型:"" | card(卡密) | link(链接)
    delivery_kind = Column(String(16), nullable=False, default="")
    delivery_link = Column(String(1000), nullable=False, default="")   # kind=link 时的内容
    delivery_tip = Column(String(500), nullable=False, default="")     # 提货页给买家的说明(可选)
    # 商户发货/链接发货的「限购总量」:0=不限量;>0 时可售数量=stock_limit-已付款单数(卖完即缺货)
    stock_limit = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(64), unique=True, nullable=False)
    product_id = Column(Integer, nullable=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    category = Column(String(60), nullable=False)
    title = Column(String(180), nullable=False)
    sku = Column(String(180), nullable=False)
    total = Column(Integer, nullable=False)  # 元
    channel = Column(String(16), nullable=False, default="wechat")
    remark = Column(String(500), nullable=False, default="")
    buyer_account = Column(String(120), nullable=False, default="")
    buyer_email = Column(String(120), nullable=False, default="")   # 下单时选填,仅用于付款后发卡邮件
    status = Column(String(16), nullable=False, default="pending")  # pending|paid
    paid_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)                  # 卡密/链接发放时间
    recharge_for_id = Column(Integer, nullable=True)
    recharge_grant_cents = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)


class FeeLedger(Base):
    __tablename__ = "fee_ledger"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    order_id = Column(Integer, nullable=True)
    delta_cents = Column(Integer, nullable=False)
    balance_after_cents = Column(Integer, nullable=False)
    reason = Column(String(24), nullable=False, default="order_fee")
    note = Column(String(255), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    installed = Column(Boolean, nullable=False, default=False)  # 安装向导完成后置 True
    consumer_account = Column(String(120), nullable=False, default="")
    consumer_password = Column(String(255), nullable=False, default="")
    consumer_auth_token = Column(String(191), nullable=False, default="")  # 爱发电网页会话 auth_token(登录持久化)
    consumer_token_at = Column(DateTime, nullable=True)  # 上次成功登录拿到 auth_token 的时间(供失效判断)
    platform_logo_url = Column(String(500), nullable=False, default="")
    wechat_enabled = Column(Boolean, nullable=False, default=True)
    wechat_disabled_note = Column(String(255), nullable=False, default="")
    alipay_enabled = Column(Boolean, nullable=False, default=True)
    alipay_disabled_note = Column(String(255), nullable=False, default="")
    # 安装向导/后台可填写的业务配置(空则回退 .env 环境变量)
    app_base_url = Column(String(300), nullable=False, default="")
    afdian_live = Column(Boolean, nullable=True)  # ⚠️遗留:代码已不读取(None=跟随 .env);保留列以兼容旧库,勿删
    enable_preview_login = Column(Boolean, nullable=True)  # None=跟随 .env
    smtp_host = Column(String(120), nullable=False, default="")
    smtp_port = Column(Integer, nullable=True)
    smtp_user = Column(String(120), nullable=False, default="")
    smtp_pass = Column(String(255), nullable=False, default="")
    smtp_from = Column(String(120), nullable=False, default="")
    api_fee_cents = Column(Integer, nullable=True, default=None)  # 单次API费用(分);NULL=用 .env FEE_PER_ORDER_CENTS
    allowed_email_domains = Column(String(600), nullable=False, default="")  # 注册允许邮箱域名,;分隔(仅后端/个人中心维护),空=不限制
    webhook_base_url = Column(String(300), nullable=False, default="")  # 爱发电 Webhook 平台外部域名,空=用当前访问域名;只作入口域名展示/拼接参考
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class Notice(Base):
    """平台通知(管理员发布,商户控制台弹窗/铃铛查看)"""
    __tablename__ = "notices"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    content = Column(String(2000), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class UserProgress(Base):
    """通用云端进度(跨设备):user_id+key 存一段 JSON 字符串。
    key 常取 tasks / notices_seen / milestones / tours 等各业务自行解析。"""
    __tablename__ = "user_progress"
    __table_args__ = (
        # 同一 user+key 仅一行
        UniqueConstraint("user_id", "pkey", name="uq_user_progress_user_pkey"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    pkey = Column(String(64), nullable=False)
    value = Column(Text, nullable=False, default="{}")  # JSON 文本
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class WebhookSend(Base):
    """平台向商户 Webhook 发送的回调记录(订单通知),供商户查看历史与响应。"""
    __tablename__ = "webhook_sends"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    order_no = Column(String(64), nullable=False, default="")
    url = Column(String(500), nullable=False, default="")
    method = Column(String(8), nullable=False, default="POST")
    status_code = Column(Integer, nullable=False, default=0)
    ok = Column(Boolean, nullable=False, default=False)
    is_test = Column(Boolean, nullable=False, default=False)  # 发送测试标记(非真实订单回调)
    resp_head = Column(Text)
    resp_body = Column(Text)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class StockCard(Base):
    """卡密库存(SKU 级)。

    生命周期:下单即锁定(locked=1, order_no=订单号) → 付款成功(used_at=付款时间)
    → 若订单 3 小时未付款被清理,则释放回库存(locked=0, order_no='')。
    库存数 = 该 product_id 下 locked=0 且 used_at IS NULL 的行数。
    """
    __tablename__ = "stock_cards"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=False, index=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)                 # 单行卡密
    locked = Column(Boolean, nullable=False, default=False, index=True)  # 被订单锁定(含未付款)
    order_no = Column(String(64), nullable=False, default="")            # 锁它的订单号
    locked_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)              # 付款成功时间;NULL=未售出
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class DeliveryRecord(Base):
    """发放记录(提货幂等核心)。

    order_no 唯一:同一订单无论查询多少次,都返回同一条记录的内容。
    kind: card(卡密) | link(链接)
    """
    __tablename__ = "delivery_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(64), unique=True, nullable=False, index=True)
    product_id = Column(Integer, nullable=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(16), nullable=False, default="")   # card | link
    content = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class OrderStat(Base):
    """订单创建计数(按商户+日期累计)。

    为什么单独存:未支付订单超过 3 小时会被物理清理,若直接统计 orders 表,
    「创建订单数」会随清理而变小。此表只增不减,保证统计口径稳定。
    """
    __tablename__ = "order_stats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(Integer, nullable=False, index=True)
    day = Column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    created_count = Column(Integer, nullable=False, default=0)
    paid_count = Column(Integer, nullable=False, default=0)
    paid_amount = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class AfdianWebhookLog(Base):
    """收到爱发电的回调原始记录,用于「回调测试/哪能看到」调试验证。"""
    __tablename__ = "afdian_webhook_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    body_text = Column(Text, nullable=False)          # 收到的原始 JSON
    order_no = Column(String(100), nullable=False, default="")
    matched = Column(Boolean, nullable=False, default=False)  # 是否命中库内 Order
    created_at = Column(DateTime, nullable=False, default=datetime.now)


def platform_settings(db) -> PlatformSetting:
    """单行平台配置(不存在自动创建)"""
    row = db.query(PlatformSetting).order_by(PlatformSetting.id).first()
    if row is None:
        row = PlatformSetting()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def init_db() -> None:
    """启动时幂等建表(也可手工导入 database/schema.sql)。

    注意:多 worker(gunicorn/uvicorn --workers)同时启动会并发执行建表,
    可能撞到 "Table already exists"(1050) / "Duplicate key name"(1061);
    这属于幂等竞态,应忽略而不是让整个 create_all 中断(否则后续表可能漏建)。
    """
    try:
        Base.metadata.create_all(engine)
    except Exception as e:  # noqa: BLE001
        code = getattr(getattr(e, "orig", None), "args", [None])[0]
        if code in (1050, 1061):  # 表已存在 / 索引已存在
            import logging
            logging.getLogger("afdianpu").info("init_db: 表/索引已存在,跳过 (code=%s)", code)
            return
        raise


def _wh_pairs(value, sep):
    """把 webhook 配置字段归一为多行 'k`sep`v' 文本。
    value 可为: 多行文本(k:v / k=v 等) 或 JSON 数组 [[k,v],..]。"""
    if value is None:
        return ""
    value = str(value).strip()
    if not value:
        return ""
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            lines = []
            for pair in parsed:
                if not isinstance(pair, (list, tuple)) or len(pair) < 1:
                    continue
                k = str(pair[0]).strip()
                v = str(pair[1]) if len(pair) > 1 else ""
                lines.append(k + sep + " " + v if v else k)
            return "\n".join(lines)
    except Exception:
        pass
    # 已是多行文本
    return value
