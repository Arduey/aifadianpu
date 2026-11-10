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
    # 单店模式:API 服务费与「注册邮箱域名白名单」都已废弃。
    # 这里仍注入兼容值(0 / 空列表),以免尚未清理干净的模板在渲染时报 undefined;
    # 新模板请不要再引用 api_fee / api_fee_cents / allow_email_domains。
    if "api_fee" not in ctx:
        ctx["api_fee"] = 0
        ctx["api_fee_cents"] = 0
        ctx["allow_email_domains"] = []
    return templates.TemplateResponse(request, name, ctx)
