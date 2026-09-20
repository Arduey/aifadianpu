"""平台发货服务(SKU 级)。

三种发货方式(由 Product.delivery_type / delivery_kind 决定):
  merchant             商户发货(默认):平台只回调 Webhook/邮件,不发放内容
  platform + card      平台发货·卡密:商户预存卡密,下单锁定,付款后自助提货
  platform + link      平台发货·链接:付款后返回商户配置的链接(无库存限制)

卡密生命周期:
  下单   → lock_card(product_id, order_no)  抢占一个空闲卡密(locked=1, order_no=订单号)
  付款   → mark_paid(order_no)              该卡密 used_at=付款时间
  清理   → release_order(order_no)          未付款订单被清时,释放回库存(locked=0)
  提货   → ensure_delivery(db, order)       读 delivery_records;没有则现场发放并落库(幂等)

库存 = 该 product_id 下 locked=0 且 used_at IS NULL 的卡密数。
"""
import logging
from datetime import datetime

from ..db import DeliveryRecord, Order, Product, SessionLocal, StockCard

log = logging.getLogger("afdianpu.delivery")


def is_platform_delivery(p: Product) -> bool:
    return (getattr(p, "delivery_type", "merchant") or "merchant") == "platform" and \
           (getattr(p, "delivery_kind", "") or "") in ("card", "link")


def is_card_type(p: Product) -> bool:
    return (getattr(p, "delivery_type", "merchant") or "merchant") == "platform" and \
           (getattr(p, "delivery_kind", "") or "") == "card"


def is_link_type(p: Product) -> bool:
    return (getattr(p, "delivery_type", "merchant") or "merchant") == "platform" and \
           (getattr(p, "delivery_kind", "") or "") == "link"


def is_limited(p: Product) -> bool:
    """是否为「限购总量」类商品(商户发货 / 链接发货且设了上限)"""
    if is_card_type(p):
        return False
    return int(getattr(p, "stock_limit", 0) or 0) > 0


def limited_sold(db, product_id: int) -> int:
    """限购类商品的已售数量(已付款订单数)"""
    if not product_id:
        return 0
    return int(
        db.query(Order).filter(Order.product_id == product_id, Order.status == "paid").count()
    )


def limited_left(db, p: Product) -> int:
    """限购类商品剩余可售量;不限量返回 -1"""
    _lim = int(getattr(p, "stock_limit", 0) or 0)
    if _lim <= 0 or is_card_type(p):
        return -1
    return max(_lim - limited_sold(db, p.id), 0)


def limited_left_map(db, products) -> dict:
    """批量:限购商品剩余量 {product_id: left}"""
    out = {}
    ids = []
    for p in products or []:
        if is_limited(p):
            ids.append(p.id)
            out[p.id] = int(getattr(p, "stock_limit", 0) or 0)
    if not ids:
        return out
    rows = (
        db.query(Order.product_id)
        .filter(Order.product_id.in_(ids), Order.status == "paid")
        .all()
    )
    for (pid,) in rows:
        if pid in out:
            out[pid] = out[pid] - 1
    for k in list(out.keys()):
        out[k] = max(out[k], 0)
    return out


# ── 库存统计 ──────────────────────────────────────────────

def stock_count(db, product_id: int) -> int:
    """可售库存 = 未锁定且未售出"""
    if not product_id:
        return 0
    return int(
        db.query(StockCard)
        .filter(StockCard.product_id == product_id,
                StockCard.locked.is_(False),
                StockCard.used_at.is_(None))
        .count()
    )


def cards_stats(db, product_id: int) -> dict:
    """卡密汇总:{available, locked, used, total}"""
    if not product_id:
        return {"available": 0, "locked": 0, "used": 0, "total": 0}
    rows = db.query(StockCard).filter(StockCard.product_id == product_id).all()
    used = sum(1 for r in rows if r.used_at is not None)
    locked = sum(1 for r in rows if r.used_at is None and r.locked)
    available = sum(1 for r in rows if r.used_at is None and not r.locked)
    return {"available": available, "locked": locked, "used": used, "total": len(rows)}


