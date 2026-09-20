"""支付成功流水线 + 余额规则
① 充值订单:买家(充值商户)增加余额
② 卖家扣 ¥0.20 服务费并写流水
③ Webhook 回调(JSON 键与约定一致)
④ 卡片式邮件通知
"""
import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from .. import config
from .. import settings as _settings
from ..db import FeeLedger, Order, OrderStat, SessionLocal, User, WebhookSend
from . import email_templates, mailer
from . import delivery

log = logging.getLogger("afdianpu.pipeline")
FEE_PER_ORDER_CENTS = config.FEE_PER_ORDER_CENTS


def fee_cents() -> int:
    """当前单次 API 费用(分):管理台可调"""
    try:
        return _settings.api_fee_cents()
    except Exception:
        return int(config.FEE_PER_ORDER_CENTS)


def bump_order_stat(merchant_id: int, created: int = 0, paid: int = 0, amount: int = 0):
    """累计订单统计(按商户+当天)。独立于 orders 表,故未付单被清理后统计仍保留。"""
    if not merchant_id:
        return
    from datetime import date as _date
    _day = _date.today().strftime("%Y-%m-%d")
    try:
        with SessionLocal() as db:
            row = db.query(OrderStat).filter(
                OrderStat.merchant_id == merchant_id, OrderStat.day == _day
            ).first()
            if row is None:
                row = OrderStat(merchant_id=merchant_id, day=_day,
                                created_count=0, paid_count=0, paid_amount=0)
                db.add(row)
            row.created_count = int(row.created_count or 0) + int(created or 0)
            row.paid_count = int(row.paid_count or 0) + int(paid or 0)
            row.paid_amount = int(row.paid_amount or 0) + int(amount or 0)
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("bump_order_stat failed")


