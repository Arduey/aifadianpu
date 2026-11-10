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
    return templates.TemplateResponse(request, name, ctx)
