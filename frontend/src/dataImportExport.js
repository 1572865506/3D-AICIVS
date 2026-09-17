// Data Import/Export - Excel parsing, manifest generation, screenshot capture

function parseExcelData(data) {
  const workbook = XLSX.read(data, { type: 'array' });
  const sheetName = workbook.SheetNames[0];
  if (!sheetName) return [];
  const sheet = workbook.Sheets[sheetName];
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '' });
  if (rows.length < 2) return [];

  const headerRow = rows[0];
  const skuIdx = headerRow.findIndex(h => /SKU|货号|编号/i.test(h));
  const nameIdx = headerRow.findIndex(h => /名称|品名|货物|商品/i.test(h));
  const wIdx = headerRow.findIndex(h => /宽|width/i.test(h));
  const dIdx = headerRow.findIndex(h => /深|长|depth|length/i.test(h));
  const hIdx = headerRow.findIndex(h => /高|height/i.test(h));
  const weightIdx = headerRow.findIndex(h => /重量|weight/i.test(h));
  const qtyIdx = headerRow.findIndex(h => /数量|件数|quantity/i.test(h));
  const reqIdx = headerRow.findIndex(h => /需求|要求|requirement/i.test(h));

  const items = [];
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i];
    if (!row || row.length === 0) continue;
    const sku = (skuIdx >= 0 && row[skuIdx]) ? String(row[skuIdx]).trim() : `SKU_${i}`;
    if (!sku) continue;
    const name = (nameIdx >= 0 && row[nameIdx]) ? String(row[nameIdx]).trim() : sku;
    const w = parseFloat(row[wIdx]) || 0;
    const d = parseFloat(row[dIdx]) || 0;
    const h = parseFloat(row[hIdx]) || 0;
    const weight = parseFloat(row[weightIdx]) || 0;
    const quantity = parseInt(row[qtyIdx], 10) || 0;
    const requirement = (reqIdx >= 0 && row[reqIdx]) ? String(row[reqIdx]).trim() : '放中间';
    if (w <= 0 || d <= 0 || h <= 0 || quantity <= 0) continue;
    items.push({ sku, name, w, d, h, weight, quantity, requirement });
  }
  return items;
}

function handleExcelFileUpload(file) {
  const reader = new FileReader();
  reader.onload = function(e) {
    try {
      const data = new Uint8Array(e.target.result);
      const items = parseExcelData(data);
      if (items.length === 0) {
        window.showToast('未能从 Excel 中解析出有效 SKU 行', 'warning');
        return;
      }
      showImportPreviewModal(items);
    } catch (err) {
      console.error('[dataImportExport] Excel parse error:', err);
      window.showToast('Excel 文件解析失败', 'error');
    }
  };
  reader.readAsArrayBuffer(file);
}

