-- 爱发电铺 · 清库重装(不可逆:删除全部数据)
-- 用途:改为「安装向导创建管理员」后,需清空旧数据重新走 /install
-- 执行:宝塔 phpMyAdmin 或 MySQL 客户端对本库执行以下语句
--  ⚠ 执行前请先备份(如有需要保留的历史数据)

SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE `orders`;
TRUNCATE `fee_ledger`;
TRUNCATE `products`;
TRUNCATE `users`;
TRUNCATE `password_resets`;
TRUNCATE `login_locks`;
TRUNCATE `platform_settings`;
SET FOREIGN_KEY_CHECKS = 1;

-- 说明:表结构如需变更(新增 installed/SMTP 等列),可用 database/schema.sql
-- 在 phpMyAdmin 重新导入该表,或在清库后由程序启动时 create_all 自动重建。
