"""店铺分类服务(独立分类表 product_categories)。

设计要点(开发阶段,不做向后兼容):
- 分类是独立实体:名称 / 图标 / 排序都在本表;
- 商品通过 products.category_id(外键) 关联分类,改名/换图标只动分类表一行;
- 订单、邮件里的分类名是「下单时的快照」,不随分类改名而变(历史留档)。
"""
import logging

from ..db import Product, ProductCategory, StockCard

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
    row = ProductCategory(
        merchant_id=merchant_id, name=name,
        icon_url=(icon_url or "").strip()[:500], sort_order=_next,
    )
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


def delete_category(db, merchant_id: int, cat_id: int, with_products: bool = False) -> dict:
    """删除分类。

    - 默认：分类下还有商品则拒绝（避免误删）；
    - with_products=True：连同该分类下所有商品一起删除（含其卡密库存）。
      订单表 orders 不动 —— 里面存的是下单时的分类/标题/SKU 快照，历史留档。
    """
    row = db.get(ProductCategory, cat_id)
    if not row or row.merchant_id != merchant_id:
        return {"ok": False, "message": "分类不存在或无权操作"}
    _prods = (
        db.query(Product)
        .filter(Product.merchant_id == merchant_id, Product.category_id == row.id)
        .all()
    )
    if _prods and not with_products:
        return {"ok": False, "message": f"该分类下还有 {len(_prods)} 个商品，请先删除或移走这些商品",
                "product_count": len(_prods), "need_confirm": True}
    _deleted_products = 0
    _deleted_cards = 0
    for p in _prods:
        _deleted_cards += delete_product_cascade(db, p)
        _deleted_products += 1
    db.delete(row)
    db.commit()
    if _deleted_products:
        return {"ok": True,
                "message": f"分类及 {_deleted_products} 个商品已删除（含 {_deleted_cards} 条卡密）"}
    return {"ok": True, "message": "分类已删除"}


def delete_product_cascade(db, product) -> int:
    """删除商品并清理其卡密库存，返回删除的卡密条数。调用方负责 commit。"""
    n = 0
    try:
        n = (
            db.query(StockCard)
            .filter(StockCard.product_id == product.id)
            .delete(synchronize_session=False)
        ) or 0
    except Exception:  # noqa: BLE001
        n = 0
    db.delete(product)
    return int(n)


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
