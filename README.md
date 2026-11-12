# 爱发电铺 · FastAPI + MySQL 版（宝塔面板部署）

一个**单店**形态的自建小铺：FastAPI + SQLAlchemy + MySQL + Jinja2 模板（无前端构建链）。
店主把自己要卖的东西挂到爱发电生态里，顾客在店铺页下单，付款后自动发货 / 自助提货。

> **单店模式**：全站只有**一个店主账号**（由安装向导创建）。没有商家注册入驻、没有多商户管理面、
> 没有平台抽成与 API 余额。顾客看到的商店 = 这位店主自己的店。

## 📚 文档导航

| 文档 | 说明 |
|---|---|
| **README.md**（当前页） | 项目总览、目录结构、宝塔部署、环境变量、日常运维、开发者指南 |
| [**RE-DEPLOY.md**](RE-DEPLOY.md) | **全新服务器从零部署**：空机器一路到网站可访问（推荐首次部署看这份） |
| [**BT-PANEL-STEP.md**](BT-PANEL-STEP.md) | **宝塔面板手把手**（逐框填写版），适合不熟悉命令行的人 |
| [**DEPLOY-TUTORIAL.md**](DEPLOY-TUTORIAL.md) | **宝塔部署教程**：启动方式、Nginx 反代与 SSL、常见问题排查 |
| [**PRODUCTION.md**](PRODUCTION.md) | **生产功能说明**：各功能的真实行为与第三方对接现状 |

> 接口细节见站内「开放接口」页（`/api-docs`）；店主功能讲解见站内「使用说明」页（`/guide`）。

## 目录速览

```
fastapi/
├── main.py               # 入口(main:app)，启动时幂等建表
├── gunicorn_conf.py      # gunicorn 配置（仅 ASCII，见下方警告）
├── requirements.txt      # 依赖
├── deploy_check.py       # 部署前环境自检
├── database/             # schema.sql(全新建库) / upgrade_*.sql(存量库升级) / reset.sql(清库重装)
└── app/
    ├── config.py         # 环境变量读取(.env 优先)
    ├── settings.py       # 平台可调设置(读写 platform_settings 表)
    ├── db.py             # SQLAlchemy 引擎 + 16 张表模型
    ├── auth.py           # PBKDF2 密码 / JWT 会话(Cookie+Bearer) / 登录锁定
    ├── utils.py          # 校验助手(邮箱、店铺名等)
    ├── render.py         # Jinja2 渲染(注入 me / qs)
    ├── routes_public.py  # 公开路由 21 个:安装向导/登录/店铺页/下单轮询/自助提货/开放接口/Webhook
    ├── routes_console.py # 控制台路由 32 个:页面 + 全部 JSON 接口
    ├── services/         # 业务服务(9 个模块，见「服务层」)
    ├── templates/        # 18 个 Jinja2 页面模板
    └── static/           # app.css / app.js / morphicons / qrcode.js 等
```

## 宝塔部署

1. **装环境**：软件商店安装 Nginx、MySQL 5.7+/8.0、「**Python 项目管理器**」插件（内含 Python 3.10+ 与 pip）。
2. **建库**：数据库 → 添加数据库（如 `afdianpu`，utf8mb4），记下账号密码。
3. **上传代码**到站点目录，如 `/www/wwwroot/store`。

   > ✅ **不需要手动创建或编辑任何文件**（包括 `.env`）。数据库、会话密钥等配置全部由**网页安装向导**填写并自动写入 `.env`。

