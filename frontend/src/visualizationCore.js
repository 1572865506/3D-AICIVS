/**
 * visualizationCore.js
 * 3D-AICIVS Visualization Core Module
 * 
 * Responsibilities:
 * - 3D Cargo Mesh creation, scaling & coordinate transformation
 * - PBR Multi-face Material generator & SKU Material Registry
 * - Orientation Geometry & Material caching (via window.BLK007F78)
 * - CoG (Center of Gravity) 3D indicator & ground target
 * - Outline stroke & highlight system for hover and selection
 * - Longitudinal slicing timeline controller & visibility engine
 * - Update & clear visualization solutions
 */

(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.visualizationCore = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  // Three.js and scene references
  function getTHREE() { return root.THREE; }
  function getScene() { return root.sceneManager ? root.sceneManager.getScene() : root.scene; }
  function getCamera() { return root.sceneManager ? root.sceneManager.getCamera() : root.camera; }
  function getRenderer() { return root.sceneManager ? root.sceneManager.getRenderer() : root.renderer; }

  // State
  let boxMeshes = [];
  let hoveredBox = null;
  let cogIndicatorGroup = null;
  let showCoGIndicator = true;
  let currentSliceCutPercent = 0;
  let groundRulerMesh = null;
  let slicingGroundMarkerMesh = null;
  let packageOrientationDisplayMode = root.BLK007F78 ? root.BLK007F78.DisplayMode.PHYSICAL : 'PHYSICAL';
  let orientationAssistLine = null;

  // Caches & Registries
  const skuMaterialRegistry = new Map();
  let orientationGeometryCache = null;
  let orientationMaterialCache = null;
  let textureCanvasCache = null;

  function initCaches() {
    const THREE = getTHREE();
    if (!THREE) return;
    if (root.BLK007F78) {
      if (!orientationGeometryCache) orientationGeometryCache = new root.BLK007F78.OrientationGeometryCache(THREE);
      if (!orientationMaterialCache) orientationMaterialCache = new root.BLK007F78.OrientationMaterialCache();
      if (!textureCanvasCache) textureCanvasCache = new root.BLK007F78.PackageTextureRegistry();
    }
  }

  // Outline geometries & materials
  let unitBoxEdgesGeoInner = null;
  let unitBoxEdgesGeoOuter = null;
  let highlightOutlineMaterial = null;
  let hoverSingleOutlineMaterial = null;

  function initOutlineResources() {
    const THREE = getTHREE();
    if (!THREE || unitBoxEdgesGeoInner) return;
    unitBoxEdgesGeoInner = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.003, 1.003, 1.003));
    unitBoxEdgesGeoOuter = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.008, 1.008, 1.008));
    highlightOutlineMaterial = new THREE.LineBasicMaterial({
      color: 0x00f0ff,
      linewidth: 2,
      transparent: true,
      opacity: 0.95,
      depthTest: true
    });
    hoverSingleOutlineMaterial = new THREE.LineBasicMaterial({
      color: 0xffeb3b,
      linewidth: 3,
      transparent: true,
      opacity: 1.0,
      depthTest: true
    });
  }

  function attachOutlineStrokeToMesh(mesh) {
    if (!mesh) return null;
    initOutlineResources();
    const THREE = getTHREE();
    const outlineGroup = new THREE.Group();
    outlineGroup.name = 'highlightOutlineStroke';
    const lineInner = new THREE.LineSegments(unitBoxEdgesGeoInner, highlightOutlineMaterial);
    const lineOuter = new THREE.LineSegments(unitBoxEdgesGeoOuter, highlightOutlineMaterial);
    outlineGroup.add(lineInner);
    outlineGroup.add(lineOuter);
    outlineGroup.visible = false;
    mesh.add(outlineGroup);
    mesh.userData.outlineStroke = outlineGroup;
    mesh.userData.outlineLines = [lineInner, lineOuter];
    return outlineGroup;
  }

  function setMeshOutlineState(mesh, isHighlighted, isHoverSingle = false) {
    if (!mesh || !mesh.userData || !mesh.userData.outlineStroke) return;
    mesh.userData.outlineStroke.visible = Boolean(isHighlighted && mesh.visible);
    if (isHighlighted) {
      const mat = isHoverSingle ? hoverSingleOutlineMaterial : highlightOutlineMaterial;
      if (mesh.userData.outlineLines) {
        mesh.userData.outlineLines.forEach(l => { l.material = mat; });
      }
    }
  }

  // --- Multi-Face Texture Generator ---
  function getOrCreateFaceTextures(baseColorHex, labelText, skuCode) {
    initCaches();
    const cacheId = `${baseColorHex}_${skuCode}`;
    if (textureCanvasCache && textureCanvasCache.has(cacheId)) {
      return textureCanvasCache.get(cacheId);
    }
    const THREE = getTHREE();

    function createBaseCardboardCanvas() {
      const c = document.createElement('canvas');
      c.width = 512;
      c.height = 512;
      const ctx = c.getContext('2d');
      ctx.fillStyle = '#' + new THREE.Color(baseColorHex).getHexString();
      ctx.fillRect(0, 0, 512, 512);

      ctx.fillStyle = 'rgba(0, 0, 0, 0.035)';
      for (let i = 0; i < 2400; i++) {
        ctx.fillRect(Math.random() * 512, Math.random() * 512, 1.5, 1.5);
      }

      ctx.strokeStyle = 'rgba(0, 0, 0, 0.20)';
      ctx.lineWidth = 6;
      ctx.strokeRect(3, 3, 506, 506);
      return { c, ctx };
    }

    const frontBack = createBaseCardboardCanvas();
    const fbCtx = frontBack.ctx;
    fbCtx.fillStyle = 'rgba(0,0,0,0.06)';
    fbCtx.fillRect(0, 0, 512, 12);
    fbCtx.strokeStyle = 'rgba(0,0,0,0.22)';
    fbCtx.lineWidth = 1.5;
    fbCtx.beginPath();
    fbCtx.moveTo(0, 12);
    fbCtx.lineTo(512, 12);
    fbCtx.stroke();

    fbCtx.fillStyle = '#ffffff';
    fbCtx.shadowColor = 'rgba(0,0,0,0.16)';
    fbCtx.shadowBlur = 4;
    fbCtx.fillRect(36, 275, 165, 145);
    fbCtx.shadowBlur = 0;

    fbCtx.fillStyle = '#1e293b';
    fbCtx.fillRect(36, 275, 165, 20);
    fbCtx.fillStyle = '#ffffff';
    fbCtx.font = 'bold 9.5px monospace';
    fbCtx.fillText('EXPRESS CARGO', 48, 289);

    fbCtx.fillStyle = '#0f172a';
    for (let bx = 48; bx < 188; bx += Math.random() * 6 + 4) {
      fbCtx.fillRect(bx, 303, Math.random() > 0.4 ? 2.5 : 1.5, 46);
    }

    fbCtx.font = 'bold 11px sans-serif';
    fbCtx.fillStyle = '#1e293b';
    fbCtx.fillText(labelText || 'CARGO', 48, 385);

    function drawUpwardArrow(ctx, cx, cy, arrowW, arrowH) {
      ctx.save();
      ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
      ctx.beginPath();
      ctx.moveTo(cx, cy - arrowH);
      ctx.lineTo(cx - arrowW, cy - arrowH * 0.25);
      ctx.lineTo(cx - arrowW * 0.38, cy - arrowH * 0.25);
      ctx.lineTo(cx - arrowW * 0.38, cy + arrowH * 0.7);
      ctx.lineTo(cx + arrowW * 0.38, cy + arrowH * 0.7);
      ctx.lineTo(cx + arrowW * 0.38, cy - arrowH * 0.25);
      ctx.lineTo(cx + arrowW, cy - arrowH * 0.25);
      ctx.closePath();
      ctx.fill();
      ctx.fillRect(cx - arrowW * 1.1, cy + arrowH * 0.92, arrowW * 2.2, 4);
      ctx.restore();
    }

    fbCtx.strokeStyle = 'rgba(15, 23, 42, 0.38)';
    fbCtx.lineWidth = 1.5;
    fbCtx.strokeRect(325, 275, 145, 145);
    drawUpwardArrow(fbCtx, 368, 345, 16, 44);
    drawUpwardArrow(fbCtx, 425, 345, 16, 44);
    fbCtx.fillStyle = 'rgba(15, 23, 42, 0.85)';
    fbCtx.font = 'bold 9px monospace';
    fbCtx.textAlign = 'center';
    fbCtx.fillText('THIS SIDE UP', 397, 402);
    fbCtx.textAlign = 'left';

    const sideFace = createBaseCardboardCanvas();
    const sCtx = sideFace.ctx;
    sCtx.fillStyle = 'rgba(0,0,0,0.06)';
    sCtx.fillRect(0, 0, 512, 12);
    sCtx.strokeStyle = 'rgba(0,0,0,0.22)';
    sCtx.lineWidth = 1.5;
    sCtx.beginPath();
    sCtx.moveTo(0, 12);
    sCtx.lineTo(512, 12);
    sCtx.stroke();

    sCtx.fillStyle = 'rgba(0, 0, 0, 0.15)';
    sCtx.fillRect(196, 236, 120, 40);
    sCtx.strokeStyle = 'rgba(0, 0, 0, 0.3)';
    sCtx.lineWidth = 2;
    sCtx.strokeRect(196, 236, 120, 40);
    sCtx.fillStyle = 'rgba(15, 23, 42, 0.65)';
    sCtx.font = 'bold 12px monospace';
    sCtx.textAlign = 'center';
    sCtx.fillText(`[ ${skuCode} ]`, 256, 316);
    sCtx.textAlign = 'left';

    const topFace = createBaseCardboardCanvas();
    const tCtx = topFace.ctx;
    tCtx.strokeStyle = 'rgba(0,0,0,0.28)';
    tCtx.lineWidth = 2;
    tCtx.beginPath();
    tCtx.moveTo(0, 256);
    tCtx.lineTo(512, 256);
    tCtx.stroke();
    tCtx.fillStyle = 'rgba(238, 214, 168, 0.94)';
    tCtx.fillRect(0, 232, 512, 48);
    tCtx.strokeStyle = 'rgba(165, 125, 70, 0.5)';
    tCtx.lineWidth = 2;
    tCtx.strokeRect(0, 232, 512, 48);

    const bottomFace = createBaseCardboardCanvas();
    const bCtx = bottomFace.ctx;
    bCtx.strokeStyle = 'rgba(0,0,0,0.25)';
    bCtx.lineWidth = 2;
    bCtx.beginPath();
    bCtx.moveTo(0, 256);
    bCtx.lineTo(512, 256);
    bCtx.stroke();
    bCtx.strokeStyle = 'rgba(15, 23, 42, 0.25)';
    bCtx.lineWidth = 2;
    bCtx.beginPath();
    bCtx.arc(256, 256, 45, 0, Math.PI * 2);
    bCtx.stroke();
    bCtx.fillStyle = 'rgba(15, 23, 42, 0.28)';
    bCtx.font = 'bold 8px monospace';
    bCtx.textAlign = 'center';
    bCtx.fillText('CERTIFIED', 256, 252);
    bCtx.fillText('STANDARD BOX', 256, 264);
    bCtx.textAlign = 'left';

    const textures = {
      frontBackTex: new THREE.CanvasTexture(frontBack.c),
      sideTex:      new THREE.CanvasTexture(sideFace.c),
      topTex:       new THREE.CanvasTexture(topFace.c),
      bottomTex:    new THREE.CanvasTexture(bottomFace.c)
    };

    if (textureCanvasCache) textureCanvasCache.set(cacheId, textures);
    return textures;
  }

  // --- Coordinate Transformation Adapter ---
  function convertCanonicalToThree(x, y, z, dx, dy, dz, usableDim) {
    const halfIntL = usableDim.length / 2;
    const startY = -usableDim.height / 2;
    const startZ = -usableDim.width / 2;
    return {
      posX: halfIntL - x - dx / 2,
      posY: startY + z + dz / 2,
      posZ: startZ + y + dy / 2
    };
  }

  // --- Orientation Assist Lines ---
  function clearOrientationAssist() {
    if (!orientationAssistLine) return;
    if (orientationAssistLine.parent) orientationAssistLine.parent.remove(orientationAssistLine);
    if (orientationAssistLine.geometry) orientationAssistLine.geometry.dispose();
    if (orientationAssistLine.material) orientationAssistLine.material.dispose();
    orientationAssistLine = null;
  }

  function rebuildOrientationAssist() {
    clearOrientationAssist();
    const THREE = getTHREE();
    if (!THREE || !root.BLK007F78) return;
    if (packageOrientationDisplayMode !== root.BLK007F78.DisplayMode.ASSIST) return;
    const scene = getScene();
    if (!scene) return;

    const positions = [];
    const colors = [];

    boxMeshes.filter(box => box.visible).forEach(box => {
      const raw = box.userData.productUpThree || [0, 1, 0];
      const up = new THREE.Vector3(raw[0], raw[1], raw[2]).applyQuaternion(box.quaternion).normalize();
      let r = 0.13, g = 0.85, b = 0.45;
      const absX = Math.abs(up.x);
      const absY = Math.abs(up.y);
      const absZ = Math.abs(up.z);

      if (absY >= absX && absY >= absZ) {
        r = 0.13; g = 0.85; b = 0.45;
      } else if (absX >= absY && absX >= absZ) {
        r = 0.23; g = 0.51; b = 0.96;
      } else {
        r = 0.96; g = 0.62; b = 0.05;
      }

      const minDimension = Math.max(0.08, Math.min(
        Number(box.userData.rawW || 0.2), Number(box.userData.rawD || 0.2), Number(box.userData.rawH || 0.2)
      ));
      const length = Math.max(0.12, Math.min(0.28, minDimension * 0.85));
      const start = box.position.clone();
      const end = start.clone().addScaledVector(up, length);
      let perpendicular = new THREE.Vector3().crossVectors(up, new THREE.Vector3(0, 1, 0));
      if (perpendicular.lengthSq() < 1e-8) perpendicular = new THREE.Vector3().crossVectors(up, new THREE.Vector3(1, 0, 0));
      perpendicular.normalize();
      const headBase = end.clone().addScaledVector(up, -length * 0.32);
      const headWidth = length * 0.18;
      const left = headBase.clone().addScaledVector(perpendicular, headWidth);
      const right = headBase.clone().addScaledVector(perpendicular, -headWidth);

      const points = [start, end, end, left, end, right];
      points.forEach(point => {
        positions.push(point.x, point.y, point.z);
        colors.push(r, g, b);
      });
    });

    if (!positions.length) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    const material = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.95,
      depthTest: false
    });
    orientationAssistLine = new THREE.LineSegments(geometry, material);
    orientationAssistLine.name = 'PRODUCT_UP_ORIENTATION_ASSIST';
    orientationAssistLine.renderOrder = 999;

    const cargoGroup = root.cargoGroup;
    if (cargoGroup) {
      cargoGroup.add(orientationAssistLine);
    } else {
      scene.add(orientationAssistLine);
    }
    if (root.isCameraDirty !== undefined) root.isCameraDirty = true;
  }

  function togglePackageOrientationMode() {
    if (!root.BLK007F78) return;
    packageOrientationDisplayMode = packageOrientationDisplayMode === root.BLK007F78.DisplayMode.PHYSICAL
      ? root.BLK007F78.DisplayMode.ASSIST : root.BLK007F78.DisplayMode.PHYSICAL;
    const text = document.getElementById('txt-orientation-mode');
    const button = document.getElementById('btn-orientation-mode');
    const isAssist = packageOrientationDisplayMode === root.BLK007F78.DisplayMode.ASSIST;
    if (text) text.textContent = isAssist ? '朝向辅助' : '真实贴图';
    if (button) button.title = isAssist
      ? '朝向三色图例：🟢 垂直向上 | 🔵 纵深朝向 | 🟠 宽度朝向（点击返回贴图）'
      : '当前显示真实包装标签，点击开启多轴彩色朝向辅助线';
    rebuildOrientationAssist();
    if (isAssist && root.showToast) {
      root.showToast('🟢 绿色：垂直向上 | 🔵 蓝色：纵深方向 | 🟠 橙色：横向宽度', 'info', '🧭 朝向三色辅助已开启');
    }
  }

  // --- CoG 3D Indicator ---
  function updateCoGIndicatorMesh(cogData, usableDim) {
    const THREE = getTHREE();
    if (!THREE) return;
    const containerGroup = root.containerGroup;
    if (!containerGroup) return;

    if (cogIndicatorGroup) {
      containerGroup.remove(cogIndicatorGroup);
      cogIndicatorGroup = null;
    }
    if (!cogData) return;

    cogIndicatorGroup = new THREE.Group();
    const halfIntL = usableDim.length / 2;
    const startY = -usableDim.height / 2;
    const startZ = -usableDim.width / 2;

    const posX = halfIntL - parseFloat(cogData.x);
    const posY = startY + parseFloat(cogData.y);
    const posZ = startZ + parseFloat(cogData.z);

    const sphereGeo = new THREE.SphereGeometry(0.08, 20, 20);
    const sphereMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b });
    const sphereMesh = new THREE.Mesh(sphereGeo, sphereMat);
    sphereMesh.position.set(posX, posY, posZ);
    cogIndicatorGroup.add(sphereMesh);

    const crossMat = new THREE.LineBasicMaterial({ color: 0xf59e0b });
    const crossGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(posX - 0.20, posY, posZ), new THREE.Vector3(posX + 0.20, posY, posZ),
      new THREE.Vector3(posX, posY - 0.20, posZ), new THREE.Vector3(posX, posY + 0.20, posZ),
      new THREE.Vector3(posX, posY, posZ - 0.20), new THREE.Vector3(posX, posY + 0.20)
    ]);
    const crossLines = new THREE.LineSegments(crossGeo, crossMat);
    cogIndicatorGroup.add(crossLines);

    const dropMat = new THREE.LineDashedMaterial({ color: 0xf59e0b, dashSize: 0.04, gapSize: 0.03 });
    const dropGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(posX, posY, posZ),
      new THREE.Vector3(posX, startY + 0.015, posZ)
    ]);
    const dropLine = new THREE.Line(dropGeo, dropMat);
    dropLine.computeLineDistances();
    cogIndicatorGroup.add(dropLine);

    const ringGeo = new THREE.RingGeometry(0.10, 0.14, 32);
    const ringMat = new THREE.MeshBasicMaterial({ color: 0xf59e0b, side: THREE.DoubleSide, transparent: true, opacity: 0.75 });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.rotation.x = -Math.PI / 2;
    ringMesh.position.set(posX, startY + 0.02, posZ);
    cogIndicatorGroup.add(ringMesh);

    cogIndicatorGroup.visible = showCoGIndicator;
    containerGroup.add(cogIndicatorGroup);
  }

  function toggleCoGDisplay(show) {
    showCoGIndicator = show;
    document.getElementById('btn-cog-on')?.classList.toggle('active', show);
    document.getElementById('btn-cog-off')?.classList.toggle('active', !show);
    if (cogIndicatorGroup) {
      cogIndicatorGroup.visible = show;
    }
  }

  // --- Slicing Timeline & Visibility Engine ---
  function updateSlicingVisuals() {
    const stateManager = root.stateManager;
    const currentSpec = stateManager ? stateManager.currentSpec : (root.currentSpec || {});
    const usableDim = currentSpec.usable || { L: currentSpec.intL || 12.032, W: currentSpec.intW || 2.352, H: currentSpec.intH || 2.698 };
    const L = usableDim.L;
    const cutDepthFromDoor = (currentSliceCutPercent / 100) * L;
    const X_cut = Math.max(0, L - cutDepthFromDoor);

    const txtEl = document.getElementById('slice-depth-txt');
    const deepLabel = document.getElementById('slice-deep-label');
    if (deepLabel) deepLabel.textContent = `0.00m 📦 (最深内壁)`;

    if (currentSliceCutPercent <= 0.01) {
      if (txtEl) txtEl.textContent = `纵深位置: ${L.toFixed(2)}m / ${L.toFixed(2)}m (全部可见)`;
      if (slicingGroundMarkerMesh) slicingGroundMarkerMesh.visible = false;
    } else {
      let visibleCount = 0;
      let hiddenCount = 0;
      boxMeshes.forEach(b => {
        const maxX = b.userData.maxX ?? (b.userData.rawX + b.userData.rawW);
        if (maxX <= X_cut + 0.001) visibleCount++;
        else hiddenCount++;
      });
      if (txtEl) {
        txtEl.textContent = `切片截面: 距门 ${cutDepthFromDoor.toFixed(2)}m • 纵深 ${X_cut.toFixed(2)}m (已显 ${visibleCount}箱 / 隐 ${hiddenCount}箱)`;
      }
      if (slicingGroundMarkerMesh) {
        const halfIntL = usableDim.L / 2;
        const sceneX = -halfIntL + cutDepthFromDoor;
        slicingGroundMarkerMesh.position.x = sceneX;
        slicingGroundMarkerMesh.visible = true;
      }
    }
  }

  function onSlicingTimelineChange(valPercent) {
    currentSliceCutPercent = parseFloat(valPercent) || 0;
    updateSlicingVisuals();
    updateBoxVisibilityAndMaterials();
  }

  function resetSlicingTimeline() {
    currentSliceCutPercent = 0;
    const slider = document.getElementById('slice-depth-slider');
    if (slider) slider.value = 0;
    updateSlicingVisuals();
    updateBoxVisibilityAndMaterials();
  }

  function updateBoxVisibilityAndMaterials() {
    if (!boxMeshes || boxMeshes.length === 0) return;

    const hoveredSKU = root.stateManager ? root.stateManager.hoveredSKU : root.hoveredSKU;
    const selectedSKUs = root.stateManager ? root.stateManager.selectedSKUs : (root.selectedSKUs || new Set());
    const unselectedDisplayMode = root.unselectedDisplayMode || 'ghost';
    const activeManifest = root.stateManager ? root.stateManager.activeManifest : (root.activeManifest || []);

    const hasHover = hoveredSKU !== null && hoveredSKU !== undefined;
    const hasFilter = selectedSKUs.size > 0;

    const currentSpec = root.stateManager ? root.stateManager.currentSpec : (root.currentSpec || {});
    const usableDim = currentSpec.usable || { L: currentSpec.intL || 12.032, W: currentSpec.intW || 2.352, H: currentSpec.intH || 2.698 };
    const L = usableDim.L;
    const cutDepthFromDoor = (currentSliceCutPercent / 100) * L;
    const X_cut = Math.max(0, L - cutDepthFromDoor);
    const isSlicingActive = (currentSliceCutPercent > 0.01);

    activeManifest.forEach(skuItem => {
      const skuMats = skuMaterialRegistry.get(skuItem.sku);
      if (!skuMats) return;
      let isHighlighted = false;
      if (hasHover) {
        isHighlighted = (skuItem.sku === hoveredSKU);
      } else if (hasFilter) {
        isHighlighted = selectedSKUs.has(skuItem.sku);
      }
      const emissiveHex = isHighlighted ? 0x1e3a8a : 0x000000;
      skuMats.solidMats.forEach(m => {
        if (m.emissive) m.emissive.setHex(emissiveHex);
      });
    });

    boxMeshes.forEach(box => {
      const sku = box.userData.sku;
      let isVisible = true;
      let isSolid = true;

      if (isSlicingActive) {
        const boxMaxX = box.userData.maxX ?? (box.userData.rawX + box.userData.rawW);
        if (boxMaxX > X_cut + 0.001) isVisible = false;
      }

      if (isVisible) {
        if (hasHover) {
          if (sku === hoveredSKU) {
            isSolid = true;
            isVisible = true;
          } else {
            isSolid = false;
            isVisible = (unselectedDisplayMode === 'ghost');
          }
        } else if (hasFilter) {
          if (selectedSKUs.has(sku)) {
            isSolid = true;
            isVisible = true;
          } else {
            isSolid = false;
            isVisible = (unselectedDisplayMode === 'ghost');
          }
        } else {
          isSolid = true;
          isVisible = true;
        }
      }

      box.visible = isVisible;
      if (isVisible) {
        const targetMats = isSolid ? box.userData.skuMaterials.solidMats : box.userData.skuMaterials.ghostMats;
        if (box.material !== targetMats) box.material = targetMats;
        const isTargetSku = (hasHover && sku === hoveredSKU) || (hasFilter && selectedSKUs.has(sku));
        setMeshOutlineState(box, isTargetSku, false);
      } else {
        setMeshOutlineState(box, false, false);
      }
    });

    if (root.BLK007F78 && packageOrientationDisplayMode === root.BLK007F78.DisplayMode.ASSIST) {
      rebuildOrientationAssist();
    }
    if (root.isRaycastDirty !== undefined) root.isRaycastDirty = true;
  }

  // --- Apply Loading Results ---
  function applyBackendLoadingResult(loadingResult, usableDim, activeManifest, currentSpec) {
    if (!loadingResult || loadingResult.version !== 'BLK007C') return false;
    const THREE = getTHREE();
    initCaches();
    initOutlineResources();

    let containerGroup = root.containerGroup;
    let cargoGroup = root.cargoGroup;

    if (cargoGroup && containerGroup) containerGroup.remove(cargoGroup);
    cargoGroup = new THREE.Group();
    root.cargoGroup = cargoGroup;
    if (containerGroup) containerGroup.add(cargoGroup);
    boxMeshes = [];
    root.boxMeshes = boxMeshes;

    const cargoById = new Map(loadingResult.cargo.map(item => [item.id, item]));
    skuMaterialRegistry.clear();
    if (orientationMaterialCache) orientationMaterialCache.clear();

    activeManifest.forEach(skuItem => {
      const texs = getOrCreateFaceTextures(skuItem.color, skuItem.name, skuItem.sku);
      const solidMats = [texs.sideTex, texs.sideTex, texs.topTex, texs.bottomTex, texs.frontBackTex, texs.frontBackTex]
        .map(map => new THREE.MeshStandardMaterial({ color: skuItem.color, map, roughness: 0.48, metalness: 0.05 }));
      const ghostMats = [texs.sideTex, texs.sideTex, texs.topTex, texs.bottomTex, texs.frontBackTex, texs.frontBackTex]
        .map(map => new THREE.MeshStandardMaterial({ color: skuItem.color, map, transparent: true, opacity: 0.10, depthWrite: false }));
      skuMaterialRegistry.set(skuItem.sku, { solidMats, ghostMats });
    });

    if (root.BLK007D) {
      root.BLK007D.sceneObjects(loadingResult).forEach(object => {
        const cargo = cargoById.get(object.uuid);
        if (!cargo) throw new Error(`Scene object has no cargo record: ${object.uuid}`);
        const skuItem = activeManifest.find(item => item.sku === object.metadata.sku);
        const registry = skuMaterialRegistry.get(object.metadata.sku);
        const fallbackMats = Array.from({ length: 6 }, () => new THREE.MeshStandardMaterial({ color: object.material.color, transparent: object.material.opacity < 1, opacity: object.material.opacity }));

        const orientationName = root.BLK007F78 ? root.BLK007F78.normalizeOrientation(
          (cargo.rotation && cargo.rotation.orientation) || object.metadata.orientation
        ) : 'UPRIGHT_NORMAL';

        const geometry = orientationGeometryCache ? orientationGeometryCache.get(orientationName) : new THREE.BoxGeometry(1, 1, 1);
        const baseSolidMats = registry ? registry.solidMats : fallbackMats;
        const physicalMats = orientationMaterialCache ? orientationMaterialCache.get(object.metadata.sku, orientationName, baseSolidMats) : baseSolidMats;
        const mesh = new THREE.Mesh(geometry, physicalMats);

        mesh.scale.set(
          Math.max(0.001, object.scale[0] - 0.003),
          Math.max(0.001, object.scale[2] - 0.003),
          Math.max(0.001, object.scale[1] - 0.003)
        );
        mesh.name = object.uuid;
        mesh.position.set(
          usableDim.length / 2 - object.position[0],
          -usableDim.height / 2 + object.position[2],
          -usableDim.width / 2 + object.position[1]
        );
        mesh.rotation.set(object.rotation[0], object.rotation[2], object.rotation[1]);
        mesh.castShadow = true;

        const rawX = object.position[0] - object.scale[0] / 2;
        mesh.userData = {
          objectId: object.uuid,
          sku: cargo.sku,
          name: cargo.name,
          color: skuItem ? skuItem.color : object.material.color,
          weight: `${cargo.weight_kg} kg`,
          requirement: cargo.context,
          productDimensions: `${Math.round(cargo.productDimensions.length * 1000)} × ${Math.round(cargo.productDimensions.width * 1000)} × ${Math.round(cargo.productDimensions.height * 1000)} mm`,
          occupiedDimensions: `${Math.round(cargo.occupiedDimensions.width * 1000)} × ${Math.round(cargo.occupiedDimensions.depth * 1000)} × ${Math.round(cargo.occupiedDimensions.height * 1000)} mm`,
          position: `X:${object.position[0].toFixed(2)} Y:${object.position[1].toFixed(2)} Z:${object.position[2].toFixed(2)}`,
          loadingStep: cargo.loading ? cargo.loading.step : null,
          wall: cargo.loading ? cargo.loading.wall : null,
          layer: cargo.loading ? cargo.loading.layer : null,
          repairGroup: cargo.stability ? cargo.stability.group_id : null,
          originY: mesh.position.y,
          skuMaterials: registry || { solidMats: fallbackMats, ghostMats: fallbackMats },
          orientation: orientationName,
          productUpThree: root.BLK007F78 ? root.BLK007F78.getFaceMapping(orientationName).productUpThree : [0, 1, 0],
          isCargoBox: true,
          rawX, rawW: object.scale[0], rawY: object.position[2] - object.scale[2] / 2,
          rawH: object.scale[2], rawZ: object.position[1] - object.scale[1] / 2,
          rawD: object.scale[1], maxX: rawX + object.scale[0]
        };

        attachOutlineStrokeToMesh(mesh);
        cargoGroup.add(mesh);
        boxMeshes.push(mesh);
      });
    }

    rebuildOrientationAssist();

    const metrics = loadingResult.metrics || {};
    const utilization = Number(metrics.utilization_pct || 0);
    const totalWeightKg = Number(metrics.total_weight_kg || loadingResult.cargo.reduce((sum, item) => sum + Number(item.weight_kg || 0), 0));
    
    const kpiUtil = document.getElementById('kpi-util');
    const kpiVol = document.getElementById('kpi-vol');
    const kpiCount = document.getElementById('kpi-count');
    const kpiWeight = document.getElementById('kpi-weight');
    if (kpiUtil) kpiUtil.innerHTML = `${utilization.toFixed(2)}<span class="kpi-unit">%</span>`;
    if (kpiVol) kpiVol.innerHTML = `—<span class="kpi-unit">后端结果</span>`;
    if (kpiCount) kpiCount.innerHTML = `${loadingResult.cargo.length}<span class="kpi-unit">箱</span>`;
    if (kpiWeight) kpiWeight.innerHTML = `${(totalWeightKg / 1000).toFixed(2)}<span class="kpi-unit">T</span>`;

    const skuStats = {};
    activeManifest.forEach(item => {
      skuStats[item.sku] = {
        sku: item.sku,
        name: item.name || '',
        requirement: item.requirement || '',
        maxStackLayers: item.maxStackLayers,
        placed: 0,
        planned: item.quantity,
        unplaced: item.quantity,
        isFullyPlaced: false,
        isElastic: item.isElastic
      };
    });
    loadingResult.cargo.forEach(item => {
      if (!skuStats[item.sku]) {
        skuStats[item.sku] = {
          sku: item.sku,
          name: item.name || '',
          requirement: item.context || '',
          maxStackLayers: null,
          placed: 0,
          planned: 0,
          unplaced: 0,
          isFullyPlaced: true,
          isElastic: false
        };
      }
      skuStats[item.sku].placed += 1;
      skuStats[item.sku].unplaced = Math.max(0, skuStats[item.sku].planned - skuStats[item.sku].placed);
      skuStats[item.sku].isFullyPlaced = (skuStats[item.sku].unplaced === 0);
    });

    const activePackingResult = {
      source: 'BLK007C_LOADING_RESULT', loadingResult, skuStats,
      totalCount: loadingResult.cargo.length,
      totalUnplacedCount: Object.values(skuStats).reduce((sum, stat) => sum + stat.unplaced, 0),
      utilization: utilization.toFixed(2), totalWeightTons: (totalWeightKg / 1000).toFixed(2), elapsedMs: 0
    };
    root.activePackingResult = activePackingResult;
    root.activeLoadingResult = loadingResult;
    root.activeLoadingJobId = loadingResult.id;
    if (root.stateManager) root.stateManager.activePackingResult = activePackingResult;

    return true;
  }

  function clearVisualization() {
    let cargoGroup = root.cargoGroup;
    if (cargoGroup) cargoGroup.clear();
    boxMeshes = [];
    root.boxMeshes = boxMeshes;
    root.activePackingResult = null;
    root.activeLoadingResult = null;
    root.activeLoadingJobId = null;
    if (root.stateManager) root.stateManager.activePackingResult = null;

    ['kpi-util', 'kpi-vol', 'kpi-count', 'kpi-weight'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '—';
    });
  }

  return {
    convertCanonicalToThree,
    getOrCreateFaceTextures,
    attachOutlineStrokeToMesh,
    setMeshOutlineState,
    updateCoGIndicatorMesh,
    toggleCoGDisplay,
    rebuildOrientationAssist,
    clearOrientationAssist,
    togglePackageOrientationMode,
    onSlicingTimelineChange,
    resetSlicingTimeline,
    updateSlicingVisuals,
    updateBoxVisibilityAndMaterials,
    applyBackendLoadingResult,
    clearVisualization,
    get boxMeshes() { return boxMeshes; },
    set boxMeshes(m) { boxMeshes = m; }
  };
});
