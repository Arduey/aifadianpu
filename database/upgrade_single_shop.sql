-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 单店化迁移（多商户平台 → 只有管理员一个商户的独立商店）
--
-- 做什么：
--   1. 选定唯一管理员（role='admin' 且 status='active' 的最早一个）
--   2. 把所有 merchant_id 指向其他商户的数据，统一改归管理员
--   3. 合并后可能撞车的唯一性/软唯一性先做去重（商品四元、卡密）
--   4. 删除其他商户账号（保留其订单数据，订单已归管理员）
--   5. users.role 默认值改为 'admin'
--
-- ⚠️ 执行顺序：先备份数据库 → 跑本文件 → 再部署新代码 → 重启后端。
--    本脚本会**删除除管理员外的所有用户账号**，务必先确认下面 PRE-CHECK 的输出。
--
-- ⚠️ 必须在与线上同一个库执行（默认库名 afd）。
-- ══════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────
-- STEP 0 · PRE-CHECK：先单独跑这一段，确认「管理员是谁」「有多少商户将被删」
--   管理员必须是 role='admin' 且 status='active'；若返回 0 行，**不要往下执行**。
-- ─────────────────────────────────────────────────────────────
SELECT id, email, shop_name, role, status,
       (SELECT COUNT(*) FROM users u2 WHERE u2.id <> u1.id) AS other_users
FROM users u1
WHERE role = 'admin' AND status = 'active'
ORDER BY id
LIMIT 1;

-- 统计会被删掉的商户账号数（含其名下商品/订单将被归给管理员）
SELECT COUNT(*) AS merchants_to_delete
FROM users
WHERE id <> (SELECT id FROM (SELECT id FROM users WHERE role='admin' AND status='active' ORDER BY id LIMIT 1) t);

-- 统计迁移后会出现「同分类+同标题+同SKU」重复的商品（这些会被去重逻辑跳过）
SELECT COUNT(*) AS dup_groups FROM (
  SELECT title, sku_name, COUNT(*) c
  FROM products
  GROUP BY title, sku_name
  HAVING c > 1
) x;


-- ─────────────────────────────────────────────────────────────
-- STEP 1 · 建一个临时视图装「唯一管理员 id」，后面所有语句都用它
--   用视图而不是变量，是为了避免 phpMyAdmin 分条执行时变量丢失。
-- ─────────────────────────────────────────────────────────────
DROP VIEW IF EXISTS v_single_owner;
CREATE VIEW v_single_owner AS
  SELECT id AS owner_id
  FROM users
  WHERE role = 'admin' AND status = 'active'
  ORDER BY id
  LIMIT 1;


-- ─────────────────────────────────────────────────────────────
-- STEP 2 · 去重（必须在改 merchant_id 之前做，否则会把别人的同款商品挤成冲突）
--   规则：同一「标题+SKU」只保留 id 最小的那条，其余商品的 merchant_id 仍会改，
--        但为避免前台出现两条一模一样的商品，这里把重复的**较新**商品标记进回收表，
--        由 STEP 3 一并处理其卡密。
-- ─────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS tmp_dup_products;
CREATE TABLE tmp_dup_products (id INT PRIMARY KEY);

INSERT INTO tmp_dup_products (id)
SELECT p.id
FROM products p
JOIN (
  SELECT title, sku_name, MIN(id) AS keep_id
  FROM products
  GROUP BY title, sku_name
  HAVING COUNT(*) > 1
) d
  ON p.title = d.title AND p.sku_name = d.sku_name
WHERE p.id <> d.keep_id;


-- ─────────────────────────────────────────────────────────────
-- STEP 3 · 把重复商品名下的卡密一起删掉，再删重复商品本身
--   只删「未锁定、未售出」的卡密（locked=0 且 used_at IS NULL），
--   已售出/已锁定的保留，历史发货记录不丢。
--   注：delivery_records 只按 order_no 记录、没有 card_id，所以用 stock_cards 自身状态判断。
-- ─────────────────────────────────────────────────────────────
DELETE FROM stock_cards
WHERE product_id IN (SELECT id FROM tmp_dup_products)
  AND locked = 0
  AND used_at IS NULL;