4. **Python 项目管理器 → 添加项目**：
   - 项目路径：站点目录（如 `/www/wwwroot/store`）
   - Python 版本：3.10+；框架：FastAPI；端口：`8000`
   - 勾选「安装模块依赖」（自动执行 `pip install -r requirements.txt`）
   - 环境变量：选「无」即可（项目读 `.env` 文件；面板里填了会覆盖同名键）
   - 启动方式选 **命令行启动**，启动命令填：

     ```
     gunicorn main:app -c gunicorn_conf.py
     ```

   > ⚠️ **worker 类用 `uvicorn_worker.UvicornWorker`**（由独立包 `uvicorn-worker` 提供）。
   > `uvicorn.workers.UvicornWorker` 在 uvicorn 0.34+ **已被移除**，用错会直接
   > `ModuleNotFoundError` 起不来。`requirements.txt` 已包含该包，勾「安装模块依赖」即可。
   >
   > `gunicorn_conf.py` 里可用环境变量覆盖：`GUNICORN_BIND`（默认 `0.0.0.0:8000`）、
   > `GUNICORN_WORKERS`、`GUNICORN_LOGLEVEL`。
   >
   > 🔴 **`gunicorn_conf.py` 必须保持纯 ASCII**：中文注释和制表符会被某些 FTP 客户端截断，
   > 导致 `SyntaxError: unterminated string literal`。

   不用项目管理器的等效命令：

   ```bash
   cd /www/wwwroot/store
   python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
   ./venv/bin/gunicorn main:app -c gunicorn_conf.py
   # 用宝塔「进程守护」(supervisor) 托管即可开机自启
   ```

5. **绑域名**：网站 → 添加站点 → 反向代理到 `127.0.0.1:8000`；申请 SSL 并**强制 HTTPS**
   （生产 Cookie 为 Secure，必须 HTTPS）。

6. **首次使用**：打开域名，自动跳 `/install`：
   - **第 1 步**：填数据库连接，系统当场测试，成功后写入 `.env`（含自动生成的 `SESSION_SECRET`），
     提示**回项目管理器点「重启」**；
   - **第 2 步**（重启后）：创建**店主账号**（邮箱 / 店铺名 / 密码）+ 平台配置（对外域名、
     爱发电消费者账号、平台 LOGO、SMTP 等）。提交即完成安装；
   - 之后：个人中心绑定爱发电 → 商品管理建分类和商品 → 分享店铺链接。

   > 店主账号由向导创建，**没有注册页**。

## 环境变量（.env）

