"""邮件 HTML 模板(卡片式)"""
import html as h
from .. import settings as _settings


def _fee_yuan() -> str:
    """当前单次API费用(元),文案显示用"""
    return f"{_settings.api_fee_cents()/100:.2f}"

BRAND = "#F95D1F"


def reset_password_html(email: str, url: str) -> str:
    eu, uu = h.escape(email), h.escape(url)
    return f'''<!doctype html><html><body style="margin:0;background:#F3F1EA;padding:32px;font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid #EAE6DA;">
<div style="background:{BRAND};padding:22px 28px"><div style="color:#fff;font-size:18px;font-weight:700">⚡ 爱发电铺</div>
<div style="color:rgba(255,255,255,.85);font-size:12px;margin-top:4px">虚拟商品自助销售平台</div></div>
<div style="padding:28px"><div style="font-size:16px;font-weight:700;color:#201D17">你好,{eu}</div>
<p style="font-size:13px;color:#6B6558;line-height:1.8">你正在申请重置登录密码。点击下方按钮设置新密码,链接 <b>10 分钟内有效</b>,每次申请都会生成新链接(旧链接立即失效)。如非本人操作请忽略。</p>
<div style="text-align:center;margin:26px 0"><a href="{uu}" style="display:inline-block;background:{BRAND};color:#fff;text-decoration:none;font-size:14px;font-weight:600;padding:12px 34px;border-radius:10px">重置我的密码</a></div>
<div style="font-size:12px;color:#9A937F;line-height:1.7">若按钮无法点击,请复制:<br><span style="word-break:break-all;color:#6B6558">{uu}</span></div></div>
<div style="padding:16px 28px;border-top:1px dashed #EAE6DA;font-size:11px;color:#B0A98F">此邮件由系统自动发送 · 爱发电铺</div></div></body></html>'''


def order_email_html(p: dict, shop_name: str, balance_yuan: float | None = None) -> str:
    es = h.escape(shop_name)
    fee_note = f"该订单已扣除 API 服务费 ¥{_fee_yuan()}，已出账"
    if balance_yuan is not None:
        fee_note += f"<br>剩余 API 服务费 ¥{balance_yuan}"
    amount = f'<span style="color:{BRAND};font-size:30px;font-weight:800">{float(p["total"]):.2f}<span style="font-size:14px;color:#B7AFA0;font-weight:600;margin-left:3px">元</span></span>'
    def v(s): return h.escape(str(s))
    rows = ''.join(
        f'<tr>'
        f'<td style="width:26%;padding:11px 0;color:#8C8574;font-size:12px;vertical-align:top;border-bottom:1px solid #F1ECE0">{k}</td>'
        f'<td style="padding:11px 0;color:#211C14;font-size:13px;font-weight:600;text-align:right;border-bottom:1px solid #F1ECE0;word-break:break-all">{val}</td>'
        f'</tr>'
        for k, val in (
            ("订单号", v(p["order_id"])), ("付款时间", v(p["creat_time"])),
            ("商品分类", v(p["type"])), ("商品标题", v(p["title"])),
            ("规格 SKU", v(p["sku"])),
        ))
    return f'''<!doctype html><html><body style="margin:0;background:#F4F0E8;padding:28px 12px;font-family:'PingFang SC','Microsoft YaHei','Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="380" cellpadding="0" cellspacing="0" style="width:380px;max-width:380px;background:#FFFFFF;border-radius:16px;overflow:hidden;border:1px solid #ECE6D8;box-shadow:0 14px 34px rgba(84,64,24,.10)">
  <tr><td style="background:linear-gradient(135deg,#FF7A1A 0%,{BRAND} 55%,#E24B06 100%);padding:26px 30px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td><div style="color:#fff;font-size:15px;font-weight:800">爱发电铺</div>
              <div style="color:rgba(255,255,255,.82);font-size:10px;letter-spacing:2px;margin-top:3px">PAYMENT RECEIVED</div></td>
          <td align="right"><div style="background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.38);color:#fff;font-size:12px;font-weight:600;border-radius:99px;text-align:center;padding:5px 13px">订单通知</div></td>
        </tr>
      </table>
      <div style="margin-top:20px;color:#fff;font-size:21px;font-weight:800;letter-spacing:.2px">一笔订单支付成功</div>
      <div style="color:rgba(255,255,255,.86);font-size:13px;line-height:1.7;margin-top:6px">来自「{es}」的商品订单,金额实时到账爱发电。</div>
  </td></tr>

  <tr><td style="padding:24px 30px 6px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr valign="middle">
          <td valign="middle" style="vertical-align:middle;white-space:nowrap"><div style="display:inline-block;font-size:20px;line-height:34px;color:#B7AFA0;font-weight:700;vertical-align:middle">订单金额</div></td>
          <td align="right" valign="middle" style="vertical-align:middle;white-space:nowrap"><span style="display:inline-block;vertical-align:middle">{amount}</span></td>
        </tr>
      </table></td></tr>

  <tr><td style="padding:14px 30px 22px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr><td style="padding:14px 16px;font-size:12px;line-height:1.8"><b style="color:#201D17">费用</b><br><span style="color:#7E6F3C">{fee_note}</span></td></tr>
      </table></td></tr>

  <tr><td style="padding:15px 30px;border-top:1px dashed #ECE6D8;color:#B4AC99;font-size:11px">此邮件由系统自动发送·请勿直接回复</td></tr>
</table>
</td></tr></table></body></html>'''


def low_balance_html(shop_name: str, balance_yuan: str) -> str:
    return f'''<!doctype html><html><body style="margin:0;background:#F3F1EA;padding:32px;font-family:'PingFang SC','Microsoft YaHei',sans-serif;">
<div style="max-width:520px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid #EAE6DA;">
<div style="background:#B42318;padding:22px 28px"><div style="color:#fff;font-size:18px;font-weight:700">⚠️ API 费用余额不足</div></div>
<div style="padding:28px;font-size:13px;color:#6B6558;line-height:1.9">「{h.escape(shop_name)}」你好,<br>有买家尝试下单,但你的 API 费用余额仅剩 <b style="color:#B42318">¥{balance_yuan}</b>(单笔订单需 ¥{_fee_yuan()}),订单已被拦截。<br>请在个人中心购买管理员的「API 费用充值」商品,到账后即可恢复售卖。</div>
<div style="padding:16px 28px;border-top:1px dashed #EAE6DA;font-size:11px;color:#B0A98F">30 分钟内仅提醒一次 · 爱发电铺</div></div></body></html>'''
