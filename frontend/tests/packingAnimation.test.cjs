const test = require('node:test');
const assert = require('node:assert/strict');
const animation = require('../src/packingAnimation.js');

function makeFrames(count, perFrame = 1) {
  const frames = [];
  for (let i = 0; i < count; i += perFrame) {
    const objects = [];
    const movements = [];
    for (let j = 0; j < perFrame; j++) {
      const id = `obj_${i + j}`;
      objects.push(id);
      movements.push({
        object: id,
        from: [12.0, 0.4 + j * 0.2, 0.5],
        to: [0.4 + (i + j) * 0.005, 0.4 + j * 0.2, 0.5],
      });
    }
    frames.push({
      step: frames.length + 1,
      objects,
      from: movements[0].from,
      to: movements[0].to,
      movements,
      duration: 2.0,
    });
  }
  return frames;
}

test('1615 箱时间轴落在 18–25 秒，且每个对象只调度一次', () => {
  const frames = makeFrames(1615);
  const plan = animation.buildPackingAnimationPlan(frames);
  assert.equal(plan.items.length, 1615);
  assert.equal(new Set(plan.items.map(item => item.object)).size, 1615);
  assert.ok(plan.totalDuration >= 18 && plan.totalDuration <= 25,
    `total=${plan.totalDuration}`);
  assert.ok(plan.targetDuration >= 18 && plan.targetDuration <= 25);
  assert.equal(plan.waves.length, Math.ceil(1615 / plan.batchSize));

  let prev = -Infinity;
  for (const item of plan.items) {
    assert.ok(item.start >= prev - 1e-9, 'item start must be monotonic');
    assert.ok(item.end >= item.start);
    prev = item.start;
  }
  const lastEnd = Math.max(...plan.items.map(item => item.end));
  assert.ok(lastEnd <= plan.totalDuration + 1e-6);
});

test('小单不会拖成几分钟，且批内错峰', () => {
  const plan = animation.buildPackingAnimationPlan(makeFrames(10));
  assert.equal(plan.items.length, 10);
  assert.ok(plan.totalDuration < 10);
  assert.equal(plan.batchSize, 4);
  assert.ok(plan.waves[0].items[1].start > plan.waves[0].items[0].start);
});

test('同一帧多 movement 全部保留，空帧被跳过', () => {
  const frames = [
    { step: 1, objects: [], from: [1, 0, 0], to: [0, 0, 0], movements: [], duration: 2 },
    ...makeFrames(5, 2),
  ];
  const plan = animation.buildPackingAnimationPlan(frames);
  assert.equal(plan.items.length, 6);
  assert.equal(plan.waves[0].items.length, 4);
});

test('没有 movements 时回退到 frame.objects/from/to', () => {
  const plan = animation.buildPackingAnimationPlan([
    { step: 1, objects: ['a', 'b'], from: [12, 1, 2], to: [1, 1, 2], duration: 2 },
  ]);
  assert.equal(plan.items.length, 2);
  assert.deepEqual(plan.items[0].from, [12, 1, 2]);
  assert.deepEqual(plan.items[0].to, [1, 1, 2]);
});

test('非法对象/坐标帧被过滤，完全空输入返回空计划', () => {
  const plan = animation.buildPackingAnimationPlan([
    { step: 1, movements: [{ object: 'ok', from: [1, 2, 3], to: [0, 2, 3] }] },
    { step: 2, movements: [{ object: null, from: [1, 2, 3], to: [0, 2, 3] }] },
    { step: 3, movements: [{ object: 'bad', from: null, to: [0, 0, 0] }] },
  ]);
  assert.equal(plan.items.length, 1);
  assert.equal(animation.buildPackingAnimationPlan([]).items.length, 0);
  assert.equal(animation.buildPackingAnimationPlan(null).totalDuration, 0);
});

test('itemProgressAt / waveIndexAt / countStarted 边界正确', () => {
  const plan = animation.buildPackingAnimationPlan(makeFrames(30));
  const item = plan.items[0];
  assert.equal(animation.itemProgressAt(item, item.start - 0.01).visible, false);
  assert.equal(animation.itemProgressAt(item, item.start).visible, true);
  assert.equal(animation.itemProgressAt(item, item.end + 0.01).completed, true);
  assert.equal(animation.waveIndexAt(plan.waves, -1), -1);
  assert.ok(animation.waveIndexAt(plan.waves, plan.waves[1].start) >= 1);
  assert.ok(animation.countStarted(plan.items, plan.items[5].start) >= 6);
});

test('目标时长随箱数单调增加但不超过 25 秒', () => {
  let prev = 0;
  for (const n of [1, 10, 100, 500, 1615, 5000]) {
    const duration = animation.computeTargetDuration(n);
    assert.ok(duration >= prev);
    assert.ok(duration <= 25);
    prev = duration;
  }
});
