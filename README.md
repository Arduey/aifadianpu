# 爱发电铺 · FastAPI + MySQL 版(宝塔面板部署)

与 Next.js 版业务规则完全一致的 Python 实现:**FastAPI + SQLAlchemy + MySQL + Jinja2 模板**(无前端构建链),宝塔「Python 项目管理器」全图形化运维。

## 目录速览

```
fastapi/
├── main.py               # 入口(main:app),启动时幂等建表
├── requirements.txt      # 依赖(9 个包,含 uvicorn 与 gunicorn)
├── .env.example          # 环境变量模板
├── database/schema.sql   # MySQL 表结构(可选手工导入,程序也会自动建表)
└── app/
    ├── config.py         # 环境变量读取
    ├── db.py             # SQLAlchemy 引擎 + 7 张表模型
    ├── auth.py           # PBKDF2 密码 / JWT 会话(Cookie+Bearer)/ 登录锁定 / 预览通行证
    ├── utils.py          # 校验助手
    ├── render.py         # Jinja2 渲染(自动注入 me/qs)
    ├── routes_public.py  # 主页注册/登录/忘记重置/店铺页/下单轮询/公开接口
    ├── routes_console.py # 控制台页面 + 全部 JSON 接口
    ├── services/         # afdian(演示模拟) mailer(smtplib) pipeline(支付流水线) email_templates
    ├── templates/        # 15 个页面模板
    └── static/           # app.css / app.js(与其他版本同一套设计系统)
```

## 宝塔部署(6 步)

1. **装环境**:软件商店安装 Nginx、MySQL 5.7+/8.0、「**Python 项目管理器**」插件(内含 Python 3.10+ 与 pip)。
2. **建库**:数据库 → 添加数据库 `afdianpu`(utf8mb4),记下账号密码。
3. **上传代码**到站点目录,如 `/www/wwwroot/afdianpu`。

   > ✅ **不需要手动创建或编辑任何文件**(包括 `.env`)。数据库/会话密钥等配置全部由**网页安装向导**填写并自动写入 `.env`;项目在未配置时也能正常启动,会自动引导你进向导。
   > (`.env.example` 仅是「可能出现的键」参考清单,可忽略。)
   >
   > 仅当你偏好手工配置时才需要:`cp .env.example .env` 后自行填写 `DB_*`、`SESSION_SECRET`、`APP_BASE_URL`、`SMTP_*`。
4. **Python 项目管理器 → 添加项目**:
   - 项目路径:`/www/wwwroot/afdianpu`
   - Python 版本:3.10+(如 3.12.8);框架:FastAPI;端口:`8000`
   - 勾选「安装模块依赖」(自动执行 `pip install -r requirements.txt`)
   - 环境变量:选「无」即可(项目读 `.env` 文件;面板里填了会覆盖同名键)
   - 启动项目。**此时无需数据库也能启动**:数据表会在数据库配置就绪后的首次启动自动创建(幂等;也可用 phpMyAdmin 导入 `database/schema.sql`)。

   > ⚠️ **面板「启动方式」只有 命令行启动 / uwsgi / gunicorn,没有 uvicorn**,二选一:
   >
   > - **A. 命令行启动(推荐,最简单)**:启动命令填
   >   ```
   >   uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
   >   ```
   >   `uvicorn` 已包含在 requirements.txt,勾选「安装模块依赖」后直接可用。
   > - **B. gunicorn 启动**:通讯协议选 **asgi**(⚠️ 不是 wsgi,否则 FastAPI 起不来),启动文件/应用填 `main:app`。面板以 `uvicorn.workers.UvicornWorker` 方式托管进程。
   >   ⚠️ 该 worker 在 uvicorn 0.34+ 已被移除,故 `requirements.txt` 已锁 `uvicorn<0.35`;若你想用新版 uvicorn,请改装独立包 `uvicorn-worker` 并改启动配置(否则会 ImportError 起不来)。**推荐直接用上面的 A 方案,不受此限制。**
   >
   > 不要选 uwsgi:uwsgi 只支持 wsgi 同步协议,不适合 FastAPI(asgi)。无论哪种方式,「项目端口」填 `8000`,且与启动命令里的端口一致。
5. **绑域名**:项目管理器 → 映射到站点域名,或 网站 → 添加站点 → 反向代理到 `127.0.0.1:8000`;申请 SSL 证书并**强制 HTTPS**(生产 Cookie 为 Secure,必须 HTTPS)。
6. **首次使用(全程网页,无需改文件)**:
   打开域名,会自动跳转 `/install` 安装向导:
   - **第 1 步**:填写第 2 步建好的数据库连接(主机/端口/库名/账号/密码)。系统会**当场测试连接**,成功后自动写入 `.env`(含自动生成的 `SESSION_SECRET`),并提示**回到项目管理器点「重启」**;
   - **第 2 步**(重启后自动进入):创建**管理员账号**(邮箱/店铺名/密码),同时填写平台配置(对外域名、爱发电消费者账号、平台 LOGO、SMTP 等)。提交后即完成安装;
   - 之后:个人中心完善爱发电绑定 → 商品管理创建商品(管理员可建「API充值」档位)→ 分享店铺链接。

   > 提示:管理员由向导创建,**不走注册页**;注册页仅用于后续普通商户自助开店。

手动方式(不用项目管理器)等效命令:
```bash
cd /www/wwwroot/afdianpu
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
# 用宝塔「进程守护」(supervisor)托管上述命令即可开机自启
```

## 环境变量(.env)

| 键 | 说明 |
|---|---|
| `DB_HOST/PORT/USER/PASSWORD/NAME` | MySQL 连接 |
| `SESSION_SECRET` | JWT 密钥(`openssl rand -hex 32`) |
| `APP_BASE_URL` | 对外域名(重置邮件链接) |
| `APP_SECURE` | Cookie Secure;生产 true(需 HTTPS),本地 http 调试 false |
| `AFDIAN_LIVE` | `true`=真实爱发电接口(默认演示模拟,订单约 12 秒自动成功) |
| `ENABLE_PREVIEW_LOGIN` | 生产设 `false`(关闭一键体验与 `?preview=` 通行证) |
| `SMTP_HOST/PORT/USER/PASS/FROM` | 邮件(QQ/163 用授权码);不配=演示模式仅写日志 |

## 日常运维(全图形化)

- **更新**:覆盖代码 → 项目管理器点「重启」即生效(无构建步骤);表结构变更由启动时自动同步。
- **备份**:计划任务 → 备份数据库(每天)+ 备份项目目录;日志在项目管理器「日志」页(邮件/回调失败可查)。
- **本地调试**:`uvicorn main:app --reload`(`.env` 中 `APP_SECURE=false` 便于 http 下测试登录)。

## 与其他版本的差异

业务规则、数据表、Webhook JSON、邮件卡片与 Next.js/ThinkPHP 版完全一致;密码哈希算法为 PBKDF2(与其他版本不同,用户数据不互通迁移,需重新注册)。无 morphicons 形变动画,交互反馈用 toast/弹窗实现。
