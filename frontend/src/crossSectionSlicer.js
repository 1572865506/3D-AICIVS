/**
 * crossSectionSlicer.js
 * 3D-AICIVS Multi-Axis Cross-Section Slicing & X-Ray Perspective Engine
 * 
 * Responsibilities:
 * - 3-Axis Interactive Slicing: X (Longitudinal Depth), Y (Transverse Width), Z (Vertical Height)
 * - Slicing Modes:
 *     1. 'CLIP': Completely cuts and hides cartons outside the section plane.
 *     2. 'XRAY': Sets outer occluding cartons to ghost transparency (15% opacity), revealing inner honeycomb pockets.
 *     3. 'CAVITY': Highlights internal gaps and low-support pockets.
 * - Visual Cutting Plane Guide (dynamic semi-transparent 3D plane aligned in Three.js container space)
 * - Robust fallback object discovery: searches window.boxMeshes, visualizationCore, and traverses THREE.Scene directly.
 */

(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.crossSectionSlicer = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  function getTHREE() { return root.THREE; }
  function getScene() { return root.sceneManager ? root.sceneManager.getScene() : (root.scene || null); }

  // Slicer State
  const state = {
    enabled: false,
    mode: 'CLIP', // 'CLIP' | 'XRAY' | 'CAVITY'
    axis: 'X',    // 'X' | 'Y' | 'Z' | 'ALL'
    cutX: 100,    // 0 - 100% (100% = fully visible, 0% = cut to rear wall)
    cutY: 100,
    cutZ: 100,
    showPlaneHelper: true,
  };

  let cuttingPlaneMesh = null;

  function initCuttingPlaneHelper() {
    const THREE = getTHREE();
    const scene = getScene();
    if (!THREE || !scene) return;
    if (cuttingPlaneMesh) {
      if (!cuttingPlaneMesh.parent && scene) scene.add(cuttingPlaneMesh);
      return;
    }

    const planeGeo = new THREE.PlaneGeometry(1, 1);
    const planeMat = new THREE.MeshBasicMaterial({
      color: 0x00f0ff,
      transparent: true,
      opacity: 0.28,
      side: THREE.DoubleSide,
      depthWrite: false,
    });

    cuttingPlaneMesh = new THREE.Mesh(planeGeo, planeMat);
    cuttingPlaneMesh.name = 'crossSectionCuttingPlane';
    cuttingPlaneMesh.visible = false;
    scene.add(cuttingPlaneMesh);
  }

  function getContainerDimensions() {
    const spec = root.stateManager ? root.stateManager.currentSpec : (root.currentSpec || {});
    const usable = spec.usable || { L: spec.intL || spec.length || 12.032, W: spec.intW || spec.width || 2.352, H: spec.intH || spec.height || 2.698 };
    return {
      L: Number(usable.L || usable.length || 12.032),
      W: Number(usable.W || usable.width || 2.352),
      H: Number(usable.H || usable.height || 2.698),
    };
  }

  /**
   * Universal discovery of all cargo box meshes currently in the 3D scene.
   */
  function getAllBoxMeshes() {
    if (Array.isArray(root.boxMeshes) && root.boxMeshes.length > 0) {
      return root.boxMeshes;
    }
    if (root.visualizationCore && Array.isArray(root.visualizationCore.boxMeshes) && root.visualizationCore.boxMeshes.length > 0) {
      return root.visualizationCore.boxMeshes;
    }
    const scene = getScene();
    if (scene) {
      const found = [];
      scene.traverse(obj => {
        if (obj.isMesh && obj.userData && (obj.userData.isCargoBox || obj.userData.sku || (obj.name && (obj.name.startsWith('p_') || obj.name.startsWith('inst_'))))) {
          found.push(obj);
        }
      });
      return found;
    }
    return [];
  }

  /**
   * Applies the cross-section slicing logic across all box meshes in scene.
   */
  function applySlicing() {
    const boxMeshes = getAllBoxMeshes();
    const { L, W, H } = getContainerDimensions();
    const halfL = L / 2;
    const startY = -H / 2;
    const startZ = -W / 2;

    const limitX = (state.cutX / 100.0) * L;
    const limitY = (state.cutY / 100.0) * W;
    const limitZ = (state.cutZ / 100.0) * H;

    const isCutActive = state.enabled && (state.cutX < 99.9 || state.cutY < 99.9 || state.cutZ < 99.9);

    boxMeshes.forEach(box => {
      const uData = box.userData || {};

      // 1. Calculate container canonical coordinates [x in 0..L, y in 0..W, z in 0..H]
      let cX, cY, cZ, cDx, cDy, cDz;

      if (uData.rawX !== undefined && uData.rawW !== undefined) {
        cX = Number(uData.rawX);
        cDx = Number(uData.rawW);
        // In legacy system, rawY was vertical height (Z) and rawZ was lateral width (Y)
        if (uData.rawZ !== undefined && uData.rawD !== undefined) {
          cY = Number(uData.rawZ);
          cDy = Number(uData.rawD);
        } else {
          cY = box.position.z - startZ - (box.scale.z / 2);
          cDy = box.scale.z;
        }
        if (uData.rawY !== undefined && uData.rawH !== undefined) {
          cZ = Number(uData.rawY);
          cDz = Number(uData.rawH);
        } else {
          cZ = box.position.y - startY - (box.scale.y / 2);
          cDz = box.scale.y;
        }
      } else {
        // Direct Three.js position inverse mapping
        cDx = Math.max(0.05, box.scale.x);
        cDy = Math.max(0.05, box.scale.z);
        cDz = Math.max(0.05, box.scale.y);

        cX = halfL - box.position.x - (cDx / 2);
        cY = box.position.z - startZ - (cDy / 2);
        cZ = box.position.y - startY - (cDz / 2);
      }

      const maxX = cX + cDx;
      const maxY = cY + cDy;
      const maxZ = cZ + cDz;

      let isOutsideSection = false;

      if (isCutActive) {
        if ((state.axis === 'X' || state.axis === 'ALL') && maxX > limitX + 0.005) {
          isOutsideSection = true;
        }
        if ((state.axis === 'Y' || state.axis === 'ALL') && maxY > limitY + 0.005) {
          isOutsideSection = true;
        }
        if ((state.axis === 'Z' || state.axis === 'ALL') && maxZ > limitZ + 0.005) {
          isOutsideSection = true;
        }
      }

      // Cache original material once
      if (!uData._origMaterial) {
        uData._origMaterial = box.material;
      }

      if (!isCutActive) {
        // Restore normal state
        box.visible = true;
        if (uData._origMaterial) {
          box.material = uData._origMaterial;
        }
      } else if (state.mode === 'CLIP') {
        // Complete physical section cut
        box.visible = !isOutsideSection;
        if (box.visible && uData._origMaterial) {
          box.material = uData._origMaterial;
        }
      } else if (state.mode === 'XRAY') {
        // Ghost X-Ray mode
        box.visible = true;
        if (isOutsideSection) {
          if (!uData._ghostMaterial) {
            if (Array.isArray(uData._origMaterial)) {
              uData._ghostMaterial = uData._origMaterial.map(m => {
                const gm = m.clone();
                gm.transparent = true;
                gm.opacity = 0.15;
                gm.depthWrite = false;
                return gm;
              });
            } else if (uData._origMaterial && uData._origMaterial.clone) {
              const gm = uData._origMaterial.clone();
              gm.transparent = true;
              gm.opacity = 0.15;
              gm.depthWrite = false;
              uData._ghostMaterial = gm;
            }
          }
          if (uData._ghostMaterial) box.material = uData._ghostMaterial;
        } else {
          if (uData._origMaterial) box.material = uData._origMaterial;
        }
      } else if (state.mode === 'CAVITY') {
        // Cavity perspective
        box.visible = !isOutsideSection;
        if (box.visible && uData._origMaterial) {
          box.material = uData._origMaterial;
        }
      }
    });

    updateCuttingPlaneHelper(L, W, H, limitX, limitY, limitZ, isCutActive);

    // Trigger immediate render
    if (root.renderer && root.scene && root.camera) {
      root.renderer.render(root.scene, root.camera);
    }
  }

  function updateCuttingPlaneHelper(L, W, H, limitX, limitY, limitZ, isCutActive) {
    initCuttingPlaneHelper();
    if (!cuttingPlaneMesh) return;

    if (!isCutActive || !state.showPlaneHelper) {
      cuttingPlaneMesh.visible = false;
      return;
    }

    cuttingPlaneMesh.visible = true;
    const halfL = L / 2;
    const startY = -H / 2;
    const startZ = -W / 2;

    // Align cutting plane with container Three.js space
    if (state.axis === 'X') {
      cuttingPlaneMesh.scale.set(W, H, 1);
      cuttingPlaneMesh.position.set(halfL - limitX, 0, 0);
      cuttingPlaneMesh.rotation.set(0, Math.PI / 2, 0);
    } else if (state.axis === 'Y') {
      cuttingPlaneMesh.scale.set(L, H, 1);
      cuttingPlaneMesh.position.set(0, 0, startZ + limitY);
      cuttingPlaneMesh.rotation.set(0, 0, 0);
    } else if (state.axis === 'Z') {
      cuttingPlaneMesh.scale.set(L, W, 1);
      cuttingPlaneMesh.position.set(0, startY + limitZ, 0);
      cuttingPlaneMesh.rotation.set(Math.PI / 2, 0, 0);
    } else {
      cuttingPlaneMesh.scale.set(W, H, 1);
      cuttingPlaneMesh.position.set(halfL - limitX, 0, 0);
      cuttingPlaneMesh.rotation.set(0, Math.PI / 2, 0);
    }
  }

  // Public API
  return {
    getState: () => ({ ...state }),

    setEnabled: (enabled) => {
      state.enabled = Boolean(enabled);
      applySlicing();
    },

    setMode: (mode) => {
      if (['CLIP', 'XRAY', 'CAVITY'].includes(mode)) {
        state.mode = mode;
        state.enabled = true;
        applySlicing();
      }
    },

    setAxis: (axis) => {
      if (['X', 'Y', 'Z', 'ALL'].includes(axis)) {
        state.axis = axis;
        state.enabled = true;
        applySlicing();
      }
    },

    setCutX: (val) => {
      state.cutX = Math.max(0, Math.min(100, Number(val)));
      state.enabled = true;
      applySlicing();
    },

    setCutY: (val) => {
      state.cutY = Math.max(0, Math.min(100, Number(val)));
      state.enabled = true;
      applySlicing();
    },

    setCutZ: (val) => {
      state.cutZ = Math.max(0, Math.min(100, Number(val)));
      state.enabled = true;
      applySlicing();
    },

    reset: () => {
      state.enabled = false;
      state.cutX = 100;
      state.cutY = 100;
      state.cutZ = 100;
      state.axis = 'X';
      state.mode = 'CLIP';
      applySlicing();
    },

    apply: applySlicing,
  };
});
