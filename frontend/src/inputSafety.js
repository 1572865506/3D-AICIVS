/* 货单文本与尺寸规范化：列单位优先，缺失或非法数值必须由用户修正。 */
(function(root) {
  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch =>
      ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  }
  function unitFromHeader(header) {
    const text=String(header || '').trim().toLowerCase();
    if (/毫米|\bmm\b/.test(text)) return 'mm';
    if (/厘米|\bcm\b/.test(text)) return 'cm';
    if (/英寸|inch|\bin\b|feet|\bft\b/.test(text)) throw new Error('暂不支持此列单位，请转换为米、厘米或毫米');
    return 'm';
  }
  function dimension(value, unit='m') {
    if (value == null || String(value).trim()==='') throw new Error('尺寸缺失');
    const factor={m:1,cm:.01,mm:.001}[unit];
    if (!factor) throw new Error('尺寸单位必须为 m、cm 或 mm');
    const number=Number(value);
    if (!Number.isFinite(number) || number<=0) throw new Error('尺寸必须为有限正数');
    const result=number*factor;
    if (!Number.isFinite(result) || result<=0) throw new Error('转换后的尺寸无效');
    return result;
  }
  const api={escapeHtml,unitFromHeader,dimension};
  root.InputSafety=api;
  if (typeof module==='object' && module.exports) module.exports=api;
})(typeof window==='undefined' ? globalThis : window);
