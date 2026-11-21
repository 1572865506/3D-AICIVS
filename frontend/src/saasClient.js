(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.SaasClient = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const TOKEN_KEY = 'aicivs_jwt';
  const USER_KEY = 'aicivs_user';

  const FALLBACK_PLANS = [
    { id: 'free', name_zh: '免费试用版', name_en: 'Free Trial', price_cny: 0, price_usd: 0, quota_monthly: 5, watermark: true, desc_zh: '每月 5 次算柜 · 含试用水印', desc_en: '5 runs/mo · Trial watermark' },
    { id: 'pro_monthly', name_zh: 'Pro 专业版 (月付)', name_en: 'Pro Monthly', price_cny: 199, price_usd: 29, quota_monthly: 200, watermark: false, desc_zh: '200 次/月 · 去水印 · 完整报告导出', desc_en: '200 runs/mo · No watermark · Exports' },
    { id: 'business_monthly', name_zh: 'Business 团队版', name_en: 'Business Monthly', price_cny: 599, price_usd: 89, quota_monthly: 1000, watermark: false, desc_zh: '1000 次/月 · 只读 3D 分享链接', desc_en: '1000 runs/mo · 3D Share Links' },
    { id: 'pack_20', name_zh: '按次加油包 (20次)', name_en: '20-Run Top-up Pack', price_cny: 39, price_usd: 6, quota_pack: 20, watermark: false, desc_zh: '永不过期 · 即买即用', desc_en: 'Never expires · Instant credit' }
  ];

  let state = {
    token: readStorage(TOKEN_KEY) || '',
    user: readJsonStorage(USER_KEY),
    plans: FALLBACK_PLANS,
    currency: 'CNY',
    provider: 'wechat',
    pendingOrder: null,
    watermarkVisible: true
  };
  if (state.token) root.__AICIVS_JWT__ = state.token;

  const t = (key) => (root.I18N && typeof root.I18N.t === 'function' ? root.I18N.t(key) : key);
  const isEn = () => root.I18N && root.I18N.getLocale() === 'en-US';

  function readStorage(k) {
    try { return root.localStorage ? root.localStorage.getItem(k) : ''; } catch (_) { return ''; }
  }
  function writeStorage(k, v) {
    try {
      if (!root.localStorage) return;
      if (v === null || v === undefined || v === '') root.localStorage.removeItem(k);
      else root.localStorage.setItem(k, String(v));
    } catch (_) { /* ignore */ }
  }
  function readJsonStorage(k) {
    try { const raw = readStorage(k); return raw ? JSON.parse(raw) : null; } catch (_) { return null; }
  }

  function apiUrl(path) {
    let base = '';
    try { if (root.BLK007D && typeof root.BLK007D.configuredBase === 'function') base = root.BLK007D.configuredBase(); } catch (_) { base = ''; }
    return base.endsWith('/api') ? `${base}${path.replace(/^\/api/, '')}` : `${base}${path}`;
  }

  async function apiFetch(path, options) {
    const headers = Object.assign({ 'Content-Type': 'application/json' }, (options && options.headers) || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await root.fetch(apiUrl(path), Object.assign({}, options || {}, { headers }));
    let data = null;
    try { data = await res.json(); } catch (_) { /* ignore */ }
    if (!res.ok) {
      const msg = (data && (data.detail || data.error || data.message)) || `HTTP ${res.status}`;
      const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function setToken(token, user) {
    state.token = token || '';
    root.__AICIVS_JWT__ = state.token;
    writeStorage(TOKEN_KEY, state.token);
    if (user !== undefined) {
      state.user = user;
      writeStorage(USER_KEY, user ? JSON.stringify(user) : '');
    }
    updateEntitlements(user);
    refreshUi();
  }

  function logout() {
    setToken('', null);
    state.watermarkVisible = true;
    closeModal();
    refreshUi();
  }

  function updateEntitlements(payload) {
    if (!payload) { state.watermarkVisible = true; return; }
    const ent = payload.entitlements || payload;
    if (typeof ent.watermark === 'boolean') state.watermarkVisible = ent.watermark;
    else if (ent.plan_id) state.watermarkVisible = ent.plan_id === 'free';
  }

  async function refreshMe() {
    if (!state.token) return null;
    try {
      const me = await apiFetch('/api/v1/auth/me', { method: 'GET' });
      state.user = me;
      writeStorage(USER_KEY, JSON.stringify(me));
      if (me && me.region === 'global') { state.currency = 'USD'; state.provider = 'stripe'; }
      updateEntitlements(me);
      refreshUi();
      return me;
    } catch (err) {
      if (err && err.status === 401) setToken('', null);
      return null;
    }
  }

  function ensureStyles() {
    const doc = root.document;
    if (!doc || doc.getElementById('aicivs-saas-style')) return;
    const style = doc.createElement('style');
    style.id = 'aicivs-saas-style';
    style.textContent = `.aicivs-watermark{position:fixed;right:24px;bottom:84px;z-index:5;pointer-events:none;padding:6px 14px;border-radius:999px;background:rgba(15,23,42,0.42);backdrop-filter:blur(6px);color:rgba(255,255,255,0.88);font-size:12px;font-weight:700;letter-spacing:.4px;border:1px solid rgba(255,255,255,0.18);user-select:none}`
      + `.aicivs-modal-backdrop{position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,0.52);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:16px}`
      + `.aicivs-modal{width:100%;max-width:520px;background:rgba(255,255,255,0.97);border-radius:16px;box-shadow:0 24px 60px rgba(15,23,42,0.28);border:1px solid #e2e8f0;padding:20px 22px;color:#0f172a;font-family:inherit}`
      + `.aicivs-modal-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.aicivs-modal-title{font-size:16px;font-weight:800;margin:0}`
      + `.aicivs-close{background:#f1f5f9;border:none;border-radius:8px;width:28px;height:28px;cursor:pointer;font-weight:700}`
      + `.aicivs-tabs{display:flex;gap:6px;background:#f1f5f9;padding:4px;border-radius:10px;margin-bottom:14px}`
      + `.aicivs-tab{flex:1;border:none;background:transparent;padding:7px 10px;border-radius:8px;font-size:12.5px;font-weight:700;cursor:pointer;color:#475569}`
      + `.aicivs-tab.active{background:#fff;color:#2563eb;box-shadow:0 2px 6px rgba(15,23,42,0.08)}`
      + `.aicivs-field{margin-bottom:11px}.aicivs-field label{display:block;font-size:11.5px;font-weight:700;color:#475569;margin-bottom:4px}`
      + `.aicivs-field input,.aicivs-field select{width:100%;box-sizing:border-box;padding:8px 10px;border-radius:8px;border:1px solid #cbd5e1;font-size:13px}`
      + `.aicivs-btn-primary{width:100%;padding:10px 14px;border:none;border-radius:10px;background:linear-gradient(135deg,#2563eb,#4f46e5);color:#fff;font-size:13px;font-weight:700;cursor:pointer}`
      + `.aicivs-btn-secondary{padding:7px 12px;border:1px solid #cbd5e1;border-radius:8px;background:#fff;color:#0f172a;font-size:12px;font-weight:700;cursor:pointer}`
      + `.aicivs-plan-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}`
      + `.aicivs-plan-card{border:1.5px solid #e2e8f0;border-radius:12px;padding:11px;display:flex;flex-direction:column;justify-content:space-between;background:#f8fafc}`
      + `.aicivs-plan-price{font-size:18px;font-weight:800;color:#2563eb;margin:4px 0}`
      + `.aicivs-alert{padding:9px 12px;border-radius:9px;font-size:12px;font-weight:600;margin-bottom:10px}`
      + `.aicivs-alert.warn{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412}.aicivs-alert.ok{background:#ecfdf5;border:1px solid #a7f3d0;color:#065f46}.aicivs-alert.err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b}`;
    doc.head.appendChild(style);
  }

  function renderWatermark() {
    const doc = root.document;
    if (!doc || !doc.body) return;
    ensureStyles();
    let el = doc.getElementById('aicivs-trial-watermark');
    if (!el) {
      el = doc.createElement('div');
      el.id = 'aicivs-trial-watermark';
      el.className = 'aicivs-watermark';
      doc.body.appendChild(el);
    }
    el.textContent = t('saas.watermark');
    el.style.display = state.watermarkVisible ? 'block' : 'none';
  }

  function refreshUi() {
    const doc = root.document;
    if (!doc) return;
    const accBtn = doc.getElementById('btn-saas-account');
    if (accBtn) {
      if (state.token && state.user) {
        const plan = (state.user.plan_id || 'free').toUpperCase();
        const quota = state.user.remaining_quota != null ? state.user.remaining_quota : (state.user.quota_remaining ?? '∞');
        accBtn.textContent = `👤 ${plan} · ${quota} ${t('nav.accountQuota')}`;
      } else {
        accBtn.textContent = t('nav.accountGuest');
      }
    }
    renderWatermark();
  }

  function closeModal() {
    const old = root.document && root.document.getElementById('aicivs-saas-modal');
    if (old) old.remove();
  }

  function mountModal(innerHtml) {
    const doc = root.document;
    if (!doc) return null;
    ensureStyles();
    closeModal();
    const wrap = doc.createElement('div');
    wrap.id = 'aicivs-saas-modal';
    wrap.className = 'aicivs-modal-backdrop';
    wrap.innerHTML = `<div class="aicivs-modal">${innerHtml}</div>`;
    wrap.addEventListener('click', (e) => { if (e.target === wrap) closeModal(); });
    doc.body.appendChild(wrap);
    return wrap;
  }

  function openAuthModal(defaultTab) {
    let tab = defaultTab === 'register' ? 'register' : 'login';
    const render = (errorMsg) => {
      const isReg = tab === 'register';
      const userBar = state.token && state.user ? `<div class="aicivs-alert ok" style="display:flex;justify-content:space-between;align-items:center;"><span>${state.user.email || ''} · ${t('saas.currentPlan')}: <b>${(state.user.plan_id || 'free').toUpperCase()}</b></span><div style="display:flex;gap:6px;"><button class="aicivs-btn-secondary" id="saas-go-billing">${t('saas.goUpgrade')}</button><button class="aicivs-btn-secondary" id="saas-do-logout">${t('saas.logout')}</button></div></div>` : '';
      const regFields = isReg ? `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;"><div class="aicivs-field"><label>${t('saas.region')}</label><select id="saas-region"><option value="cn">${t('saas.regionCn')}</option><option value="global">${t('saas.regionGlobal')}</option></select></div><div class="aicivs-field"><label>${t('saas.defaultLang')}</label><select id="saas-locale"><option value="zh-CN">简体中文</option><option value="en-US">English</option></select></div></div>` : '';
      const modal = mountModal(`
        <div class="aicivs-modal-head"><h3 class="aicivs-modal-title">${isReg ? t('saas.authTitleReg') : t('saas.authTitleLogin')}</h3><button class="aicivs-close" id="saas-modal-close">✕</button></div>
        ${userBar}
        <div class="aicivs-tabs"><button class="aicivs-tab ${!isReg ? 'active' : ''}" id="saas-tab-login">${t('saas.tabLogin')}</button><button class="aicivs-tab ${isReg ? 'active' : ''}" id="saas-tab-reg">${t('saas.tabReg')}</button></div>
        ${errorMsg ? `<div class="aicivs-alert err">${errorMsg}</div>` : ''}
        <form id="saas-auth-form">
          <div class="aicivs-field"><label>${t('saas.email')}</label><input type="email" id="saas-email" required placeholder="name@company.com"></div>
          <div class="aicivs-field"><label>${t('saas.password')}</label><input type="password" id="saas-pwd" required minlength="6" placeholder="••••••"></div>
          ${regFields}
          <button type="submit" class="aicivs-btn-primary">${isReg ? t('saas.submitReg') : t('saas.submitLogin')}</button>
        </form>`);
      modal.querySelector('#saas-modal-close').onclick = closeModal;
      modal.querySelector('#saas-tab-login').onclick = () => { tab = 'login'; render(); };
      modal.querySelector('#saas-tab-reg').onclick = () => { tab = 'register'; render(); };
      const goBill = modal.querySelector('#saas-go-billing');
      if (goBill) goBill.onclick = () => openBillingModal();
      const doOut = modal.querySelector('#saas-do-logout');
      if (doOut) doOut.onclick = logout;
      if (isReg) {
        const regSel = modal.querySelector('#saas-region'), locSel = modal.querySelector('#saas-locale');
        regSel.onchange = () => { locSel.value = regSel.value === 'global' ? 'en-US' : 'zh-CN'; };
      }
      modal.querySelector('#saas-auth-form').onsubmit = async (e) => {
        e.preventDefault();
        const email = modal.querySelector('#saas-email').value.trim();
        const password = modal.querySelector('#saas-pwd').value;
        try {
          if (isReg) {
            const region = modal.querySelector('#saas-region').value;
            const locale = modal.querySelector('#saas-locale').value;
            const unit_system = region === 'global' ? 'imperial' : 'metric';
            const res = await apiFetch('/api/v1/auth/register', { method: 'POST', body: JSON.stringify({ email, password, region, locale, unit_system }) });
            setToken(res.access_token || res.token, res.user || res);
            if (root.I18N) { root.I18N.setLocale(locale); root.I18N.setUnitSystem(unit_system); }
            state.currency = region === 'global' ? 'USD' : 'CNY';
            state.provider = region === 'global' ? 'stripe' : 'wechat';
          } else {
            const res = await apiFetch('/api/v1/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
            setToken(res.access_token || res.token, res.user || res);
          }
          await refreshMe();
          closeModal();
        } catch (err) { render(err.message || 'Authentication failed'); }
      };
    };
    render();
  }

  async function openBillingModal(warnMsg) {
    try {
      const data = await apiFetch('/api/v1/billing/plans', { method: 'GET' });
      if (data && Array.isArray(data.plans) && data.plans.length) state.plans = data.plans;
    } catch (_) { /* use fallback plans */ }

    const render = (notice, isOk) => {
      const isUsd = state.currency === 'USD';
      const providers = isUsd ? [['stripe', 'Stripe'], ['paddle', 'Paddle']] : [['wechat', '微信支付 WeChat'], ['alipay', '支付宝 Alipay']];
      if (!providers.some(([id]) => id === state.provider)) state.provider = providers[0][0];

      const cards = state.plans.filter(p => p.id !== 'free').map(p => {
        const name = isEn() ? (p.name_en || p.name || p.id) : (p.name_zh || p.name || p.id);
        const desc = isEn() ? (p.desc_en || '') : (p.desc_zh || '');
        const price = isUsd ? `$${p.price_usd ?? 0}` : `¥${p.price_cny ?? 0}`;
        return `<div class="aicivs-plan-card"><div><div style="font-size:13px;font-weight:800;">${name}</div><div class="aicivs-plan-price">${price}</div><div style="font-size:11px;color:#64748b;margin-bottom:8px;">${desc}</div></div><button class="aicivs-btn-primary" data-buy-plan="${p.id}" style="padding:7px 10px;font-size:12px;">${t('saas.buyNow')}</button></div>`;
      }).join('');

      const sandboxBox = state.pendingOrder ? `<div class="aicivs-alert ok"><div style="margin-bottom:6px;">${t('saas.sandboxReady')}: <code>${state.pendingOrder.order_id}</code> (${state.pendingOrder.provider})</div><button class="aicivs-btn-primary" id="saas-sandbox-pay" style="background:linear-gradient(135deg,#059669,#10b981);">${t('saas.sandboxBtn')}</button></div>` : '';

      const modal = mountModal(`
        <div class="aicivs-modal-head"><h3 class="aicivs-modal-title">${t('saas.billingTitle')}</h3><button class="aicivs-close" id="saas-modal-close">✕</button></div>
        ${warnMsg ? `<div class="aicivs-alert warn">${warnMsg}</div>` : ''}
        ${notice ? `<div class="aicivs-alert ${isOk ? 'ok' : 'err'}">${notice}</div>` : ''}
        <div class="aicivs-tabs"><button class="aicivs-tab ${!isUsd ? 'active' : ''}" id="saas-cur-cny">${t('saas.currencyCn')}</button><button class="aicivs-tab ${isUsd ? 'active' : ''}" id="saas-cur-usd">${t('saas.currencyUsd')}</button></div>
        <div class="aicivs-field" style="display:flex;align-items:center;gap:8px;"><label style="margin:0;white-space:nowrap;">${t('saas.payMethod')}:</label><select id="saas-provider-sel" style="flex:1;">${providers.map(([id, label]) => `<option value="${id}" ${state.provider === id ? 'selected' : ''}>${label}</option>`).join('')}</select></div>
        <div class="aicivs-plan-grid">${cards}</div>
        ${sandboxBox}`);
      modal.querySelector('#saas-modal-close').onclick = closeModal;
      modal.querySelector('#saas-cur-cny').onclick = () => { state.currency = 'CNY'; state.provider = 'wechat'; render(); };
      modal.querySelector('#saas-cur-usd').onclick = () => { state.currency = 'USD'; state.provider = 'stripe'; render(); };
      modal.querySelector('#saas-provider-sel').onchange = (e) => { state.provider = e.target.value; };
      modal.querySelectorAll('[data-buy-plan]').forEach(btn => {
        btn.onclick = async () => {
          const planId = btn.getAttribute('data-buy-plan');
          try {
            const ord = await apiFetch('/api/v1/billing/checkout', { method: 'POST', body: JSON.stringify({ plan_id: planId, currency: state.currency, provider: state.provider }) });
            state.pendingOrder = { order_id: ord.order_id, provider: state.provider, plan_id: planId };
            render();
          } catch (err) { render(err.message || 'Checkout failed', false); }
        };
      });
      const sbBtn = modal.querySelector('#saas-sandbox-pay');
      if (sbBtn) {
        sbBtn.onclick = async () => {
          try {
            const p = state.pendingOrder;
            await apiFetch(`/api/v1/billing/webhook/${encodeURIComponent(p.provider)}`, {
              method: 'POST', body: JSON.stringify({ order_id: p.order_id, event_id: `evt_sb_${Date.now()}`, status: 'paid' })
            });
            state.pendingOrder = null;
            await refreshMe();
            render(t('saas.paySuccess'), true);
          } catch (err) { render(err.message || 'Webhook simulation failed', false); }
        };
      }
    };
    render();
  }

  function handleQuotaExceeded(status, details) {
    const msg = (details && (details.message || details.error || details.detail)) || t('saas.quotaExceededDesc');
    openBillingModal(`[HTTP ${status}] ${msg}`);
  }

  if (root.document) {
    const boot = () => { refreshUi(); if (state.token) refreshMe(); };
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', boot);
    else setTimeout(boot, 0);
  }

  return {
    getToken: () => state.token, setToken, logout, refreshMe, refreshUi,
    updateEntitlements, openAuthModal, openBillingModal,
    openSmartModal: () => openAuthModal('login'),
    handleQuotaExceeded
  };
});
