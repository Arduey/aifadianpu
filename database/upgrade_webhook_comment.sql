-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 修正 platform_settings.webhook_base_url 的列注释
--
-- 背景:旧注释里写死了一个测试域名(已移除),而实际行为是
--       「留空 = 用当前访问域名」。仅影响列注释(元数据),不动任何数据。
--
-- 幂等:可重复执行(MODIFY COLUMN 反复跑无副作用)。
-- 顺序:先跑本 SQL,再回宝塔重启后端(本次同时改了 .py,必须重启)。
-- ══════════════════════════════════════════════════════════════

ALTER TABLE `platform_settings`
  MODIFY COLUMN `webhook_base_url` VARCHAR(300) NOT NULL DEFAULT ''
  COMMENT '爱发电 Webhook 平台外部域名,留空用当前访问域名,仅供后台展示拼接';

-- ── 自查 ──
-- 看返回的 Comment 列,应为「爱发电 Webhook 平台外部域名,留空用当前访问域名,仅供后台展示拼接」。
-- 这里用 SHOW FULL COLUMNS 而不是查 information_schema:
-- 受限账号(如宝塔为站点建的 'afd')读 information_schema 会报 #1044 Access denied。
SHOW FULL COLUMNS FROM `platform_settings` LIKE 'webhook_base_url';