| 键 | 说明 |
|---|---|
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | MySQL 连接 |
| `SESSION_SECRET` | JWT 密钥（`openssl rand -hex 32`）；向导自动生成 |
| `APP_BASE_URL` | 对外域名（重置链接等）。**一般不用手填**：后台「平台配置 → 平台域名」会同时写这一项 |
| `APP_SECURE` | Cookie Secure；生产 `true`（需 HTTPS），本地 http 调试改 `false` |
| `ENABLE_PREVIEW_LOGIN` | 生产设 `false`（关闭 `?preview=admin` 免密预览通行证） |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` | 邮件（QQ/163 用授权码）；未配 SMTP 时邮件不发、仅记日志 |
| `AFDIAN_LIVE` | **历史遗留，当前业务代码不读取**（下单/查单固定走 `afd_live.py`） |

> 留空 ≠ 未设置：**空 `.env` 等同于没有 `.env`**。`DB_USER=` 这种空值会让 `os.getenv`
> 返回空串、兜底失效，容易演变成 `Access denied for user 'www'@'localhost'`。

## 平台配置（后台独立页）

侧边栏「**平台配置**」（`/console/platform`），仅店主可见。常用项：

- **平台域名**：一处填写、三处生效 —— 开放接口页的「基础地址」、密码重置链接、爱发电 Webhook 回调地址。
  保存时同时写 `webhook_base_url` 与 `app_base_url`，二者永远一致；**留空 = 跟随当前访问域名**。
- **付款方式控制**：
  - `wechat_limit_on`：是否启用微信大额拦截（默认开）
  - `wechat_max_yuan`：单笔上限（默认 100；`0` 也视为不限制）
  - 前台店铺页与购买弹窗会按它把微信按钮置灰并提示改用支付宝。

## 日常运维

- **更新**：覆盖代码 → 项目管理器点「重启」。`.html/.css/.js` 免重启，但**改了静态资源要升
  `base.html` 里的版本号**（`app.css?v=N`）。
- **改 `.py` 必须重启后端**才生效。
- **新增表**由启动时 `create_all()` 自动建；**给已有表加列**必须先跑 `database/upgrade_*.sql`
  再重启（反了会 `Unknown column`）。
- **备份**：计划任务 → 备份数据库 + 备份项目目录；日志在项目管理器「日志」页。

## 开发者指南

### 本地运行

```bash
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 不写任何配置直接起；访问 http://127.0.0.1:8000 会自动进安装向导
uvicorn main:app --reload
```

> ⚠️ 向导写入的 `APP_SECURE` 默认是 `true`（生产值）。**本地 http 调试要改成 `false`**，
> 否则 Secure Cookie 写不进去，登录会「看似成功却立刻掉线」。

### 请求生命周期

1. `main.py` 的中间件解析登录态 → `request.state.me`，并注入 `request.state.qs`（预览通行证参数）；
2. 未完成安装时，除 `/install`、`/static` 外一律 302 到向导；
3. 页面路由统一走 `app/render.py` 的 `render()`，自动注入 `me / qs`；
4. 控制台页面用 `_need(request)` 守卫；JSON 接口用 `_me()` 判空返回 401。

### 服务层（`app/services/`）

| 模块 | 职责 |
|---|---|
| `pipeline.py` | **支付流水线**：`mark_order_paid()` 幂等标记已付 → 核销卡密/写发放记录 → 发 Webhook → 发邮件 → 订单统计；另含 Webhook 模板渲染（`@变量`）、发送历史修剪、`gc_stale_pending()` 清理过期未付单 |
| `delivery.py` | **发货服务**：卡密 / 链接 / 限购商品发货、库存扣减、卡密去重与锁定、`ensure_delivery()` 提货幂等 |
| `categories.py` | **分类服务**：分类增删改、排序、级联删除（连商品与其卡密；历史订单不动） |
| `reconcile.py` | **对账兜底**：Webhook 漏推时，用消费者账号拉「已支付」账单补推进（5 秒节流，异常静默） |
| `afdian.py` | 爱发电只读对接：绑定校验 `test_connection()` + 拉单 `fetch_sponsored_bills()` |
| `afd_live.py` | 真实下单/查单：`live_create_auto / live_check_auto`（token 失效自动重登再试）；优先 `curl_cffi` 伪装指纹 |
| `afd_login.py` | 消费者账号 AES+RSA 加密登录、`auth_token` 持久化与失效判断 |
| `mailer.py` | SMTP 发信（smtplib），未配置时降级为仅记日志 |
| `email_templates.py` | 订单邮件模板 |

### 数据层

- **16 张表**模型集中在 `app/db.py`，建表由 `main.py` 启动时 `create_all()` 幂等完成。
- 其中 `notices` / `verification_codes` / `fee_ledger` 三张**已停用**（单店化后无对应功能），
  模型保留只为不丢历史数据，代码不再读写。
- 平台级可调配置都在 `platform_settings`，通过 `app/settings.py` 读取，**不要**在代码里写死。
- ⚠️ `create_all()` **不会修改已存在的表**。给旧表加列必须走 `ALTER TABLE`，
  且 `CREATE TABLE IF NOT EXISTS` 也不会修正列定义（旧表要用 `MODIFY COLUMN` 补默认值，
  否则报 `#1364 Field 'x' doesn't have a default value`）。

### 数据库升级（存量库）

