-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 订单测试标记（虚拟订单）
-- 语义：is_test = 1 表示这是店主在「商品管理」里生成的虚拟订单，
--       供第三方对接测试查单 / 提货，不占真实卡密、不计销量与限购。
-- 执行顺序：先跑本文件 → 再重启后端（先重启会因新列未加载而报 Unknown column）。
-- ══════════════════════════════════════════════════════════════

ALTER TABLE `orders`
  ADD COLUMN `is_test` BOOL NOT NULL DEFAULT false COMMENT '测试订单:1=店铺管理里生成的虚拟订单,不计销量/不占库存';

-- 自查：确认列已加（SHOW COLUMNS 只需要本表权限，不碰 information_schema）
-- 注意：不要用 SELECT ... FROM information_schema.COLUMNS —— 库用户通常没有该库权限，
--       会报 #1044 Access denied for user 'xxx'@'localhost' to database 'information_schema'。
SHOW COLUMNS FROM `orders` LIKE 'is_test';