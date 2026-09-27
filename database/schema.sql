-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 数据库表结构(手工导入用)
--
-- ⚠️ 本文件由 app/db.py 的 SQLAlchemy 模型**逐列转写**而来,与当前代码保持同步。
--    平时用不到它 —— 程序首次启动时会按模型自动建表(init_db → create_all)。
--    只有"程序自动建表失败、需要手工导入"时才用本文件,二选一即可。
--
-- 约定(与 create_all 的实际行为保持一致):
--   · 自增主键      → INT NOT NULL AUTO_INCREMENT
--   · String(n)     → VARCHAR(n)     · Text → TEXT
--   · Boolean       → BOOL(=TINYINT(1))
--   · index=True    → KEY ix_<表>_<列>
--   · unique=True   → UNIQUE KEY ix_<表>_<列>
--   · 代码里的 default=datetime.now / onupdate 属**应用层默认**,
--     模型不会生成 DDL 的 DEFAULT CURRENT_TIMESTAMP,故此处也不写。
--   · 表之间**没有真正的外键约束**(category_id / product_id 等都是普通整数列),
--     所以建表顺序无所谓。
-- ══════════════════════════════════════════════════════════════

-- ── 商户/管理员账号 ──
CREATE TABLE IF NOT EXISTS `users` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(120) NOT NULL,
  `shop_name` VARCHAR(36) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `role` VARCHAR(16) NOT NULL DEFAULT 'merchant' COMMENT 'admin|merchant',
  `status` VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active|disabled',
  `afdian_user_id` VARCHAR(120) NOT NULL DEFAULT '',
  `afdian_token` VARCHAR(255) NOT NULL DEFAULT '',
  `shop_logo_url` VARCHAR(500) NOT NULL DEFAULT '',
  `bio` VARCHAR(600) NOT NULL DEFAULT '',
  `qq` VARCHAR(40) NOT NULL DEFAULT '' COMMENT '商家 QQ(前台店铺展示)',
  `wechat` VARCHAR(60) NOT NULL DEFAULT '' COMMENT '商家微信(前台店铺展示)',
  `webhook_url` VARCHAR(500) NOT NULL DEFAULT '',
  `webhook_method` VARCHAR(8) NOT NULL DEFAULT 'post' COMMENT 'post|get',
  `webhook_encode` VARCHAR(12) NOT NULL DEFAULT 'raw' COMMENT 'raw|form|field',
  `webhook_headers` VARCHAR(1000) NOT NULL DEFAULT '' COMMENT '自定义请求头,多行 k: v',
  `webhook_params` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '自定义查询参数,多行 k=v',
  `webhook_body` VARCHAR(2000) NOT NULL DEFAULT '' COMMENT '附加自定义字段 JSON(并入订单 payload)',
  `email_notify` BOOL NOT NULL DEFAULT true,
  `balance_notify` BOOL NOT NULL DEFAULT true,
  `api_balance_cents` INT NOT NULL DEFAULT 0,
  `balance_threshold_cents` INT NOT NULL DEFAULT 100,
  `last_balance_notify_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_users_email` (`email`),
  UNIQUE KEY `ix_users_shop_name` (`shop_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商户/管理员账号';

-- ── 找回密码令牌 ──
CREATE TABLE IF NOT EXISTS `password_resets` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(120) NOT NULL,
  `token` VARCHAR(64) NOT NULL,
  `expires_at` DATETIME NOT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_password_resets_token` (`token`),
  KEY `ix_password_resets_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='找回密码令牌';

-- ── 注册邮箱验证码 ──
CREATE TABLE IF NOT EXISTS `verification_codes` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(120) NOT NULL,
  `code` VARCHAR(8) NOT NULL,
  `expires_at` DATETIME NOT NULL,
  `last_sent_at` DATETIME NOT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_verification_codes_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='注册邮箱验证码';

-- ── 登录失败锁定 ──
CREATE TABLE IF NOT EXISTS `login_locks` (
  `identifier` VARCHAR(120) NOT NULL,
  `fail_count` INT NOT NULL DEFAULT 0,
  `window_started_at` DATETIME NOT NULL,
  `locked_until` DATETIME NULL,
  PRIMARY KEY (`identifier`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录失败锁定';

-- ── 店铺分类(独立表,与 SKU 解耦) ──
CREATE TABLE IF NOT EXISTS `product_categories` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `merchant_id` INT NOT NULL,
  `name` VARCHAR(60) NOT NULL COMMENT '分类名',
  `icon_url` VARCHAR(500) NOT NULL DEFAULT '',
  `sort_order` INT NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_product_categories_merchant_id` (`merchant_id`),
  KEY `ix_product_categories_sort_order` (`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺分类';

-- ── 商品 ──
CREATE TABLE IF NOT EXISTS `products` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `merchant_id` INT NOT NULL,
  `category_id` INT NOT NULL DEFAULT 0 COMMENT '关联 product_categories.id',
  `title` VARCHAR(180) NOT NULL,
  `sku_name` VARCHAR(180) NOT NULL,
  `price` INT NOT NULL COMMENT '元,>=5',
  `is_recharge` BOOL NOT NULL DEFAULT false,
  `recharge_grant_cents` INT NOT NULL DEFAULT 0,
  `sort_order` INT NOT NULL DEFAULT 0,
  `delivery_type` VARCHAR(16) NOT NULL DEFAULT 'merchant' COMMENT 'merchant=商户发货|platform=平台发货',
  `delivery_kind` VARCHAR(16) NOT NULL DEFAULT '' COMMENT '平台发货时:card=卡密|link=链接',
  `delivery_link` VARCHAR(1000) NOT NULL DEFAULT '' COMMENT 'kind=link 时的发货内容',
  `delivery_tip` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '提货页给买家的说明(可选)',
  `stock_limit` INT NOT NULL DEFAULT 0 COMMENT '限购总量:0=不限量;>0 时可售数量=stock_limit-已付款单数',
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_products_merchant_id` (`merchant_id`),
  KEY `ix_products_category_id` (`category_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品(SKU)';

-- ── 订单 ──
CREATE TABLE IF NOT EXISTS `orders` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `order_no` VARCHAR(64) NOT NULL COMMENT '爱发电订单号(out_trade_no)',
  `product_id` INT NULL,
  `merchant_id` INT NOT NULL COMMENT '卖家',
  `category` VARCHAR(60) NOT NULL COMMENT '下单时的分类名快照',
  `title` VARCHAR(180) NOT NULL,
  `sku` VARCHAR(180) NOT NULL,
  `total` INT NOT NULL COMMENT '元',
  `channel` VARCHAR(16) NOT NULL DEFAULT 'wechat' COMMENT 'wechat|alipay',
  `remark` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '分类&标题&SKU名&价格',
  `buyer_account` VARCHAR(120) NOT NULL DEFAULT '',
  `buyer_email` VARCHAR(120) NOT NULL DEFAULT '' COMMENT '下单时选填,仅用于付款后发卡邮件',
  `status` VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending|paid',
  `paid_at` DATETIME NULL,
  `delivered_at` DATETIME NULL COMMENT '卡密/链接发放时间',
  `delivery_tip` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '下单时的提货说明快照',
  `recharge_for_id` INT NULL COMMENT '充值订单:充值商户(买家)',
  `recharge_grant_cents` INT NULL COMMENT '充值到账金额(分)',
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_orders_order_no` (`order_no`),
  KEY `ix_orders_merchant_id` (`merchant_id`),
  KEY `ix_orders_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单';

-- ── API 余额流水 ──
CREATE TABLE IF NOT EXISTS `fee_ledger` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `merchant_id` INT NOT NULL,
  `order_id` INT NULL,
  `delta_cents` INT NOT NULL,
  `balance_after_cents` INT NOT NULL,
  `reason` VARCHAR(24) NOT NULL DEFAULT 'order_fee',
  `note` VARCHAR(255) NOT NULL DEFAULT '',
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_fee_ledger_merchant_id` (`merchant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='API 余额流水';

-- ── 平台配置(单行) ──
CREATE TABLE IF NOT EXISTS `platform_settings` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `installed` BOOL NOT NULL DEFAULT false COMMENT '安装向导完成后置 true',
  `consumer_account` VARCHAR(120) NOT NULL DEFAULT '',
  `consumer_password` VARCHAR(255) NOT NULL DEFAULT '',
  `consumer_auth_token` VARCHAR(191) NOT NULL DEFAULT '' COMMENT '爱发电网页会话 auth_token',
  `consumer_token_at` DATETIME NULL COMMENT '上次成功登录拿 token 的时间',
  `platform_logo_url` VARCHAR(500) NOT NULL DEFAULT '',
  `wechat_enabled` BOOL NOT NULL DEFAULT true,
  `wechat_disabled_note` VARCHAR(255) NOT NULL DEFAULT '',
  `alipay_enabled` BOOL NOT NULL DEFAULT true,
  `alipay_disabled_note` VARCHAR(255) NOT NULL DEFAULT '',
  `app_base_url` VARCHAR(300) NOT NULL DEFAULT '',
  `afdian_live` BOOL NULL COMMENT '遗留列:代码已不读取,保留仅为兼容旧库',
  `enable_preview_login` BOOL NULL COMMENT 'NULL=跟随 .env',
  `smtp_host` VARCHAR(120) NOT NULL DEFAULT '',
  `smtp_port` INT NULL,
  `smtp_user` VARCHAR(120) NOT NULL DEFAULT '',
  `smtp_pass` VARCHAR(255) NOT NULL DEFAULT '',
  `smtp_from` VARCHAR(120) NOT NULL DEFAULT '',
  `api_fee_cents` INT NULL COMMENT '单次API费用(分);NULL=用 .env',
  `allowed_email_domains` VARCHAR(600) NOT NULL DEFAULT '' COMMENT '注册允许邮箱域名,;分隔,空=不限制',
  `webhook_base_url` VARCHAR(300) NOT NULL DEFAULT '' COMMENT '爱发电 Webhook 平台外部域名,留空用当前访问域名',
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台配置(单行)';

-- ── 平台通知 ──
CREATE TABLE IF NOT EXISTS `notices` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `title` VARCHAR(200) NOT NULL,
  `content` VARCHAR(2000) NOT NULL DEFAULT '',
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台通知';

-- ── 通用云端进度(跨设备) ──
CREATE TABLE IF NOT EXISTS `user_progress` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `pkey` VARCHAR(64) NOT NULL,
  `value` TEXT NOT NULL COMMENT 'JSON 文本',
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_progress_user_pkey` (`user_id`, `pkey`),
  KEY `ix_user_progress_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通用云端进度(跨设备)';

-- ── Webhook 回调发送记录 ──
CREATE TABLE IF NOT EXISTS `webhook_sends` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `order_no` VARCHAR(64) NOT NULL DEFAULT '',
  `url` VARCHAR(500) NOT NULL DEFAULT '',
  `method` VARCHAR(8) NOT NULL DEFAULT 'POST',
  `status_code` INT NOT NULL DEFAULT 0,
  `ok` BOOL NOT NULL DEFAULT false,
  `is_test` BOOL NOT NULL DEFAULT false COMMENT '发送测试标记(非真实订单回调)',
  `resp_head` TEXT,
  `resp_body` TEXT,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_webhook_sends_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Webhook 回调发送记录';

-- ── 卡密库存(SKU 级) ──
CREATE TABLE IF NOT EXISTS `stock_cards` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `product_id` INT NOT NULL,
  `merchant_id` INT NOT NULL,
  `content` TEXT NOT NULL COMMENT '单行卡密',
  `locked` BOOL NOT NULL DEFAULT false COMMENT '被订单锁定(含未付款)',
  `order_no` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '锁它的订单号',
  `locked_at` DATETIME NULL,
  `used_at` DATETIME NULL COMMENT '付款成功时间;NULL=未售出',
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_stock_cards_product_id` (`product_id`),
  KEY `ix_stock_cards_merchant_id` (`merchant_id`),
  KEY `ix_stock_cards_locked` (`locked`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='卡密库存';

-- ── 发放记录(提货幂等核心) ──
CREATE TABLE IF NOT EXISTS `delivery_records` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `order_no` VARCHAR(64) NOT NULL,
  `product_id` INT NULL,
  `merchant_id` INT NOT NULL,
  `kind` VARCHAR(16) NOT NULL DEFAULT '' COMMENT 'card=卡密|link=链接|""=不发放',
  `content` TEXT NOT NULL DEFAULT '',
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_delivery_records_order_no` (`order_no`),
  KEY `ix_delivery_records_merchant_id` (`merchant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发放记录(同一订单号只发一次)';

-- ── 订单创建计数(只增不减,不受未付款订单被清理影响) ──
CREATE TABLE IF NOT EXISTS `order_stats` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `merchant_id` INT NOT NULL,
  `day` VARCHAR(10) NOT NULL COMMENT 'YYYY-MM-DD',
  `created_count` INT NOT NULL DEFAULT 0,
  `paid_count` INT NOT NULL DEFAULT 0,
  `paid_amount` INT NOT NULL DEFAULT 0,
  `updated_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_order_stats_merchant_id` (`merchant_id`),
  KEY `ix_order_stats_day` (`day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单创建计数';

-- ── 爱发电回调原始记录(调试用) ──
CREATE TABLE IF NOT EXISTS `afdian_webhook_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `body_text` TEXT NOT NULL COMMENT '收到的原始 JSON',
  `order_no` VARCHAR(100) NOT NULL DEFAULT '',
  `matched` BOOL NOT NULL DEFAULT false COMMENT '是否命中库内 Order',
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='爱发电回调原始记录';
