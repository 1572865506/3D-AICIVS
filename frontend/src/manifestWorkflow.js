(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ManifestWorkflow = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const CalculationStatus = Object.freeze({
    EMPTY: 'EMPTY', DRAFT: 'DRAFT', DIRTY: 'DIRTY', RUNNING: 'RUNNING',
    READY: 'READY', FAILED: 'FAILED'
  });

  function deleteSelected(manifest, selectedIds) {
    const selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
    return (manifest || []).filter(item => !selected.has(item.sku));
  }

  function validateManifest(manifest) {
    const errors = [];
    const seen = new Set();
    (manifest || []).forEach((item, index) => {
      const path = `SKU[${index}]`;
      const sku = String(item.sku || '').trim();
      if (!sku) errors.push(`${path}.sku 不能为空`);
      else if (seen.has(sku)) errors.push(`${path}.sku ${sku} 重复`);
      seen.add(sku);
      ['w', 'd', 'h', 'weight', 'quantity'].forEach(key => {
        if (!(Number(item[key]) > 0)) errors.push(`${sku || path}.${key} 必须大于0`);
      });
      if (item.minimumQuantity != null && Number(item.minimumQuantity) > Number(item.quantity)) {
        errors.push(`${sku || path}.minimumQuantity 不能超过计划数量`);
      }
      const profile = item.cargoProfile || {};
      const stability = profile.stabilityPolicy || {};
      const support = stability.minSupportRatio ?? item.minSupportRatio;
      if (support != null && (Number(support) < 0 || Number(support) > 1)) {
        errors.push(`${sku || path}.minSupportRatio 必须在0到1之间`);
      }
      const span = stability.maxUnsupportedSpan ?? item.maxUnsupportedSpanM;
      if (span != null && Number(span) < 0) errors.push(`${sku || path}.maxUnsupportedSpan 不能为负`);
      const handling = profile.handlingPolicy || {};
      const orientation = profile.orientationPolicy || {};
      if (handling.keepUpright === true && (orientation.allowFlat === true || orientation.allowSide === true)) {
        errors.push(`${sku || path} 保持直立与开放平放/侧卧冲突`);
      }
    });
    return { valid: errors.length === 0, errors };
  }

  function doorPolicyStatus(item) {
    const profile = item && item.cargoProfile;
    if (profile) {
      const placement = profile.placementPolicy || {};
      const zone = profile.zonePolicy || {};
      const roles = (placement.packingRoles || []).map(value => String(value).toUpperCase());
      const zones = [...(zone.required || []), ...(zone.preferred || [])]
        .map(value => String(value).toUpperCase());
      const declared = roles.includes('DOOR_SEAL') || zones.includes('DOOR');
      return {
        declared,
        source: 'CARGO_PROFILE',
        conflict: !declared && /封柜门|封门|门区|door(?:_zone)?|door\s*seal/i.test(String(item.requirement || ''))
      };
    }
    return {
      declared: Boolean(item && (item.allowDoorZone === true || item.doorAllowed === true ||
        item.door_allowed === true || /封柜门|封门|门区|door(?:_zone)?|door\s*seal/i.test(String(item.requirement || '')))),
      source: 'LEGACY_EXPLICIT_RULE',
      conflict: false
    };
  }

  // Cheap request preflight only. The backend remains authoritative for exact
  // door-wall coverage, orientation and stability validation.
  function validateDoorWallAdmission(manifest, container) {
    const width = Number(container && (container.intW ?? container.width ?? container.W ??
      (container.usable && container.usable.W)));
    const height = Number(container && (container.intH ?? container.height ?? container.H ??
      (container.usable && container.usable.H)));
    const candidates = [];
    const conflicts = [];
    (manifest || []).forEach(item => {
      const policy = doorPolicyStatus(item);
      if (policy.conflict) conflicts.push(item.sku);
      if (!policy.declared) return;
      const faceWidth = Math.max(Number(item.w) || 0, Number(item.d) || 0);
      const wallFormable = Number(item.quantity) > 0 && Number(item.h) > 0 &&
        (!Number.isFinite(width) || faceWidth <= width + 1e-9) &&
        (!Number.isFinite(height) || Number(item.h) <= height + 1e-9) &&
        Number(item.weight) <= 80;
      candidates.push({ sku: item.sku, source: policy.source, wallFormable });
    });
    const wallFormable = candidates.filter(item => item.wallFormable);
    let code = null;
    if (conflicts.length) code = 'DOOR_PROFILE_CONFLICT';
    const messages = {
      DOOR_PROFILE_CONFLICT: `SKU ${conflicts.join('、')} 的“封柜门”文字与结构化 CargoProfile 冲突，请打开 SKU 参数并重新保存门区规则`,
    };
    return {
      valid: code === null,
      code,
      message: code ? messages[code] : '',
      hasExplicitDoorCargo: candidates.length > 0,
      candidates,
      wallFormableCandidates: wallFormable,
      conflicts
    };
  }

  function buildCargoProfile(item, values) {
    const source = 'USER_DEFINED';
    const orientationMode = values.allowedOrientation || item.allowedOrientation || 'upright';
    const allowFlat = orientationMode === 'allow_flat' || orientationMode === 'any';
    const allowSide = orientationMode === 'allow_side' || orientationMode === 'any';
    const topState = String(values.topFillState || 'AUTO').toUpperCase();
    const orientationRules = [{
      orientation: 'UPRIGHT', allowedRegions: ['MAIN_BODY', 'TOP_FILL', 'DOOR_ZONE'], condition: 'ALWAYS'
    }];
    if (allowFlat) orientationRules.push({
      orientation: 'FLAT', allowedRegions: ['TOP_FILL'],
      maxTopFillLayers: Number(values.topFillMaxLayers) || 1,
      minBaseHeight: Number(values.topFillMinBaseHeight) || 0,
      minSupportRatio: Number(values.minSupportRatio) || 0.70,
      condition: 'UPRIGHT_DOES_NOT_FIT'
    });
    if (allowSide) orientationRules.push({
      orientation: 'SIDE', allowedRegions: ['TOP_FILL', 'DOOR_ZONE'], condition: 'EXPLICIT_PROFILE'
    });
    return {
      geometryPolicy: { source, clearanceM: Number(values.clearanceM) || 0 },
      orientationPolicy: {
        source, allowFlat, allowSide, maxFlatLayers: Number(values.topFillMaxLayers) || 1,
        rules: orientationRules
      },
      placementPolicy: {
        source, loadPriority: Number(values.loadPriority) || 0,
        reductionAllowed: Boolean(values.reductionAllowed),
        minimumQuantity: Number(values.minimumQuantity) || 0,
        packingRoles: values.packingRoles || ['MAIN_WALL']
      },
      stackPolicy: {
        source,
        maxStackLayers: Number(values.maxStackLayers) || null,
        allowStackingOnTop: values.allowStackingOnTop !== false,
        mustBeOnFloor: Boolean(values.mustBeOnFloor),
        stackOnSelf: values.stackOnSelf !== false
      },
      compressionPolicy: {
        source,
        maxTopLoad: Number(values.maxBearingKg) || null,
        maxPressureKgM2: Number(values.maxPressureKgM2) || null
      },
      stabilityPolicy: {
        source, antiTipRequired: values.antiTipRequired !== false,
        minSupportRatio: Number(values.minSupportRatio) || 0.70,
        maxUnsupportedSpan: Number(values.maxUnsupportedSpanM) || 0.10,
        groupStabilityRequired: true, wallStabilityRequired: true
      },
      topFillPolicy: {
        source, state: topState, enabled: topState === 'ALLOW',
        allowedOrientations: ['UPRIGHT'],
        conditionalOrientations: allowFlat ? ['FLAT'] : [],
        maxLayers: Number(values.topFillMaxLayers) || 0,
        minBaseHeight: Number(values.topFillMinBaseHeight) || 0,
        minSupportRatio: Number(values.minSupportRatio) || 0.70
      },
      zonePolicy: {
        source,
        preferred: values.preferredZones || [], required: values.requiredZones || [], forbidden: values.forbiddenZones || []
      },
      handlingPolicy: {
        source, keepUpright: values.keepUpright !== false,
        fragile: Boolean(values.fragile), specialInstructions: values.specialInstructions || []
      }
    };
  }

  return { CalculationStatus, deleteSelected, validateManifest, validateDoorWallAdmission,
    doorPolicyStatus, buildCargoProfile };
});
