"""爱发电开放平台封装

本模块当前只保留**商户绑定校验**(只读):`test_connection()` — 用商户的
user_id + token 真请求一次订单查询,`ec=200` 即判定能连通并读取。

注意:真实的「下单 / 查单」链路**不在本模块**,而在 `afd_live.py`
(经 curl_cffi 伪装指纹调用 /api/order/create-order、/api/order/check)。
历史上本文件曾有一个演示用的 `create_order` / `order_paid` 占位实现,
已无任何调用方,已删除。
"""
import hashlib
import json
import ssl
import threading
import time
import urllib.error
import urllib.request


_AFD_API_BASES = (
    "https://api.ifdian.net",
    "https://afdian.net",
    "https://afdian.com",
)

_EC_MSG = {
    400002: "ts 时间过期(签名时间与服务器差>1h)",
    400004: "没有找到对应 token(凭证无效)",
    400005: "签名校验失败(user_id / token / 时间戳不一致)",
}


def _afd_md5(token: str, params_str: str, ts: str, user_id: str) -> str:
    """爱发电签名:sign = md5(token + 'params' + paramsJSON + 'ts' + ts + 'user_id' + user_id)"""
    kv = token + "params" + params_str + "ts" + ts + "user_id" + user_id
    return hashlib.md5(kv.encode("utf-8")).hexdigest()


def test_connection(user_id: str, token: str):
    """用当前商户的 user_id+token 真请求爱发电一次订单查询,校验是否连得上。
    返回 (connected: bool, message: str, detail: str)。只读、不产生订单。"""
    uid = (user_id or "").strip()
    tok = (token or "").strip()
    if not uid or not tok:
        return False, "连接失败:尚未完整填写 user_id 与 token", ""
    params = json.dumps({"page": 1}, separators=(",", ":"), ensure_ascii=True)
    ts = str(int(time.time()))
    sign = _afd_md5(tok, params, ts, uid)
    body = json.dumps({"user_id": uid, "params": params, "ts": int(ts), "sign": sign},
                      ensure_ascii=True).encode("utf-8")
    last_notices = []
    _ctx_verify = ssl.create_default_context()  # 系统 CA 校验
    _ctx_insec = ssl._create_unverified_context()  # 证书降级(纯连通测试)
    for base in _AFD_API_BASES:
        url = base + "/api/open/query-order"
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={
                                         "Content-Type": "application/json",
                                         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36 AfdTest/1.0",
                                         "Accept": "*/*",
                                     })
        raw = None
        ctx_errors = []
        try:
            for ctx in (_ctx_verify, _ctx_insec):
                try:
                    with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
                        raw = resp.read().decode("utf-8", "replace")
                    break
                except Exception as _e:  # noqa: BLE001
                    body_hint = ""
                    try:
                        if isinstance(_e, urllib.error.HTTPError):
                            _b = _e.read(160).decode("utf-8", "replace")
                            body_hint = (" body=" + _b) if _b.strip() else ""
                    except Exception:  # noqa: BLE001
                        pass
                    ctx_errors.append(type(_e).__name__ + ":" + str(getattr(_e, "reason", _e)) + body_hint)
            if raw is None:
                raise RuntimeError(" | ".join(ctx_errors) or "未知连接错误")
            ec = 9_99_999
            em = ""
            data = None
            try:
                j = json.loads(raw)
                ec = int(j.get("ec", ec))
                em = str(j.get("em", ""))
                data = j.get("data")
            except (ValueError, TypeError, AttributeError):
                raw = str(raw)[:200]
            if ec == 200:
                _show = json.dumps({"ec": ec, "em": em, "data": data}, ensure_ascii=False, indent=2) if (em or data is not None) else str(raw)[:300]
                return True, "已连通爱发电(平台返回 ec=200)", "该结果只代表连通并可读取，不代表 user_id/token 已通过业务校验\n爱发电原始返回:\n" + _show
            if ec in _EC_MSG:
                _show = json.dumps({"ec": ec, "em": em, "data": data}, ensure_ascii=False, indent=2) if (em or data is not None) else str(raw)[:300]
                return False, "连接失败:" + _EC_MSG[ec], _show if (em or data is not None) else _show
            _show = json.dumps({"ec": ec, "em": em, "data": data}, ensure_ascii=False, indent=2) if (em or data is not None) else str(raw)[:300]
            return False, "连接失败:爱发电返回了未预期的 ec=" + str(ec), _show
        except Exception as e:  # noqa: BLE001
            last_notices.append(base + " => " + str(e))
            continue
    joined = " | ".join(last_notices)
    return False, "无法连到爱发电服务器(逐一尝试失败):详见 detail", joined


