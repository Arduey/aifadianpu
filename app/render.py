"""Jinja2 模板渲染助手(自动注入 me / qs)"""
import os

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


def render(request: Request, name: str, ctx: dict | None = None):
    ctx = dict(ctx or {})
    ctx.setdefault("me", getattr(request.state, "me", None))
    ctx.setdefault("qs", getattr(request.state, "qs", ""))
    if "api_fee" not in ctx:
        try:
            from . import config
            from . import settings as _s
            ctx["api_fee"] = _s.api_fee_cents() / 100
            ctx["api_fee_cents"] = _s.api_fee_cents()
            try:
                _al = _s.allowed_email_domains()
            except Exception:
                _al = []
            ctx["allow_email_domains"] = _al
        except Exception:
            from . import config
            ctx["api_fee"] = config.FEE_PER_ORDER_CENTS / 100
            ctx["api_fee_cents"] = config.FEE_PER_ORDER_CENTS
    return templates.TemplateResponse(request, name, ctx)