function showImportPreviewModal(items) {
  const modal = document.getElementById('import-preview-modal');
  const tbody = document.querySelector('#import-preview-table tbody');
  tbody.innerHTML = '';
  items.forEach(it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${it.sku}</td>
      <td>${it.name}</td>
      <td>${it.w}m</td>
      <td>${it.d}m</td>
      <td>${it.h}m</td>
      <td>${it.weight}kg</td>
      <td>${it.quantity}</td>
      <td>${it.requirement}</td>
    `;
    tbody.appendChild(tr);
  });
  modal.style.display = 'flex';

  document.getElementById('btn-confirm-import').onclick = function() {
    window.stateManager.activeManifest = items;
    window.stateManager.saveAppState();
    window.renderManifestUI();
    window.stateManager.markManifestDirty('EXCEL_IMPORT');
    modal.style.display = 'none';
    window.showToast(`已导入 ${items.length} 个 SKU`, 'success');
  };
  document.getElementById('btn-cancel-import').onclick = function() {
    modal.style.display = 'none';
  };
}

function downloadExactTemplate() {
  const templateRows = [
    ['SKU', '货物名称', '宽(m)', '深(m)', '高(m)', '重量(kg)', '数量', '需求'],
    ['A001', '纸箱小', 0.4, 0.3, 0.25, 8, 100, '放中间'],
    ['A002', '纸箱大', 0.6, 0.5, 0.4, 15, 50, '放最里面'],
    ['B001', '木箱重', 0.8, 0.8, 0.6, 120, 20, '封柜门']
  ];
  const ws = XLSX.utils.aoa_to_sheet(templateRows);
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'SKU清单');
  XLSX.writeFile(wb, '3D-AICIVS-SKU-Template.xlsx');
}

window.captureViewportScreenshot = async function({ withUI = false, action = 'copy' } = {}) {
  try {
    const now = new Date();
    const timestamp = `${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}_${String(now.getHours()).padStart(2,'0')}${String(now.getMinutes()).padStart(2,'0')}${String(now.getSeconds()).padStart(2,'0')}`;
    const modeLabel = withUI ? 'FULL' : '3D';
    const containerCode = window.stateManager.activeContainerCode;
    const filename = `3D-AICIVS-${modeLabel}-${containerCode}-${timestamp}.png`;

    if (withUI) {
      if (action === 'copy') {
        const blobPromise = new Promise(async (resolve, reject) => {
          try {
            const canvas = await window.html2canvas(document.body, {
              backgroundColor: '#dce5ef',
              scale: Math.min(window.devicePixelRatio || 2, 2),
              ignoreElements: (el) => {
                if (el.id === 'screenshot-menu-dropdown') return true;
                if (el.classList && el.classList.contains('toast-notification')) return true;
                return false;
              }
            });
            canvas.toBlob((b) => {
              if (b) resolve(b);
              else reject(new Error('html2canvas blob conversion failed'));
            }, 'image/png');
          } catch (err) {
            reject(err);
          }
        });
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blobPromise })]);
        window.showToast('截图已复制到剪贴板（含 UI）', 'success');
      } else {
        const canvas = await window.html2canvas(document.body, {
          backgroundColor: '#dce5ef',
          scale: Math.min(window.devicePixelRatio || 2, 2),
          ignoreElements: (el) => {
            if (el.id === 'screenshot-menu-dropdown') return true;
            if (el.classList && el.classList.contains('toast-notification')) return true;
            return false;
          }
        });
        window.downloadCanvasImage(canvas, filename);
        window.showToast(`截图已下载: ${filename}`, 'success');
      }
    } else {
      const renderer = window.sceneManager.renderer;
      const scene = window.sceneManager.scene;
      const camera = window.sceneManager.camera;
      renderer.render(scene, camera);
      if (action === 'copy') {
        const blobPromise = new Promise((resolve, reject) => {
          renderer.domElement.toBlob((b) => {
            if (b) resolve(b);
            else reject(new Error('WebGL Canvas toBlob failed'));
          }, 'image/png');
        });
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blobPromise })]);
        window.showToast('纯 3D 截图已复制到剪贴板', 'success');
      } else {
        window.downloadCanvasImage(renderer.domElement, filename);
        window.showToast(`3D 截图已下载: ${filename}`, 'success');
      }
    }
  } catch (err) {
    console.error('[dataImportExport] screenshot error:', err);
    if (err.name === 'NotAllowedError') {
      window.showToast('剪贴板访问被拒绝，请检查浏览器权限', 'error');
    } else {
      window.showToast('截图失败: ' + err.message, 'error');
    }
  }
};

function downloadCanvasImage(canvas, filename) {
  const dataUrl = canvas.toDataURL('image/png');
  downloadDataUrl(dataUrl, filename);
}

function downloadDataUrl(dataUrl, filename) {
  const a = document.createElement('a');
  a.href = dataUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

window.downloadCanvasImage = downloadCanvasImage;
window.downloadDataUrl = downloadDataUrl;

const dropZone = document.getElementById('excel-drop-zone');
if (dropZone) {
  dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.add('drag-over');
  });
  dropZone.addEventListener('dragleave', e => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('drag-over');
  });
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      handleExcelFileUpload(files[0]);
    }
  });
}

window.handleExcelFileUpload = handleExcelFileUpload;
window.downloadExactTemplate = downloadExactTemplate;
