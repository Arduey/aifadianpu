/* ═══ 爱发电铺 · 前端工具(原生 JS,无构建链) ═══ */

/* 预览通行证:当前页带 ?preview= 时,所有 fetch 自动附加 */
function previewSuffix() {
  const p = new URLSearchParams(location.search).get('preview');
  return (p === 'admin' || p === 'merchant') ? 'preview=' + p : '';
}
function withPreview(url) {
  const s = previewSuffix();
  if (!s || url.includes('preview=')) return url;
  return url + (url.includes('?') ? '&' : '?') + s;
}

/* JSON 请求;后端返回 {ok, message, ...} */
async function api(url, opts = {}) {
  const res = await fetch(withPreview(url), {
    headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'fetch' },
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (e) { throw new Error('服务响应异常'); }
  if (!res.ok || data.ok === false) throw new Error(data.message || ('请求失败(' + res.status + ')'));
  return data;
}

/* Toast */
function toast(type, title, desc) {
  let wrap = document.getElementById('toast-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'toast-wrap';
    document.body.appendChild(wrap);
  }
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.innerHTML = '<div style="flex:1"><b></b>' + (desc ? '<small></small>' : '') + '</div>';
  el.querySelector('b').textContent = title;
  if (desc) el.querySelector('small').textContent = desc;
  wrap.appendChild(el);
  while (wrap.children.length >= 2) {
    const old = wrap.firstChild;
    if (old && old !== el) old.remove();
  }
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; setTimeout(() => el.remove(), 300); }, 3200);
}

/* 云端进度(换设备同步):读全量 / 增量合并(仅控制台登录时调用;游客页不会发) */
window.afpProgressLoad = function(cb){ try { fetch('/console/api/progress').then(function(r){ return r.json(); }).then(function(d){ cb((d && d.progress) || {}); }).catch(function(){ cb({}); }); } catch(e){ cb({}); } };
window.afpProgressPush = function(updates){ if(!updates) return; try { fetch('/console/api/progress', { method:'POST', headers:{ 'Content-Type':'application/json', 'X-Requested-With':'fetch' }, body: JSON.stringify({ updates: updates }) }) } catch(e){} };

/* Modal:任意元素加 data-modal 切换显示 */
function openModal(id) { var m = document.getElementById(id); if (!m) { return; } if (m.parentNode !== document.body) { document.body.appendChild(m); } m.style.display = 'flex'; }
function closeModal(id) { document.getElementById(id).style.display = 'none'; }
document.addEventListener('click', (e) => {
  // 点 modal-mask(外部)默认关闭;带 data-lock-close-outside 的表单(如新增商品)不响应外部点击,只能走关闭按钮,防误点丢数据
  if (e.target.classList && e.target.classList.contains('modal-mask') && !e.target.hasAttribute('data-lock-close-outside')) {
    e.target.style.display = 'none';
  }
  const opener = e.target.closest('[data-open-modal]');
  if (opener) openModal(opener.dataset.openModal);
  const closer = e.target.closest('[data-close-modal]');
  if (closer) closeModal(closer.dataset.closeModal);
});

/* 金额格式化:分 → ¥0.00 */
function yuan(cents) { return '¥' + (cents / 100).toFixed(2); }

/* 北京时间显示 */
function fmtTime(s) { return s ? String(s).replace('T', ' ').slice(0, 19) : '-'; }

/* 云端里程碑兜底:控制台路径里 localStorage 每写一次 afp_* 都同步到 user_progress(milestones) */
(function(){
  function isConsole(){ try { return /^\/console\//.test(String(location.pathname)); } catch(e){ return false; } }
  var prev = Storage.prototype.setItem;
  Storage.prototype.setItem = function(k, v){
    if (prev) { try { prev.call(this, k, v); } catch(e){} }
    try {
      if (k && String(k).indexOf('afp_') === 0 && isConsole() && window.afpProgressPush && typeof v !== 'undefined') {
        var one = {}; one[k] = String(v); window.afpProgressPush({ milestones: one });
      }
    } catch(e){}
  };
})();