def stock_map(db, product_ids) -> dict:
    """批量库存统计(前台列表用):{product_id: 可售库存}"""
    ids = [int(i) for i in (product_ids or []) if i]
    if not ids:
        return {}
    rows = (
        db.query(StockCard)
        .filter(StockCard.product_id.in_(ids),
                StockCard.locked.is_(False),
                StockCard.used_at.is_(None))
        .all()
    )
    out = {i: 0 for i in ids}
    for r in rows:
        out[r.product_id] = out.get(r.product_id, 0) + 1
    return out


# ── 卡密导入 / 删除 ───────────────────────────────────────

def import_cards(db, product_id: int, merchant_id: int, text: str) -> dict:
    """按行导入卡密,**同一商户下所有商品之间去重**(与已有卡密及本批次内部均去重)。

    返回 {added, dup, empty, dup_other}  added=新增, dup=重复跳过, empty=空行跳过,
    dup_other=其中属于「本商户其它商品已有」的重复数(便于提示商户)。
    """
    if not product_id:
        return {"added": 0, "dup": 0, "empty": 0, "dup_other": 0}
    raw_lines = str(text or "").splitlines()
    lines = [ln.strip() for ln in raw_lines]
    lines = [ln for ln in lines if ln]
    empty_skipped = len(raw_lines) - len(lines) if text else 0
    if not lines:
        return {"added": 0, "dup": 0, "empty": 0, "dup_other": 0}

    # 同商户全部商品的已有卡密(含其它商品) —— 卡密在商户内全局唯一
    _existing = db.query(StockCard.content, StockCard.product_id).filter(
        StockCard.merchant_id == merchant_id
    ).all()
    existing_all = {(c or "").strip() for c, _pid in _existing}
    existing_other = {(c or "").strip() for c, _pid in _existing if _pid != product_id}

    seen = set()
    added = 0
    dup = 0
    dup_other = 0
    for ln in lines:
        if ln in existing_all or ln in seen:
            dup += 1
            if ln in existing_other:
                dup_other += 1
            continue
        seen.add(ln)
        db.add(StockCard(product_id=product_id, merchant_id=merchant_id, content=ln))
        added += 1
    return {"added": added, "dup": dup, "empty": empty_skipped, "dup_other": dup_other}


def list_cards(db, product_id: int, limit: int = 500) -> list:
    """列出卡密(仅状态,不解密):[{id, content, used, locked, order_no}]"""
    rows = (
        db.query(StockCard)
        .filter(StockCard.product_id == product_id)
        .order_by(StockCard.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "content": r.content,
            "locked": bool(r.locked and r.used_at is None),
            "used": bool(r.used_at is not None),
            "order_no": r.order_no or "",
        }
        for r in rows
    ]


def delete_unused_cards(db, product_id: int, merchant_id: int) -> int:
    """删除该商品所有「未锁定且未售出」的卡密,返回删除数(清理库存重导入用)"""
    rows = (
        db.query(StockCard)
        .filter(StockCard.product_id == product_id,
                StockCard.merchant_id == merchant_id,
                StockCard.locked.is_(False),
                StockCard.used_at.is_(None))
        .all()
    )
    n = len(rows)
    for r in rows:
        db.delete(r)
    return n


def prune_duplicate_cards(db, product_id: int, merchant_id: int | None = None) -> int:
    """清理重复卡密(保留最早一条),返回删除数。

    默认按**该商品所属商户的全部商品**去重(与导入规则一致);
    只删除「未锁定且未售出」的重复项,已售出/已锁定的永远保留。
    """
    if not merchant_id:
        _p = db.get(Product, product_id)
        merchant_id = getattr(_p, "merchant_id", 0) if _p else 0
    if not merchant_id:
        return 0
    rows = (
        db.query(StockCard)
        .filter(StockCard.merchant_id == merchant_id)
        .order_by(StockCard.id)
        .all()
    )
    seen = set()
    n = 0
    for r in rows:
        key = (r.content or "").strip()
        if key in seen:
            # 已被订单占用或已售出的不删,避免影响买家已领取的内容
            if r.used_at is None and not r.locked:
                db.delete(r)
                n += 1
        else:
            seen.add(key)
    return n


