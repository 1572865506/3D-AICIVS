/**
 * main.js
 * Application Entry Point & Event Wiring Module
 * 
 * Responsibilities:
 * - Application lifecycle initialization
 * - Event delegation & DOM listener attachment
 * - State restoration & synchronization
 */

(function (root) {
  'use strict';

  function initializeApp() {
    console.log('[Main] Initializing 3D-AICIVS...');

    // 1. Load persisted state from stateManager
    if (root.stateManager && typeof root.stateManager.loadAppState === 'function') {
      root.stateManager.loadAppState();
    }

    // 2. Bind DOM event listeners
    bindUIEvents();

    // 3. Restore last session data
    restoreLastSession();

    console.log('[Main] Application ready');
  }

  function bindUIEvents() {
    // Solve button
    const solveBtn = document.getElementById('btn-run-packing');
    if (solveBtn) {
      solveBtn.addEventListener('click', () => {
        if (root.uiHandlers && typeof root.uiHandlers.onSolveButtonClick === 'function') {
          root.uiHandlers.onSolveButtonClick(true);
        } else if (typeof root.runSmartPackingAlgorithm === 'function') {
          root.runSmartPackingAlgorithm(true);
        }
      });
    }

    // Abort button
    window.abortPackingCalculation = function() {
      if (root.uiHandlers && typeof root.uiHandlers.abortPackingCalculation === 'function') {
        root.uiHandlers.abortPackingCalculation();
      }
    };

    // Clean cache button
    const cleanCacheBtn = document.getElementById('btn-clean-cache');
    if (cleanCacheBtn) {
      cleanCacheBtn.addEventListener('click', () => {
        if (typeof root.clearAllAppCaches === 'function') root.clearAllAppCaches();
      });
    }

    // Slicing Timeline Slider
    const sliceSlider = document.getElementById('slice-depth-slider');
    if (sliceSlider) {
      sliceSlider.addEventListener('input', (e) => {
        if (root.visualizationCore) {
          root.visualizationCore.onSlicingTimelineChange(e.target.value);
        } else if (typeof root.onSlicingTimelineChange === 'function') {
          root.onSlicingTimelineChange(e.target.value);
        }
      });
    }

    // Package Orientation Mode toggle
    const oriBtn = document.getElementById('btn-orientation-mode');
    if (oriBtn) {
      oriBtn.addEventListener('click', () => {
        if (root.visualizationCore) {
          root.visualizationCore.togglePackageOrientationMode();
        } else if (typeof root.togglePackageOrientationMode === 'function') {
          root.togglePackageOrientationMode();
        }
      });
    }

    // Excel Drop Zone & Input
    const excelInput = document.getElementById('excel-file-input');
    if (excelInput) {
      excelInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
          if (root.uiHandlers && typeof root.uiHandlers.onExcelUploadChange === 'function') {
            root.uiHandlers.onExcelUploadChange(e.target.files[0]);
          } else if (typeof root.handleExcelFileUpload === 'function') {
            root.handleExcelFileUpload(e.target.files[0]);
          }
        }
      });
    }
  }

  function restoreLastSession() {
    const stateManager = root.stateManager;
    if (!stateManager) return;
    const activeCode = stateManager.activeContainerCode;
    if (activeCode && typeof root.switchContainerType === 'function') {
      root.switchContainerType(activeCode);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
  } else {
    initializeApp();
  }

  console.log('[Main] Module loaded');
})(typeof window !== 'undefined' ? window : globalThis);
