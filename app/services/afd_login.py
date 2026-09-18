"""爱发电「网页会话 auth_token」登录 + 持久化 + 失效判断。

真实路由(已被用户实测可用):
   POST https://afdian.com/api/passport/login
   JSON: {"account": <账号>, "password": <密码>, "mp_token": "-1"}
   成功: {"ec":200,"em":"登录成功","data":{"auth_token":"..."}}

持久化放在 platform_settings.consumer_auth_token / consumer_token_at。
本模块只做: 登录一个 token / 存库 / 取回 / "是否已失效" 判断 —— 不负责调用方的下游重试流程。
"""
import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime

from ..db import SessionLocal, platform_settings

_LOGIN_URL = "https://afdian.com/api/passport/login"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36")
_DEFAULT_MAX_AGE = 7 * 24 * 3600  # 无平台侧超时字段时,保守默认 7 天内视为有效


def _post(url: str, body: bytes, headers: dict, timeout: int = 12):
    """带 UA/头 + 证书兜底(纯登录用)的 POST;在内部完整读回字节返回(避免响应被二次关闭),失败向上抛。"""
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    ctxs = (ssl.create_default_context(), ssl._create_unverified_context())
    last = None
    for ctx in ctxs:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def consumer_login(account: str, password: str) -> dict:
    """用账密登录爱发电,换取 data.auth_token。

    返回 dict: {"ok": True, "ec":200, "em":"登录成功", "token":"<auth>",
                "at": <datetime>, "raw":"<原始返回纯文本>"}
          失败:{"ok":False,"ec":...,"em":...,"token":"","at":None,"raw":...}
    网络级异常也会被吞成 ok=False 错误信息(便于上层直接展示)。
    """
    account = (account or "").strip()
    password = (password or "").strip()
    if not account or not password:
        return {"ok": False, "ec": 0, "em": "consumer 账号/密码不能为空", "token": "", "at": None, "raw": ""}
    body = json.dumps({"account": account, "password": password, "mp_token": "-1"},
                      ensure_ascii=True).encode("utf-8")
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": _UA,
        "afd-fe-version": "20220508",
        "origin": "https://afdian.com",
        "referer": "https://afdian.com/login",
    }
    try:
        raw = _post(_LOGIN_URL, body, headers).decode("utf-8", "replace")
        j = json.loads(raw)
        ec = int(j.get("ec") or 0)
        em = str(j.get("em") or "")
        data = j.get("data") or {}
        if ec == 200:
            tok = str(data.get("auth_token") or "").strip()
            if tok:
                return {"ok": True, "ec": ec, "em": em or "登录成功", "token": tok, "at": datetime.now(), "raw": raw}
            return {"ok": False, "ec": ec, "em": "登录成功但未返回 auth_token", "token": "", "at": None, "raw": raw}
        return {"ok": False, "ec": ec, "em": f"登录失败: {em}", "token": "", "at": None, "raw": raw}
    except (json.JSONDecodeError, ValueError, urllib.error.URLError, OSError) as e:
        return {"ok": False, "ec": 0, "em": f"登录请求异常: {e}", "token": "", "at": None, "raw": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "ec": 0, "em": f"登录请求异常: {e}", "token": "", "at": None, "raw": ""}


def save_consumer_token(token: str, at: datetime | None = None) -> None:
    """把新取得的 auth_token 与时间落库(供重启后续用)。"""
    with SessionLocal() as db:
        row = platform_settings(db)
        row.consumer_auth_token = (token or "").strip()
        row.consumer_token_at = at or datetime.now()
        db.commit()


def consumer_token_expired(token_at, max_age_seconds: int = _DEFAULT_MAX_AGE) -> bool:
    """判断一个「存库时间(tok_at)」对应的 auth_token 是否已失效(纯粹时间阀)。

    - token_at is None            => 视为失效(没记录过登录时间)
    - now-token_at > max_age      => 视为失效(超过阀值,平台会话按此续登一次)
    - 其它                        => 有效

    *只做判断*:不触发任何重新登录流程(this is per design)。
    """
    if token_at is None:
        return True
    try:
        age = (datetime.now() - token_at).total_seconds()
    except TypeError:
        return True
    return age > max(max_age_seconds, 0)


def consumer_ensure_token(force: bool = True) -> dict:
    """取一个可用 token 的完整流程(无人自动化,无下游重试):

    1. 库里已有未过期 token 且非 force => 直接复用(cached)
    2. 否则用平台配置的 consumer 账密登录一次并持久化(refreshed)
    3. 登录失败但库里仍有旧 token(未显式判定失效) => 兜底返回旧 token(last_resort)

    说明:当下单/查单这类「必须拿 token 才能干活」的场景调用时,默认 force=True 会
    主动续登,避免“曾登录过但已过期”导致业务直接失败的假性未登录。
    """
    with SessionLocal() as db:
        row = platform_settings(db)
        account = (row.consumer_account or "").strip()
        password = (row.consumer_password or "").strip()
        token = str(getattr(row, "consumer_auth_token", "") or "").strip()
        token_at = getattr(row, "consumer_token_at", None)

    if not force and token and not consumer_token_expired(token_at):
        return {"ok": True, "token": token, "at": token_at, "source": "cached", "em": "使用已登录 auth_token"}

    result = consumer_login(account, password)
    if result.get("ok"):
        tok = result["token"]
        save_consumer_token(tok, result["at"])
        return {"ok": True, "token": tok, "at": result["at"], "source": "refreshed", "em": "登录成功并已持久化"}
    # 登录失败:若库里还有旧 token,先兜底用(可能是爱发电风控/网络抖动,旧 token 仍可用)
    if token:
        return {"ok": True, "token": token, "at": token_at, "source": "last_resort",
                "em": f"自动登录失败({result.get('em')}),回退使用缓存 auth_token"}
    return {"ok": False, "token": "", "at": None, "source": "fail", "em": result.get("em", "登录失败")}
