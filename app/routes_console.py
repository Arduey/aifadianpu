"""控制台:页面(需登录) + JSON 接口(数据预览/商品/订单/个人中心/后台管理)"""
import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import auth, config, settings
from .db import (FeeLedger, Notice, Order, OrderStat, Product, SessionLocal, User, WebhookSend, _wh_pairs, platform_settings)
from .render import render
from .services import afdian, afd_login, afd_live, categories, delivery, email_templates, mailer, pipeline
from .utils import has_amp

router = APIRouter()


def err(message: str, status: int = 400):
    return JSONResponse({"ok": False, "message": message}, status_code=status)


def _me(request: Request):
    return getattr(request.state, "me", None)


def _need(request: Request, admin: bool = False):
    """页面守卫:未登录→跳转;非管理员→拦截页"""
    me = _me(request)
    if not me:
        return None, RedirectResponse("/login", status_code=302)
    if admin and me.role != "admin":
        return None, render(request, "noadmin.html")
    return me, None


# ═══════════════ 页面 ═══════════════

@router.get("/console/dashboard")
def dashboard(request: Request):
    me, resp = _need(request)
    return resp or render(request, "dashboard.html", {"scope": "mine", "title": "数据预览", "badge": ""})


@router.get("/console/admin-stats")
def admin_stats(request: Request):
    me, resp = _need(request, admin=True)
    return resp or render(request, "dashboard.html", {"scope": "all", "title": "数据预览 · 管理员", "badge": "全平台汇总"})


@router.get("/console/admin-orders")
def admin_orders(request: Request):
    me, resp = _need(request, admin=True)
    return resp or render(request, "orders.html", {"scope": "all", "title": "订单管理 · 管理员", "badge": "全部商家订单"})


@router.get("/console/products")
def products_page(request: Request):
    me, resp = _need(request)
    if resp:
        return resp
    with SessionLocal() as db:
        rows = db.query(Product).filter(Product.merchant_id == me.id).order_by(Product.category, Product.sort_order, Product.id).all()
        _stats = {}
        for p in rows:
            if p.delivery_type == "platform" and p.delivery_kind == "card":
                _stats[p.id] = delivery.cards_stats(db, p.id)
        # 历史销量(仅已付款订单):按 product_id 匹配,兼容历史无 product_id 的单据按「分类+标题+SKU」兜底
        _sold = {}       # product_id -> 件数
        _sold_amt = {}   # product_id -> 金额(元)
        _sold_key = {}   # "分类|标题|SKU" -> 件数
        _sold_key_amt = {}
        _orders = (
            db.query(Order.product_id, Order.category, Order.title, Order.sku, Order.total)
            .filter(Order.merchant_id == me.id, Order.status == "paid")
            .all()
        )
        for _pid, _cat, _title, _sku, _total in _orders:
            _k = f"{_cat}|{_title}|{_sku}"
            _sold_key[_k] = _sold_key.get(_k, 0) + 1
            _sold_key_amt[_k] = _sold_key_amt.get(_k, 0) + int(_total or 0)
            if _pid:
                _sold[_pid] = _sold.get(_pid, 0) + 1
                _sold_amt[_pid] = _sold_amt.get(_pid, 0) + int(_total or 0)
        # 分类销量汇总(用于分类头部显示)
        _cat_sold = {}
        _cat_amount = {}
        for p in rows:
            _k = f"{p.category}|{p.title}|{p.sku_name}"
            _n = _sold.get(p.id, 0) or _sold_key.get(_k, 0)
            _a = _sold_amt.get(p.id, 0) or _sold_key_amt.get(_k, 0)
            _cat_sold[p.category] = _cat_sold.get(p.category, 0) + _n
            _cat_amount[p.category] = _cat_amount.get(p.category, 0) + _a
        # 限购类商品的剩余可售量
        _lim_left = delivery.limited_left_map(db, [p for p in rows if delivery.is_limited(p)])
        # 独立分类表:用于分类卡片(名称/图标/排序)与「编辑分类」;顺序以分类表为准
        _cats = categories.list_categories(db, me.id)
        _cat_order = {c.name: int(c.sort_order or 0) for c in _cats}
        _cat_icon_map = {c.name: (c.icon_url or "") for c in _cats}
        _cat_items = [{"id": c.id, "name": c.name, "icon_url": c.icon_url or "",
                       "sort_order": int(c.sort_order or 0)} for c in _cats]
        items = [{
            "id": p.id, "category": p.category, "category_icon_url": p.category_icon_url,
            "title": p.title, "sku_name": p.sku_name, "price": p.price,
            "is_recharge": 1 if p.is_recharge else 0, "recharge_grant_cents": p.recharge_grant_cents,
            "delivery_type": p.delivery_type or "merchant",
            "delivery_kind": p.delivery_kind or "",
            "delivery_link": p.delivery_link or "",
            "delivery_tip": p.delivery_tip or "",
            "stock_limit": int(p.stock_limit or 0),
            "limited_left": int(_lim_left.get(p.id, -1)),
            "is_limited": bool(delivery.is_limited(p)),
            "stock": int((_stats.get(p.id) or {}).get("available", 0)),
            "stock_locked": int((_stats.get(p.id) or {}).get("locked", 0)),
            "stock_used": int((_stats.get(p.id) or {}).get("used", 0)),
            "sold": (lambda _k: (_sold.get(p.id, 0) or _sold_key.get(_k, 0)))(
                f"{p.category}|{p.title}|{p.sku_name}"),
            "sold_amount": (lambda _k: (_sold_amt.get(p.id, 0) or _sold_key_amt.get(_k, 0)))(
                f"{p.category}|{p.title}|{p.sku_name}"),
        } for p in rows]
        _plogo = platform_settings(db).platform_logo_url or ""
    return render(request, "products.html", {
        "products": items, "configured": me.is_afdian_configured(), "is_admin": me.role == "admin",
        "platformLogo": _plogo, "cat_sold": _cat_sold, "cat_amount": _cat_amount,
        "cat_items": _cat_items, "cat_icon_map": _cat_icon_map, "cat_order": _cat_order,
    })


@router.get("/console/orders")
def orders_page(request: Request):
    me, resp = _need(request)
    return resp or render(request, "orders.html", {"scope": "mine", "title": "订单管理", "badge": ""})


@router.get("/console/fees")
def fees_page(request: Request):
    me, resp = _need(request)
    if resp:
        return resp
    with SessionLocal() as db:
        rows = (
            db.query(FeeLedger)
            .filter(FeeLedger.merchant_id == me.id)
            .order_by(FeeLedger.created_at.desc(), FeeLedger.id.desc())
            .limit(300)
            .all()
        )
        items = [{
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "delta_cents": r.delta_cents, "balance_after_cents": r.balance_after_cents,
            "reason": r.reason, "note": r.note or "-",
        } for r in rows]
        income = sum(r.delta_cents for r in rows if r.delta_cents > 0)
        expense = sum(-r.delta_cents for r in rows if r.delta_cents < 0)
    return render(request, "fees.html", {
        "rows": items, "balance": me.api_balance_cents, "income": income, "expense": expense,
    })