# ── 平台侧订单拉取(用「平台消费者账号」的 auth_token,不是商户 token)──
# 这是网页后台的内部接口(非公开开放 API),靠 cookie auth_token 认证,
# 与上面 test_connection 那套「user_id + token 签名」完全是两回事。
_SPONSORED_BASES = (
    "https://ifdian.net",
    "https://afdian.com",   # 登录走 afdian.com,这里两个域名都试,兼容会话域名差异
)
_UA_BILL = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36")

# ★ 节流(全平台共享):记录「上次真正发起请求」的时间戳,距上次不足 min_interval 秒
#   就直接跳过。这样无论从哪里、被多频繁地调用,最快也只是每 min_interval 秒打一次爱发电。
_fetch_lock = threading.Lock()
_last_fetch = 0.0

# 爱发电在「会话失效(需重新登录)」时返回的 ec:{"ec":40101,"em":"请重新登录","data":{}}
_EC_NEED_LOGIN = 40101


def fetch_sponsored_bills(auth_token: str, page: int = 1, status: int = 2,
                          timeout: int = 12, min_interval: float = 5.0):
    """用平台消费者账号的 auth_token 拉「我买过(已支付)」的账单。

    接口(网页后台内部接口):
        GET /api/my/sponsored-bill-out-filter
            ?page=&sort_field=update_time&sort_value=desc&is_redeem=0&plan_id=&sign_status=&status=2
    status=2 表示只取自「已支付」的,所以返回的每一条都已是付款状态。

    ★ 节流:被节流时不发请求,返回 (True, [], "节流跳过...") —— 用 ok=True 表示
      「没出错,只是这次没去取」,调用方据此正常往下走即可。
      传 min_interval=0 可强制发起(用于重新登录后的重试)。

    返回 (ok: bool, items: list[dict], message: str),items 即 data.list。
    只读,不改任何东西;失败不抛异常,交给调用方决定怎么处理。
    """
    global _last_fetch
    now = time.time()
    with _fetch_lock:
        if min_interval and (now - _last_fetch) < min_interval:
            return True, [], "节流跳过:距上次请求不足 " + str(min_interval) + " 秒"
        _last_fetch = now
    tok = (auth_token or "").strip()
    if not tok:
        return False, [], "缺少 auth_token(平台消费者账号尚未登录)"
    qs = ("page=" + str(int(page)) +
          "&sort_field=update_time&sort_value=desc" +
          "&is_redeem=0&plan_id=&sign_status=&status=" + str(int(status)))
    last_err = []
    for base in _SPONSORED_BASES:
        url = base + "/api/my/sponsored-bill-out-filter?" + qs
        req = urllib.request.Request(url, method="GET", headers={
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "user-agent": _UA_BILL,
            "referer": base + "/dashboard/order?order_status=2",
            "locale-lang": "zh-CN",
            "cookie": "auth_token=" + tok,
        })
        raw = None
        for ctx in (ssl.create_default_context(), ssl._create_unverified_context()):
            try:
                with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                break
            except Exception as e:  # noqa: BLE001
                last_err.append(base + " => " + type(e).__name__ + ":" + str(getattr(e, "reason", e)))
        if raw is None:
            continue
        try:
            j = json.loads(raw)
        except (ValueError, TypeError):
            last_err.append(base + " => 返回不是 JSON: " + str(raw)[:120])
            continue
        ec = int(j.get("ec") or 0)
        if ec != 200:
            if ec == _EC_NEED_LOGIN:
                # 会话已失效(爱发电返回 {"ec":40101,"em":"请重新登录"})——单独标出,
                # 让调用方据此强制重新登录后重试;其它错误(限流/服务端异常)不该白登一次。
                last_err.append(base + " => 会话失效 ec=" + str(_EC_NEED_LOGIN) +
                                " em=" + str(j.get("em") or ""))
            else:
                last_err.append(base + " => ec=" + str(ec) + " em=" + str(j.get("em") or ""))
            continue
        data = j.get("data") or {}
        items = data.get("list")
        if not isinstance(items, list):
            items = []
        return True, items, "已取回 " + str(len(items)) + " 条"
    return False, [], " | ".join(last_err) or "拉取失败"


def is_session_invalid(message: str) -> bool:
    """fetch_sponsored_bills 的失败信息是否表示「会话失效,需要重新登录」。

    仅用于判断"要不要强制重登重试":只有真掉线(爱发电返回 ec=40101 请重新登录)才重登,
    其它失败(限流、服务端抽风、网络抖动)重登也没用,不该白跑一次登录。
    """
    return str(_EC_NEED_LOGIN) in str(message or "")
