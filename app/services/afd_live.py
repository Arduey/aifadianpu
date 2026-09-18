"""爱发电「真实网页/内部下单」对照 Arduey/store 的收链版（stage A 探针）。只读测试,不接 page。

凭证约定:
- 请求/轮询用「平台配置持久化的消费者 auth_token」(见 afd_login)
- body.user_id = 真实收款方爱发电账号(通常管理员/商户绑定的 afdian_user_id)

请求优先用 curl_cffi 模拟浏览器 TLS/指纹(绕爱发电前置 Cloudflare 1010 拦截);
未安装 curl_cffi 时回退标准库 urllib(会被 1010 拒,仅作兜底不崩)。
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

try:  # 浏览器指纹伪装(可选依赖);服务器建议 pip install curl_cffi
    from curl_cffi import requests as _curl_requests  # type: ignore
except Exception:  # noqa: BLE001
    _curl_requests = None

# store 源码里同款基址;版本对齐真实浏览器请求
AFDIAN_API_BASE = "https://ifdian.net"
_AFD_FE_VERSION = "1.22.2"
# curl_cffi 伪装目标(可换 chrome110/chrome120 等)
_IMPERSONATE = "chrome"

# 与 store PAY_TYPES 相同
PAY_TYPES = {
    "wechat": {"py_type": "wpy_qr", "label": "微信"},
    "alipay": {"py_type": "apy", "label": "支付宝"},
}


def _cookie_header(cookies: dict | None) -> dict:
    if not cookies:
        return {}
    return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}


def _urllib_fetch(method: str, url: str, hd: dict, body_bytes=None, timeout: int = 15):
    req = urllib.request.Request(url, data=body_bytes, headers=hd, method=method)
    ctxs = (ssl.create_default_context(), ssl._create_unverified_context())
    last = None
    for ctx in ctxs:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def _post(url, body_bytes, headers, cookies: dict | None = None, timeout: int = 15):
    hd = dict(headers)
    hd.update(_cookie_header(cookies))
    if _curl_requests is not None:
        # 模拟 Chrome 的 TLS/JA3 指纹,绕爱发电前置 Cloudflare 1010 拦截
        r = _curl_requests.post(url, data=body_bytes, headers=hd,
                                impersonate=_IMPERSONATE, timeout=timeout)
        return r.text
    return _urllib_fetch("POST", url, hd, body_bytes, timeout)


def _get(url, headers, cookies: dict | None = None, timeout: int = 10):
    hd = dict(headers)
    hd.update(_cookie_header(cookies))
    if _curl_requests is not None:
        r = _curl_requests.get(url, headers=hd,
                               impersonate=_IMPERSONATE, timeout=timeout)
        return r.text
    return _urllib_fetch("GET", url, hd, None, timeout)


def live_create(creator_user_id: str, auth_token: str, amount: float, remark: str,
                py_type: str = "wpy_qr") -> dict:
    """POST /api/order/create-order（对照 store）。

    返回 {"ok":bool,"raw":…,"data":…,"message":…}
    """
    if creator_user_id and "\u4fee\u6539" in creator_user_id:
        return {"ok": False, "raw": "", "data": None, "message": "收款账号未填写"}
    auth = (auth_token or "").encode("ascii", "ignore").decode("ascii").strip()
    if not auth:
        return {"ok": False, "raw": "", "data": None, "message": "缺少消费者 auth_token(请先在平台配置登录)"}

    body = {
        "plan_id": "", "month": 1, "total_amount": float(amount),
        "out_trade_no": "", "py_type": py_type, "code": "",
        "user_id": creator_user_id,
        "per_month": str(amount), "remark": remark or "",
        "mp_token": -1, "show_amount": float(amount), "user_address_id": "",
        "sku_detail": [], "plan_invite_code": "", "custom_order_id": "",
        "cmid": "", "card_id_list": [], "ticket_round_id": "", "agreement": "",
        "bundle_count": "", "is_cart": "", "cart_order_no": "",
        "pay_cart_order_no": "", "agreement_npp": "", "affiliate_code": "",
    }
    url = f"{AFDIAN_API_BASE}/api/order/create-order"
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "content-type": "application/json; charset=utf-8",
        "origin": AFDIAN_API_BASE,
        "referer": f"{AFDIAN_API_BASE}/order/create?user_id={creator_user_id}",
        "afd-fe-version": _AFD_FE_VERSION,
    }
    cookies = {"auth_token": auth}
    try:
        raw = _post(url, json.dumps(body, ensure_ascii=False).encode("utf-8"), headers, cookies)
        try:
            j = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {"ok": False, "raw": raw[:500], "data": None, "message": "返回非 JSON"}
        ec = int(j.get("ec") or 0)
        if ec != 200:
            return {"ok": False, "raw": raw[:1000], "data": None,
                    "message": f"ec={ec} " + str(j.get("em", ""))}
        return {"ok": True, "raw": raw, "data": j.get("data") or {}, "message": "已创建"}
    except urllib.error.HTTPError as he:  # 4xx/5xx(如403)把正文放进 raw,便于定位
        try:
            _body = he.read(3000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            _body = ""
        return {"ok": False, "raw": _body, "data": None,
                "message": f"HTTP {getattr(he, 'code', '')} 拒绝,详情见 raw"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "raw": "", "data": None, "message": f"请求异常: {e}"}


def live_create_auto(creator_user_id: str, amount: float, remark: str, py_type: str = "wpy_qr") -> dict:
    """下单的无人自动化入口:自动取/续消费者 token;若首次因 token 失效失败,强制重登后再试一次。

    返回 {"ok","raw","data","message","source"};token 完全取不到时 ok=False。
    """
    from . import afd_login
    tok = afd_login.consumer_ensure_token()
    if not tok.get("ok") or not tok.get("token"):
        return {"ok": False, "raw": "", "data": None, "source": "fail",
                "message": tok.get("em") or "消费者账号自动登录失败"}
    r = live_create(creator_user_id, tok["token"], amount, remark, py_type)
    if r.get("ok"):
        r["source"] = tok.get("source")
        return r
    # 首次失败且疑似登录态问题 -> 强制重登再试一次
    if _looks_like_auth_error(r):
        tok2 = afd_login.consumer_ensure_token(force=True)
        if tok2.get("ok") and tok2.get("token") and tok2.get("token") != tok.get("token"):
            r2 = live_create(creator_user_id, tok2["token"], amount, remark, py_type)
            r2["source"] = "relogin"
            return r2
    r["source"] = tok.get("source")
    return r


def live_check_auto(out_trade_no: str) -> dict:
    """查单的无人自动化入口:自动取/续 token;失效则强制重登再试一次。"""
    from . import afd_login
    tok = afd_login.consumer_ensure_token()
    if not tok.get("ok") or not tok.get("token"):
        return {"ok": False, "raw": "", "paid": False, "status": None,
                "message": tok.get("em") or "消费者账号自动登录失败"}
    r = live_check(out_trade_no, tok["token"])
    if r.get("ok"):
        r["source"] = tok.get("source")
        return r
    if _looks_like_auth_error(r):
        tok2 = afd_login.consumer_ensure_token(force=True)
        if tok2.get("ok") and tok2.get("token") and tok2.get("token") != tok.get("token"):
            r2 = live_check(out_trade_no, tok2["token"])
            r2["source"] = "relogin"
            return r2
    r["source"] = tok.get("source")
    return r


def _looks_like_auth_error(r: dict) -> bool:
    """粗判返回是否属于「登录态失效/未登录」,用于决定是否强制重登。"""
    msg = str((r or {}).get("message") or "").lower()
    if not msg:
        return False
    keys = ("login", "未登录", "登录", "token", "auth", "401", "403", "unauthorized", "expire", "过期")
    return any(k in msg for k in keys)


def live_check(out_trade_no: str, auth_token: str) -> dict:
    """GET /api/order/check?out_trade_no=… -> (paid:status==2)。返回 {"ok","paid","raw","status"}。"""
    auth = (auth_token or "").encode("ascii", "ignore").decode("ascii").strip()
    if not auth:
        return {"ok": False, "raw": "", "paid": False, "status": None, "message": "缺少 auth_token"}
    url = f"{AFDIAN_API_BASE}/api/order/check?out_trade_no={urllib.parse.quote(str(out_trade_no))}"
    headers = {
        "accept": "application/json, text/plain, */*",
        "referer": f"{AFDIAN_API_BASE}/order/create",
        "afd-fe-version": _AFD_FE_VERSION,
    }
    try:
        raw = _get(url, headers, {"auth_token": auth})
        j = json.loads(raw)
        ec = int(j.get("ec") or 0)
        if ec != 200:
            return {"ok": False, "raw": raw[:600], "paid": False, "status": None,
                    "message": f"ec={ec} " + str(j.get("em", ""))}
        order = (j.get("data") or {}).get("order") or {}
        status = order.get("status")
        return {"ok": True, "raw": raw, "paid": int(status or 0) == 2, "status": status, "message": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "raw": "", "paid": False, "status": None, "message": f"请求异常: {e}"}