@router.get("/console/account")
def account_page(request: Request):
    me, resp = _need(request)
    if resp:
        return resp
    settings = None
    smtp_has_pass = False
    if me.role == "admin":
        with SessionLocal() as db:
            s = platform_settings(db)
            settings = {
                "consumer_account": s.consumer_account,
                "consumer_password": "******" if s.consumer_password else "",
                "platform_logo_url": s.platform_logo_url,
                "wechat_enabled": s.wechat_enabled, "wechat_disabled_note": s.wechat_disabled_note,
                "alipay_enabled": s.alipay_enabled, "alipay_disabled_note": s.alipay_disabled_note,
                "allowed_email_domains": s.allowed_email_domains,
                "webhook_base_url": s.webhook_base_url,
                "smtp_host": s.smtp_host, "smtp_port": s.smtp_port,
                "smtp_user": s.smtp_user, "smtp_from": s.smtp_from,
            }
            smtp_has_pass = bool(s.smtp_pass)
    return render(request, "account.html", {"user": me, "settings": settings, "smtp_has_pass": smtp_has_pass})


@router.get("/console/webhook-history")
def webhook_history_page(request: Request):
    """商户 Webhook 回调(发送)历史:每笔订单支付成功后平台发给商户回调地址的记录"""
    me = _me(request)
    if not me:
        return RedirectResponse("/login", status_code=302)
    scope_all = me.role == "admin" and request.query_params.get("scope") == "all"
    with SessionLocal() as db:
        q = db.query(WebhookSend)
        if not scope_all:
            q = q.filter(WebhookSend.user_id == me.id)
        rows = q.order_by(WebhookSend.id.desc()).limit(200).all()
        recs = [{
            "id": r.id, "order_no": r.order_no or "", "url": r.url or "",
            "method": (r.method or "").upper(), "status_code": r.status_code or 0,
            "ok": bool(r.ok), "is_test": bool(getattr(r, "is_test", False)),
            "resp_head": r.resp_head or "", "resp_body": r.resp_body or "",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        } for r in rows]
    return render(request, "webhook_history.html", {
        "scope": "all" if scope_all else "mine", "title": "Webhook 记录", "badge": "", "records": recs,
    })


@router.get("/console/tasks")
def tasks_page(request: Request):
    """新手任务清单页(自动识别完成状态)"""
    me, resp = _need(request)
    if resp:
        return resp
    with SessionLocal() as db:
        product_count = db.query(Product).filter(Product.merchant_id == me.id).count()
    return render(request, "tasks.html", {"product_count": product_count})


@router.get("/console/admin")
def admin_page(request: Request):
    me, resp = _need(request, admin=True)
    if resp:
        return resp
    with SessionLocal() as db:
        users = db.query(User).order_by(User.id).all()
        items = []
        for u in users:
            items.append({
                "id": u.id, "email": u.email, "shop_name": u.shop_name, "role": u.role,
                "status": u.status, "afdian_user_id": u.afdian_user_id,
                "api_balance_cents": u.api_balance_cents,
                "product_count": db.query(Product.id).filter(Product.merchant_id == u.id).count(),
                "paid_order_count": db.query(Order.id).filter(Order.merchant_id == u.id, Order.status == "paid").count(),
            })
    return render(request, "admin.html", {"merchants": items})


# ═══════════════ JSON:统计 / 订单 ═══════════════

@router.get("/console/api/stats")
def stats(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    scope_all = me.role == "admin" and request.query_params.get("scope") == "all"
    from_s = request.query_params.get("from", "")
    to_s = request.query_params.get("to", "")
    with SessionLocal() as db:
        q = db.query(Order.merchant_id, Order.category, Order.title, Order.sku, Order.total, Order.status, Order.created_at)
        if not scope_all:
            q = q.filter(Order.merchant_id == me.id)
        if from_s:
            try:
                q = q.filter(Order.created_at >= datetime.fromisoformat(from_s.replace("Z", "+00:00")).replace(tzinfo=None))
            except ValueError:
                pass
        if to_s:
            try:
                q = q.filter(Order.created_at < datetime.fromisoformat(to_s.replace("Z", "+00:00")).replace(tzinfo=None))
            except ValueError:
                pass
        rows = q.all()
        merchant_cache: dict[int, tuple] = {}
        created_count = paid_count = paid_amount = 0
        daily: dict[str, dict] = {}
        product_map: dict[str, dict] = {}
        long_range = not from_s or not to_s
        for r in rows:
            created_count += 1
            key = r.created_at.strftime("%Y-%m" if long_range else "%Y-%m-%d")
            d = daily.setdefault(key, {"date": key, "created": 0, "paid": 0, "amount": 0})
            d["created"] += 1
            if r.status == "paid":
                paid_count += 1
                paid_amount += r.total
                d["paid"] += 1
                d["amount"] += r.total
                pk = f"{r.category}|{r.title}|{r.sku}"
                p = product_map.get(pk)
                if p is None:
                    p = {"category": r.category, "title": r.title, "sku": r.sku, "count": 0, "amount": 0}
                    if scope_all:
                        if r.merchant_id not in merchant_cache:
                            m = db.get(User, r.merchant_id)
                            merchant_cache[r.merchant_id] = (m.email, m.shop_name) if m else ("", "")
                        p["merchantEmail"], p["merchantShop"] = merchant_cache[r.merchant_id]
                    product_map[pk] = p
                p["count"] += 1
                p["amount"] += r.total
    products = sorted(product_map.values(), key=lambda x: -x["amount"])
    # 补正「创建订单数」:未支付订单超 3 小时会被物理清理,orders 表统计不到。
    # 用 order_stats 的累计创建数兜底(取二者较大值),并回填到 daily 序列。
    try:
        with SessionLocal() as _db2:
            _st = _db2.query(OrderStat)
            if not scope_all:
                _st = _st.filter(OrderStat.merchant_id == me.id)
            if from_s:
                _st = _st.filter(OrderStat.day >= from_s[:10])
            if to_s:
                _st = _st.filter(OrderStat.day <= to_s[:10])
            _stat_created = sum(int(x.created_count or 0) for x in _st.all())
            _st2 = _db2.query(OrderStat)
            if not scope_all:
                _st2 = _st2.filter(OrderStat.merchant_id == me.id)
            if from_s:
                _st2 = _st2.filter(OrderStat.day >= from_s[:10])
            if to_s:
                _st2 = _st2.filter(OrderStat.day <= to_s[:10])
            for _r in _st2.all():
                _k = str(_r.day)
                if long_range:
                    _k = _k[:7]
                _d = daily.setdefault(_k, {"date": _k, "created": 0, "paid": 0, "amount": 0})
                if int(_r.created_count or 0) > int(_d["created"] or 0):
                    _d["created"] = int(_r.created_count or 0)
        if _stat_created > created_count:
            created_count = _stat_created
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True, "createdCount": created_count, "paidCount": paid_count,
        "paidAmount": paid_amount,
        "avgAmount": round(paid_amount / paid_count, 2) if paid_count else 0,
        "daily": [daily[k] for k in sorted(daily)],
        "products": products, "scope": "all" if scope_all else "mine",
    }


