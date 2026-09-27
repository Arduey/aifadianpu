-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · orders 表新增「提货说明」下单快照
--
-- 背景:提货说明(delivery_tip)原本是提货时**实时读商品**的,商品一改,
--       历史订单显示的内容也跟着变。本列把下单时的说明存下来,历史订单固定不变。
--
-- 幂等:MySQL 不支持 ADD COLUMN IF NOT EXISTS,重复执行会报
--       #1060 Duplicate column name —— 那是**正常**的,说明已经加过了,忽略即可。
-- 顺序:**先跑本 SQL,再回宝塔重启后端**(反了会报 Unknown column)。
-- ══════════════════════════════════════════════════════════════

ALTER TABLE `orders`
  ADD COLUMN `delivery_tip` VARCHAR(500) NOT NULL DEFAULT ''
  COMMENT '下单时的提货说明快照';

-- ── 自查:应看到 delivery_tip 这一行 ──
-- (用 SHOW 而非 information_schema:受限账号读 information_schema 会报 #1044)
SHOW FULL COLUMNS FROM `orders` LIKE 'delivery_tip';