def mark_order_paid(order_no: str):
    """幂等:订单标记已支付并执行流水线"""
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.order_no == order_no).first()
        if not order:
            return None
        if order.status == "paid":
            return order
        paid_at = datetime.now()
        order.status = "paid"
        order.paid_at = paid_at
        paid_at_str = paid_at.strftime("%Y-%m-%d %H:%M:%S")
        _stat_merchant = order.merchant_id
        _stat_amount = order.total or 0

        # ⓪ 平台发货:核销卡密 + 写发放记录(提货页据此幂等返回同一内容)
        _deliv = None
        try:
            delivery.mark_paid(db, order_no)
            _deliv = delivery.ensure_delivery(db, order)
            if _deliv and _deliv.get("kind"):
                order.delivered_at = paid_at
        except Exception:  # noqa: BLE001
            log.exception("delivery ensure failed: %s", order_no)

        # ① 充值订单:为充值商户加余额
        if order.recharge_for_id and order.recharge_grant_cents:
            buyer = db.get(User, order.recharge_for_id)
            if buyer:
                after = buyer.api_balance_cents + order.recharge_grant_cents
                buyer.api_balance_cents = after
                db.add(FeeLedger(
                    merchant_id=buyer.id, order_id=order.id,
                    delta_cents=order.recharge_grant_cents, balance_after_cents=after,
                    reason="recharge",
                    note=f"购买「{order.title} · {order.sku}」支付成功,充值到账",
                    created_at=paid_at,
                ))

        merchant = db.get(User, order.merchant_id)
        payload = {
            "order_id": order_no,
            "creat_time": paid_at_str,
            "type": order.category,
            "title": order.title,
            "sku": order.sku,
            "total": order.total,
            "seller": merchant.afdian_user_id or str(merchant.id) if merchant else "",
        }
        if merchant:
            # ② 扣服务费(费用由管理台可调)
            _fee = fee_cents()
            after_fee = merchant.api_balance_cents - _fee
            merchant.api_balance_cents = after_fee
            db.add(FeeLedger(
                merchant_id=merchant.id, order_id=order.id,
                delta_cents=-_fee, balance_after_cents=after_fee,
                reason="order_fee",
                note=f"订单 {order_no} 支付成功,扣除服务费",
                created_at=paid_at,
            ))
            db.commit()

            # 统计:已支付笔数与金额(独立于 orders 表,未付单被清理也不影响创建数)
            bump_order_stat(_stat_merchant, paid=1, amount=_stat_amount)

            # ③ Webhook(自定义回调:body_template+请求头+查询参数;模板空则发整单 JSON)
            if merchant.webhook_url:
                _wh = send_webhook_detail(
                    merchant.webhook_url, payload,
                    method=(merchant.webhook_method or "post"),
                    encode=(merchant.webhook_encode or "raw"),
                    extra_headers=_parse_headers(merchant.webhook_headers),
                    extra_params=_parse_params(merchant.webhook_params),
                    body_template=(merchant.webhook_body or ""),
                )
                if not _wh.get("ok"):
                    log.warning("[webhook] 回调失败 %s: %s", merchant.webhook_url, _wh.get("error") or _wh.get("status"))
                # 记录发送历史(供商户在「Webhook 记录」页查看)
                try:
                    db.add(WebhookSend(
                        user_id=merchant.id, order_no=str(order_no or ""),
                        url=merchant.webhook_url,
                        method=(merchant.webhook_method or "post").upper(),
                        status_code=int(_wh.get("status") or 0), ok=bool(_wh.get("ok")),
                        resp_head=json.dumps(_wh.get("headers") or {}, ensure_ascii=False)[:4000],
                        resp_body=(_wh.get("body") or "")[:4000],
                        created_at=datetime.now(),
                    ))
                    _prune_webhook_sends(db, merchant.id)
                except Exception:  # noqa: BLE001
                    pass
            # ④ 邮件通知(附扣费后剩余 API 服务费)
            if merchant.email_notify:
                mailer.send(
                    merchant.email,
                    f"【爱发电铺】订单支付成功 {order_no}",
                    email_templates.order_email_html(payload, merchant.shop_name, f"{after_fee / 100:.2f}"),
                )
            # ⑤ 买家发货邮件(下单时填了收货邮箱才发;卡密/链接直接送达)
            _buyer = (getattr(order, "buyer_email", "") or "").strip()
            if _buyer and _deliv and _deliv.get("kind"):
                try:
                    _dk = "卡密" if _deliv.get("kind") == "card" else "链接"
                    _lines = [
                        f"您在「{merchant.shop_name}」的订单已支付成功。",
                        "",
                        f"订单号：{order_no}",
                        f"商品：{order.category} · {order.title} · {order.sku}",
                        f"金额：¥{order.total}",
                        "",
                        f"您的{_dk}：",
                        str(_deliv.get("content") or ""),
                    ]
                    if _deliv.get("tip"):
                        _lines += ["", str(_deliv["tip"])]
                    _lines += ["", "如需再次查看，可到店铺页「自助提货」用订单号查询。"]
                    if merchant.email:
                        _lines += [f"商家客服邮箱：{merchant.email}"]
                    mailer.send(
                        _buyer,
                        f"【{merchant.shop_name}】订单 {order_no} 已发货（{_dk}）",
                        "\n".join(_lines),
                    )
                except Exception:  # noqa: BLE001
                    log.exception("buyer delivery mail failed: %s", order_no)
        else:
            db.commit()
        return order


def _merge_extra(payload: dict, config_text: str) -> dict:
    """把商户栏 '请求体' 输入(合法 JSON 对象)字段并入 payload(作为附加/覆盖)。"""
    out = dict(payload)
    if not config_text:
        return out
    try:
        extra = json.loads(config_text)
        if isinstance(extra, dict):
            out.update(extra)
    except Exception:
        pass
    return out


_BODY_VARS = ("order_id", "creat_time", "type", "title", "sku", "total", "seller")


