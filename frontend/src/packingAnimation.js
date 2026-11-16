/**
 * 演示装柜时间轴（纯函数，不依赖 Three.js / DOM）。
 *
 * 背景：生产 LoadingResult.animation 是“一箱一帧、固定 2 秒”，直接播放
 * 1615 箱需要约 54 分钟。本模块把原始帧重新编排为“连续批次”：
 * - 保留每个 movement 的原始顺序；
 * - 每批 4~12 箱，批内 18ms 错峰，批间重叠；
 * - 按箱数反解总时长（1600 箱约 22 秒）；
 * - 每一波给出 start/end/centerCanonicalX，供镜头跟随和落点提示使用。
 *
 * 被谁调用：index.html 的演示装柜控制器；frontend/tests/packingAnimation.test.cjs。
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PackingAnimation = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DEFAULTS = {
    minDuration: 2.5,
    maxDuration: 25,
    perItemDuration: 0.5,
    smallOrderPerItemDuration: 0.7,
    stagger: 0.018,
    leadIn: 0.45,
    minWaveGap: 0.04,
    minBatch: 4,
    maxBatch: 12,
  };

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function isPoint(value) {
    return Array.isArray(value) && value.length >= 3 &&
      Number.isFinite(Number(value[0])) &&
      Number.isFinite(Number(value[1])) &&
      Number.isFinite(Number(value[2]));
  }

  function computeTargetDuration(itemCount, options) {
    const opts = Object.assign({}, DEFAULTS, options || {});
    const n = Math.max(0, Number(itemCount) || 0);
    return clamp(2 + Math.sqrt(n) * 0.5, opts.minDuration, opts.maxDuration);
  }

  function easeOutCubic(t) {
    const p = clamp(t, 0, 1);
    return 1 - Math.pow(1 - p, 3);
  }

  function flattenFrames(frames) {
    const items = [];
    (Array.isArray(frames) ? frames : []).forEach((frame, frameIndex) => {
      if (!frame || typeof frame !== 'object') return;
      let movements = Array.isArray(frame.movements) ? frame.movements : [];
      if (!movements.length && Array.isArray(frame.objects)) {
        movements = frame.objects.map(object => ({
          object,
          from: frame.from,
          to: frame.to,
        }));
      }
      movements.forEach((movement, moveIndex) => {
        if (!movement || typeof movement.object !== 'string') return;
        if (!isPoint(movement.from) || !isPoint(movement.to)) return;
        items.push({
          object: movement.object,
          from: movement.from.slice(0, 3).map(Number),
          to: movement.to.slice(0, 3).map(Number),
          step: frame.step,
          frameIndex,
          moveIndex,
        });
      });
    });
    return items;
  }

  function buildWaves(items, batchSize) {
    const waves = [];
    const size = Math.max(1, Number(batchSize) || 1);
    for (let i = 0; i < items.length; i += size) {
      waves.push({ index: waves.length, items: items.slice(i, i + size) });
    }
    return waves;
  }

  function buildPackingAnimationPlan(frames, options) {
    const opts = Object.assign({}, DEFAULTS, options || {});
    const items = flattenFrames(frames);
    const n = items.length;
    if (!n) {
      return {
        items: [],
        waves: [],
        totalDuration: 0,
        targetDuration: 0,
        batchSize: 0,
        leadIn: opts.leadIn,
        perItemDuration: 0,
        stagger: opts.stagger,
        waveGap: 0,
      };
    }

    const targetDuration = computeTargetDuration(n, opts);
    // Keep each wave small enough that item start times stay monotonic even at
    // the 20–25s target. A 4-box wave plus 18ms stagger gives a continuous
    // stream without reordering the original loading sequence.
    const batchSize = clamp(Math.ceil(n / 500), opts.minBatch, opts.maxBatch);
    const perItemDuration = n < 20
      ? opts.smallOrderPerItemDuration
      : opts.perItemDuration;
    const waves = buildWaves(items, batchSize);
    const spread = Math.max(0, batchSize - 1) * opts.stagger;
    const waveGap = waves.length <= 1
      ? 0
      : Math.max(
        // Never start wave N+1 before the last item of wave N has started;
        // otherwise batch overlap would visually reorder loading.
        Math.max(opts.minWaveGap, spread),
        (targetDuration - opts.leadIn - perItemDuration - spread) /
          Math.max(1, waves.length - 1)
      );

    let lastEnd = opts.leadIn;
    waves.forEach((wave, waveIndex) => {
      wave.start = opts.leadIn + waveIndex * waveGap;
      wave.items.forEach((item, itemIndex) => {
        item.start = wave.start + itemIndex * opts.stagger;
        item.duration = perItemDuration;
        item.end = item.start + perItemDuration;
      });
      wave.end = wave.items.length
        ? wave.items[wave.items.length - 1].end
        : wave.start;
      wave.centerCanonicalX = wave.items.length
        ? wave.items.reduce((sum, item) => sum + Number(item.to[0] || 0), 0) /
          wave.items.length
        : 0;
      lastEnd = Math.max(lastEnd, wave.end);
    });

    return {
      items,
      waves,
      totalDuration: Math.max(0.001, lastEnd),
      targetDuration,
      batchSize,
      leadIn: opts.leadIn,
      perItemDuration,
      stagger: opts.stagger,
      waveGap,
    };
  }

  function itemProgressAt(item, time) {
    if (!item) return { visible: false, progress: 0, completed: false };
    const elapsed = Number(time) - Number(item.start);
    if (!Number.isFinite(elapsed) || elapsed < 0) {
      return { visible: false, progress: 0, completed: false };
    }
    const raw = clamp(elapsed / Math.max(1e-6, item.duration), 0, 1);
    return {
      visible: true,
      progress: easeOutCubic(raw),
      rawProgress: raw,
      completed: raw >= 1,
    };
  }

  function waveIndexAt(waves, time) {
    if (!Array.isArray(waves) || !waves.length) return -1;
    let current = -1;
    for (let i = 0; i < waves.length; i++) {
      if (Number(time) >= waves[i].start) current = i;
      else break;
    }
    return current;
  }

  function countStarted(items, time) {
    if (!Array.isArray(items)) return 0;
    let count = 0;
    for (let i = 0; i < items.length; i++) {
      if (Number(time) >= items[i].start) count += 1;
      else break;
    }
    return count;
  }

  return {
    DEFAULTS,
    clamp,
    computeTargetDuration,
    easeOutCubic,
    flattenFrames,
    buildWaves,
    buildPackingAnimationPlan,
    itemProgressAt,
    waveIndexAt,
    countStarted,
  };
});