| 脚本 | 作用 |
|---|---|
| `upgrade_category.sql` | 分类独立成表（`product_categories` + `products.category_id`），并迁移原 `products.category` 数据 |
| `upgrade_pickup.sql` | 自助提货：`products` 补发货字段；`stock_cards` / `delivery_records` 由程序自动建 |
| `upgrade_stock_limit.sql` | `products.stock_limit`（限购总量，0 = 不限） |
| `upgrade_order_tip.sql` | `orders.delivery_tip`（下单时的提货说明快照） |
| `upgrade_delivery_lock.sql` | 给历史「商户发货」已付款订单补空发货记录，钉住「此单不自动发放」 |
| `upgrade_webhook_comment.sql` | 只修正 `platform_settings.webhook_base_url` 的列注释（不动数据） |
| `upgrade_wechat_limit.sql` | `platform_settings.wechat_max_yuan` + `wechat_limit_on`（微信大额拦截） |
| `upgrade_single_shop.sql` | 🔴 **单店化迁移（破坏性）**：把各表 `merchant_id` 归给店主、去重、**删除其他商户账号**、`role` 默认改 admin、清废弃设置 |

> ⚠️ 硬规则：**① 先跑 SQL、再重启后端**；**② `COMMENT '...'` 里不要写半角分号**（部分客户端会截断语句）。
> 🔴 `upgrade_single_shop.sql` 会**删除除店主外的所有账号及其名下商品**（订单归给店主保留），**先备份再执行**。

### 鉴权

- 密码 `PBKDF2`（`app/auth.py`）；会话为 JWT，同时支持 **Cookie**（浏览器）与 **Bearer**（API）；
- 登录失败按 IP 锁定（5 分钟内 5 次），状态存 `login_locks`；
- 调试用预览通行证 `?preview=admin`（受 `ENABLE_PREVIEW_LOGIN` 控制，**生产必须 `false`**）。

### 前端约定

- **无构建链**：原生 JS + Jinja2 服务端渲染，改完刷新即生效；
- 图标统一用 `<morph-icon data-name="…">`（`app/static/morphicons/morph-icons.js`），**不用 emoji**；
- 静态资源在 `base.html` 带版本号（`app.css?v=N`、`app.js?v=N`），**改了记得 +1**；
- **禁止浏览器原生弹窗**（`alert/confirm/prompt`），统一用 `app.js` 的 `appConfirm()`（返回 `Promise<boolean>`，调用方需 `async`）；
- 公共样式在 `app/static/app.css`；页面专属样式写对应模板的 `{% block style %}`。

### 扩展点

- **新增公开接口**：`app/routes_public.py` 加 `@router.get/post`，错误统一用 `err(msg, status)`；
- **新增控制台接口**：`app/routes_console.py` 加路由；页面用 `_need()` 守卫，JSON 用 `_me()` 判空；
- **新增配置项**：`platform_settings` 加列 + `app/settings.py` 加读取函数 + `/console/platform` 加表单字段；
- **改发货/通知顺序**：`pipeline.mark_order_paid()` 的流水线步骤。

### 依赖说明

- `curl_cffi`：**建议生产必装**。不装会回退 urllib，但从机房 IP 用 urllib 发请求时，
  爱发电的「微信 >100 元的发电」会被风控拒绝（`ec=400 不支持发电`）。≤100 元与支付宝不受影响。
- `uvicorn-worker`：gunicorn 的 ASGI worker 实现，见上方启动说明。

### 自检脚本

```bash
python deploy_check.py   # 部署前环境检查
```

## 已知边界（不要当 bug）

- **下单/查单走 `afd_live.py`（真实接口）**；`afdian.py` 只保留只读能力，原 `create_order / order_paid` 占位实现已删除。
- **Webhook 不保证必达**（爱发电官方说明建议结合 API），故有 `reconcile.py` 兜底补单；
  它在控制台请求上**惰性触发**（5 秒节流），不是常驻定时器。
- 未支付订单**超过 3 小时会被物理清除**（`gc_stale_pending`），「创建订单数」由独立
  `order_stats` 表累计保障，不受清理影响。
- **微信单笔 >100 元在机房 IP 下不可用**（风控）。已做成平台设置项：要么把「微信上限」开关关掉
  （需出站 IP 换掉之后），要么就让大额只走支付宝。
- 爱发电**不允许自己给自己发电**：消费者下单账号不能是被购买店铺的同一个账号。