def _wh_lit(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return value  # 纯数字字符串按数值输出(免引号),契合 {"订单号":order_id} -> {"订单号":123}
    if value is None or value == "":
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _wh_str_raw(value):
    """输出可放进 JSON 字符串内部的裸文本(已转义),用于变量本身写在引号内的情况。"""
    s = "" if value is None else str(value)
    try:
        return json.dumps(s, ensure_ascii=False)[1:-1]
    except Exception:
        return s


def _token_replace(text, fields):
    """仅把带 @ 前缀的已知变量名(@order_id 等)替换为订单实际值；裸词(order_id)保留原样，避免与 JSON 键重名。
    跟踪 JSON 字符串状态:变量在引号内 → 输出裸文本(已转义);引号外 → 数值免引号 / 字符串补引号。"""
    if not text:
        return ""
    text = str(text)
    n = len(text)
    out = []
    i = 0
    in_str = False

    def is_id(c):
        return c is not None and (c.isalnum() or c == "_")

    while i < n:
        c = text[i]
        if c == '"' and (i == 0 or text[i - 1] != "\\"):
            in_str = not in_str
            out.append(c)
            i += 1
            continue
        if c == "@":
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            name = text[i + 1:j]
            if name in fields and not is_id(text[i - 1] if i else None) and not (j < n and is_id(text[j])):
                if in_str:
                    out.append(_wh_str_raw(fields.get(name, "")))  # 在 JSON 字符串内:输出裸值(转义)
                else:
                    out.append(_wh_lit(fields.get(name, "")))      # 引号外:数值免引号 / 字符串补引号
                i = j
                continue
            # 非变量（或粘贴但未绑定）→ 保留一个 @ 原样
            out.append("@")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _render_template(tpl: str, payload: dict) -> str:
    """把回调正文里的变量名(order_id/creat_time/type/title/sku/total/seller)直接替换为实际订单值(免@@),数值输出免引号。"""
    return _token_replace(tpl or "", payload)


def _prune_webhook_sends(db, user_id: int, keep: int = 30) -> None:
    """每个商户的 Webhook 记录最多保留 keep 条,超出时删最旧的。"""
    try:
        old = (db.query(WebhookSend.id)
               .filter(WebhookSend.user_id == user_id)
               .order_by(WebhookSend.id.desc())
               .offset(keep).all())
        ids = [x[0] for x in old]
        if ids:
            db.query(WebhookSend).filter(WebhookSend.id.in_(ids)).delete(synchronize_session=False)
    except Exception:  # noqa: BLE001
        pass


def _webhook_open(req, timeout: int = 6):
    """带 CA 兜底的 urlopen:优先用 certifi 的 CA 证书;证书链缺失时降级为不校验(仅本次)。"""
    ctx = None
    try:
        import certifi  # type: ignore
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        try:
            ctx = ssl.create_default_context()
        except Exception:  # noqa: BLE001
            ctx = None
    try:
        if ctx is not None:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        return urllib.request.urlopen(req, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or isinstance(e, ssl.SSLError):
            return urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context())
        raise


def _prepare_webhook(url, payload, method, encode, extra_headers, extra_params, body_template=None):
    """构造 webhook 请求,返回 (q_url, data, headers, method)。供 send_webhook / send_webhook_detail 复用。"""
    method = method or "post"
    encode = encode or "raw"
    extra_headers = dict(extra_headers or {})
    extra_params = {k: _token_replace(v, payload) for k, v in (extra_params or {}).items()}
    for k, v in (extra_params or {}).items():
        sep = "&" if "?" in url else "?"
        url += sep + urllib.parse.quote(str(k)) + "=" + urllib.parse.quote(str(v))
    headers = {}
    tpl = (body_template or "").strip()
    if tpl:
        rendered = _render_template(tpl, payload)
        headers["Content-Type"] = "application/json"
        headers.update(extra_headers)
        if method == "get":
            sep = "&" if "?" in url else "?"
            q_url = url + sep + urllib.parse.quote(rendered)
            data = None
        else:
            q_url = url
            data = rendered.encode("utf-8")
    else:
        # 旧默认:整单订单 JSON(按 encode 决定形状)
        json_str = json.dumps(payload, ensure_ascii=False)
        if method == "get":
            sep = "&" if "?" in url else "?"
            data = None
            q_url = url + sep + "payload=" + urllib.parse.quote(json_str)
        elif encode == "form":
            data = ("payload=" + urllib.parse.quote(json_str)).encode("utf-8")
            q_url = url
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif encode == "field":
            data = json.dumps({"payload": json_str}, ensure_ascii=False).encode("utf-8")
            q_url = url
            headers["Content-Type"] = "application/json"
        else:  # raw
            data = json_str.encode("utf-8")
            q_url = url
            headers["Content-Type"] = "application/json"
        if method != "get":
            headers.update(extra_headers)
    return q_url, data, headers, method.upper()


def send_webhook(url: str, payload: dict, method: str = "post", encode: str = "raw", extra_headers: dict = None, extra_params: dict = None, body_template: str = None) -> tuple:
    """发送 webhook。返回 (ok,msg)。订单通知使用,签名/行为保持不变。"""
    try:
        q_url, data, headers, m = _prepare_webhook(url, payload, method, encode, extra_headers, extra_params, body_template)
        req = urllib.request.Request(q_url, data=data, headers=headers, method=m)
        with _webhook_open(req) as resp:
            return True, f"HTTP {resp.status}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def send_webhook_detail(url: str, payload: dict, method: str = "post", encode: str = "raw", extra_headers: dict = None, extra_params: dict = None, body_template: str = None) -> dict:
    """发送 webhook 并返回响应详情(供“发送测试”响应面板):
    {ok, status, elapsed_ms, headers, body, error}
    - 4xx/5xx 也读取其响应头/体(不当作构造失败)
    """
    import time as _t
    out = {"ok": False, "status": 0, "elapsed_ms": 0, "headers": {}, "body": "", "error": ""}
    try:
        q_url, data, headers, m = _prepare_webhook(url, payload, method, encode, extra_headers, extra_params, body_template)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"构造请求失败: {e}"
        return out
    t0 = _t.time()
    req = urllib.request.Request(q_url, data=data, headers=headers, method=m)
    try:
        with _webhook_open(req) as resp:
            out["status"] = resp.status
            out["headers"] = {k: v for k, v in resp.headers.items()}
            out["body"] = resp.read(65536).decode("utf-8", "replace")
            out["ok"] = 200 <= resp.status < 300
    except urllib.error.HTTPError as he:
        out["status"] = he.code
        try:
            out["headers"] = {k: v for k, v in he.headers.items()}
            out["body"] = he.read(65536).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        out["ok"] = 200 <= he.code < 300
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    out["elapsed_ms"] = int((_t.time() - t0) * 1000)
    return out


def _parse_headers(text: str) -> dict:
    """把多行 'k: v' 文本解析为请求头 dict(跳过空行/无效行)"""
    out: dict = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return out


def _parse_params(text: str) -> dict:
    """把多行 'k=v' 文本解析为查询参数 dict(跳过空行/无效行)"""
    out: dict = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def _post_webhook(url: str, payload: dict, method: str = "post", encode: str = "raw", extra_headers: dict = None, extra_params: dict = None, body_template: str = None) -> None:
    ok, msg = send_webhook(url, payload, method, encode, extra_headers, extra_params, body_template)
    if not ok:
        log.warning("[webhook] 回调失败 %s: %s", url, msg)


def notify_low_balance(merchant_id: int) -> bool:
    """余额不足提醒(30 分钟内一次);返回是否发送"""
    with SessionLocal() as db:
        m = db.get(User, merchant_id)
        if not m or not m.balance_notify:
            return False
        last = m.last_balance_notify_at
        if last and datetime.now() - last < timedelta(minutes=30):
            return False
        m.last_balance_notify_at = datetime.now()
        db.commit()
        return mailer.send(
            m.email,
            "【爱发电铺】API 费用余额不足提醒",
            email_templates.low_balance_html(m.shop_name, f"{m.api_balance_cents / 100:.2f}"),
        )


def gc_stale_pending(max_hours: float = 3.0) -> dict:
    """清理过期未付订单(惰性:由下单/回调顺带调用,无定时器)。
    只删「始终未支付」且创建超过 N 小时的行;已 paid 不碰。

    返回 dict:{"deleted":n,"expired":x,"now":iso,"error":""}
    - deleted : 本次真正删除条数
    - expired : 现在里符合(>N小时未付)的条数(不含删除前计算)
    任何异常不再吞成 0,而是回 em + log.exception,方便定位为什么"没删"。"""
    from datetime import datetime as _dt
    cutoff = datetime.now() - timedelta(hours=max_hours)
    try:
        with SessionLocal() as db:
            expired = db.query(Order).filter(
                Order.status != "paid",
                Order.created_at < cutoff,
            ).count()
            # 释放这些订单锁定的卡密(方案 A:未付款单被清时,卡密回到可售库存)
            _stale = (
                db.query(Order.order_no)
                .filter(Order.status != "paid", Order.created_at < cutoff)
                .all()
            )
            _released = 0
            for (_no,) in _stale:
                if _no:
                    _released += delivery.release_order(db, _no)
            q = db.query(Order).filter(
                Order.status != "paid",
                Order.created_at < cutoff,
            )
            n = q.delete(synchronize_session=False)
            db.commit()
            out = {"deleted": int(n or 0), "expired": int(expired or 0),
                   "cards_released": int(_released or 0),
                   "now": _dt.now().isoformat(timespec="seconds"), "error": ""}
            log.info("gc_stale_pending completed: %s", out)
            return out
    except Exception as e:  # noqa: BLE001
        log.exception("gc_stale_pending failed")
        return {"deleted": 0, "expired": 0, "now": "", "error": "异常:" + str(e)}