@router.get("/console/api/orders")
def orders_list(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    # 惰性清理:打开订单列表时先把「超过 3 小时仍未支付」的订单清掉,避免旧未付单一直挂着
    try:
        from .services import pipeline as _pipe
        _pipe.gc_stale_pending()
    except Exception:  # noqa: BLE001
        pass
    scope_all = me.role == "admin" and request.query_params.get("scope") == "all"
    q = (request.query_params.get("q") or "").strip()
    channel = request.query_params.get("channel", "")
    merchant = (request.query_params.get("merchant") or "").strip()
    with SessionLocal() as db:
        query = db.query(Order).filter(Order.status.in_(("paid", "pending")))
        if not scope_all:
            query = query.filter(Order.merchant_id == me.id)
        if scope_all and merchant.isdigit():
            query = query.filter(Order.merchant_id == int(merchant))
        if channel in ("wechat", "alipay"):
            query = query.filter(Order.channel == channel)
        if q:
            like = f"%{q}%"
            query = query.filter(
                Order.order_no.like(like) | Order.title.like(like) | Order.sku.like(like) | Order.category.like(like)
            )
        rows = query.order_by(Order.created_at.desc()).limit(500).all()
        cache: dict[int, tuple] = {}
        # 分类图标映射(商户+分类 -> 图标):取该分类下任一商品的 category_icon_url
        _cat_icon: dict[tuple, str] = {}
        try:
            for _p in db.query(Product).filter(
                Product.merchant_id.in_([o.merchant_id for o in rows] or [0])
            ).all():
                _k = (_p.merchant_id, _p.category)
                if _k not in _cat_icon or (not _cat_icon.get(_k) and (_p.category_icon_url or "").strip()):
                    _cat_icon[_k] = (_p.category_icon_url or "").strip()
        except Exception:  # noqa: BLE001
            _cat_icon = {}
        _plogo = ""
        try:
            _plogo = platform_settings(db).platform_logo_url or ""
        except Exception:  # noqa: BLE001
            _plogo = ""
        out = []
        for o in rows:
            item = {
                "order_no": o.order_no, "category": o.category, "title": o.title, "sku": o.sku,
                "total": o.total, "channel": o.channel, "remark": o.remark, "status": o.status,
                "paid_at": o.paid_at.strftime("%Y-%m-%d %H:%M:%S") if o.paid_at else "",
                "created_at": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else "",
                "category_icon_url": _cat_icon.get((o.merchant_id, o.category), "") or _plogo,
            }
            if scope_all:
                if o.merchant_id not in cache:
                    m = db.get(User, o.merchant_id)
                    cache[o.merchant_id] = (m.email, m.shop_name) if m else ("", "")
                item["merchantEmail"], item["merchantShop"] = cache[o.merchant_id]
            out.append(item)
    return {"ok": True, "orders": out, "total": len(out)}


# ═══════════════ JSON:商品 ═══════════════

@router.post("/console/api/product/save")
async def product_save(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    if not me.is_afdian_configured():
        return err("请先在个人中心绑定爱发电 user_id 与 token,否则无法创建商品", 403)
    b = await request.json()
    pid = int(b.get("id", 0) or 0)
    category = str(b.get("category", "")).strip()
    icon_url = str(b.get("category_icon_url", "")).strip()
    title = str(b.get("title", "")).strip()
    sku = str(b.get("sku_name", "")).strip()
    price = b.get("price", "")
    grant_yuan = str(b.get("recharge_grant", "")).strip()
    # 发货方式(SKU 级)
    delivery_type = str(b.get("delivery_type", "merchant") or "merchant").strip()
    delivery_kind = str(b.get("delivery_kind", "") or "").strip()
    delivery_link = str(b.get("delivery_link", "") or "").strip()[:1000]
    delivery_tip = str(b.get("delivery_tip", "") or "").strip()[:500]
    # 限购总量(商户发货/链接发货用;0=不限量)
    try:
        stock_limit = int(str(b.get("stock_limit", "0") or "0").strip() or 0)
    except (TypeError, ValueError):
        stock_limit = 0
    if stock_limit < 0:
        stock_limit = 0
    if delivery_type not in ("merchant", "platform"):
        delivery_type = "merchant"
    if delivery_type == "merchant":
        delivery_kind, delivery_link = "", ""
    elif delivery_kind not in ("card", "link"):
        return err("请选择平台发货的具体方式(卡密 / 链接)")
    elif delivery_kind == "link":
        if not delivery_link:
            return err("链接型发货需填写内容(链接或发货提示文字)")

    if not category or not title or not sku:
        return err("分类/标题/SKU 均不能为空")
    if len(category) > 16:
        return err(f"分类最多16字,当前{len(category)}字")
    if len(title) > 24:
        return err(f"商品标题最多24字,当前{len(title)}字")
    if len(sku) > 12:
        return err(f"SKU名最多12字,当前{len(sku)}字")
    if has_amp(category) or has_amp(title) or has_amp(sku):
        return err("分类/标题/SKU 不允许包含 & 符号")
    try:
        price_i = int(price)
        if price_i < 5:
            raise ValueError
    except (TypeError, ValueError):
        return err("价格仅支持不小于 5 的正整数(元)")

    with SessionLocal() as db:
        # 商品重复判定：同一店铺(商家)下 分类+标题+SKU 四元复合唯一 才判定重复
        dup = db.query(Product).filter(
            Product.merchant_id == me.id,
            Product.category == category,
            Product.title == title,
            Product.sku_name == sku,
        )
        if pid:
            dup = dup.filter(Product.id != pid)
        if dup.first():
            return err("该店铺的分类下已存在同名 SKU(标题也需不同才可区分)")

        is_recharge = me.role == "admin" and category == "API充值"
        grant_cents = price_i * 100
        if is_recharge and grant_yuan:
            try:
                g = float(grant_yuan)
                if g > 0:
                    grant_cents = round(g * 100)
            except ValueError:
                return err("到账金额需为正数(元)")

        # 分类图标统一:同一分类共用一个图标(改动即同步该分类全部商品)
        _siblings = db.query(Product).filter(Product.merchant_id == me.id, Product.category == category).all()
        _existing_icon = ""
        for _s in _siblings:
            if (_s.category_icon_url or "").strip():
                _existing_icon = _s.category_icon_url.strip()
                break
        if _siblings:
            # 已存在的分类:提交的图标若与分类现有图标不同 → 视为「修改分类图标」;否则沿用分类图标
            final_icon = icon_url if (icon_url and icon_url != _existing_icon) else _existing_icon
        else:
            final_icon = icon_url
        # 与独立分类表保持一致:商品用到的新分类自动落表;图标以分类表为准并回写商品
        try:
            _cat = categories.get_or_create(db, me.id, category)
            if _cat is not None:
                if final_icon:
                    _cat.icon_url = final_icon
                elif _cat.icon_url:
                    final_icon = _cat.icon_url
        except Exception:  # noqa: BLE001
            pass

        data = dict(
            merchant_id=me.id, category=category, category_icon_url=final_icon,
            title=title, sku_name=sku, price=price_i,
            is_recharge=is_recharge, recharge_grant_cents=grant_cents if is_recharge else 0,
            delivery_type=delivery_type, delivery_kind=delivery_kind,
            delivery_link=delivery_link, delivery_tip=delivery_tip,
            stock_limit=(0 if (delivery_type == "platform" and delivery_kind == "card") else stock_limit),
        )
        if pid:
            product = db.get(Product, pid)
            if not product or (product.merchant_id != me.id and me.role != "admin"):
                return err("无权操作该商品", 403)
            for k, v in data.items():
                setattr(product, k, v)
            msg = "商品已更新"
        else:
            _last = db.query(Product).filter(Product.merchant_id == me.id).order_by(Product.sort_order.desc(), Product.created_at.desc(), Product.id.desc()).first()
            _new_sort = (_last.sort_order if _last else 0) + 100  # 新增商品默认排在最后
            db.add(Product(**data, sort_order=_new_sort))
            msg = "API 充值商品创建成功(不进前台店铺)" if is_recharge else "商品创建成功"
        if _siblings and final_icon and final_icon != _existing_icon:
            for _s in _siblings:
                _s.category_icon_url = final_icon
        db.commit()
    return JSONResponse({"ok": True, "message": msg}, status_code=200 if pid else 201)


@router.post("/console/api/product/delete")
async def product_delete(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    pid = int(b.get("id", 0))
    with SessionLocal() as db:
        product = db.get(Product, pid)
        if not product:
            return err("商品不存在", 404)
        if product.merchant_id != me.id and me.role != "admin":
            return err("无权操作该商品", 403)
        db.delete(product)
        db.commit()
    return {"ok": True, "message": "商品已删除"}


# ═══════════════ JSON:卡密库存(SKU 级) ═══════════════

@router.get("/console/api/product/cards")
def product_cards(request: Request):
    """查看某商品的卡密:统计 + 列表(未用/锁定/已用)"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    try:
        pid = int(request.query_params.get("id") or 0)
    except (TypeError, ValueError):
        pid = 0
    if not pid:
        return err("缺少商品 id")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        if not p or (p.merchant_id != me.id and me.role != "admin"):
            return err("无权查看该商品", 403)
        stats = delivery.cards_stats(db, pid)
        rows = delivery.list_cards(db, pid, limit=800)
    return {"ok": True, "stats": stats, "cards": rows}


@router.post("/console/api/product/cards/import")
async def product_cards_import(request: Request):
    """粘贴导入卡密(一行一个,同一商品内去重)"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    try:
        pid = int(b.get("id") or 0)
    except (TypeError, ValueError):
        pid = 0
    text = str(b.get("text") or "")
    if not pid:
        return err("缺少商品 id")
    if not text.strip():
        return err("请粘贴卡密内容(一行一个)")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        if not p or (p.merchant_id != me.id and me.role != "admin"):
            return err("无权操作该商品", 403)
        if not (p.delivery_type == "platform" and p.delivery_kind == "card"):
            return err("该商品未设置为「平台发货 · 卡密」")
        r = delivery.import_cards(db, pid, p.merchant_id, text)
        db.commit()
        stats = delivery.cards_stats(db, pid)
    msg = f"已导入 {r['added']} 条"
    if r["dup"]:
        msg += f",跳过重复 {r['dup']} 条"
        if r.get("dup_other"):
            msg += f"(其中 {r['dup_other']} 条是你其它商品已用过的卡密)"
    return {"ok": True, "message": msg, "added": r["added"], "dup": r["dup"],
            "dup_other": r.get("dup_other", 0), "stats": stats}


@router.post("/console/api/product/cards/clean")
async def product_cards_clean(request: Request):
    """清理:删除未售出的卡密(用于重新导入) / 清理同商品内重复"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    try:
        pid = int(b.get("id") or 0)
    except (TypeError, ValueError):
        pid = 0
    mode = str(b.get("mode") or "unused")
    if not pid:
        return err("缺少商品 id")
    with SessionLocal() as db:
        p = db.get(Product, pid)
        if not p or (p.merchant_id != me.id and me.role != "admin"):
            return err("无权操作该商品", 403)
        if mode == "dedup":
            n = delivery.prune_duplicate_cards(db, pid)
            msg = f"已清理重复卡密 {n} 条"
        else:
            n = delivery.delete_unused_cards(db, pid, p.merchant_id)
            msg = f"已删除未售出卡密 {n} 条"
        db.commit()
        stats = delivery.cards_stats(db, pid)
    return {"ok": True, "message": msg, "deleted": n, "stats": stats}


# ═══════════════ JSON:个人中心 ═══════════════

@router.post("/console/api/account/save")
async def account_save(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    with SessionLocal() as db:
        user = db.get(User, me.id)
        if "shop_name" in b:
            name = str(b["shop_name"]).strip()
            from .utils import shop_name_ok
            if not shop_name_ok(name):
                return err("店铺名仅支持中文/字母/数字,不含特殊符号;汉字按2字符,最长折合12字符")
            dup = db.query(User).filter(User.shop_name == name, User.id != user.id).first()
            if dup:
                return err("该店铺名已被占用")
            user.shop_name = name
        if "bio" in b:
            _bio = str(b["bio"]).strip()
            _lines = _bio.split("\n")[:3]      # 店铺介绍最多 3 行
            _bio = "\n".join(_lines)[:60]      # 且不超过 60 字符(与 textarea maxlength 一致)
            user.bio = _bio
        for field in ("shop_logo_url", "afdian_user_id", "afdian_token", "qq", "wechat"):
            if field in b:
                setattr(user, field, str(b[field]).strip())
        if "webhook_url" in b:
            url = str(b["webhook_url"]).strip()
            if url and not url.startswith(("http://", "https://")):
                return err("Webhook URL 需以 http:// 或 https:// 开头")
            user.webhook_url = url
        if "webhook_method" in b and str(b["webhook_method"]) in ("post", "get"):
            user.webhook_method = str(b["webhook_method"])
        _enc = str(b.get("webhook_encode", ""))
        if _enc in ("raw", "form", "field", "json", "json_field", "file"):
            user.webhook_encode = _enc  # 前端别名:json→raw, json_field→field 由发送端兼容
        if "webhook_headers" in b:
            user.webhook_headers = _wh_pairs(b["webhook_headers"], ":")[:1000]
        if "webhook_params" in b:
            user.webhook_params = _wh_pairs(b["webhook_params"], "=")[:500]
        if "webhook_body" in b:
            user.webhook_body = str(b["webhook_body"])[:2000]
        for flag in ("email_notify", "balance_notify"):
            if flag in b:
                setattr(user, flag, bool(int(b[flag])))
        if "balance_threshold_yuan" in b and str(b["balance_threshold_yuan"]) != "":
            try:
                cents = round(float(b["balance_threshold_yuan"]) * 100)
                if cents < 0:
                    raise ValueError
                user.balance_threshold_cents = cents
            except ValueError:
                return err("提醒阈值需为不小于 0 的数字")
        db.commit()

        # 管理员平台配置
        if me.role == "admin":
            s = platform_settings(db)
            if "consumer_account" in b:
                s.consumer_account = str(b["consumer_account"]).strip()
            if b.get("consumer_password") and b["consumer_password"] != "******":
                s.consumer_password = str(b["consumer_password"])
            if "platform_logo_url" in b:
                s.platform_logo_url = str(b["platform_logo_url"]).strip()
            for flag in ("wechat_enabled", "alipay_enabled"):
                if flag in b:
                    setattr(s, flag, bool(int(b[flag])))
            for note in ("wechat_disabled_note", "alipay_disabled_note"):
                if note in b:
                    setattr(s, note, str(b[note]).strip())
            # SMTP 邮件服务(仅管理员)
            for key in ("smtp_host", "smtp_user", "smtp_from"):
                if key in b:
                    setattr(s, key, str(b[key]).strip())
            if "smtp_port" in b:
                try:
                    s.smtp_port = int(str(b["smtp_port"]).strip() or 465)
                except (ValueError, TypeError):
                    s.smtp_port = 465
            if b.get("smtp_pass") and str(b["smtp_pass"]) != "******":
                s.smtp_pass = str(b["smtp_pass"])
            # 注册允许邮箱域名(仅admin;分号分隔,白名单非空才限制)
            if "allowed_email_domains" in b:
                _dom = str(b["allowed_email_domains"]).strip().replace("，", ";").replace(",", ";")
                _parts = [x.strip().lower().lstrip("@") for x in _dom.split(";") if x.strip()]
                s.allowed_email_domains = ";".join(_parts)
            if "webhook_base_url" in b:
                s.webhook_base_url = str(b["webhook_base_url"] or "").strip().rstrip("/")
            # 单次API费用(管理台可调;单位:元→存分)
            if "api_fee_cents" in b:
                try:
                    _fc = int(round(float(str(b["api_fee_cents"]).strip() or 0) * 100))
                    if _fc >= 1:
                        s.api_fee_cents = _fc
                except (ValueError, TypeError):
                    pass
            db.commit()
    return {"ok": True, "message": "保存成功"}


@router.post("/console/api/account/test_smtp")
async def test_smtp(request: Request):
    """仅管理员:用当前 SMTP 配置发送一封测试邮件验证连通性"""
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    b = await request.json()
    to = str(b.get("to", "")).strip()
    if not to:
        to = (me.email or "").strip()  # 留空默认管理员邮箱
    if "@" not in to:
        return err("收件邮箱无效,请填写或使用管理员邮箱")
    s = settings.smtp()
    if not (s["host"] and s["user"] and s["pass"]):
        return err("尚未配置 SMTP,无法发送测试邮件")
    try:
        ok = mailer.send(to, "系统测试邮件",
                         "<div style='font-family:sans-serif;padding:24px;color:#333'>"
                         "<p>如果你收到这封邮件,说明邮件服务设置正确可用。</p>"
                         "<p style='color:#888'>这是一封系统自动发送的测试信息。</p></div>")
    except Exception as e:  # noqa: BLE001
        return err(f"发送失败: {e}")
    if not ok:
        return err("邮件发送失败:服务器未收到发送成功的确认(可能授权码无效或端口/账号错误)")
    return {"ok": True, "message": f"测试邮件已发送至 {to},请查收"}


# 订单邮件"发送测试"的每日次数(内存记录;进程重启清零,失败不计数)
_order_mail_test_daily = {}
_balance_mail_test_daily = {}
from datetime import date as _date


@router.post("/console/api/account/test_afdian")
async def test_afdian(request: Request):
    """商户:真实请求爱发电验证 user_id+token(优先用表单新填,未填用已保存)"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    try:
        b = await request.json()
    except Exception:  # noqa: BLE001
        b = {}
    with SessionLocal() as db:
        u = db.get(User, me.id)
        uid = str(b.get("afdian_user_id") or "").strip() or (u.afdian_user_id or "").strip()
        tok = str(b.get("afdian_token") or "").strip() or (u.afdian_token or "").strip()
    connected, message, detail = afdian.test_connection(uid, tok)
    out = {"ok": True, "connected": connected, "message": message}
    if detail:
        out["detail"] = detail
    return JSONResponse(out)


@router.post("/console/api/account/login_consumer")
async def login_consumer(request: Request):
    """[管理员]「爱发电(消费者)账号」登录测试:真实 POST 爱发电登录,原始 JSON 回传前端展示;
    登录成功的 auth_token 立即写入 platform_settings,供后续代下单流程复用/失效再登。"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    if me.role != "admin":
        return err("仅管理员可操作", 403)
    try:
        b = await request.json() or {}
    except Exception:  # noqa: BLE001
        b = {}

    from .services.afd_login import consumer_login as _login_consumer
    from .services.afd_login import save_consumer_token as _save_consumer
    with SessionLocal() as db:
        row = platform_settings(db)
        account = str(b.get("consumer_account") or "").strip() or (row.consumer_account or "").strip()
        pwd = str(b.get("consumer_password") or "") or (row.consumer_password or "")
        pwd = pwd.strip()
    result = _login_consumer(account, pwd)
    saved = False
    if result.get("ok") and result.get("token"):
        _save_consumer(result["token"], result.get("at"))
        saved = True
    return JSONResponse({"ok": bool(result.get("ok")), "saved": saved, "ec": result.get("ec", 0),
                         "em": result.get("em", ""), "raw": result.get("raw", ""),
                         "message": "登录成功,已写入数据库供下单流程复用,失效将自动重新获取" if saved
                                    else (result.get("em") or "登录测试失败")})


@router.post("/console/api/account/test_order_mail")
async def test_order_mail(request: Request):
    """商户:向自己的邮箱发送一封订单通知测试(同账号每天限1次,失败不计)"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    today = _date.today().isoformat()
    if me.role != "admin" and _order_mail_test_daily.get(me.id) == today:
        return err("邮件通知测试每日仅限 1 次(管理员不限);预览请用「预览模板」")
    with SessionLocal() as db:
        u = db.get(User, me.id)
        email = u.email
        shop = u.shop_name
    s = settings.smtp()
    if not (s["host"] and s["user"] and s["pass"]):
        return err("尚未配置 SMTP,无法发送测试邮件")
    html = email_templates.order_email_html({
        "order_id": "TEST-ORDER-0001",
        "creat_time": "2026-01-01 10:24:36",
        "type": "邮件推送测试-类型",
        "title": "邮件通知功能测试-标题",
        "sku": "测试SKU-规格",
        "total": 0.25,
        "seller": (u.afdian_user_id or str(u.id)),
    }, shop, balance_yuan=50.25)  # 复用真实「订单已支付」邮件模板 => 测试即真实样式预览
    try:
        ok = mailer.send(email, "【爱发电铺】订单通知测试", html)
    except Exception as e:  # noqa: BLE001
        return err(f"发送失败: {e}")
    if not ok:
        return err("邮件发送失败(未配置有效 SMTP 或授权码无效);本次不占用每日次数")
    if me.role != "admin":
        _order_mail_test_daily[me.id] = today
    return {"ok": True, "message": f"订单通知测试邮件已发送至 {email},请查收"}


@router.post("/console/api/account/test_balance_mail")
async def test_balance_mail(request: Request):
    """商户:向自己的邮箱发送一封「API 余额不足提醒」真实邮件测试(同账号每天限1次,失败不计)"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    today = _date.today().isoformat()
    if me.role != "admin" and _balance_mail_test_daily.get(me.id) == today:
        return err("余额提醒邮件测试每日仅限 1 次(管理员不限);预览请用「预览模板」")
    with SessionLocal() as db:
        u = db.get(User, me.id)
        email = u.email
        shop = (u.shop_name or "").strip() or "店铺"
        cur_bal = (u.api_balance_cents or 0) / 100  # 用当前真实余额
    s = settings.smtp()
    if not (s["host"] and s["user"] and s["pass"]):
        return err("尚未配置 SMTP,无法发送测试邮件")
    html = email_templates.low_balance_html(shop, f"{cur_bal:.2f}")  # 以当前余额为展示(非固定样值)
    try:
        ok = mailer.send(email, "【爱发电铺】API 余额不足提醒测试", html)
    except Exception as e:  # noqa: BLE001
        return err(f"发送失败: {e}")
    if not ok:
        return err("邮件发送失败(未配置有效 SMTP 或授权码无效);本次不占用每日次数")
    if me.role != "admin":
        _balance_mail_test_daily[me.id] = today
    return {"ok": True, "message": f"余额提醒测试邮件已发送至 {email},请查收(页面/邮件中余额为当前真实 ¥{cur_bal:.2f})"}


@router.post("/console/api/account/mail_preview")
async def mail_preview(request: Request):
    """模板预览(纯本地渲染,不发信):body.kind=order(默认)渲染订单邮件,kind=balance 渲染「API 余额不足提醒」"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    try:
        b = await request.json() or {}
    except Exception:  # noqa: BLE001
        b = {}
    kind = str(b.get("kind") or "order").strip().lower()
    shop = (me.shop_name or "").strip() or "店铺"
    cur_bal = (getattr(me, "api_balance_cents", 0) or 0) / 100
    try:
        with SessionLocal() as db:
            u = db.get(User, me.id)
            if u and (u.shop_name or "").strip():
                shop = u.shop_name.strip()
            if u:
                cur_bal = (u.api_balance_cents or 0) / 100
    except Exception:  # noqa: BLE001
        pass
    if kind == "balance":
        html = email_templates.low_balance_html(shop, f"{cur_bal:.2f}")  # 当前真实余额
        return JSONResponse({"ok": True, "html": html, "subject": "【爱发电铺】API 余额不足提醒-模板预览"})
    html = email_templates.order_email_html({
        "order_id": "TEST-ORDER-0001",
        "creat_time": "2026-01-01 10:24:36",
        "type": "邮件推送测试-类型",
        "title": "邮件通知功能测试-标题",
        "sku": "测试SKU-规格",
        "total": 0.25,
        "seller": (me.afdian_user_id or str(me.id)),
    }, shop, balance_yuan=50.25)
    return JSONResponse({"ok": True, "html": html, "subject": "【爱发电铺】订单邮件-模板预览"})


@router.post("/console/api/account/test_webhook")
async def test_webhook(request: Request):
    """测试:按当前输入(或已保存)配置发测试回调,验证能送达"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    cfg = {}
    try:
        cfg = await request.json() or {}
    except Exception:
        cfg = {}
    with SessionLocal() as db:
        u = db.get(User, me.id)
        url = str(cfg.get("webhook_url") or (u.webhook_url or "")).strip()
        method = str(cfg.get("webhook_method") or u.webhook_method or "post")
        enc = str(cfg.get("webhook_encode") or u.webhook_encode or "raw")
        headers = str(cfg.get("webhook_headers") or u.webhook_headers or "")
        params = str(cfg.get("webhook_params") or u.webhook_params or "")
        body = str(cfg.get("webhook_body") or u.webhook_body or "").strip()
    if not url:
        return err("请先填写 Webhook 回调地址")
    test_payload = {
        "order_id": "AFD-TEST-0001",
        "creat_time": "2026-01-01 00:00:00",
        "type": "图标素材",
        "title": "测试商品",
        "sku": "测试SKU",
        "total": 1,
        "seller": me.afdian_user_id or str(me.id),
    }
    det = pipeline.send_webhook_detail(url, test_payload, method, enc,
                                       extra_headers=pipeline._parse_headers(headers),
                                       extra_params=pipeline._parse_params(params),
                                       body_template=(body or ""))
    st = det.get("status") or 0
    # 测试发送也写入 Webhook 记录(标注 is_test)
    try:
        import json as _json
        with SessionLocal() as _db:
            _db.add(WebhookSend(
                user_id=me.id, order_no="", url=url, method=(method or "post").upper(),
                status_code=st, ok=bool(det.get("ok")), is_test=True,
                resp_head=_json.dumps(det.get("headers") or {}, ensure_ascii=False)[:4000],
                resp_body=(det.get("body") or "")[:4000],
                created_at=datetime.now(),
            ))
            pipeline._prune_webhook_sends(_db, me.id)
            _db.commit()
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": bool(det.get("ok")),
        "status": st,
        "elapsed_ms": det.get("elapsed_ms") or 0,
        "headers": det.get("headers") or {},
        "body": det.get("body") or "",
        "error": det.get("error") or "",
        "message": (f"HTTP {st}" if st else (det.get("error") or "已发送")),
    }


@router.get("/console/api/progress")
def progress_get(request: Request):
    """通用云端进度:返回当前登录者全部 key → dict(解析后)。"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    import json as _json
    from .db import UserProgress as _P
    result = {}
    with SessionLocal() as db:
        rows = db.query(_P).filter(_P.user_id == me.id).all()
        for r in rows:
            try:
                result[r.pkey] = _json.loads(r.value or "{}")
            except Exception:  # noqa: BLE001
                result[r.pkey] = {}
    return JSONResponse({"ok": True, "progress": result})


@router.post("/console/api/progress")
async def progress_update(request: Request):
    """通用云端进度 upsert:body {'updates':{key:value,...}}。
    dict 值与既有值做深合并;标量则直接覆盖。返回最新进度。"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    import json as _json
    from .db import UserProgress as _P
    try:
        b = await request.json() or {}
    except Exception:  # noqa: BLE001
        b = {}
    updates = b.get("updates") or {}
    if not isinstance(updates, dict) or not updates:
        return JSONResponse({"ok": False, "message": "没有可写入的进度"})
    now = datetime.now()
    with SessionLocal() as db:
        for key, value in updates.items():
            if not isinstance(value, (dict, list, str, int, float, bool)) and value is not None:
                continue
            row = db.query(_P).filter(_P.user_id == me.id, _P.pkey == str(key)).first()
            if row is None:
                row = _P(user_id=me.id, pkey=str(key), value="{}", updated_at=now)
                db.add(row)
            try:
                prev = _json.loads(row.value or "{}")
            except Exception:  # noqa: BLE001
                prev = {}
            if isinstance(prev, dict) and isinstance(value, dict):
                merged = {**prev, **value}
            else:
                merged = value
            row.value = _json.dumps(merged, ensure_ascii=False)
        db.commit()
        rows = db.query(_P).filter(_P.user_id == me.id).all()
        out = {}
        for r in rows:
            try:
                out[r.pkey] = _json.loads(r.value or "{}")
            except Exception:  # noqa: BLE001
                out[r.pkey] = {}
    return JSONResponse({"ok": True, "progress": out})


def rm_progress_key(request: Request, key: str) -> None:
    """（预留）删除某 key 的云端进度,当前登录者为作用域。"""
    me = _me(request)
    if not me:
        return
    from .db import UserProgress as _P
    with SessionLocal() as db:
        row = db.query(_P).filter(_P.user_id == me.id, _P.pkey == key).first()
        if row:
            db.delete(row)
            db.commit()


@router.post("/console/api/account/password")
async def account_password(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    current = str(b.get("current", ""))
    nxt = str(b.get("next", ""))
    if not auth.verify_password(current, me.password_hash):
        return err("当前密码不正确")
    if len(nxt) < 8:
        return err("新密码至少 8 位")
    with SessionLocal() as db:
        user = db.get(User, me.id)
        user.password_hash = auth.hash_password(nxt)
        db.commit()
    return {"ok": True, "message": "密码修改成功"}


@router.post("/console/api/account/deactivate")
def account_deactivate(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    if me.role == "admin":
        return err("管理员账号不可注销(平台仅一位管理员)")
    with SessionLocal() as db:
        user = db.get(User, me.id)
        user.status = "disabled"
        db.commit()
    resp = JSONResponse({"ok": True, "message": "账号已注销停用,数据已保留"})
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ═══════════════ JSON:充值 ═══════════════

@router.get("/console/api/recharge/products")
def recharge_products(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    with SessionLocal() as db:
        rows = (
            db.query(Product, User.shop_name)
            .join(User, User.id == Product.merchant_id)
            .filter(Product.is_recharge == True, User.status == "active")  # noqa: E712
            .order_by(Product.price)
            .all()
        )
        items = [{
            "id": p.id, "title": p.title, "sku_name": p.sku_name, "price": p.price,
            "recharge_grant_cents": p.recharge_grant_cents, "seller_shop": sn,
        } for p, sn in rows]
        s = platform_settings(db)
        pay = {
            "wechat": {"enabled": bool(s.wechat_enabled), "note": s.wechat_disabled_note},
            "alipay": {"enabled": bool(s.alipay_enabled), "note": s.alipay_disabled_note},
        }
    return {"ok": True, "products": items, "payMethods": pay}


@router.post("/console/api/recharge/create")
async def recharge_create(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    product_id = int(b.get("product_id", 0))
    channel = b.get("channel", "")
    if channel not in ("wechat", "alipay"):
        return err("请选择付款方式")
    with SessionLocal() as db:
        s = platform_settings(db)
        if channel == "wechat" and not s.wechat_enabled:
            return err(s.wechat_disabled_note or "微信支付暂不可用", 403)
        if channel == "alipay" and not s.alipay_enabled:
            return err(s.alipay_disabled_note or "支付宝暂不可用", 403)
        product = db.get(Product, product_id)
        if not product or not product.is_recharge:
            return err("充值商品不存在", 404)
        seller = db.get(User, product.merchant_id)
        if not seller or seller.status != "active":
            return err("充值商品卖家已停用", 403)
        grant = product.recharge_grant_cents or product.price * 100
        remark = f"{product.category}&{product.title}&{product.sku_name}&{product.price}"
        # 无人自动化充值:自动取/续登消费者 token;token 失效自动重登再试
        pay_type = (afd_live.PAY_TYPES.get(channel) or {}).get("py_type", "wpy_qr")
        r = afd_live.live_create_auto(seller.afdian_user_id or str(seller.id), product.price, remark, pay_type)
        if not r.get("ok"):
            return err(f"充值下单失败: {r.get('message') or '未知错误'}", 503 if r.get("source") == "fail" else 500)
        _d = r.get("data") or {}
        order_no = str(_d.get("out_trade_no") or "")
        qr = _d.get("redirect_url") or ""
        if not order_no:
            return err("充值下单失败:爱发电未返回订单号", 500)
        db.add(Order(
            order_no=order_no, product_id=product.id, merchant_id=seller.id,
            category=product.category, title=product.title, sku=product.sku_name,
            total=product.price, channel=channel, remark=remark,
            buyer_account=me.afdian_user_id or me.email, status="pending",
            recharge_for_id=me.id, recharge_grant_cents=grant, created_at=datetime.now(),
        ))
        db.commit()
        try:
            pipeline.bump_order_stat(seller.id, created=1)
        except Exception:  # noqa: BLE001
            pass
    return JSONResponse({"ok": True, "orderNo": order_no, "qrPayload": qr, "total": product.price}, status_code=201)


@router.get("/console/api/recharge/poll/{order_no}")
def recharge_poll(request: Request, order_no: str):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        return err("订单不存在", 404)
    if order.status == "paid":
        return {"ok": True, "status": "paid"}
    # 无人工单:自动取/续登消费者 token,失效自动重登
    r = afd_live.live_check_auto(order_no)
    if r.get("ok") and r.get("paid"):
        pipeline.mark_order_paid(order_no)
        return {"ok": True, "status": "paid"}
    return {"ok": True, "status": "pending"}


# ═══════════════ JSON:后台管理 ═══════════════

@router.get("/console/api/admin/merchants")
def admin_merchants(request: Request):
    """仅管理员:返回商户列表(供订单按商户筛选)"""
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    with SessionLocal() as db:
        rows = db.query(User).filter(User.role == "merchant").order_by(User.id).all()
        out = [{"id": u.id, "shop_name": u.shop_name, "email": u.email, "status": u.status} for u in rows]
    return {"ok": True, "merchants": out}


@router.get("/console/api/admin/products")
def admin_products(request: Request):
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    with SessionLocal() as db:
        rows = (
            db.query(Product, User.email, User.shop_name)
            .join(User, User.id == Product.merchant_id)
            .order_by(Product.id)
            .all()
        )
        items = [{
            "id": p.id, "category": p.category, "title": p.title, "sku_name": p.sku_name,
            "price": p.price, "is_recharge": 1 if p.is_recharge else 0,
            "merchant_email": em, "merchant_shop": sn,
            "delivery_type": p.delivery_type or "merchant",
            "delivery_kind": p.delivery_kind or "",
            "stock": (delivery.cards_stats(db, p.id)["available"]
                      if (p.delivery_type == "platform" and p.delivery_kind == "card") else 0),
        } for p, em, sn in rows]
    return {"ok": True, "products": items}


@router.post("/console/api/admin/merchant")
async def admin_merchant(request: Request):
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    b = await request.json()
    mid = int(b.get("id", 0))
    with SessionLocal() as db:
        target = db.get(User, mid)
        if not target:
            return err("商户不存在", 404)
        status = str(b.get("status", ""))
        if status:
            if status not in ("active", "disabled"):
                return err("状态值无效")
            if target.role == "admin" and status == "disabled":
                return err("不可停用管理员账号")
            target.status = status
            db.commit()
            return {"ok": True, "message": "商户已启用" if status == "active" else "商户已停用"}
        adjust = b.get("adjust_cents", "")
        if str(adjust) != "":
            delta = int(adjust)
            if delta == 0:
                return err("调整金额不能为 0")
            after = target.api_balance_cents + delta
            target.api_balance_cents = after
            db.add(FeeLedger(
                merchant_id=target.id, delta_cents=delta, balance_after_cents=after,
                reason="recharge" if delta > 0 else "admin_adjust",
                note=str(b.get("note", "") or ("管理员手动充值" if delta > 0 else "管理员调整")),
                created_at=datetime.now(),
            ))
            db.commit()
            return {"ok": True, "message": "余额已调整", "balanceAfterCents": after}
    return err("请提供 status 或 adjust_cents")


@router.post("/console/api/admin/product/delete")
async def admin_product_delete(request: Request):
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    b = await request.json()
    pid = int(b.get("id", 0))
    with SessionLocal() as db:
        product = db.get(Product, pid)
        if not product:
            return err("商品不存在", 404)
        db.delete(product)
        db.commit()
    return {"ok": True, "message": "商品已删除"}


# ═══════════════ 平台通知 ═══════════════
@router.get("/console/admin-notices")
def admin_notices_page(request: Request):
    """管理员:平台通知管理页"""
    me, resp = _need(request, admin=True)
    return resp or render(request, "admin_notices.html", {})


@router.get("/console/api/notices")
def api_notices(request: Request):
    """商户/管理员:通知列表(按时间倒序)"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    with SessionLocal() as db:
        rows = db.query(Notice).order_by(Notice.id.desc()).limit(200).all()
        out = [{
            "id": n.id, "title": n.title, "content": n.content,
            "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "",
        } for n in rows]
    return {"ok": True, "notices": out}


@router.get("/console/api/admin/notices")
def admin_notices_list(request: Request):
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    with SessionLocal() as db:
        rows = db.query(Notice).order_by(Notice.id.desc()).limit(200).all()
        out = [{
            "id": n.id, "title": n.title, "content": n.content,
            "created_at": n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "",
        } for n in rows]
    return {"ok": True, "notices": out}


@router.post("/console/api/admin/notices")
async def admin_notices_create(request: Request):
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    b = await request.json()
    title = str(b.get("title", "")).strip()
    content = str(b.get("content", "")).strip()
    if not title:
        return err("请填写通知标题")
    with SessionLocal() as db:
        db.add(Notice(title=title[:200], content=content[:2000], created_at=datetime.now()))
        db.commit()
    return {"ok": True, "message": "通知已发布"}


@router.post("/console/api/admin/notices/delete")
async def admin_notices_delete(request: Request):
    me = _me(request)
    if not me or me.role != "admin":
        return err("仅管理员可操作", 403)
    b = await request.json()
    nid = int(b.get("id", 0))
    with SessionLocal() as db:
        row = db.get(Notice, nid)
        if not row:
            return err("通知不存在", 404)
        db.delete(row)
        db.commit()
    return {"ok": True, "message": "已删除"}


@router.post("/console/api/product/sort")
async def product_sort(request: Request):
    """保存商品的拖拽展示顺序(全量):ids 按展示从前到后,写库 sort_order。"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids:
        return err("无效的排序数据")
    clean, seen = [], set()
    for x in ids:
        try:
            v = int(x)
        except (ValueError, TypeError):
            continue
        if v not in seen:
            seen.add(v)
            clean.append(v)
    if not clean:
        return err("无效的排序数据")
    from sqlalchemy import case
    with SessionLocal() as db:
        mine = {pid for (pid,) in db.query(Product.id).filter(Product.merchant_id == me.id).all()}
        # 先统一重置,未在本列表中的项排最后
        db.query(Product).filter(Product.merchant_id == me.id).update({"sort_order": 1000000})
        pairs = [(pid, i) for i, pid in enumerate(clean) if pid in mine]
        if pairs:
            whens = {pid: i for pid, i in pairs}
            expr = case(whens, value=Product.id, else_=Product.sort_order)
            db.query(Product).filter(Product.id.in_([p for p, _ in pairs])).update({Product.sort_order: expr})
        db.commit()
    return {"ok": True, "message": "排序已保存"}


@router.post("/console/api/category/sort")
async def category_sort(request: Request):
    """保存分类展示顺序(cats 按从前到后)。

    分类顺序写进独立分类表 product_categories.sort_order;
    同时把该顺序下沉到商品的 sort_order,保证前台按此展示分类目录。
    """
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    cats = b.get("cats")
    if not isinstance(cats, list) or not cats:
        return err("无效的排序数据")
    clean, seen = [], set()
    for x in cats:
        c = str(x or "")
        if c and c not in seen:
            seen.add(c)
            clean.append(c)
    if not clean:
        return err("无效的排序数据")
    with SessionLocal() as db:
        categories.sort_categories(db, me.id, clean)
        for i, cat in enumerate(clean):
            db.query(Product).filter(
                Product.merchant_id == me.id, Product.category == cat
            ).update({"sort_order": i * 100})
        db.commit()
    return {"ok": True, "message": "分类排序已保存"}


@router.post("/console/api/category/save")
async def category_save(request: Request):
    """新增 / 编辑分类(仅分类自身:名称 + 图标)。

    传 id=0 或省略 => 新增;传 id => 编辑。
    """
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    try:
        cid = int(b.get("id") or 0)
    except (TypeError, ValueError):
        cid = 0
    name = b.get("name")
    icon = b.get("icon_url")
    with SessionLocal() as db:
        if cid:
            r = categories.update_category(
                db, me.id, cid,
                name=(str(name) if name is not None else None),
                icon_url=(str(icon) if icon is not None else None),
            )
        else:
            r = categories.create_category(db, me.id, str(name or ""), str(icon or ""))
    if not r.get("ok"):
        return err(r.get("message") or "保存失败")
    return {"ok": True, "message": r.get("message") or "已保存"}


@router.post("/console/api/category/delete")
async def category_delete(request: Request):
    """删除分类(分类下仍有商品时拒绝)。"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    b = await request.json()
    try:
        cid = int(b.get("id") or 0)
    except (TypeError, ValueError):
        cid = 0
    if not cid:
        return err("缺分类 id")
    with SessionLocal() as db:
        r = categories.delete_category(db, me.id, cid)
    if not r.get("ok"):
        return err(r.get("message") or "删除失败")
    return {"ok": True, "message": r.get("message") or "分类已删除"}


# ── 爱发电回调测试日志(管理员) ─────────────────────────────
@router.get("/console/afdian-callback-logs")
def afdian_callback_logs_page(request: Request):
    me, resp = _need(request, admin=True)
    return resp or render(request, "afdian_logs.html", {"title": "回调记录", "badge": "收到日志"})


@router.get("/console/api/afdian-callback-logs")
def afdian_callback_logs_list(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    if me.role != "admin":
        return err("仅管理员可查看", 403)
    from .db import AfdianWebhookLog as _W
    limit = min(60, max(1, int(request.query_params.get("limit", 30) or 30)))
    items = []
    with SessionLocal() as db:
        rows = db.query(_W).order_by(_W.created_at.desc()).limit(limit).all()
        for r in rows:
            items.append({
                "id": r.id,
                "order_no": r.order_no or "",
                "matched": bool(r.matched),
                "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
                "body_text": r.body_text or "",
            })
    return {"ok": True, "items": items}


@router.post("/console/api/account/afd_live_probe")
async def afd_live_probe(request: Request):
    me = _me(request)
    if not me:
        return err("未登录", 401)
    if me.role != "admin":
        return err("仅管理员可操作", 403)
    b = {}
    try:
        _j = await request.json() or {}
        if isinstance(_j, dict):
            b = _j
    except Exception:  # noqa: BLE001
        pass
    if not b:
        try:
            b = dict(await request.form())
        except Exception:  # noqa: BLE001
            pass
    from .services.afd_login import consumer_ensure_token as _ensure
    from .services import afd_live as _live
    amount = float(b.get("amount") or 0)
    if amount < 5:
        return err("金额最低 5 元")
    remark = str(b.get("remark") or "售后验证").strip()
    creator = str(b.get("creator") or "").strip() or (me.afdian_user_id or "").strip()
    if not creator:
        return err("请传收款 user_id creator(或管理员先绑定爱发电 user_id)")
    pm = str(b.get("pay") or "wechat").lower()
    pay = _live.PAY_TYPES.get(pm)
    if not pay:
        return err("支付方式仅 wechat/alipay")
    tok_res = _ensure()
    if not tok_res.get("ok") or not tok_res.get("token"):
        return err("consumer auth 不可用," + str(tok_res.get("em")))
    r = _live.live_create(creator, tok_res["token"], amount, remark, pay["py_type"])
    return JSONResponse({
        "ok": bool(r.get("ok")), "message": r.get("message", ""),
        "creator": creator, "amount": amount, "pay": pm,
        "data": r.get("data"), "raw": r.get("raw", ""),
    })


@router.get("/console/api/afd-gc-status")
def afd_gc_status(request: Request):
    """后台观察:过期未付单清理。
    ?run=1 当场跑一次惰性删除并回 deleted/error(否则仅统计 pending/过期,不删)。"""
    me = _me(request)
    if not me:
        return err("未登录", 401)
    if me.role != "admin":
        return err("仅管理员", 403)
    from datetime import datetime, timedelta
    from .services import pipeline as _p
    cutoff = datetime.now() - timedelta(hours=3)
    with SessionLocal() as db:
        expired = db.query(Order).filter(
            Order.status != "paid", Order.created_at < cutoff
        ).count()
        pending = db.query(Order).filter(
            Order.status == "pending"
        ).count()
        recent = db.query(Order).filter(
            Order.status != "paid", Order.created_at < cutoff
        ).order_by(Order.created_at.desc()).limit(3).all()
    sample = [
        {"no": o.order_no, "status": o.status, "created": o.created_at.strftime("%Y-%m-%d %H:%M:%S") if o.created_at else ""}
        for o in recent
    ]
    out = {"ok": True, "expired_pending": expired, "total_pending": pending,
           "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "cutoff": cutoff.strftime("%Y-%m-%d %H:%M:%S"), "sample": sample}
    if request.query_params.get("run") == "1":
        out["clean_run"] = _p.gc_stale_pending()
    return JSONResponse(out)
