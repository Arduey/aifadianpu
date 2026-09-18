"""爱发电铺 · 部署自检(新服务器装完代码第一步跑它)
用法(把路径换成你的实际项目目录与虚拟环境 Python):
  cd /www/wwwroot/<你的项目目录>
  <你的虚拟环境>/bin/python deploy_check.py

检查:Python 版本、依赖是否装好、.env 数据库配置、能否连上 MySQL、
平台是否已安装(未安装会提示走 /install 安装向导)。
"""
import os
import sys

OK = "\033[92m[OK]\033[0m"
BAD = "\033[91m[FAIL]\033[0m"
WARN = "\033[93m[WARN]\033[0m"


def main():
    print("=" * 60)
    print("  爱发电铺 部署自检")
    print("=" * 60)

    v = sys.version_info
    print(f"{OK if v >= (3, 10) else BAD} Python 版本: {'%d.%d.%d' % (v[0], v[1], v[2])} (需 >=3.10)")

    try:
        import app.main  # noqa: F401
        print(f"{OK} 应用 import 成功 (依赖齐全)")
    except ImportError as e:
        print(f"{BAD} 依赖缺失或 import 失败: {e}")
        print("     请先安装依赖: pip install -r requirements.txt")
        return 1
    except Exception as e:
        print(f"{BAD} 应用加载异常: {type(e).__name__}: {e}")
        return 1

    from dotenv import load_dotenv
    load_dotenv()
    db_host = os.getenv("DB_HOST", "").strip()
    db_name = os.getenv("DB_NAME", "").strip()
    db_user = os.getenv("DB_USER", "").strip()
    db_pwd = os.getenv("DB_PASSWORD", "").strip()
    missing = [k for k, val in (("DB_HOST", db_host), ("DB_NAME", db_name),
                                ("DB_USER", db_user), ("DB_PASSWORD", db_pwd)) if not val]
    if missing:
        print(f"{WARN} 尚未配置数据库(缺: {', '.join(missing)})")
        print(f"{OK}   这是全新部署的正常状态 → 启动后访问 /install 安装向导,网页填写数据库与管理员即可(配置由向导自动写入 .env)")
        print("=" * 60)
        return 0
    if "请改为" in db_pwd or "请改为" in str(os.getenv("SESSION_SECRET", "")):
        print(f"{WARN} .env 里仍有「请改为」占位符,建议交给安装向导重写")

    try:
        from sqlalchemy import text
        from app.db import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"{OK} 数据库 {db_name}@{db_host} 连接成功")
    except Exception as e:
        print(f"{BAD} 数据库连接失败: {e}")
        print("     可访问 /install 安装向导在网页里重新填写数据库配置")
        return 1

    try:
        from app.auth import is_installed
        if is_installed():
            print(f"{OK} 平台已安装,可正常启用")
        else:
            print(f"{WARN} 平台尚未安装 → 启动后访问网站会自动进入 /install 安装向导,创建管理员")
    except Exception as e:
        print(f"{WARN} 无法判断安装状态(可能表未建): {e}")
        print("     提示:启动应用会自动建表;若已存在旧表且缺新列,请先按 database/reset.sql 或删 platform_settings 让程序重建")

    print("=" * 60)
    print("自检完成。没有 [FAIL] 即可启动应用 → 访问域名 → 走 /install 安装向导。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