DELETE FROM products WHERE id IN (SELECT id FROM tmp_dup_products);


-- ─────────────────────────────────────────────────────────────
-- STEP 4 · 把所有 merchant_id 统一改归管理员
--   注意：orders 也一起迁，历史订单会显示在新店主名下（订单里的分类/标题快照不受影响）
-- ─────────────────────────────────────────────────────────────
UPDATE product_categories SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE products           SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE orders             SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE stock_cards        SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE delivery_records   SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE order_stats        SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE fee_ledger         SET merchant_id = (SELECT owner_id FROM v_single_owner);
UPDATE webhook_sends      SET user_id     = (SELECT owner_id FROM v_single_owner);


-- ─────────────────────────────────────────────────────────────
-- STEP 5 · 删掉除管理员外的所有用户账号
--   它们的商品/订单/卡密已在 STEP 4 归给管理员，delivery_records 也保留。
--   ⚠️ 这一步不可逆，确认 STEP 0 的输出后再执行。
-- ─────────────────────────────────────────────────────────────
DELETE FROM users WHERE id <> (SELECT owner_id FROM v_single_owner);


-- ─────────────────────────────────────────────────────────────
-- STEP 6 · 单店化后的字段默认值与清理
-- ─────────────────────────────────────────────────────────────
-- 新用户默认就是 admin（安装向导创建的人；程序不再有商户注册入口）
ALTER TABLE users MODIFY COLUMN role VARCHAR(16) NOT NULL DEFAULT 'admin';

-- 余额/服务费体系已废弃：把唯一管理员的余额置 0、关掉余额提醒（列保留，程序不再读写判断）
UPDATE users SET api_balance_cents = 0,
                 balance_notify = 0,
                 balance_threshold_cents = 0,
                 last_balance_notify_at = NULL;

-- 公告体系已下线（管理员没有需要通知的商户了）
DROP TABLE IF EXISTS notices;

-- 注册验证码已下线（不再有商户注册）
DROP TABLE IF EXISTS verification_codes;

-- 多余的邮箱域名白名单/单次费用设置不再使用（列保留，程序不再读取）
UPDATE platform_settings SET allowed_email_domains = '';
UPDATE platform_settings SET api_fee_cents = 0;


-- ─────────────────────────────────────────────────────────────
-- STEP 7 · 清理临时对象 + 自查
-- ─────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS tmp_dup_products;
DROP VIEW IF EXISTS v_single_owner;

-- 应只剩 1 行
SELECT COUNT(*) AS users_left FROM users;

-- 应该全部等于管理员 id（下面每行都应是 0）
SELECT 'product_categories' AS table_name, COUNT(*) AS not_owner FROM product_categories WHERE merchant_id <> (SELECT MIN(id) FROM users)
UNION ALL SELECT 'products',         COUNT(*) FROM products         WHERE merchant_id <> (SELECT MIN(id) FROM users)
UNION ALL SELECT 'orders',           COUNT(*) FROM orders           WHERE merchant_id <> (SELECT MIN(id) FROM users)
UNION ALL SELECT 'stock_cards',      COUNT(*) FROM stock_cards      WHERE merchant_id <> (SELECT MIN(id) FROM users)
UNION ALL SELECT 'delivery_records', COUNT(*) FROM delivery_records WHERE merchant_id <> (SELECT MIN(id) FROM users)
UNION ALL SELECT 'order_stats',      COUNT(*) FROM order_stats      WHERE merchant_id <> (SELECT MIN(id) FROM users)
UNION ALL SELECT 'fee_ledger',       COUNT(*) FROM fee_ledger       WHERE merchant_id <> (SELECT MIN(id) FROM users);

-- 用「同一标题+SKU」再查一遍重复（应为 0 行）
SELECT title, sku_name, COUNT(*) c FROM products GROUP BY title, sku_name HAVING c > 1;
