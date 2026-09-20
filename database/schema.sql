-- ═════════════════════════════════════════════════════════
-- 爱发电铺 · MySQL 表结构(与 PostgreSQL 版完全对应)
-- 宝塔:数据库 → phpMyAdmin → 导入本文件,或命令行执行
-- 字符集 utf8mb4,引擎 InnoDB
-- ═════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS `users` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(120) NOT NULL COMMENT '仅QQ/163邮箱,唯一',
  `shop_name` VARCHAR(36) NOT NULL COMMENT '店铺名:中文/字母/数字≤12字符,唯一',
  `password_hash` VARCHAR(255) NOT NULL,
  `role` VARCHAR(16) NOT NULL DEFAULT 'merchant' COMMENT 'admin|merchant',
  `status` VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active|disabled(注销=停用)',
  `afdian_user_id` VARCHAR(120) NOT NULL DEFAULT '',
  `afdian_token` VARCHAR(255) NOT NULL DEFAULT '',
  `shop_logo_url` VARCHAR(500) NOT NULL DEFAULT '',
  `bio` VARCHAR(600) NOT NULL DEFAULT '',
  `qq` VARCHAR(40) NOT NULL DEFAULT '' COMMENT '商家QQ',
  `wechat` VARCHAR(60) NOT NULL DEFAULT '' COMMENT '商家微信',
  `webhook_url` VARCHAR(500) NOT NULL DEFAULT '',
  `webhook_method` VARCHAR(8) NOT NULL DEFAULT 'post' COMMENT 'post|get',
  `webhook_encode` VARCHAR(12) NOT NULL DEFAULT 'raw' COMMENT 'raw|form|field',
  `webhook_headers` VARCHAR(1000) NOT NULL DEFAULT '' COMMENT '自定义请求头,多行 k: v',
  `webhook_params` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '自定义查询参数,多行 k=v',
  `webhook_body` VARCHAR(2000) NOT NULL DEFAULT '' COMMENT '附加自定义字段 JSON(并入订单 payload)',
  `email_notify` TINYINT(1) NOT NULL DEFAULT 1,
  `balance_notify` TINYINT(1) NOT NULL DEFAULT 1,
  `api_balance_cents` INT NOT NULL DEFAULT 0 COMMENT 'API余额(分),每笔成功订单扣20',
  `balance_threshold_cents` INT NOT NULL DEFAULT 100 COMMENT '余额提醒阈值(分),默认¥1',
  `last_balance_notify_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_email` (`email`),
  UNIQUE KEY `uq_users_shop_name` (`shop_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商户/管理员(首位注册者=管理员)';

CREATE TABLE IF NOT EXISTS `password_resets` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(120) NOT NULL,
  `token` VARCHAR(64) NOT NULL,
  `expires_at` DATETIME NOT NULL COMMENT '10分钟有效,每次申请刷新',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_reset_token` (`token`),
  KEY `idx_reset_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='密码重置链接(每邮箱一条)';

CREATE TABLE IF NOT EXISTS `verification_codes` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(120) NOT NULL COMMENT '目标邮箱',
  `code` VARCHAR(8) NOT NULL COMMENT '6位验证码',
  `expires_at` DATETIME NOT NULL COMMENT '10分钟有效',
  `last_sent_at` DATETIME NOT NULL COMMENT '最近发送时间(判断1分钟重发间隔)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_vc_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='注册/操作邮箱验证码(每邮箱最新一条作数)';

CREATE TABLE IF NOT EXISTS `login_locks` (
  `identifier` VARCHAR(120) NOT NULL COMMENT '小写邮箱或店铺名',
  `fail_count` INT NOT NULL DEFAULT 0,
  `window_started_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `locked_until` DATETIME NULL COMMENT '5分钟内失败5次→锁定5分钟',
  PRIMARY KEY (`identifier`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录防爆破';

CREATE TABLE IF NOT EXISTS `product_categories` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `merchant_id` INT UNSIGNED NOT NULL,
  `name` VARCHAR(60) NOT NULL COMMENT '分类名,禁&;同商户内唯一',
  `icon_url` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '空则前台回退平台LOGO',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '越大越靠后',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_categories_merchant` (`merchant_id`),
  KEY `idx_categories_sort` (`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='店铺分类(独立于商品)';

CREATE TABLE IF NOT EXISTS `products` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `merchant_id` INT UNSIGNED NOT NULL,
  `category_id` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联 product_categories.id;分类名「API充值」=充值商品',
  `title` VARCHAR(180) NOT NULL COMMENT '禁&',
  `sku_name` VARCHAR(180) NOT NULL COMMENT '禁&;同标题下唯一',
  `price` INT NOT NULL COMMENT '元,正整数≥5',
  `is_recharge` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '充值商品不进前台店铺',
  `recharge_grant_cents` INT NOT NULL DEFAULT 0 COMMENT '充值到账金额(分)',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '后台拖拽排序,越大越靠后',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_products_title_sku` (`title`,`sku_name`),
  KEY `idx_products_merchant` (`merchant_id`),
  KEY `idx_products_category` (`category_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品';

CREATE TABLE IF NOT EXISTS `orders` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_no` VARCHAR(64) NOT NULL COMMENT '爱发电订单号',
  `product_id` INT UNSIGNED NULL,
  `merchant_id` INT UNSIGNED NOT NULL COMMENT '卖家',
  `category` VARCHAR(60) NOT NULL,
  `title` VARCHAR(180) NOT NULL,
  `sku` VARCHAR(180) NOT NULL,
  `total` INT NOT NULL COMMENT '元',
  `channel` VARCHAR(16) NOT NULL DEFAULT 'wechat' COMMENT 'wechat|alipay',
  `remark` VARCHAR(500) NOT NULL DEFAULT '' COMMENT '分类&标题&SKU名&价格',
  `buyer_account` VARCHAR(120) NOT NULL DEFAULT '',
  `status` VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending|paid',
  `paid_at` DATETIME NULL,
  `recharge_for_id` INT UNSIGNED NULL COMMENT '充值订单:充值商户(买家)',
  `recharge_grant_cents` INT NULL COMMENT '充值到账金额(分)',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_orders_no` (`order_no`),
  KEY `idx_orders_merchant` (`merchant_id`),
  KEY `idx_orders_status` (`status`),
  KEY `idx_orders_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单';

CREATE TABLE IF NOT EXISTS `fee_ledger` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `merchant_id` INT UNSIGNED NOT NULL,
  `order_id` INT UNSIGNED NULL,
  `delta_cents` INT NOT NULL COMMENT '正=入账 负=扣减',
  `balance_after_cents` INT NOT NULL,
  `reason` VARCHAR(24) NOT NULL DEFAULT 'order_fee' COMMENT 'order_fee|recharge|admin_adjust|seed',
  `note` VARCHAR(255) NOT NULL DEFAULT '',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ledger_merchant` (`merchant_id`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='API费用流水';

CREATE TABLE IF NOT EXISTS `platform_settings` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `installed` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已完成安装向导',
  `consumer_account` VARCHAR(120) NOT NULL DEFAULT '' COMMENT '爱发电(消费者)账号,未配置全平台无法下单',
  `consumer_password` VARCHAR(255) NOT NULL DEFAULT '',
  `consumer_auth_token` VARCHAR(191) NOT NULL DEFAULT '' COMMENT '爱发电(消费者)网页会话 auth_token,登录后持久化、失效后重登',
  `consumer_token_at` DATETIME NULL COMMENT '上次成功登录拿到 auth_token 的时间,用于会话失效判断',
  `platform_logo_url` VARCHAR(500) NOT NULL DEFAULT '',
  `wechat_enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `wechat_disabled_note` VARCHAR(255) NOT NULL DEFAULT '',
  `alipay_enabled` TINYINT(1) NOT NULL DEFAULT 1,
  `alipay_disabled_note` VARCHAR(255) NOT NULL DEFAULT '',
  `app_base_url` VARCHAR(300) NOT NULL DEFAULT '' COMMENT '在安装向导/后台可配置,空则用 .env APP_BASE_URL',
  `afdian_live` TINYINT(1) NULL COMMENT 'NULL=跟随 .env AFDIAN_LIVE',
  `enable_preview_login` TINYINT(1) NULL COMMENT 'NULL=跟随 .env ENABLE_PREVIEW_LOGIN',
  `smtp_host` VARCHAR(120) NOT NULL DEFAULT '',
  `smtp_port` INT UNSIGNED NULL,
  `smtp_user` VARCHAR(120) NOT NULL DEFAULT '',
  `smtp_pass` VARCHAR(255) NOT NULL DEFAULT '',
  `smtp_from` VARCHAR(120) NOT NULL DEFAULT '',
  `api_fee_cents` INT NULL COMMENT '单次API费用(分),NULL=用.env默认',
  `allowed_email_domains` VARCHAR(600) NOT NULL DEFAULT '' COMMENT '注册允许邮箱域名(;分隔,空=不限制)',
  `webhook_base_url` VARCHAR(300) NOT NULL DEFAULT '' COMMENT '爱发电 Webhook 平台外部域名,留空默认test.arduey.top,仅供后台展示拼接',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台配置(单行)';

CREATE TABLE IF NOT EXISTS `notices` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `title` VARCHAR(200) NOT NULL,
  `content` VARCHAR(2000) NOT NULL DEFAULT '',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台通知';

CREATE TABLE IF NOT EXISTS `user_progress` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id` INT UNSIGNED NOT NULL,
  `pkey` VARCHAR(64) NOT NULL COMMENT '业务 key:tasks/notices_seen/milestones/tours 等',
  `value` TEXT NOT NULL COMMENT 'JSON 文本(云端进度)',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_progress_user_pkey` (`user_id`,`pkey`),
  KEY `idx_user_progress_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通用云端进度(跨设备:任务/导览/通知已读)';

CREATE TABLE IF NOT EXISTS `afdian_webhook_logs` (
  `id` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  `body_text` TEXT NOT NULL COMMENT '收到的回调原始 JSON/文本',
  `order_no` VARCHAR(100) NOT NULL DEFAULT '' COMMENT '回调中识别到的爱发电订单号',
  `matched` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=命中库内 Order;0=测试/未命中',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_afdiandwb_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='爱发电回调收到记录(回调测试在哪里看)';
