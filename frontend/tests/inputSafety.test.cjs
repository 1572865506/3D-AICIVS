const {test}=require('node:test');
const assert=require('node:assert/strict');
const safety=require('../src/inputSafety.js');
test('数值与文本单元格按同一显式单位转换',()=>{
  for(const unit of ['m','cm','mm']) assert.equal(safety.dimension(500,unit),safety.dimension('500',unit));
  assert.equal(safety.dimension(500,'mm'),.5);
});
test('非法尺寸不得补默认值',()=>{
  for(const value of [null,'',-1,0,NaN,Infinity,'500mm']) assert.throws(()=>safety.dimension(value));
});
test('导入单位与文本转义',()=>{
  assert.equal(safety.unitFromHeader('长(mm)'),'mm');
  assert.equal(safety.unitFromHeader('width(cm)'),'cm');
  assert.equal(safety.escapeHtml('<img src=x onerror="x()">'), '&lt;img src=x onerror=&quot;x()&quot;&gt;');
  assert.throws(()=>safety.unitFromHeader('length(inch)'));
});
