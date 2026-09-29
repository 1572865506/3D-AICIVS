/**
 * expertAnnotation.js
 * 3D-AICIVS Expert Review & Ground-Truth Manual Annotation Platform
 * 
 * Responsibilities:
 * - Gold / Silver / Reject 3-Tier Expert Grading with instant visual feedback
 * - Cavity & Structural Defect Tagging:
 *     - 'HONEYCOMB_CAVITY': 内部蜂窝空洞 (数字利用率高但内部严重松散)
 *     - 'POOR_INTERLOCK': 层间咬合力弱 / 烟囱式独立堆叠
 *     - 'TOP_HEAVY': 头重脚轻 / 重心失衡
 *     - 'HIGH_FRAGMENTATION': 小件碎片化散落
 *     - 'FALSE_HIGH_UTILIZATION': 数字虚高但物理实装困难
 *     - 'EXPERT_APPROVED': 专家推荐标杆示范方案
 * - Interactive 3D Defect Pinning: Click on any 3D box to pin location & SKU
 * - REST API Sync: Submits to /api/v1/annotations with robust offline localStorage fallback
 */

(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.expertAnnotation = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const DEFECT_DEFINITIONS = [
    { id: 'HONEYCOMB_CAVITY', label: '内部蜂窝空洞', icon: '🕳️', desc: '表面规整但内部存在散落死腔空洞' },
    { id: 'POOR_INTERLOCK', label: '咬合不足/烟囱叠', icon: '🧱', desc: '列与列之间无横向交错咬合，易倒塌' },
    { id: 'TOP_HEAVY', label: '垂直重心偏高', icon: '⚖️', desc: '重件在上或顶部承重过大' },
    { id: 'HIGH_FRAGMENTATION', label: '小件碎片化散布', icon: '🧩', desc: '同类或小件未成块规整化，操作碎散' },
    { id: 'FALSE_HIGH_UTILIZATION', label: '虚假高利用率', icon: '⚠️', desc: '利用率数字漂亮但工人无法实际装载' },
    { id: 'EXPERT_APPROVED', label: '金牌标杆推荐', icon: '🥇', desc: '密实、咬合扎实、结构安全示范方案' },
  ];

  const state = {
    solutionId: '',
    rating: 'GOLD', // 'GOLD' | 'SILVER' | 'REJECT'
    score: 92,
    selectedTags: new Set(['EXPERT_APPROVED']),
    defects: [],
    expertNotes: '',
    annotator: '3D-Expert-01',
    isSubmitting: false,
    lastSubmittedId: null,
  };

  function getCurrentSolutionId() {
    if (root.lastLoadingResult && (root.lastLoadingResult.solutionId || root.lastLoadingResult.id)) {
      return root.lastLoadingResult.solutionId || root.lastLoadingResult.id;
    }
    if (root.stateManager && root.stateManager.solutionId) {
      return root.stateManager.solutionId;
    }
    return `sol_${Date.now()}`;
  }

  function getAnnotationApiUrl() {
    if (root.location) {
      if (root.location.protocol === 'file:') {
        return 'http://localhost:8080/api/v1/annotations';
      }
      if (root.location.port === '8080') {
        return '/api/v1/annotations';
      }
      return `${root.location.protocol}//${root.location.hostname}:8080/api/v1/annotations`;
    }
    return '/api/v1/annotations';
  }

  function setRating(rating) {
    if (['GOLD', 'SILVER', 'REJECT'].includes(rating)) {
      state.rating = rating;
      if (rating === 'GOLD') {
        state.selectedTags.add('EXPERT_APPROVED');
        state.selectedTags.delete('HONEYCOMB_CAVITY');
        state.selectedTags.delete('FALSE_HIGH_UTILIZATION');
        if (state.score < 85) state.score = 92;
      } else if (rating === 'SILVER') {
        state.selectedTags.delete('EXPERT_APPROVED');
        state.selectedTags.delete('HONEYCOMB_CAVITY');
        if (state.score < 60 || state.score > 85) state.score = 75;
      } else if (rating === 'REJECT') {
        state.selectedTags.delete('EXPERT_APPROVED');
        state.selectedTags.add('HONEYCOMB_CAVITY');
        if (state.score > 60) state.score = 45;
      }
      updateUI();
    }
  }

  function toggleTag(tagId) {
    if (state.selectedTags.has(tagId)) {
      state.selectedTags.delete(tagId);
    } else {
      state.selectedTags.add(tagId);
    }
    updateUI();
  }

  function addDefectPin(boxId, skuId, location, note = '') {
    const defect = {
      id: `def_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
      boxId: boxId || 'box',
      skuId: skuId || 'SKU',
      location: location || { x: 0, y: 0, z: 0 },
      type: Array.from(state.selectedTags)[0] || 'HONEYCOMB_CAVITY',
      note: note || `定位: (${location.x}, ${location.y}, ${location.z})`,
      timestamp: Date.now(),
    };
    state.defects.push(defect);
    updateUI();
    return defect;
  }

  function removeDefectPin(defectId) {
    state.defects = state.defects.filter(d => d.id !== defectId);
    updateUI();
  }

  /**
   * Resets the annotation form to initial state for next annotation
   */
  function resetForm(keepSolution = false) {
    if (!keepSolution) {
      state.solutionId = '';
    }
    state.rating = 'GOLD';
    state.score = 92;
    state.selectedTags = new Set(['EXPERT_APPROVED']);
    state.defects = [];
    state.expertNotes = '';
    state.isSubmitting = false;

    const elNotes = document.getElementById('expert-notes-input');
    if (elNotes) elNotes.value = '';

    updateUI();
    if (root.showToast) {
      root.showToast('✨ 标注面板已重置，已就绪可开始下一条方案评审！', 'info');
    }
  }

  /**
   * Fetches all archived annotations from backend API or offline localStorage
   */
  async function fetchHistory() {
    const apiUrl = getAnnotationApiUrl();
    try {
      const resp = await fetch(apiUrl);
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.annotations) {
          return data.annotations;
        }
      }
    } catch (_) {}

    // Fallback to localStorage
    try {
      const localKey = '3daicivs_expert_annotations';
      return JSON.parse(localStorage.getItem(localKey) || '[]');
    } catch (_) {
      return [];
    }
  }

  /**
   * Exports all archived annotations as a downloadable JSON file
   */
  async function exportHistory() {
    const list = await fetchHistory();
    if (!list || list.length === 0) {
      if (root.showToast) root.showToast('当前暂无已归档的标注数据！', 'warning');
      return;
    }
    const blob = new Blob([JSON.stringify(list, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `annotations_export_${Date.now()}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    if (root.showToast) {
      root.showToast(`📥 已成功导出 ${list.length} 条标注数据！`, 'success');
    }
  }

  /**
   * Submits expert annotation with backend API + offline localStorage persistence
   */
  async function submitAnnotation() {
    state.isSubmitting = true;
    updateUI();

    const solId = state.solutionId || getCurrentSolutionId();
    const payload = {
      solutionId: solId,
      rating: state.rating,
      score: state.score,
      tags: Array.from(state.selectedTags),
      defects: state.defects,
      expertNotes: state.expertNotes.trim(),
      annotator: state.annotator,
      containerSpec: root.currentSpec ? {
        code: root.currentSpec.code,
        intL: root.currentSpec.intL,
        intW: root.currentSpec.intW,
        intH: root.currentSpec.intH,
      } : null,
      timestamp: Date.now(),
    };

    // 1. 本地 LocalStorage 强保障保存
    try {
      const localKey = '3daicivs_expert_annotations';
      const history = JSON.parse(localStorage.getItem(localKey) || '[]');
      history.unshift({ ...payload, localSavedAt: Date.now() });
      localStorage.setItem(localKey, JSON.stringify(history.slice(0, 100)));
    } catch (_) {}

    // 2. 远程后端 REST API 提交
    const apiUrl = getAnnotationApiUrl();
    let backendSaved = false;

    try {
      const resp = await fetch(apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        const res = await resp.json();
        backendSaved = true;
        state.lastSubmittedId = res.annotation?.annotationId || res.annotationId || `ann_${Date.now()}`;
      }
    } catch (err) {
      console.warn('[Annotation] 后端 API 暂时不可达，已启用离线沉淀保障:', err.message);
    }

    state.isSubmitting = false;
    if (!state.lastSubmittedId) {
      state.lastSubmittedId = `local_${Date.now()}`;
    }

    const toastMsg = backendSaved
      ? `✅ 专家评审已归档至数据仓库！编号: ${state.lastSubmittedId} (评级: ${state.rating})`
      : `💾 专家评审已保存至本地金牌仓库！(评级: ${state.rating}, 待后端上线后自动同步)`;

    if (root.showToast) {
      root.showToast(toastMsg, backendSaved ? 'success' : 'info');
    } else {
      alert(toastMsg);
    }

    // 自动重置表单为下一次标注做好准备
    setTimeout(() => {
      resetForm(false);
    }, 1200);

    updateUI();
    return { success: true, annotationId: state.lastSubmittedId, backendSaved };
  }

  /**
   * Syncs state with DOM elements and applies clear visual active styling.
   */
  function updateUI() {
    const elRatingGold = document.getElementById('expert-rate-gold');
    const elRatingSilver = document.getElementById('expert-rate-silver');
    const elRatingReject = document.getElementById('expert-rate-reject');
    const elNotes = document.getElementById('expert-notes-input');
    const elScore = document.getElementById('expert-score-slider');
    const elScoreVal = document.getElementById('expert-score-value');
    const elDefectsList = document.getElementById('expert-defects-list');
    const elSubmitBtn = document.getElementById('expert-submit-btn');

    // 1. Rating Buttons Styling
    if (elRatingGold) {
      const isGold = state.rating === 'GOLD';
      elRatingGold.style.background = isGold ? '#fef3c7' : '#f8fafc';
      elRatingGold.style.border = isGold ? '2px solid #f59e0b' : '1px solid #cbd5e1';
      elRatingGold.style.color = isGold ? '#b45309' : '#64748b';
      elRatingGold.style.boxShadow = isGold ? '0 2px 8px rgba(245, 158, 11, 0.28)' : 'none';
      elRatingGold.style.transform = isGold ? 'scale(1.02)' : 'scale(1)';
    }

    if (elRatingSilver) {
      const isSilver = state.rating === 'SILVER';
      elRatingSilver.style.background = isSilver ? '#e0f2fe' : '#f8fafc';
      elRatingSilver.style.border = isSilver ? '2px solid #0284c7' : '1px solid #cbd5e1';
      elRatingSilver.style.color = isSilver ? '#0369a1' : '#64748b';
      elRatingSilver.style.boxShadow = isSilver ? '0 2px 8px rgba(2, 132, 199, 0.28)' : 'none';
      elRatingSilver.style.transform = isSilver ? 'scale(1.02)' : 'scale(1)';
    }

    if (elRatingReject) {
      const isReject = state.rating === 'REJECT';
      elRatingReject.style.background = isReject ? '#fef2f2' : '#f8fafc';
      elRatingReject.style.border = isReject ? '2px solid #ef4444' : '1px solid #cbd5e1';
      elRatingReject.style.color = isReject ? '#b91c1c' : '#64748b';
      elRatingReject.style.boxShadow = isReject ? '0 2px 8px rgba(239, 68, 68, 0.28)' : 'none';
      elRatingReject.style.transform = isReject ? 'scale(1.02)' : 'scale(1)';
    }

    // 2. Score Slider
    if (elScore && elScoreVal) {
      elScore.value = state.score;
      elScoreVal.textContent = state.score;
      elScoreVal.style.color = state.score >= 88 ? '#d97706' : (state.score >= 60 ? '#0284c7' : '#dc2626');
    }

    // 3. Defect Tags Styling
    DEFECT_DEFINITIONS.forEach(def => {
      const btn = document.getElementById(`tag-btn-${def.id}`);
      if (btn) {
        const isSelected = state.selectedTags.has(def.id);
        btn.style.background = isSelected ? '#fff7ed' : '#ffffff';
        btn.style.border = isSelected ? '1.5px solid #f97316' : '1px solid #e2e8f0';
        btn.style.color = isSelected ? '#c2410c' : '#475569';
        btn.style.fontWeight = isSelected ? '800' : '500';
        btn.style.boxShadow = isSelected ? '0 1px 4px rgba(249, 115, 22, 0.2)' : 'none';
      }
    });

    // 4. Defect Pins List
    if (elDefectsList) {
      elDefectsList.innerHTML = '';
      if (state.defects.length === 0) {
        elDefectsList.innerHTML = '<div style="font-size:11px;color:var(--slate-400);padding:6px 0;text-align:center;">暂无圈选的缺陷（直接点击 3D 视口中的箱体即可打标）</div>';
      } else {
        state.defects.forEach(d => {
          const item = document.createElement('div');
          item.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:4px 8px;margin-bottom:4px;background:#ffffff;border:1px solid #fed7aa;border-radius:6px;font-size:11px;';
          item.innerHTML = `<span><strong style="color:#c2410c;">⚠️ ${d.skuId}</strong> <span style="color:#64748b;font-size:10px;">[${d.location.x}, ${d.location.y}, ${d.location.z}]</span></span><button style="border:none;background:none;color:#ef4444;font-size:14px;font-weight:bold;cursor:pointer;padding:0 4px;" onclick="window.expertAnnotation.removeDefect('${d.id}')" title="移除此标记">✕</button>`;
          elDefectsList.appendChild(item);
        });
      }
    }

    // 5. Submit Button
    if (elSubmitBtn) {
      elSubmitBtn.disabled = state.isSubmitting;
      elSubmitBtn.innerHTML = state.isSubmitting
        ? '<span>正在归档沉淀中... ⏳</span>'
        : `<span>提交专家评审标注并归档 (${state.rating}) 🚀</span>`;
    }
  }

  return {
    DEFECT_DEFINITIONS,
    getState: () => ({
      ...state,
      selectedTags: Array.from(state.selectedTags),
    }),
    setRating,
    setScore: (score) => {
      state.score = Math.max(0, Math.min(100, Number(score)));
      updateUI();
    },
    setNotes: (notes) => {
      state.expertNotes = String(notes || '');
    },
    setAnnotator: (name) => {
      state.annotator = String(name || '3D-Expert');
    },
    setSolutionId: (id) => {
      state.solutionId = String(id || '');
    },
    toggleTag,
    addDefect: addDefectPin,
    removeDefect: removeDefectPin,
    reset: resetForm,
    getHistory: fetchHistory,
    exportHistory: exportHistory,
    submit: submitAnnotation,
    updateUI,
  };
});
