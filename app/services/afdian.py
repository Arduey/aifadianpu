"""爱发电开放平台封装
真实模式:.env AFDIAN_LIVE=true
  创建订单 POST https://afdian.com/api/open/create-order
  sign = md5( json.dumps(params) + user_id + token + str(tn) )
演示模式(默认):创建即返回收款码,约 12 秒后轮询为已支付
"""
import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime

from .. import config, settings


def create_order(merchant_afdian_id: str, remark: str, price_yuan: int, channel: str):
    """返回 (订单号, 收款码内容)"""
    order_no = f"AFD{time.strftime('%Y%m%d%H%M%S')}{int(time.time()*1000) % 1000}"
    if settings.afdian_live():
        # 落地接入示例:
        # params = {"out_trade_no": order_no, "remark": remark, "buy_count": 1}
        # tn = int(time.time()); sign = md5(json.dumps(params)+user_id+token+str(tn))
        # POST https://afdian.com/api/open/create-order {"user_id","sign","params","tn"}
        raise RuntimeError("AFDIAN_LIVE 模式需完成真实接口对接(见本文件注释)")
    return order_no, f"{channel}://{merchant_afdian_id}/{order_no}?amt={price_yuan}"


def order_paid(created_at: datetime) -> bool:
    if settings.afdian_live():
        # 真实调用:/api/open/query-order,order.status == 2 为已支付
        return False
    return (datetime.now() - created_at).total_seconds() > 12


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
