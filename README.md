# 爱发电铺 · FastAPI + MySQL 版(宝塔面板部署)

与 Next.js 版业务规则完全一致的 Python 实现:**FastAPI + SQLAlchemy + MySQL + Jinja2 模板**(无前端构建链),宝塔「Python 项目管理器」全图形化运维。

## 📚 文档导航

| 文档 | 说明 |
|---|---|
| **README.md**（当前页） | 项目总览、目录结构、宝塔部署 6 步、环境变量、日常运维、开发者指南 |
| [**RE-DEPLOY.md**](RE-DEPLOY.md) | **全新服务器从零部署**：完全没有代码/数据库/`.env` 的空机器，一路到网站可访问、管理员创建完成（最完整，推荐首次部署看这份） |
| [**BT-PANEL-STEP.md**](BT-PANEL-STEP.md) | **宝塔面板手把手**（逐框填写版）：每步告诉你点哪个菜单、出现哪个框、填什么，适合不熟悉命令行的人 |
| [**DEPLOY-TUTORIAL.md**](DEPLOY-TUTORIAL.md) | **宝塔部署教程**（从零到上线）：含启动方式选择（命令行 / gunicorn）、Nginx 反代与 SSL、常见问题排查 |
| [**PRODUCTION.md**](PRODUCTION.md) | **生产功能说明**：注册/登录/订单/Webhook/邮件/计费/管理台等功能到底怎么工作，以及**哪些仍是演示未接入** |

> 补充：接口细节见站内「开放接口」页（`/api-docs`）；面向商户的功能讲解见站内「使用说明」页（`/guide`）。
> 当前页：**README.md**（项目总览）

## 目录速览

```
fastapi/
├── main.py               # 入口(main:app),启动时幂等建表
├── requirements.txt      # 依赖(uvicorn 锁 <0.35,见下方说明)
├── .env.example          # 环境变量模板(仅参考,配置由安装向导生成)
├── database/schema.sql   # MySQL 表结构(可选手工导入,程序也会自动建表)
└── app/
    ├── config.py         # 环境变量读取(.env 优先)
    ├── settings.py       # 平台可调设置(读写 platform_settings 表)
    ├── db.py             # SQLAlchemy 引擎 + 12 张表模型
    ├── auth.py           # PBKDF2 密码 / JWT 会话(Cookie+Bearer)/ 登录锁定
    ├── utils.py          # 校验助手(邮箱、店铺名等)
    ├── render.py         # Jinja2 渲染(自动注入 me/qs/api_fee 等)
    ├── routes_public.py  # 公开路由 24 个:安装向导/注册登录/店铺页/下单轮询/开放接口
    ├── routes_console.py # 控制台路由 44 个:页面 + 全部 JSON 接口
    ├── services/         # 业务服务(见「开发者指南 · 服务层」)
    ├── templates/        # 21 个 Jinja2 页面模板
    └── static/           # app.css / app.js / morphicons / qrcode.js 等
```

## 宝塔部署(6 步)

1. **装环境**:软件商店安装 Nginx、MySQL 5.7+/8.0、「**Python 项目管理器**」插件(内含 Python 3.10+ 与 pip)。
2. **建库**:数据库 → 添加数据库 `afdianpu`(utf8mb4),记下账号密码。
3. **上传代码**到站点目录,如 `/www/wwwroot/afdianpu`。

   > ✅ **不需要手动创建或编辑任何文件**(包括 `.env`)。数据库、会话密钥等配置全部由**网页安装向导**填写并自动写入 `.env`;项目未配置时也能正常启动,会自动把你引导进向导。`.env.example` 仅是「可能出现的键」参考清单,可忽略。
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
- **本地调试**:`uvicorn main:app --reload`(注意 http 下的 `APP_SECURE` 用法,见「开发者指南 · 本地运行」)。

## 与其他版本的差异

业务规则、数据表、Webhook JSON、邮件卡片与 Next.js/ThinkPHP 版完全一致;密码哈希算法为 PBKDF2(与其他版本不同,用户数据不互通迁移,需重新注册)。无 morphicons 形变动画,交互反馈用 toast/弹窗实现。

## 开发者指南

### 本地运行

```bash
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 不写任何配置，直接起；浏览器访问 http://127.0.0.1:8000 会自动进安装向导
uvicorn main:app --reload
```

> 首次进入向导后再填数据库连接即可（配置由向导自动写入 `.env`）。
>
> ⚠️ 向导写入的 `APP_SECURE` 默认为 `true`(生产值)。**本地用 http 调试时需把 `.env` 里的 `APP_SECURE` 改为 `false`**,否则 Secure Cookie 写不进去,登录会「看似成功却立刻掉线」。

### 请求生命周期

