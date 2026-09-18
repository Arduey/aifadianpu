# 爱发电铺 · 全新从零开始部署教程(无预填 env,全网页安装向导)

> 目标:**在一台完全空白的服务器上**,从「装系统环境」到「网站可访问、管理员创建完成」,一路走完。
> 前提:**没有任何代码、没有网站、没有数据库、没有 `.env`** —— 全部从零开始。
> 核心:**全程不需要手动编辑任何环境变量文件**;数据库连接、会话密钥、管理员账号、SMTP 等业务配置全部在网页「安装向导」里填写。

---

## 0. 准备一台全新服务器

| 项 | 要求 |
|---|---|
| 服务器 | 全新云服务器(2 核 2G 以上即可),系统 CentOS 7+ / Ubuntu 22.04 / Debian 12 |
| 域名 | 一个已解析到该服务器 IP 的域名(后续必须能开 HTTPS) |
| 账户 | 能通过 SSH 登录 root |

> 下面所有操作先在 SSH(或宝塔网页终端)里做。

---

## 1. 安装宝塔面板(从零开始)

SSH 登录后,执行宝塔官方安装脚本(以官网最新命令为准):

```bash
yum install -y wget && wget -O install.sh https://download.bt.cn/install/install_6.0.sh && bash install.sh
# Ubuntu/Debian 用:
# wget -O install.sh https://download.bt.cn/install/install-ubuntu_6.0.sh && sudo bash install.sh
```

安装完成会打印**面板地址 / 用户名 / 密码**,保存好。浏览器打开面板并登录。

---

## 2. 在宝塔内安装运行环境

进入宝塔「软件商店」,安装:

1. **Nginx**
2. **MySQL**(5.7 或 8.0;装完记下 root 密码,或用它建库)
3. **Python 项目管理器**(插件,内含 Python 3.10+ 与 pip)

---

## 3. 创建全新数据库

宝塔 → **数据库 → 添加数据库**:

- 数据库名:`afdianpu`(可自定义,记下来)
- 用户名 / 密码:自动生成或自填,**保存好**(安装向导第 1 步要用)
- 字符集:`utf8mb4`

> 现在就建好库即可,**不需要导任何表**——表结构由程序启动时自动创建。

---

## 4. 上传代码(不需要写任何 `.env`)

把项目目录 `fastapi/`(本仓库内)整个上传到服务器,例如:

```
/www/wwwroot/afd/
```

上传方式任选:宝塔「文件」上传 / FTP / `git clone`。

> ⚠️ 上传的是**完整的 `fastapi/` 内容**(`main.py`、`app/`、`database/`、`deploy_check.py` 等)。
> **不要复制 `.env.example` 为 `.env`** —— 本流程不需要预填 env;`.env` 会由安装向导自动生成。

---

## 5. 安装依赖 + 部署自检

在项目目录执行(或宝塔项目管理器勾选「安装模块依赖」):

```bash
cd /www/wwwroot/afd
/www/server/pyporject_evn/afd_venv/bin/pip install -r requirements.txt
```

> 若还没建虚拟环境,可用:
> ```bash
> python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
> ```

自检(可选但推荐,会提示缺什么):

```bash
/www/server/pyporject_evn/afd_venv/bin/python deploy_check.py
```

- 看到「未配置数据库 → 将进入安装向导」之类提示 = 正常,继续;
- 看到 `[FAIL]`(缺依赖等)→ 按提示处理后再继续。

---

## 6. 添加 Python 项目并启动

宝塔 → **Python 项目管理器 → 添加项目**:

- 项目路径:`/www/wwwroot/afd`
- Python 版本:3.10+
- 框架:FastAPI
- 端口:`8000`
- **启动方式**:面板无 uvicorn 选项,二选一:
  - **命令行启动**,启动命令:
    ```
    uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
    ```
  - 或 **gunicorn**:通讯协议选 **asgi**,启动文件/应用填 `main:app`
    > ⚠️ 该方式依赖 `uvicorn.workers.UvicornWorker`,而它在 uvicorn 0.34+ 已被移除,故 `requirements.txt` 已锁 `uvicorn<0.35`。**推荐用上面的命令行启动方式,不受此限制。**
- 勾选「安装模块依赖」
- 启动项目

> 首次启动会自动建表(含 `platform_settings.installed` 等新列)。**没有 `.env` 也能启动**,因为程序已容错——连不上库会正常进入安装向导。

---

## 7. 绑定域名 + HTTPS

方式任选:

- **A(推荐)**:Python 项目管理器 → 项目 →「映射域名」→ 选你的站点/填域名;
- **B**:宝塔「网站 → 添加站点」→ 反向代理到 `127.0.0.1:8000`。

然后**申请 SSL 证书并强制 HTTPS**(生产环境 Cookie 为 Secure,必须 HTTPS)。

---

## 8. 打开网站 → 安装向导(分两步,全网页)

浏览器访问 `https://你的域名`。

**STEP 1 · 数据库配置**(首次访问自动进入 `/install`):

- 填 `DB_HOST=127.0.0.1`、`DB_PORT=3306`、`DB_NAME=afdianpu`、`DB_USER`、`DB_PASSWORD`(第 3 步建的);
- 点「测试并保存」→ 服务端**当场测试连接**;成功后自动把 `DB_*` + **自动生成的会话密钥**写入项目 `.env`;
- 页面提示「配置已保存」。

**重启一次**:宝塔项目管理器 → 该项目 → **重启**(让 `.env` 配置生效)。

**STEP 2 · 创建管理员 + 业务配置**(重启后刷新 `/install`):

- 填**管理员账号**:邮箱(QQ/163)/店铺名/密码/确认;
- 可选填业务配置:SMTP(邮件)、平台 Logo、爱发电消费者账号/密码;
- 提交 → 管理员创建成功 → 自动登录进入「数据预览」。

---

## 9. 完成后的规则

- **管理员唯一来源 = 安装向导**;此后注册的新账号一律是普通商户(送 ¥0.20 API 费用)。
- 管理员可在「个人中心 → 平台配置」修改 SMTP、平台账号、微信/支付宝开关等,**即时生效**(存数据库,优先于 `.env`)。
- 忘记管理员账号/密码:清库重走安装向导,或数据库里直接改 `users` 表。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| 第一次访问仍是首页而非 `/install` | 数据库里 `platform_settings` 有残留 `installed=1`。清空该表(或整库重建,见 `database/reset.sql`)后重启 |
| STEP1 提交提示连接失败 | 检查 MySQL 是否启动、库名/账号/密码是否填对、该库是否允许本机访问 |
| 填完 STEP1 后刷新仍在 STEP1 | 说明没有重启;重启项目后再刷新 |
| 重启后白屏/500 | 查看 Python 项目管理器「日志」;常见是依赖没装全或 `.env` 写权限问题(站点目录需对 www 可写) |
| 换服务器迁移 | 把 `fastapi/` 目录带走,新机按本教程从第 2 步开始即可(数据库重填、管理员重新创建) |

---

## 随代码一起带走的资产

- `deploy_check.py` —— 部署自检脚本(建议每次部署后先跑)
- `database/schema.sql` —— 表结构(可选手工导入;程序也会自动建)
- `database/reset.sql` —— 清库重装
- `.env.example` —— 仅供参考(实际 `.env` 由安装向导自动生成,无需手编)
- `DEPLOY-TUTORIAL.md` —— 更详细的操作图解版(若需要)