# ── 锁定 / 释放 / 核销 ────────────────────────────────────

def lock_card(db, product_id: int, order_no: str) -> str:
    """下单时抢占一个空闲卡密并绑定订单号。成功返回卡密内容,无库存返回 ""。

    用 SELECT ... FOR UPDATE 防并发超卖(MySQL 支持)。
    """
    if not product_id or not order_no:
        return ""
    q = (
        db.query(StockCard)
        .filter(StockCard.product_id == product_id,
                StockCard.locked.is_(False),
                StockCard.used_at.is_(None))
        .order_by(StockCard.id)
    )
    try:
        row = q.with_for_update().first()
    except Exception:  # noqa: BLE001  某些驱动/方言不支持 FOR UPDATE 时降级
        row = q.first()
    if row is None:
        return ""
    row.locked = True
    row.order_no = order_no
    row.locked_at = datetime.now()
    return row.content or ""


def release_order(db, order_no: str) -> int:
    """释放某订单锁定的卡密(订单被清理 / 下单失败回滚)。返回释放数。"""
    if not order_no:
        return 0
    rows = (
        db.query(StockCard)
        .filter(StockCard.order_no == order_no, StockCard.used_at.is_(None))
        .all()
    )
    for r in rows:
        r.locked = False
        r.order_no = ""
        r.locked_at = None
    return len(rows)


def mark_paid(db, order_no: str) -> int:
    """付款成功:把该订单锁定的卡密标记为已售出(used_at=付款时间)。返回条数。"""
    if not order_no:
        return 0
    rows = db.query(StockCard).filter(StockCard.order_no == order_no).all()
    n = 0
    for r in rows:
        if r.used_at is None:
            r.used_at = datetime.now()
            r.locked = True
            n += 1
    return n


# ── 发放(提货核心,幂等) ─────────────────────────────────

def ensure_delivery(db, order) -> dict:
    """确保该订单有发放记录,返回 {kind, content, tip, needs_manual}。

    幂等:delivery_records 里已有该 order_no 则直接返回历史内容。
    仅对「平台发货」类型发放;商户发货返回 needs_manual=True。
    """
    order_no = getattr(order, "order_no", "") or ""
    if not order_no:
        return {"kind": "", "content": "", "tip": "", "needs_manual": True}

    rec = db.query(DeliveryRecord).filter(DeliveryRecord.order_no == order_no).first()
    tip = ""
    p = None
    if getattr(order, "product_id", None):
        p = db.get(Product, order.product_id)
    if p is not None:
        tip = getattr(p, "delivery_tip", "") or ""

    if rec is not None:
        return {"kind": rec.kind, "content": rec.content, "tip": tip,
                "needs_manual": rec.kind == ""}

    kind = ""
    content = ""
    if p is not None and is_card_type(p):
        # 优先取已锁定给本订单的卡密;没有则现场抢一个(兼容历史/异常单)
        row = (
            db.query(StockCard)
            .filter(StockCard.order_no == order_no, StockCard.product_id == p.id)
            .order_by(StockCard.id)
            .first()
        )
        if row is None:
            lock_card(db, p.id, order_no)
            row = (
                db.query(StockCard)
                .filter(StockCard.order_no == order_no, StockCard.product_id == p.id)
                .order_by(StockCard.id)
                .first()
            )
        if row is not None:
            if row.used_at is None:
                row.used_at = datetime.now()
            row.locked = True
            kind = "card"
            content = row.content or ""
    elif p is not None and is_link_type(p):
        kind = "link"
        content = getattr(p, "delivery_link", "") or ""

    if kind:
        db.add(DeliveryRecord(order_no=order_no, product_id=getattr(order, "product_id", None),
                              merchant_id=getattr(order, "merchant_id", 0) or 0,
                              kind=kind, content=content))
    return {"kind": kind, "content": content, "tip": tip, "needs_manual": kind == ""}
