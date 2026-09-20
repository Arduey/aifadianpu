"""店铺分类服务(独立分类表 product_categories)。

设计要点(开发阶段,不做向后兼容):
- 分类是独立实体:名称 / 图标 / 排序都在本表;
- 商品通过 products.category_id(外键) 关联分类,改名/换图标只动分类表一行;
- 订单、邮件里的分类名是「下单时的快照」,不随分类改名而变(历史留档)。
"""
import logging

from ..db import Product, ProductCategory, SessionLocal

log = logging.getLogger("afdianpu.category")


def list_categories(db, merchant_id: int) -> list:
    """取某商户的分类列表(按排序)。"""
    return (
        db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .order_by(ProductCategory.sort_order, ProductCategory.id)
        .all()
    )


def map_by_id(db, merchant_id: int) -> dict:
    """{分类id: ProductCategory}"""
    return {c.id: c for c in list_categories(db, merchant_id)}


def map_by_name(db, merchant_id: int) -> dict:
    """{分类名: ProductCategory}"""
    return {c.name: c for c in list_categories(db, merchant_id)}
            continue
        db.add(ProductCategory(merchant_id=merchant_id, name=_c,
                               icon_url=icon.get(_c, ""), sort_order=_s))
        added += 1
    if added:
        db.commit()
    return added


def get_by_id(db, merchant_id: int, cat_id: int) -> ProductCategory | None:
    """按 id 取分类(校验归属商户)。"""
    if not cat_id:
        return None
    row = db.get(ProductCategory, int(cat_id))
    if not row or row.merchant_id != merchant_id:
        return None
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
    """编辑分类(名称 / 图标)。商品通过 category_id 关联,改名无需迁移商品。"""
    row = db.get(ProductCategory, cat_id)
    if not row or row.merchant_id != merchant_id:
        return {"ok": False, "message": "分类不存在或无权操作"}
    if name is not None:
        n = (name or "").strip()
        if not n:
            return {"ok": False, "message": "分类名不能为空"}
        if len(n) > 16:
            return {"ok": False, "message": f"分类最多16字，当前{len(n)}字"}
        if "&" in n:
            return {"ok": False, "message": "分类名不允许包含 & 符号"}
        if n != row.name:
            dup = (
                db.query(ProductCategory)
                .filter(ProductCategory.merchant_id == merchant_id,
                        ProductCategory.name == n, ProductCategory.id != cat_id)
                .first()
            )
            if dup:
                return {"ok": False, "message": "已存在同名分类"}
            row.name = n
    if icon_url is not None:
        row.icon_url = (icon_url or "").strip()[:500]
    db.commit()
    return {"ok": True, "message": "分类已更新"}


def delete_category(db, merchant_id: int, cat_id: int) -> dict:
    """删除分类。若该分类下仍有商品则拒绝(避免商品悬空)。"""
    row = db.get(ProductCategory, cat_id)
    if not row or row.merchant_id != merchant_id:
        return {"ok": False, "message": "分类不存在或无权操作"}
    n = (
        db.query(Product)
        .filter(Product.merchant_id == merchant_id, Product.category_id == row.id)
        .count()
    )
    if n > 0:
        return {"ok": False, "message": f"该分类下还有 {n} 个商品，请先删除或移走这些商品"}
    db.delete(row)
    db.commit()
    return {"ok": True, "message": "分类已删除"}


def sort_categories(db, merchant_id: int, ids: list) -> dict:
    """按给定分类 id 顺序重排(写回 sort_order)。"""
    clean = []
    seen = set()
    for x in ids or []:
        try:
            v = int(x)
        except (TypeError, ValueError):
            continue
        if v not in seen:
            seen.add(v)
            clean.append(v)
    if not clean:
        return {"ok": False, "message": "排序数据为空"}
    rows = {
        c.id: c
        for c in db.query(ProductCategory)
        .filter(ProductCategory.merchant_id == merchant_id)
        .all()
    }
    for i, cid in enumerate(clean):
        if cid in rows:
            rows[cid].sort_order = i * 100
    db.commit()
    return {"ok": True, "message": "分类排序已保存"}
