"""爱发电铺 · FastAPI 入口
宝塔 Python 项目管理器(面板「启动方式」无 uvicorn 选项,二选一):
  A. 启动方式=命令行启动,启动命令填:
     uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
  B. 启动方式=gunicorn,通讯协议=asgi,启动文件/应用填 main:app
     (依赖 requirements.txt 中的 gunicorn;面板会以 uvicorn worker 方式运行)
本地调试:uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
import os

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app import auth, config
from app.db import init_db
from app.routes_console import router as console_router
from app.routes_public import router as public_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="爱发电铺", description="依托爱发电开放接口的虚拟商品销售平台", version="1.0")

# 静态资源
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "app", "static")), name="static")


@app.middleware("http")
async def auth_context(request: Request, call_next):
    """为每个请求解析当前用户与预览通行证参数(页面模板使用)"""
    try:
        request.state.me = auth.current_user(request)
    except Exception:  # 数据库未就绪等场景不阻断静态资源
        request.state.me = None
    preview = request.query_params.get("preview")
    request.state.qs = f"?preview={preview}" if preview in ("admin", "merchant") else ""
    # 未完成安装时,除安装页与静态资源外一律重定向到安装向导
    path = request.url.path
    if not path.startswith("/install") and not path.startswith("/static"):
        try:
            if not auth.is_installed():
                from starlette.responses import RedirectResponse
                return RedirectResponse("/install", status_code=302)
        except Exception:
            pass
    return await call_next(request)


@app.on_event("startup")
def _startup():
    # 幂等建表。数据库尚未配置/未就绪时仅记日志,不阻断启动(以便进入 /install 安装向导)。
    try:
        init_db()
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("afdianpu").warning("init_db 失败(等待安装向导配置数据库): %s", e)


app.include_router(public_router)
app.include_router(console_router)