1. `main.py` 的 HTTP 中间件对每个请求解析登录态 → `request.state.me`,并注入 `request.state.qs`(预览通行证参数);
2. 未完成安装时,除 `/install`、`/static` 外一律 302 到安装向导;
3. 页面路由统一走 `app/render.py` 的 `render()` — 它自动向模板注入 `me / qs / api_fee / allow_email_domains` 等公共变量,新增页面直接用即可;
4. 控制台页面路由用 `_need(request)` 守卫,返回 `(me, resp)`;`resp` 非空时直接 return 它(未登录 → 302 `/login`;非管理员 → `noadmin.html`)。

### 服务层(`app/services/`)

| 模块 | 职责 |
|---|---|
| `pipeline.py` | **支付流水线**:`mark_order_paid()` 幂等标记已付并执行「加充值余额 → 扣服务费写流水 → 发 Webhook → 发邮件」;另含 Webhook 模板渲染(`@变量`)、发送历史修剪、`gc_stale_pending()` 清理过期未付单、`bump_order_stat()` 订单计数 |
| `afdian.py` | 爱发电对接(含演示模拟分支) |
| `afd_live.py` | 真实下单/查单:优先用 `curl_cffi` 伪装浏览器指纹绕过 Cloudflare,未安装则回退 urllib;含 `live_create_auto / live_check_auto`(token 失效自动重登再试) |
| `afd_login.py` | 消费者账号登录、`auth_token` 持久化与失效判断(`consumer_ensure_token`) |
| `mailer.py` | SMTP 发信(smtplib),未配置时降级为仅记日志 |
| `email_templates.py` | 订单/余额提醒邮件模板 |
| `verification.py` | 邮箱验证码的生成、发送与校验 |

### 数据层

- 12 张表模型集中在 `app/db.py`;建表由 `main.py` 启动时 `Base.metadata.create_all()` 幂等完成,新增模型**无需手工 ALTER**(新增表同理);
- ⚠️ 给**已有表新增列**时,`create_all` 不会改已存在的表,需自行 `ALTER TABLE` 后再重启;
- 平台级可调配置都在 `platform_settings` 表,通过 `app/settings.py` 读取(如 `api_fee_cents()`),**不要**在代码里写死。

### 鉴权

- 密码:`PBKDF2`(见 `app/auth.py`);会话:JWT,同时支持 **Cookie**(浏览器)与 **Bearer**(API 调用);
- 登录失败按 IP 锁定(5 分钟内 5 次),状态存 `login_locks` 表;
- 调试用预览通行证 `?preview=admin|merchant`(受 `ENABLE_PREVIEW_LOGIN` 控制,**生产必须为 false**)。

### 前端约定

- **无构建链**:原生 JS + Jinja2 服务端渲染,改完刷新即生效;
- 图标统一用 `<morph-icon data-name="…">`(`app/static/morphicons/morph-icons.js`),**不使用 emoji**;新增图标在该文件 `ICONS` 里加一条即可;
- 静态资源在 `app/templates/base.html` 里带版本号引用(`app.css?v=N`、`app.js?v=N`),**改了 CSS/JS 记得把版本号 +1**,否则浏览器/CDN 会继续用旧缓存;
- 公共样式放 `app/static/app.css`;页面专属样式写在对应模板的 `{% block style %}` 或 `{% block contentcss %}`。

### 扩展点

- **新增公开接口**:在 `app/routes_public.py` 加 `@router.get/post`,错误统一用 `err(msg, status)`;
- **新增控制台接口**:在 `app/routes_console.py` 加路由,页面路由记得用 `_need()` 守卫,JSON 接口用 `_me()` 判空返回 401;
- **新增配置项**:`platform_settings` 加列 + `app/settings.py` 加读取函数 + 控制台「平台配置」页面加表单字段;
- **对接支付/发货**:改 `pipeline.mark_order_paid()` 的流水线步骤顺序即可。

### 依赖与版本约束

- `requirements.txt` 里 **`uvicorn[standard]` 锁定 `<0.35`**:宝塔「gunicorn」启动方式依赖 `uvicorn.workers.UvicornWorker`,该模块在 uvicorn 0.34+ 已被移除;若改用独立包 `uvicorn-worker` 可解除上限。**命令行 A 方案(`uvicorn main:app`)不受此限制**。
- `curl_cffi` 为**可选依赖**:不装也能运行(回退 urllib),但对接真实爱发电时可能因 Cloudflare 指纹校验失败,建议生产安装。

### 自检脚本

```bash
python deploy_check.py   # 部署前环境检查
```

### 已知边界(不要当 bug)

- **下单/查单走 `afd_live.py`(真实接口)**,不是 `afdian.py`;后者里的 `create_order / order_paid` 是**历史占位且已无调用方**,属死代码,别混淆;
- 下单依赖 `curl_cffi` 伪装指纹绕 Cloudflare:未安装时可回退 urllib,但**很可能被 1010 拦截**;
- 未支付订单**超过 3 小时会被物理清除**(`gc_stale_pending`),因此「创建订单数」由独立的 `order_stats` 表累计保障,不受清理影响。
