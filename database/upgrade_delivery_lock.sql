-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 堵住「旧商户发货订单被改成卡密后能提到卡密」
--
-- 背景:提货是「先查 delivery_records,没有才按商品【当前】配置现场发放」。
--       商户发货的订单过去**不落发放记录**,所以商品一旦被改成
--       「平台发货 · 卡密」,拿旧订单号来查就会现场抢一个卡密(凭白消耗库存)。
--       本次给这类历史订单补一条**空记录**,把「此单不发放」这个结论钉死。
--
-- 判定:订单已付款 + 没有发放记录 + 商品当前不是平台发货(或商品已被删)。
-- 幂等:可重复执行(靠 LEFT JOIN ... IS NULL 过滤)。
-- 顺序:先跑本 SQL,再回宝塔重启后端(本次同时改了 .py,必须重启)。
-- ══════════════════════════════════════════════════════════════

INSERT INTO `delivery_records` (`order_no`, `product_id`, `merchant_id`, `kind`, `content`, `created_at`)
SELECT o.`order_no`, o.`product_id`, o.`merchant_id`, '', '', NOW()
FROM `orders` o
LEFT JOIN `delivery_records` d ON d.`order_no` = o.`order_no`
LEFT JOIN `products` p ON p.`id` = o.`product_id`
WHERE d.`id` IS NULL
  AND o.`status` = 'paid'
  AND (p.`id` IS NULL OR p.`delivery_type` <> 'platform');

-- ── 自查 ──
-- 「已付款但无记录的剩余数」跑完后应为 0(或只剩平台发货待领的单,那是正常的)。
SELECT
  (SELECT COUNT(*) FROM `delivery_records`) AS 记录总数,
  (SELECT COUNT(*) FROM `orders` o
     LEFT JOIN `delivery_records` d ON d.`order_no` = o.`order_no`
    WHERE d.`id` IS NULL AND o.`status` = 'paid') AS 已付款但无记录数;
