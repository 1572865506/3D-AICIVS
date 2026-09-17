/**
 * uiHandlers.js
 * 3D-AICIVS UI Event Handlers & Interactions Module
 * 
 * Responsibilities:
 * - Container Type selection & camera updating
 * - Solve button triggering & progress modal lifecycle
 * - Drawer toggles (left workbench, algorithm weights, studio console)
 * - Preset manifest switching, SKU CRUD modals & form binding
 * - Toast notification rendering
 */

(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.uiHandlers = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  function showToast(msg, type = 'success', customTitle = '') {
    let container = document.getElementById('global-toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'global-toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast-card ${type}`;
    const icon = (type === 'success') ? '✓' : (type === 'info' ? '⚡' : '⚠️');
    const title = customTitle || (type === 'success' ? '算柜排布成功' : (type === 'warning' ? '装载提示' : '系统通知'));

    toast.innerHTML = `
      <div class="toast-icon-wrap">${icon}</div>
      <div class="toast-content">
        <div class="toast-title">${title}</div>
        <div class="toast-body">${msg}</div>
      </div>
      <button class="toast-close" onclick="this.parentElement.remove()" title="关闭提示">✕</button>
    `;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(12px) scale(0.96)';
      setTimeout(() => toast.remove(), 260);
    }, 3600);
  }

  function updateBackendStatus(status, mockMode = false) {
    const badge = document.getElementById('hud-cache-badge');
    const text = document.getElementById('txt-cache-badge');
    const dot = document.getElementById('cache-dot');
    if (!badge || !text || !dot) return;
    if (mockMode) {
      text.textContent = '离线 Mock 模式'; dot.style.background = '#8b5cf6';
      badge.style.color = '#7c3aed'; badge.style.background = '#f5f3ff'; badge.style.borderColor = '#ddd6fe';
      badge.title = '显式 ?mode=mock；未调用后端';
    } else if (status === 'ONLINE') {
      text.textContent = '服务在线'; dot.style.background = '#10b981';
      badge.style.color = '#059669'; badge.style.background = '#ecfdf5'; badge.style.borderColor = '#a7f3d0';
      badge.title = '3D-AICIVS 智能算柜引擎连接正常';
    } else if (status === 'OFFLINE') {
      text.textContent = '服务离线'; dot.style.background = '#ef4444';
      badge.style.color = '#dc2626'; badge.style.background = '#fef2f2'; badge.style.borderColor = '#fecaca';
      badge.title = '后端服务未启动或连接异常';
    } else {
      text.textContent = '状态检测中'; dot.style.background = '#f59e0b';
      badge.style.color = '#b45309'; badge.style.background = '#fffbeb'; badge.style.borderColor = '#fde68a';
      badge.title = '正在检测算柜服务状态...';
    }
  }

  let __packingProgressRunId = 0;
  function nextPaint() {
    return new Promise(res => requestAnimationFrame(() => setTimeout(res, 16)));
  }

  function createPackingProgress() {
    const runId = ++__packingProgressRunId;
    document.getElementById('packing-progress-overlay')?.remove();

    const overlay = document.createElement('div');
    overlay.id = 'packing-progress-overlay';
    overlay.className = 'pp-overlay';
    overlay.innerHTML = `
      <div class="pp-card">
        <div class="pp-header">
          <span class="pp-spinner"></span>
          <span class="pp-title">AI 算柜推演中…</span>
          <span class="pp-elapsed">0.0s</span>
          <button type="button" class="pp-abort-btn" onclick="window.abortPackingCalculation()" title="终止当前算柜计算">✕ 终止</button>
        </div>
        <div class="pp-steps">
          <div class="pp-step" data-step="1"><span class="pp-dot"></span><span>提交参数请求（策略 / 间距 / 配平）</span></div>
          <div class="pp-step" data-step="2"><span class="pp-dot"></span><span>智能装箱内核推演</span></div>
          <div class="pp-step" data-step="3"><span class="pp-dot"></span><span>重建 3D 装载场景</span></div>
        </div>
        <div class="pp-bar"><div class="pp-bar-fill"></div></div>
        <div class="pp-note">正在准备…</div>
      </div>`;
    document.body.appendChild(overlay);

    const card = overlay.querySelector('.pp-card');
    const elapsedEl = overlay.querySelector('.pp-elapsed');
    const noteEl = overlay.querySelector('.pp-note');
    const barFill = overlay.querySelector('.pp-bar-fill');
    const steps = overlay.querySelectorAll('.pp-step');
    const titleEl = overlay.querySelector('.pp-title');
    const spinnerEl = overlay.querySelector('.pp-spinner');

    const t0 = Date.now();
    const alive = () => runId === __packingProgressRunId && document.body.contains(overlay);
    const timer = setInterval(() => {
      if (!alive()) { clearInterval(timer); return; }
      elapsedEl.textContent = ((Date.now() - t0) / 1000).toFixed(1) + 's';
    }, 100);

    return {
      isCurrent: () => runId === __packingProgressRunId,
      elapsedSec: () => (Date.now() - t0) / 1000,
      step(idx, note) {
        if (!alive()) return;
        steps.forEach(s => {
          const i = parseInt(s.dataset.step, 10);
          s.classList.toggle('active', i === idx);
          s.classList.toggle('done', i < idx);
        });
        barFill.style.width = (idx === 1 ? '12%' : idx === 2 ? '55%' : '90%');
        if (note !== undefined) noteEl.textContent = note;
      },
      note(text) { if (alive()) noteEl.textContent = text; },
      finish(ok, summary, holdMs) {
        if (!alive()) return;
        clearInterval(timer);
        spinnerEl.style.display = 'none';
        if (ok) {
          steps.forEach(s => { s.classList.add('done'); s.classList.remove('active'); });
          barFill.style.width = '100%';
          card.classList.add('ok');
          titleEl.textContent = '✓ 算柜完成';
        } else {
          card.classList.add('err');
          titleEl.textContent = summary && summary.includes('终止') ? '已终止算柜' : '算柜失败';
        }
        if (summary) noteEl.textContent = summary;
        setTimeout(() => {
          overlay.classList.add('closing');
          setTimeout(() => overlay.remove(), 400);
        }, holdMs !== undefined ? holdMs : (ok ? 1300 : 3600));
      }
    };
  }

  let activePackingAbortController = null;
  let __currentPackingProgress = null;

  function abortPackingCalculation() {
    console.log('[3D-AICIVS] 用户手动终止算柜推演...');
    if (activePackingAbortController) {
      try { activePackingAbortController.abort(); } catch (_) {}
      activePackingAbortController = null;
    }
    if (root.currentSolutionEpoch !== undefined) root.currentSolutionEpoch++;
    if (__currentPackingProgress) {
      __currentPackingProgress.finish(false, '已终止算柜推演', 200);
    }
    const runBtn = document.getElementById('btn-run-packing');
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.style.opacity = '';
      runBtn.style.pointerEvents = '';
      const runBtnLabel = runBtn.querySelector('span');
      if (runBtnLabel) runBtnLabel.textContent = '开始计算';
    }
    if (root.ManifestWorkflow) {
      root.calculationStatus = root.ManifestWorkflow.CalculationStatus.DIRTY;
    }
    if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
    showToast('已由用户手动终止算柜推演。', 'info', '算柜已终止');
  }

  async function onSolveButtonClick(forceRecompute = true) {
    const activeManifest = root.stateManager ? root.stateManager.activeManifest : (root.activeManifest || []);
    const currentSpec = root.stateManager ? root.stateManager.currentSpec : (root.currentSpec || {});
    
    if (root.ManifestWorkflow) {
      const manifestValidation = root.ManifestWorkflow.validateManifest(activeManifest);
      if (activeManifest.length === 0) {
        showToast('货单为空，请先导入、新增或加载示例货单。', 'warning', '无法开始算柜');
        root.calculationStatus = root.ManifestWorkflow.CalculationStatus.EMPTY;
        if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
        return;
      }
      if (!manifestValidation.valid) {
        showToast(manifestValidation.errors.slice(0, 4).join('；'), 'warning', '货单校验失败');
        root.calculationStatus = root.ManifestWorkflow.CalculationStatus.DIRTY;
        if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
        return;
      }
    }

    const mode = root.BLK007D ? root.BLK007D.getMode() : 'BACKEND';
    if (mode === 'BACKEND' && root.ManifestWorkflow) {
      const doorAdmission = root.ManifestWorkflow.validateDoorWallAdmission(activeManifest, currentSpec);
      if (!doorAdmission.valid) {
        showToast(`${doorAdmission.message}。系统不会自动把普通货物开放到门区。`, 'warning', '门墙配置未就绪');
        root.calculationStatus = root.ManifestWorkflow.CalculationStatus.DIRTY;
        if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
        return;
      }
    }

    const requestedRevision = root.manifestRevision || 0;
    if (root.ManifestWorkflow) {
      root.calculationStatus = root.ManifestWorkflow.CalculationStatus.RUNNING;
      if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
    }

    if (activePackingAbortController) {
      try { activePackingAbortController.abort(); } catch (_) {}
    }
    activePackingAbortController = new AbortController();

    if (root.currentSolutionEpoch === undefined) root.currentSolutionEpoch = 0;
    const thisEpoch = ++root.currentSolutionEpoch;

    const prog = createPackingProgress();
    __currentPackingProgress = prog;
    const runBtn = document.getElementById('btn-run-packing');
    const runBtnLabel = runBtn ? runBtn.querySelector('span') : null;
    const setRunBusy = (busy) => {
      if (!runBtn || !prog.isCurrent()) return;
      runBtn.disabled = busy;
      runBtn.style.opacity = busy ? '0.55' : '';
      runBtn.style.pointerEvents = busy ? 'none' : '';
      if (runBtnLabel && busy) runBtnLabel.textContent = '算柜推演中…';
      if (!busy && typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
    };
    setRunBusy(true);

    const currentStrategy = root.currentStrategy || 'cluster';
    const currentGap = root.currentGap || 0;
    const isCoGBalanceEnabled = root.isCoGBalanceEnabled !== false;

    prog.step(1, `策略 ${currentStrategy === 'mec' ? 'MEC 紧凑填充' : '同品聚合'} · 货物间距 ${Math.round(currentGap * 1000)}mm · 配平 ${isCoGBalanceEnabled ? '开' : '关'}`);
    await nextPaint();

    const usableDim = {
      length: currentSpec.intL,
      height: currentSpec.intH,
      width:  currentSpec.intW
    };

    prog.step(2, mode === 'MOCK' ? '读取离线预设装载方案…' : `提交 3D-AICIVS 后端算柜任务（${activeManifest.length} 种 SKU · ${currentSpec.code || ''}）…`);
    await nextPaint();

    let loadingResult;
    try {
      if (mode === 'BACKEND' && root.BLK007D) {
        updateBackendStatus('CHECKING');
        const health = await root.BLK007D.checkHealth();
        updateBackendStatus(health);
        if (health !== 'ONLINE') {
          throw new root.BLK007D.BackendError('NETWORK_ERROR', '后端算柜服务不可用');
        }
      } else {
        updateBackendStatus('OFFLINE', true);
      }

      if (root.BLK007D) {
        loadingResult = await root.BLK007D.calculate({
          solverVersion: 'v2',
          mode: currentStrategy === 'mec' ? 'MAX_COMPACT' : 'BALANCED',
          timeBudgetSec: 20,
          randomSeed: 42,
          container: {
            code: currentSpec.code,
            usable: currentSpec.usable || { L: currentSpec.intL, W: currentSpec.intW, H: currentSpec.intH },
            maxPayloadKg: (currentSpec.maxPayloadTons || 26.5) * 1000,
            doorZoneLengthM: 1.2,
            rearZoneLengthM: 1.0
          },
          sku: activeManifest
        }, { signal: activePackingAbortController.signal });
      }

      if (thisEpoch < root.currentSolutionEpoch || (root.manifestRevision !== undefined && requestedRevision !== root.manifestRevision)) {
        console.warn('[3D-AICIVS] 请求已被后续任务取代，终止渲染');
        if (root.ManifestWorkflow) root.calculationStatus = root.ManifestWorkflow.CalculationStatus.DIRTY;
        if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
        return;
      }
    } catch (err) {
      const errorType = err && err.type ? err.type : 'NETWORK_ERROR';
      if (errorType === 'ABORTED' || (err && err.message && (err.message.includes('终止') || err.message.includes('abort') || err.message.includes('AbortError')))) {
        console.log('[3D-AICIVS] 算柜任务已取消/终止');
        prog.finish(false, '已终止算柜推演', 200);
        setRunBusy(false);
        return;
      }
      const isInputConstraint = errorType === 'INPUT_CONSTRAINT';
      if (root.reportAppError) {
        root.reportAppError(err, { source: 'BACKEND_API', operation: 'CALCULATE_LOADING', type: errorType });
      }
      if (mode === 'BACKEND' && errorType === 'NETWORK_ERROR') updateBackendStatus('OFFLINE');
      const copy = { title: '算柜失败', message: err.message || String(err) };
      showToast(copy.message, 'warning', copy.title);
      if (root.ManifestWorkflow) {
        root.calculationStatus = isInputConstraint
          ? root.ManifestWorkflow.CalculationStatus.DIRTY
          : root.ManifestWorkflow.CalculationStatus.FAILED;
      }
      if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
      prog.finish(false, `${errorType}: ${copy.message}`);
      setRunBusy(false);
      return;
    }

    if (thisEpoch < root.currentSolutionEpoch) return;

    prog.step(3, `正在根据全局推演数据重建 3D 场景（${loadingResult.cargo.length} 箱）…`);
    await nextPaint();

    try {
      if (root.visualizationCore) {
        root.visualizationCore.applyBackendLoadingResult(loadingResult, usableDim, activeManifest, currentSpec);
      }
      if (typeof root.saveLoadingResultCache === 'function') {
        root.saveLoadingResultCache(loadingResult, usableDim, activeManifest, currentSpec);
      }

      root.isCameraDirty = true;
      root.isRaycastDirty = true;
      if (typeof root.updateAdaptiveCutaway === 'function') root.updateAdaptiveCutaway();
      if (typeof root.renderManifestUI === 'function') root.renderManifestUI();
      if (typeof root.renderAnchorRibbon === 'function') root.renderAnchorRibbon();
      if (root.visualizationCore) root.visualizationCore.updateBoxVisibilityAndMaterials();

      if (forceRecompute && root.activePackingResult) {
        const unplaced = root.activePackingResult.totalUnplacedCount || 0;
        showToast(`${mode === 'MOCK' ? '离线' : '3D-AICIVS 后端'}算柜结果已加载：${root.activePackingResult.totalCount} 箱，利用率 ${root.activePackingResult.utilization}%${unplaced ? `，未装 ${unplaced} 箱` : ''}`, unplaced ? 'warning' : 'success');
      }

      if (root.ManifestWorkflow) {
        root.calculatedRevision = requestedRevision;
        root.calculationStatus = root.ManifestWorkflow.CalculationStatus.READY;
      }
      if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();

      if (root.activePackingResult) {
        prog.finish(true, `${mode === 'MOCK' ? '离线推演引擎' : '3D-AICIVS 智能算柜引擎'} · 共 ${root.activePackingResult.totalCount} 箱 · 利用率 ${root.activePackingResult.utilization}% · 总耗时 ${prog.elapsedSec().toFixed(1)}s`);
      }
      setRunBusy(false);
    } catch (renderErr) {
      console.error('[3D-AICIVS] 3D 场景渲染异常:', renderErr);
      showToast('⚠️ 3D 渲染异常: ' + renderErr.message, 'warning');
      prog.finish(false, '3D 渲染异常: ' + (renderErr.message || renderErr));
      if (root.ManifestWorkflow) root.calculationStatus = root.ManifestWorkflow.CalculationStatus.FAILED;
      if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
      setRunBusy(false);
    }
  }

  function onClearButtonClick() {
    if (root.visualizationCore) root.visualizationCore.clearVisualization();
    if (root.stateManager) {
      root.stateManager.activePackingResult = null;
      root.stateManager.saveAppState();
    }
    if (typeof root.updateCalculationStateUI === 'function') root.updateCalculationStateUI();
    showToast('已清空当前装载视图', 'info');
  }

  function onScreenshotButtonClick(withUI = false, action = 'copy') {
    if (typeof root.captureViewportScreenshot === 'function') {
      root.captureViewportScreenshot({ withUI, action });
    }
  }

  function onExcelUploadChange(file) {
    if (typeof root.handleExcelFileUpload === 'function') {
      root.handleExcelFileUpload(file);
    }
  }

  // Window exports
  return {
    showToast,
    updateBackendStatus,
    abortPackingCalculation,
    onSolveButtonClick,
    onClearButtonClick,
    onScreenshotButtonClick,
    onExcelUploadChange
  };
});
