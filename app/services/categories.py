"""店铺分类服务(独立分类表 product_categories)。

设计要点:
- 分类的「名称 / 图标 / 排序」以本表为准;商品仍用 products.category(字符串) 关联分类名。
- 兼容迁移:首次访问某商户的分类时,用其现有商品的 (category, category_icon_url)
  自动回填本表,保证老店铺无需手工重建分类。
- 图标一致性:改分类图标时,同步该分类下所有商品的 category_icon_url
  (前台/订单仍读商品字段,避免多处分叉)。
- 改名:可迁移该分类下所有商品的 category 字符串,保持归属不断。
"""
import logging

from ..db import Product, ProductCategory, SessionLocal

log = logging.getLogger("afdianpu.category")


def list_categories(db, merchant_id: int) -> list:
    """取某商户的分类列表(按排序);为空时用现有商品回填。"""
    rows = (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .order_by(ProductCategory.sort_order, ProductCategory.id)
        .all()
    )
    if rows:
        return rows
    # 首次:从现有商品回填(老数据平滑迁移)
    sync_from_products(db, merchant_id)
    return (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .order_by(ProductCategory.sort_order, ProductCategory.id)
        .all()
    )


def map_by_name(db, merchant_id: int) -> dict:
    """{分类名: ProductCategory},便于列表渲染时取图标/排序。"""
    return {c.name: c for c in list_categories(db, merchant_id)}


def sync_from_products(db, merchant_id: int) -> int:
    """把现有商品里出现过的分类回填进分类表(仅补缺失项)。返回新增数。

    排序按商品 sort_order 的最小值,尽量保持原有先后。
    """
    goods = db.query(Product).filter(Product.merchant_id == merchant_id).all()
    if not goods:
        return 0
    order: dict[str, int] = {}
    icon: dict[str, str] = {}
    for p in goods:
        _c = (p.category or "").strip()
        if not _c:
            continue
        _s = int(p.sort_order or 0)
        if _c not in order or _s < order[_c]:
            order[_c] = _s
        if not icon.get(_c) and (p.category_icon_url or "").strip():
            icon[_c] = p.category_icon_url.strip()
    existing = {
        c.name
        for c in db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .all()
    }
    added = 0
    for _c, _s in sorted(order.items(), key=lambda kv: kv[1]):
        if _c in existing:
            continue
        db.add(ProductCategory(merchant_id=merchant_id, name=_c,
                               icon_url=icon.get(_c, ""), sort_order=_s))
        added += 1
    if added:
        db.commit()
    return added


def get_or_create(db, merchant_id: int, name: str) -> ProductCategory | None:
    """按名取分类,不存在则创建(商品保存时自动补分类,保证分类表不落后)。"""
    name = (name or "").strip()
    if not name:
        return None
    row = (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id, ProductCategory.name == name)
        .first()
    )
    if row:
        return row
    _max = (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .order_by(ProductCategory.sort_order.desc())
        .first()
    )
    _next = (int(_max.sort_order or 0) + 100) if _max else 0
    row = ProductCategory(merchant_id=merchant_id, name=name, icon_url="", sort_order=_next)
    db.add(row)
    db.flush()
    return row


def create_category(db, merchant_id: int, name: str, icon_url: str = "") -> dict:
    """新增分类(仅分类自身,不涉及任何商品)。"""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "message": "分类名不能为空"}
    if len(name) > 16:
        return {"ok": False, "message": f"分类最多16字，当前{len(name)}字"}
    if "&" in name:
        return {"ok": False, "message": "分类名不允许包含 & 符号"}
    dup = (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id, ProductCategory.name == name)
        .first()
    )
    if dup:
        return {"ok": False, "message": "该分类已存在"}
    _max = (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .order_by(ProductCategory.sort_order.desc())
        .first()
    )
    _next = (int(_max.sort_order or 0) + 100) if _max else 0
    row = ProductCategory(merchant_id=merchant_id, name=name,
                          icon_url=(icon_url or "").strip()[:500], sort_order=_next)
    db.add(row)
    db.commit()
    return {"ok": True, "message": "分类已创建", "id": row.id}


def update_category(db, merchant_id: int, cat_id: int, name: str = None,
                    icon_url: str = None) -> dict:
    """编辑分类(名称 / 图标)。改名会同时迁移该分类下所有商品的 category。"""
    row = db.get(ProductCategory, cat_id)
    if not row or row.merchant_id != merchant_id:
        return {"ok": False, "message": "分类不存在或无权操作"}
    old_name = row.name
    if name is not None:
        n = (name or "").strip()
        if not n:
            return {"ok": False, "message": "分类名不能为空"}
        if len(n) > 16:
            return {"ok": False, "message": f"分类最多16字，当前{len(n)}字"}
        if "&" in n:
            return {"ok": False, "message": "分类名不允许包含 & 符号"}
        if n != old_name:
            dup = (
                db.query(ProductCategory)
                .filter(ProductCategory.merchant_id == merchant_id,
                        ProductCategory.name == n, ProductCategory.id != cat_id)
                .first()
            )
            if dup:
                return {"ok": False, "message": "已存在同名分类"}
            row.name = n
            # 迁移该分类下商品的归属(保持不断链)
            db.query(Product).filter(
                Product.merchant_id == merchant_id, Product.category == old_name
            ).update({"category": n}, synchronize_session=False)
    if icon_url is not None:
        ic = (icon_url or "").strip()[:500]
        row.icon_url = ic
        # 图标一致性:同步该分类下所有商品(前台/订单仍读商品字段)
        db.query(Product).filter(
            Product.merchant_id == merchant_id, Product.category == row.name
        ).update({"category_icon_url": ic}, synchronize_session=False)
    db.commit()
    return {"ok": True, "message": "分类已更新"}


def delete_category(db, merchant_id: int, cat_id: int) -> dict:
    """删除分类。若该分类下仍有商品则拒绝(避免商品变成无归属分类)。"""
    row = db.get(ProductCategory, cat_id)
    if not row or row.merchant_id != merchant_id:
        return {"ok": False, "message": "分类不存在或无权操作"}
    n = (
        db.query(Product)
        .filter(Product.merchant_id == merchant_id, Product.category == row.name)
        .count()
    )
    if n > 0:
        return {"ok": False, "message": f"该分类下还有 {n} 个商品，请先删除或移走这些商品"}
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "分类已删除"}


def sort_categories(db, merchant_id: int, names: list) -> dict:
    """按给定分类名顺序重排(写回 sort_order)。"""
    clean = []
    seen = set()
    for x in names or []:
        c = str(x or "").strip()
        if c and c not in seen:
            seen.add(c)
            clean.append(c)
    if not clean:
        return {"ok": False, "message": "排序数据为空"}
    rows = {
        c.name: c
        for c in db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .all()
    }
    for i, name in enumerate(clean):
        if name in rows:
            rows[name].sort_order = i * 100
    db.commit()
    return {"ok": True, "message": "分类排序已保存"}
