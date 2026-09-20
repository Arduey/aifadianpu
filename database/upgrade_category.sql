-- ============================================================================
--  爱发电铺 —— 分类独立成表 迁移脚本（原地升级你当前测试库的数据）
-- ============================================================================
--  背景：分类原先寄生在 products.category / products.category_icon_url 上；
--        现已改为独立表 product_categories，商品用 products.category_id 关联。
--
--  本脚本【不需要清库】，会把你现有的商品分类原地搬进新表并重建关联。
--
--  ★ 执行顺序（重要）：
--      ① 宝塔里【停掉后端】服务（或至少准备好马上重启）
--      ② 在宝塔 phpMyAdmin 里选中数据库 afd，粘贴执行本文件
--      ③ 【立刻重启后端】
--    ②→③ 之间站点会短暂 500，属正常；本脚本可重复执行，重跑无害。
--
--  ★ 执行前建议先备份：
--      mysqldump -u 用户名 -p afd products orders > afd_backup.sql
--
--  数据安全说明：
--    - orders（历史订单）表完全不动，其 category 列是下单时的快照，保留。
--    - products 的 category / category_icon_url 两列会先被搬运、再删除，
--      删除放在【最后一步】，中间任何一步失败都不会丢数据。
-- ============================================================================


-- ─────────────────────────────────────────────────────────────
-- 步骤 1/8  建独立分类表
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `product_categories` (
  `id`          INT          NOT NULL AUTO_INCREMENT,
  `merchant_id` INT          NOT NULL,
  `name`        VARCHAR(60)  NOT NULL COMMENT '分类名 禁& 同商户内唯一',
  `icon_url`    VARCHAR(500) NOT NULL DEFAULT '' COMMENT '空则前台回退平台LOGO',
  `sort_order`  INT          NOT NULL DEFAULT 0 COMMENT '越大越靠后',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_product_categories_merchant_id` (`merchant_id`),
  KEY `ix_product_categories_sort_order`  (`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺分类(独立于商品)';


-- ─────────────────────────────────────────────────────────────
-- 步骤 2/8  把现有商品里的分类回填成分类记录
--           每个「商户 + 分类名」一条；图标取该分类下任一非空值；
--           排序取该分类下最小的 sort_order（尽量保持原有先后）。
--           已存在的分类会跳过（可重复执行）。
-- ─────────────────────────────────────────────────────────────
INSERT INTO `product_categories` (`merchant_id`, `name`, `icon_url`, `sort_order`)
SELECT
  t.`merchant_id`,
  t.`category`,
  COALESCE(NULLIF(MAX(t.`category_icon_url`), ''), ''),
  MIN(t.`sort_order`)
FROM `products` t
WHERE t.`category` IS NOT NULL
  AND t.`category` <> ''
  AND NOT EXISTS (
    SELECT 1 FROM `product_categories` c
    WHERE c.`merchant_id` = t.`merchant_id` AND c.`name` = t.`category`
  )
GROUP BY t.`merchant_id`, t.`category`;


-- ─────────────────────────────────────────────────────────────
-- 步骤 3/8  给 products 加 category_id 列（已存在会报 "Duplicate column"，
--           忽略即可 —— 说明这步已经跑过了）。
-- ─────────────────────────────────────────────────────────────
ALTER TABLE `products` ADD COLUMN `category_id` INT NOT NULL DEFAULT 0
  COMMENT '关联 product_categories.id';


-- ─────────────────────────────────────────────────────────────
-- 步骤 4/8  按「商户 + 分类名」把商品的 category_id 关联到分类表
-- ─────────────────────────────────────────────────────────────
UPDATE `products` p
JOIN `product_categories` c
  ON c.`merchant_id` = p.`merchant_id` AND c.`name` = p.`category`
SET p.`category_id` = c.`id`;


-- ─────────────────────────────────────────────────────────────
-- 步骤 5/8  加索引（已存在会报 "Duplicate key name"，忽略即可）
-- ─────────────────────────────────────────────────────────────
ALTER TABLE `products` ADD KEY `ix_products_category_id` (`category_id`);


-- ─────────────────────────────────────────────────────────────
-- 步骤 6/8  ★ 自查：下面这句的结果必须是 0
--           若有商品 category_id = 0，说明它有分类名但没匹配上（比如分类名为空），
--           请先手工处理这些商品，再继续执行步骤 7、8。
-- ─────────────────────────────────────────────────────────────
SELECT COUNT(*) AS `未关联商品数_应为0` FROM `products` WHERE `category_id` = 0;


-- ─────────────────────────────────────────────────────────────
-- 步骤 7/8  数据核对（可选，看一眼搬得对不对；不产生任何修改）
-- ─────────────────────────────────────────────────────────────
SELECT
  c.`id`          AS 分类id,
  c.`merchant_id` AS 商户,
  c.`name`        AS 分类名,
  c.`icon_url`    AS 图标,
  c.`sort_order`  AS 排序,
  COUNT(p.`id`)   AS 商品数
FROM `product_categories` c
LEFT JOIN `products` p ON p.`category_id` = c.`id`
GROUP BY c.`id`, c.`merchant_id`, c.`name`, c.`icon_url`, c.`sort_order`
ORDER BY c.`merchant_id`, c.`sort_order`, c.`id`;


-- ─────────────────────────────────────────────────────────────
-- 步骤 8/8  ★★ 确认步骤 6 结果为 0 之后，才执行下面两句 —— 删除旧列
--           决定执行前，请确认步骤 6/7 的结果符合预期，且已备份。
-- ─────────────────────────────────────────────────────────────
ALTER TABLE `products` DROP COLUMN `category`;
ALTER TABLE `products` DROP COLUMN `category_icon_url`;


-- ============================================================================
--  附：如果中途出错想回退
--   步骤 8 之前（旧列还在）回退很简单：
--     ALTER TABLE `products` DROP COLUMN `category_id`;
--     DROP TABLE `product_categories`;
--   步骤 8 之后旧列已删，需用备份恢复：
--     mysql -u 用户名 -p afd < afd_backup.sql
-- ============================================================================
