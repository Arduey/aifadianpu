-- ============================================================
-- 升级：分类独立成表（商品用 category_id 关联）
-- ============================================================
-- 用途：把原先「分类名 + 分类图标」寄生在 products 上的设计，
--       升级为独立分类表 product_categories，商品通过 category_id 关联。
--
-- ⚠️ 执行顺序：先执行本 SQL，再重启后端。
--    顺序不可反 —— 若先重启，SQLAlchemy 会按新结构查询 products.category_id，
--    而库里还没有该列，会报 Unknown column。
--
-- 本脚本是「有历史数据也要平滑升级」的版本：会先建表、回填、加列、再删旧列。
-- 如果你的库是全新库（还没有 products 表），什么都不用执行 ——
-- 重启后端时 create_all 会直接按新结构建好全部表。
-- ============================================================

-- ① 建独立分类表（若已存在则跳过报错，可重复执行）
CREATE TABLE IF NOT EXISTS `product_categories` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `merchant_id` INT          NOT NULL,
  `name`        VARCHAR(60)  NOT NULL,
  `icon_url`    VARCHAR(500) NOT NULL DEFAULT '',
  `sort_order`  INT          NOT NULL DEFAULT 0,
  `created_at`  DATETIME     NOT NULL,
  `updated_at`  DATETIME     NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_product_categories_merchant_id` (`merchant_id`),
  KEY `ix_product_categories_sort_order`  (`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ② 把现有商品里出现过的分类回填成分类记录
--    （每个商户的每个分类名一条，图标取该分类下任意非空的 category_icon_url，
--      排序取该分类下最小的商品 sort_order，尽量保持原有先后）
INSERT INTO `product_categories` (`merchant_id`, `name`, `icon_url`, `sort_order`, `created_at`, `updated_at`)
SELECT
  t.`merchant_id`,
  t.`category`,
  COALESCE(NULLIF(MAX(t.`category_icon_url`), ''), ''),
  MIN(t.`sort_order`),
  NOW(),
  NOW()
FROM `products` t
WHERE t.`category` IS NOT NULL AND t.`category` <> ''
  AND NOT EXISTS (
    SELECT 1 FROM `product_categories` c
    WHERE c.`merchant_id` = t.`merchant_id` AND c.`name` = t.`category`
  )
GROUP BY t.`merchant_id`, t.`category`;

-- ③ products 增加 category_id 列（若已存在则跳过报错，可重复执行）
ALTER TABLE `products` ADD COLUMN `category_id` INT NOT NULL DEFAULT 0;

-- ④ 按「商户 + 分类名」把商品的 category_id 关联到分类表
UPDATE `products` p
JOIN `product_categories` c
  ON c.`merchant_id` = p.`merchant_id` AND c.`name` = p.`category`
SET p.`category_id` = c.`id`;

-- ⑤ 加索引
ALTER TABLE `products` ADD KEY `ix_products_category_id` (`category_id`);

-- ⑥ 确认 ④ 全部关联成功后再删旧列
--    先跑这句自查：结果应为 0（没有 category_id 为 0 的残留商品）
--    SELECT COUNT(*) AS 未关联商品数 FROM products WHERE category_id = 0;
ALTER TABLE `products` DROP COLUMN `category`;
ALTER TABLE `products` DROP COLUMN `category_icon_url`;

-- ============================================================
-- 订单表 orders.category 是「下单时的分类名快照」，**不要动**，
-- 历史订单要保留当时的分类名，才能真实留档。
-- ============================================================

-- ------------------------------------------------------------
-- 单条执行版本（若你的工具不支持一次跑多条，可逐条复制执行）
-- ------------------------------------------------------------
-- CREATE TABLE IF NOT EXISTS `product_categories` (
--   `id` INT NOT NULL AUTO_INCREMENT, `merchant_id` INT NOT NULL,
--   `name` VARCHAR(60) NOT NULL, `icon_url` VARCHAR(500) NOT NULL DEFAULT '',
--   `sort_order` INT NOT NULL DEFAULT 0, `created_at` DATETIME NOT NULL,
--   `updated_at` DATETIME NOT NULL, PRIMARY KEY (`id`),
--   KEY `ix_product_categories_merchant_id` (`merchant_id`),
--   KEY `ix_product_categories_sort_order` (`sort_order`)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
