(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.I18N = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const STORAGE_LOCALE_KEY = 'aicivs_locale';
  const STORAGE_UNIT_KEY = 'aicivs_unit_system';
  const SUPPORTED_LOCALES = ['zh-CN', 'en-US'];
  const SUPPORTED_UNITS = ['metric', 'imperial'];

  const DICT = {
    'zh-CN': {
      'brand.title': '3D-AICIVS 智能装载', 'kpi.util': '内腔利用率', 'kpi.count': '装载件数',
      'kpi.gate': '交付质检', 'kpi.cog': '3D 重心配平', 'kpi.cogOn': '配平开', 'kpi.cogOff': '配平关', 'kpi.checking': '状态检测中',
      'nav.testDashboard': '测试看板', 'nav.algoSpace': '算法空间', 'nav.configDrawer': '货柜与货单配置',
      'nav.dynamicWeights': '算法动态权重', 'nav.slicer': '3D 剖面透视', 'nav.cavity': '🕳️ 空洞可视化',
      'nav.health': '🩺 方案体检', 'nav.expert': '🥇 专家评审打标', 'nav.studio': '渲染调优控制台',
      'nav.langBtn': '🌐 中/EN', 'nav.unitMetric': '📏 m·kg', 'nav.unitImperial': '📏 in·lbs',
      'nav.accountGuest': '👤 登录 / 套餐配额', 'nav.accountQuota': '次',
      'config.drawerTitle': '货柜箱型与装载货单', 'config.containerSec': 'ISO 集装箱柜型选择',
      'config.extDim': '外部尺寸:', 'config.intDim': '可用净空:', 'config.stdVol': '标准容积:', 'config.maxPayload': '限重载重:',
      'config.uploadSec': '智能表格导入 (Excel / CSV)', 'config.downloadTpl': '导出产线标准模板',
      'config.uploadMain': '点击或拖拽上传清洗表格 (.xlsx / .csv)',
      'config.uploadSub': '深度适配「产品名、长(m)、宽(m)、高(m)、单件毛重、数量、摆放要求」',
      'config.strategySec': 'AI 算柜排布策略', 'config.stickyBadge': '吸顶常驻',
      'config.stratCluster': '同品聚合+重力支撑', 'config.stratMec': '紧凑空闲块 (MEC)',
      'config.gapZero': '0% 紧密零间隙', 'config.gapSubtle': '1cm 宽松装卸',
      'config.cogTitle': '载荷偏置平衡优化 (CoG)', 'config.doorTitle': '开门倾覆安全 (门端降台阶)',
      'config.altTitle': '多方案对比 (统一评分)', 'config.runBtn': '开始 AI 算柜',
      'config.runNote': '请先准备货单，再手动点击开始算柜', 'config.manifestSec': '混装货物清单',
      'saas.watermark': 'Trial 试用版 · 升级解锁无水印与高清导出',
      'saas.authTitleLogin': '登录 3D-AICIVS 商业版', 'saas.authTitleReg': '注册 3D-AICIVS 账号',
      'saas.tabLogin': '账号登录', 'saas.tabReg': '免费注册', 'saas.email': '工作邮箱', 'saas.password': '登录密码',
      'saas.region': '所在地区 (决定默认币种)', 'saas.regionCn': '中国大陆 (CNY ¥)', 'saas.regionGlobal': '海外地区 (USD $)',
      'saas.defaultLang': '默认界面语言', 'saas.submitLogin': '立即登录', 'saas.submitReg': '注册并领取免费额度',
      'saas.logout': '退出登录', 'saas.goUpgrade': '升级套餐 / 充值', 'saas.currentPlan': '当前方案', 'saas.quotaRemain': '剩余算柜次数',
      'saas.billingTitle': '套餐升级与按次充值', 'saas.currencyCn': '🇨🇳 人民币 CNY ¥ (微信 / 支付宝)',
      'saas.currencyUsd': '🌐 美元 USD $ (Stripe / Paddle)', 'saas.payMethod': '选择支付渠道', 'saas.buyNow': '立即购买',
      'saas.sandboxReady': '订单已创建（沙盒模式）', 'saas.sandboxBtn': '⚡ 沙盒一键模拟支付回调',
      'saas.paySuccess': '支付回调成功，配额与套餐权益已即时生效！',
      'saas.quotaExceededTitle': '算柜配额已用完或权限受限',
      'saas.quotaExceededDesc': '当前账号可用次数不足或功能受限，请升级套餐或购买按次加油包。', 'saas.close': '关闭'
    },
    'en-US': {
      'brand.title': '3D-AICIVS Smart Load', 'kpi.util': 'Volume Util.', 'kpi.count': 'Loaded Boxes',
      'kpi.gate': 'Delivery Gate', 'kpi.cog': '3D CoG Balance', 'kpi.cogOn': 'CoG ON', 'kpi.cogOff': 'CoG OFF', 'kpi.checking': 'Checking',
      'nav.testDashboard': 'Test Board', 'nav.algoSpace': 'Algo Lab', 'nav.configDrawer': 'Container & Manifest',
      'nav.dynamicWeights': 'Algo Weights', 'nav.slicer': '3D Slicer', 'nav.cavity': '🕳️ Void View',
      'nav.health': '🩺 Plan Health', 'nav.expert': '🥇 Expert Review', 'nav.studio': 'Render Studio',
      'nav.langBtn': '🌐 EN/中', 'nav.unitMetric': '📏 m·kg', 'nav.unitImperial': '📏 in·lbs',
      'nav.accountGuest': '👤 Sign In / Plans', 'nav.accountQuota': 'runs',
      'config.drawerTitle': 'Container & Cargo Manifest', 'config.containerSec': 'ISO Container Selection',
      'config.extDim': 'Exterior:', 'config.intDim': 'Usable Inner:', 'config.stdVol': 'Cubic Vol.:', 'config.maxPayload': 'Max Payload:',
      'config.uploadSec': 'Smart Import (Excel / CSV)', 'config.downloadTpl': 'Download Standard Template',
      'config.uploadMain': 'Click or drop manifest (.xlsx / .csv)',
      'config.uploadSub': 'Supports SKU, L, W, H, Weight, Qty, Orientation',
      'config.strategySec': 'AI Packing Strategy', 'config.stickyBadge': 'Sticky',
      'config.stratCluster': 'Cluster + Gravity', 'config.stratMec': 'Compact MEC',
      'config.gapZero': '0% Tight Fit', 'config.gapSubtle': '1cm Loose Gap',
      'config.cogTitle': 'CoG Axle Load Balancing', 'config.doorTitle': 'Door-Open Tipping Guard',
      'config.altTitle': 'Multi-Plan Comparison', 'config.runBtn': 'Run AI Packing',
      'config.runNote': 'Prepare manifest, then click Run AI Packing', 'config.manifestSec': 'Cargo Manifest List',
      'saas.watermark': 'Trial Edition · Upgrade to remove watermark & unlock exports',
      'saas.authTitleLogin': 'Sign In to 3D-AICIVS', 'saas.authTitleReg': 'Create 3D-AICIVS Account',
      'saas.tabLogin': 'Sign In', 'saas.tabReg': 'Sign Up', 'saas.email': 'Work Email', 'saas.password': 'Password',
      'saas.region': 'Region (Default Currency)', 'saas.regionCn': 'China Mainland (CNY ¥)', 'saas.regionGlobal': 'Global (USD $)',
      'saas.defaultLang': 'Default Language', 'saas.submitLogin': 'Sign In', 'saas.submitReg': 'Sign Up & Claim Free Quota',
      'saas.logout': 'Sign Out', 'saas.goUpgrade': 'Upgrade / Top-up', 'saas.currentPlan': 'Current Plan', 'saas.quotaRemain': 'Remaining Runs',
      'saas.billingTitle': 'Plans & Pay-As-You-Go Top-up', 'saas.currencyCn': '🇨🇳 CNY ¥ (WeChat / Alipay)',
      'saas.currencyUsd': '🌐 USD $ (Stripe / Paddle)', 'saas.payMethod': 'Payment Method', 'saas.buyNow': 'Purchase',
      'saas.sandboxReady': 'Order Created (Sandbox)', 'saas.sandboxBtn': '⚡ Simulate Payment Webhook',
      'saas.paySuccess': 'Payment confirmed! Your plan & quota are now active.',
      'saas.quotaExceededTitle': 'Quota Exceeded or Plan Restricted',
      'saas.quotaExceededDesc': 'Your remaining quota is insufficient or this feature requires an upgrade.', 'saas.close': 'Close'
    }
  };

  let currentLocale = readStored(STORAGE_LOCALE_KEY, SUPPORTED_LOCALES, 'zh-CN');
  let currentUnit = readStored(STORAGE_UNIT_KEY, SUPPORTED_UNITS, 'metric');
  let lastSpec = {
    extL: 12.192, extW: 2.438, extH: 2.896, intL: 12.032, intW: 2.352, intH: 2.698,
    usable: { L: 12.032, W: 2.352, H: 2.698 }, nominalVol: 76.4, maxPayloadTons: 28.6
  };

  function readStored(key, validList, fallback) {
    try {
      const val = root.localStorage && root.localStorage.getItem(key);
      if (val && validList.includes(val)) return val;
    } catch (_) { /* ignore */ }
    return fallback;
  }

  function writeStored(key, value) {
    try { if (root.localStorage) root.localStorage.setItem(key, value); } catch (_) { /* ignore */ }
  }

  function t(key, vars) {
    const table = DICT[currentLocale] || DICT['zh-CN'];
    let text = (table && table[key]) || (DICT['zh-CN'] && DICT['zh-CN'][key]) || key;
    if (vars && typeof vars === 'object') {
      Object.keys(vars).forEach(k => { text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), String(vars[k])); });
    }
    return text;
  }

  // 公英制换算辅助函数
  const mToIn = (m) => Number(m) * 39.37007874;
  const mToFt = (m) => Number(m) * 3.280839895;
  const kgToLbs = (kg) => Number(kg) * 2.2046226218;
  const m3ToCuFt = (m3) => Number(m3) * 35.31466672;

  function formatLength(meters, decimals) {
    const val = Number(meters) || 0;
    if (currentUnit === 'imperial') {
      return `${mToIn(val).toFixed(decimals != null ? decimals : 1)} in (${mToFt(val).toFixed(2)} ft)`;
    }
    return `${val.toFixed(decimals != null ? decimals : 3)} m`;
  }

  function formatDimensions(lM, wM, hM) {
    if (currentUnit === 'imperial') {
      return `${mToIn(lM).toFixed(1)} × ${mToIn(wM).toFixed(1)} × ${mToIn(hM).toFixed(1)} in`;
    }
    return `${Number(lM).toFixed(3)} × ${Number(wM).toFixed(3)} × ${Number(hM).toFixed(3)} m`;
  }

  function formatWeight(kg) {
    const val = Number(kg) || 0;
    if (currentUnit === 'imperial') return `${Math.round(kgToLbs(val)).toLocaleString()} lbs`;
    const unitTon = currentLocale === 'en-US' ? 't' : '吨';
    return `${Math.round(val).toLocaleString()} kg (${(val / 1000).toFixed(1)} ${unitTon})`;
  }

  function formatVolume(m3) {
    const val = Number(m3) || 0;
    return currentUnit === 'imperial' ? `${m3ToCuFt(val).toFixed(1)} cu ft` : `${val.toFixed(1)} m³`;
  }

  const SELECTOR_MAP = [
    ['.brand-text h1', 'brand.title'],
    ['.kpi-hud-bar .kpi-item:nth-child(1) .kpi-label', 'kpi.util'],
    ['.kpi-hud-bar .kpi-item:nth-child(2) .kpi-label', 'kpi.count'],
    ['#kpi-gate-item .kpi-label', 'kpi.gate'],
    ['#kpi-cog-item .kpi-label', 'kpi.cog'],
    ['#btn-open-test-dashboard span', 'nav.testDashboard'],
    ['#btn-open-algo-space span', 'nav.algoSpace'],
    ['#btn-toggle-left span', 'nav.configDrawer'],
    ['#btn-toggle-weights span', 'nav.dynamicWeights'],
    ['#btn-toggle-slicer span', 'nav.slicer'],
    ['#btn-toggle-cavity span', 'nav.cavity'],
    ['#btn-toggle-health span', 'nav.health'],
    ['#btn-toggle-expert span', 'nav.expert'],
    ['#btn-toggle-studio span', 'nav.studio'],
    ['#left-drawer .drawer-heading span', 'config.drawerTitle'],
    ['#sec-card-container .section-label span:first-child', 'config.containerSec'],
    ['#sec-card-container .spec-item:nth-child(1) .spec-k', 'config.extDim'],
    ['#sec-card-container .spec-item:nth-child(2) .spec-k', 'config.intDim'],
    ['#sec-card-container .spec-item:nth-child(3) .spec-k', 'config.stdVol'],
    ['#sec-card-container .spec-item:nth-child(4) .spec-k', 'config.maxPayload'],
    ['#sec-card-upload .section-label span:first-child', 'config.uploadSec'],
    ['#sec-card-upload .upload-text-main', 'config.uploadMain'],
    ['#sec-card-upload .upload-text-sub', 'config.uploadSub'],
    ['#btn-strat-cluster span', 'config.stratCluster'],
    ['#btn-strat-mec span', 'config.stratMec'],
    ['#btn-gap-zero', 'config.gapZero'],
    ['#btn-gap-subtle', 'config.gapSubtle'],
    ['#btn-run-packing span', 'config.runBtn'],
    ['#calculation-state-note', 'config.runNote']
  ];

  function applyDomTranslations() {
    const doc = root.document;
    if (!doc) return;
    doc.documentElement.lang = currentLocale;
    doc.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (key) el.textContent = t(key);
    });
    SELECTOR_MAP.forEach(([sel, key]) => {
      const el = doc.querySelector(sel);
      if (el) el.textContent = t(key);
    });
    const langBtn = doc.getElementById('btn-i18n-locale');
    if (langBtn) langBtn.textContent = t('nav.langBtn');
    const unitBtn = doc.getElementById('btn-i18n-unit');
    if (unitBtn) unitBtn.textContent = currentUnit === 'imperial' ? t('nav.unitImperial') : t('nav.unitMetric');
    syncContainerSpecs();
    if (root.SaasClient && typeof root.SaasClient.refreshUi === 'function') root.SaasClient.refreshUi();
  }

  function syncContainerSpecs(spec) {
    if (spec && typeof spec === 'object') lastSpec = Object.assign({}, lastSpec, spec);
    const doc = root.document;
    if (!doc || !lastSpec) return;
    const extEl = doc.getElementById('spec-ext');
    const intEl = doc.getElementById('spec-int');
    const volEl = doc.getElementById('spec-vol');
    const payEl = doc.getElementById('spec-payload');
    const deepEl = doc.getElementById('slice-deep-label');
    if (extEl) extEl.textContent = formatDimensions(lastSpec.extL, lastSpec.extW, lastSpec.extH);
    if (intEl) intEl.textContent = formatDimensions(lastSpec.intL, lastSpec.intW, lastSpec.intH);
    if (volEl) volEl.textContent = formatVolume(lastSpec.nominalVol);
    if (payEl) payEl.textContent = formatWeight((lastSpec.maxPayloadTons || 28.6) * 1000);
    if (deepEl && lastSpec.usable) {
      const prefix = currentLocale === 'en-US' ? '📦 Far End' : '📦 最远端';
      deepEl.textContent = `${prefix} (${formatLength(lastSpec.usable.L, 2)})`;
    }
  }

  function setLocale(locale) {
    if (!SUPPORTED_LOCALES.includes(locale)) return currentLocale;
    currentLocale = locale;
    writeStored(STORAGE_LOCALE_KEY, locale);
    applyDomTranslations();
    if (root.dispatchEvent && typeof root.CustomEvent === 'function') {
      root.dispatchEvent(new root.CustomEvent('aicivs:locale-change', { detail: { locale } }));
    }
    return currentLocale;
  }

  function setUnitSystem(unitSystem) {
    if (!SUPPORTED_UNITS.includes(unitSystem)) return currentUnit;
    currentUnit = unitSystem;
    writeStored(STORAGE_UNIT_KEY, unitSystem);
    applyDomTranslations();
    if (root.dispatchEvent && typeof root.CustomEvent === 'function') {
      root.dispatchEvent(new root.CustomEvent('aicivs:unit-change', { detail: { unitSystem } }));
    }
    return currentUnit;
  }

  if (root.document) {
    if (root.document.readyState === 'loading') root.document.addEventListener('DOMContentLoaded', applyDomTranslations);
    else setTimeout(applyDomTranslations, 0);
  }

  return {
    getLocale: () => currentLocale, setLocale,
    toggleLocale: () => setLocale(currentLocale === 'zh-CN' ? 'en-US' : 'zh-CN'),
    getUnitSystem: () => currentUnit, setUnitSystem,
    toggleUnitSystem: () => setUnitSystem(currentUnit === 'metric' ? 'imperial' : 'metric'),
    t, mToIn, mToFt, kgToLbs, m3ToCuFt,
    formatLength, formatDimensions, formatWeight, formatVolume,
    syncContainerSpecs, applyDomTranslations
  };
});
