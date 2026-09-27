"""平台订单对账(兜底 Webhook 漏推)。

背景:爱发电官方文档明确写着 Webhook「如果服务器异常,可能不保证能及时推送,
因此建议结合 API 一起使用」。一旦漏推,本地订单会永远停在 pending,买家付了钱
却拿不到货。

做法:用**平台消费者账号**(管理员在个人中心填的那个)的 auth_token 拉一份
「已支付」订单列表,把本地漏掉付款的订单补推进成已付款。

★ 判据(两条必须同时满足,缺一不可):
    ① title 含「自选发电」              —— 本站商品在爱发电侧的标题形态
    ② remark(留言) 里至少有 3 个 '&'    —— 本站下单写入的 "分类&标题&SKU&价格"
  只靠 remark 会被别人的留言蒙混,只靠 title 会被同名的非本站商品蒙混,故两条并用。

★ 只对「本地已存在」的订单补推进:
  pipeline.mark_order_paid() 对「本地没有」返回 None、对「已付款」幂等返回,
  所以本地没有的订单天然不会被新建(与「只补状态、不补建」的口径一致)。

★ 节流:进程内记上次执行时间,默认 90 秒内不重复跑,免得每个页面请求都去打爱发电。
  多 worker 下最多各跑一次,而补推进本身幂等,无副作用。
★ 静默:任何异常都吞掉并记日志,绝不因对账失败而影响页面渲染。

本模块与 afdian.test_connection 是**两个独立功能**:
  · test_connection —— 商户向,验证该商户自己填的 user_id/token 是否有效;
  · 本模块          —— 平台向,用平台消费者账号把本站产生的订单数据补齐。
"""

import logging
import threading
import time

from ..db import Order, SessionLocal
from . import afdian, afd_login, pipeline

log = logging.getLogger("afdianpu.reconcile")

_SELF_MARK = "自选发电"   # 本站商品在爱发电侧的标题特征
_MIN_AMP = 3              # 留言里至少这么多个 '&'

_lock = threading.Lock()
_last_run = 0.0


def is_platform_order(row: dict) -> bool:
    """判断一条爱发电订单是不是本站产生的(两条判据缺一不可)。"""
    title = str((row or {}).get("title") or "")
    remark = str((row or {}).get("remark") or "")
    return (_SELF_MARK in title) and (remark.count("&") >= _MIN_AMP)


def reconcile_platform_orders(min_interval: float = 5.0, force: bool = False) -> dict:
    """跑一次平台订单对账(带节流,默认 5 秒内不重复)。

    与 afdian.fetch_sponsored_bills 内部的节流并存:这里管「别太频繁走进对账流程」,
    那里管「别太频繁真去打爱发电」。返回统计字典;永不抛异常。
    """
    global _last_run
    now = time.time()
    with _lock:
        if not force and (now - _last_run) < max(min_interval, 0):
            return {"ok": True, "skipped": True, "reason": "节流中",
                    "checked": 0, "matched": 0, "fixed": []}
        _last_run = now
    try:
        return _run()
    except Exception as e:  # noqa: BLE001
        log.warning("平台订单对账异常: %s", e)
        return {"ok": False, "skipped": False, "reason": str(e),
                "checked": 0, "matched": 0, "fixed": []}


def _run() -> dict:
    """实际执行:取 token → 拉已支付账单 → 筛本站单 → 补推进。

    会话掉线的处理:平台消费者账号的账密存在平台配置里,afd_login.consumer_ensure_token()
    本身就会在「token 过期」时自动重新登录;这里额外补一层——如果**拉取失败**
    (常见于会话已被服务端作废、但本地时间戳还没到过期),就强制重登一次再用新 token 重试。
    """
    got = afd_login.consumer_ensure_token(force=False)
    token = str(got.get("token") or "")
    if not token:
        got = afd_login.consumer_ensure_token(force=True)   # 本地压根没 token → 强制登一次
        token = str(got.get("token") or "")
    if not token:
        return {"ok": False, "skipped": False,
                "reason": "平台消费者账号未登录:" + str(got.get("em") or ""),
                "checked": 0, "matched": 0, "fixed": []}

    ok, items, msg = afdian.fetch_sponsored_bills(token, page=1)
    if not ok:
        # 拉取失败 → 强制重登换新 token 再试一次(min_interval=0 绕过节流,这次是新会话)
        refreshed = afd_login.consumer_ensure_token(force=True)
        token2 = str(refreshed.get("token") or "")
        if token2 and token2 != token:
            ok, items, msg = afdian.fetch_sponsored_bills(token2, page=1, min_interval=0)
    if not ok:
        return {"ok": False, "skipped": False, "reason": msg,
                "checked": 0, "matched": 0, "fixed": []}
    matched = [r for r in items if is_platform_order(r)]

    # 先只读地筛出「本地存在且仍不是 paid」的订单号,关掉 session 后再逐个补推进,
    # 避免与 mark_order_paid 自己开的 session 叠在一起。
    todo = []
    with SessionLocal() as db:
        for r in matched:
            order_no = str(r.get("out_trade_no") or "").strip()
            if not order_no:
                continue
            row = db.query(Order.order_no, Order.status).filter(Order.order_no == order_no).first()
            if row and row.status != "paid":
                todo.append(order_no)

    fixed = []
    for order_no in todo:
        if pipeline.mark_order_paid(order_no):
            fixed.append(order_no)
    if fixed:
        log.info("平台订单对账:补推进 %s 单 %s", len(fixed), fixed)
    return {"ok": True, "skipped": False, "reason": msg,
            "checked": len(items), "matched": len(matched), "fixed": fixed}
