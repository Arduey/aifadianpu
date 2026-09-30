"""爱发电「网页会话 auth_token」登录 + 持久化 + 失效判断。

真实路由:
   POST https://ifdian.net/api/passport/login
   JSON: {"account": <加密串>, "password": <加密串>, "mp_token": "-1", "ar_ept": <RSA 加密的 AES 密钥>}
   成功: {"ec":200,"em":"登录成功","data":{"auth_token":"..."}}

⚠️ 官网前端(afd-fe-version 1.24.x,module 71861)已把登录改成「AES + RSA」加密:
   - 每次登录随机生成 16 字节密钥,取十六进制 32 字符作为 AES-256-CBC 的密钥(明文 UTF-8)
   - IV 固定 "7brVHncu7wIDAQAB",PKCS7 填充,密文 Base64
   - 该密钥串再用官网内置 RSA 公钥(PKCS#1 v1.5)加密成 Base64,放入正文 ar_ept
   旧版明文提交网页端已不再受理(实测返回 ec=404 账号不正确,与“账号不存在”同文案),
   所以本模块默认走加密通道,仅在失败时兜底再试一次明文(老协议)。

持久化放在 platform_settings.consumer_auth_token / consumer_token_at。
本模块只做: 登录一个 token / 存库 / 取回 / "是否已失效" 判断 —— 不负责调用方的下游重试流程。
"""
import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from datetime import datetime

from cryptography.hazmat.primitives import padding as _sym_pad
from cryptography.hazmat.primitives import serialization as _serial
from cryptography.hazmat.primitives.asymmetric import padding as _asym_pad
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..db import SessionLocal, platform_settings

AFDIAN_HOST = "https://ifdian.net"
_LOGIN_URL = f"{AFDIAN_HOST}/api/passport/login"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
# 与官网当前前端一致(旧值 20220508 对应明文协议,服务端已不再受理)
_AFD_FE_VERSION = "1.24.2"
# 以下两项直接取自官网前端源码:登录加密用的 RSA 公钥与固定 IV
_AFD_LOGIN_PUBKEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA4Top/Mt2ofZeAIMh9AHw
4d6Q+iyBxXbou+1mbhclLsB3YSMbFD+X6QnlAY1vMHO7fteKevn25iVIELBXsmcQ
S5/oA2hO3VHi9uTG3XmYVcrw94cK5ppODeBOV0hV0dFS/NOT66pqPAuLW6HgRrnt
gznl4ju6ttOddDNJ7e97RH9qrZEpzjl9GqVZQ2sFdmmw4dNET9fP9HWq8VlfW+BF
G7TuxzEjZNcxAgrG/f41Z0+G3RxAccF8LOxu4Ztk1ZDdv5xukdx2ukoEhgdmKUkD
v/W5r3HPj1uX+buzDi/UsumMblWXb0Bys7ENhZ/n4+naZ3b3rJ32DnTF7brVHncu
7wIDAQAB
-----END PUBLIC KEY-----"""
_AFD_LOGIN_AES_IV = b"7brVHncu7wIDAQAB"
_DEFAULT_MAX_AGE = 7 * 24 * 3600  # 无平台侧超时字段时,保守默认 7 天内视为有效


def _aes_encrypt(plain: str, key_hex: str) -> str:
    """AES-256-CBC(密钥=32 字符十六进制串的 UTF-8 字节,IV 固定,PKCS7)→ Base64。"""
    padder = _sym_pad.PKCS7(128).padder()
    data = padder.update((plain or "").encode("utf-8")) + padder.finalize()
    enc = Cipher(algorithms.AES(key_hex.encode("utf-8")), modes.CBC(_AFD_LOGIN_AES_IV)).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode("ascii")


def _rsa_encrypt(plain: str) -> str:
    """RSA(PKCS#1 v1.5)加密 → Base64(官网 JSEncrypt 同款填充)。"""
    pub = _serial.load_pem_public_key(_AFD_LOGIN_PUBKEY_PEM.encode("utf-8"))
    return base64.b64encode(pub.encrypt(plain.encode("utf-8"), _asym_pad.PKCS1v15())).decode("ascii")


def _encrypt_login_fields(account: str, password: str) -> dict:
    """按官网协议把 account/password 加密,并生成 ar_ept(承载本次 AES 密钥)。"""
    key_hex = os.urandom(16).hex()  # 等价前端 WordArray.random(16).toString():32 位十六进制串
    return {
        "account": _aes_encrypt(account, key_hex),
        "password": _aes_encrypt(password, key_hex),
        "ar_ept": _rsa_encrypt(key_hex),
    }


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
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": _UA,
        "afd-fe-version": _AFD_FE_VERSION,
        "locale-lang": "zh-CN",
        "origin": AFDIAN_HOST,
        "referer": f"{AFDIAN_HOST}/login",
    }
    # 1) 官网现协议:account/password 走 AES 加密,ar_ept 携带 RSA 加密的本次密钥
    try:
        enc = _encrypt_login_fields(account, password)
        first = _post_login({**enc, "mp_token": "-1"}, headers)
    except Exception as e:  # noqa: BLE001
        first = {"ok": False, "ec": 0, "em": f"登录加密失败: {e}", "token": "", "at": None, "raw": ""}
    if first.get("ok"):
        return first
    # 2) 兜底:旧版明文协议(服务端仍可能受理;失败时把两条错误都带回去便于定位)
    plain = _post_login({"account": account, "password": password, "mp_token": "-1"}, headers)
    if plain.get("ok"):
        plain["em"] = "登录成功(明文兼容通道)"
        return plain
    first["em"] = f"{first.get('em')}; 明文兼容通道同样失败: {plain.get('em')}"
    return first


def _post_login(body: dict, headers: dict) -> dict:
    """真正发一次登录请求并解析返回(两条通道共用)。"""
    try:
        raw = _post(_LOGIN_URL, json.dumps(body, ensure_ascii=True).encode("utf-8"), headers).decode("utf-8", "replace")
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
