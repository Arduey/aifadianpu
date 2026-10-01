-- ══════════════════════════════════════════════════════════════
-- 爱发电铺 · 微信大额拦截（平台设置项：开关 + 单笔上限）
-- 语义：开关 wechat_limit_on = 1 时启用拦截，微信「发电」超过 wechat_max_yuan 元会被爱发电风控拒
--        （ec=400 不支持发电），前台店铺页与充值弹窗会把微信按钮置灰并提示改用支付宝；
--       开关 = 0 或上限 = 0 都表示不限制（例如平台出站请求改走非机房 IP 之后）。
-- 执行顺序：先跑本文件 → 再重启后端（先重启会因新列未加载而报 Unknown column）。
-- ══════════════════════════════════════════════════════════════

ALTER TABLE platform_settings
  ADD COLUMN wechat_max_yuan INT NOT NULL DEFAULT 100 COMMENT '微信单笔上限(元),0=不限制,前台据此置灰微信并提示改用支付宝';

ALTER TABLE platform_settings
  ADD COLUMN wechat_limit_on BOOL NOT NULL DEFAULT true COMMENT '是否启用微信大额拦截,1=启用(前台按微信单笔上限置灰微信),0=关闭(不置灰微信)';
