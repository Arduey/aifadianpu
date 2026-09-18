"""业务校验与格式化助手"""
import re

EMAIL_RE = re.compile(r"^[\w.-]+@(qq|163)\.com$", re.IGNORECASE)
SHOP_NAME_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9]{1,12}$")


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip()))


def valid_shop_name(name: str) -> bool:
    return bool(SHOP_NAME_RE.match(name.strip()))


def shop_name_ok(name: str) -> bool:
    """店铺名规范:禁特殊符号;汉字按2字符、字母/数字/其他按1字符,合计≤12(纯汉字≤6)。"""
    n = name.strip()
    if not n:
        return False
    weight = 0
    for ch in n:
        if ord(ch) in (38, 64, 35, 37, 94, 42, 40, 41, 61, 58, 59, 34, 39,
                       96, 60, 62, 123, 125, 91, 93, 92, 124, 47, 63, 32):
            return False
        weight += 2 if ord(ch) >= 0x4E00 else 1
    return 0 < weight <= 12


def shop_name_weight(name: str) -> int:
    """返回店铺名字符权重(汉字2、其他1),供前端计数/后端提示。"""
    return sum(2 if ord(ch) >= 0x4E00 else 1 for ch in (name or ""))


def has_amp(s: str) -> bool:
    return "&" in s


def yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"
