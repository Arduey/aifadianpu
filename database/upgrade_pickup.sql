-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 自助提货功能 升级 SQL（新增列）
-- 表（stock_cards / delivery_records）由程序启动时自动创建，无需手工建。
-- 已有表新增列 create_all 不会自动同步，需先执行下面的 ALTER，再重启后端。
-- 执行顺序：先 ALTER（本文件）→ 再重启后端。
-- ══════════════════════════════════════════════════════════════

-- 1) products：SKU 级发货方式
ALTER TABLE products
  ADD COLUMN delivery_type VARCHAR(16)  NOT NULL DEFAULT 'merchant' COMMENT 'merchant=商户发货|platform=平台发货',
  ADD COLUMN delivery_kind VARCHAR(16)  NOT NULL DEFAULT ''         COMMENT '平台发货类型:card=卡密|link=链接',
  ADD COLUMN delivery_link VARCHAR(1000) NOT NULL DEFAULT ''        COMMENT 'kind=link 时的链接',
  ADD COLUMN delivery_tip  VARCHAR(500) NOT NULL DEFAULT ''         COMMENT '提货页给买家的说明(可选)';

-- 2) orders：买家收货邮箱（仅用于付款后发卡邮件）与发放时间
ALTER TABLE orders
  ADD COLUMN buyer_email  VARCHAR(120) NOT NULL DEFAULT '' COMMENT '下单时选填,用于付款后发卡邮件',
  ADD COLUMN delivered_at DATETIME     NULL                COMMENT '卡密/链接发放时间';
