
(function(){
'use strict';

/* =========================================================
   小笑肖 · 在线生活工作台
   数据层：资料库云端数据表（双向实时同步，无任何本地缓存）
   ========================================================= */

/* 七张云端数据表的 ID（硬编码常量，页面即绑定）
   每张表独立声明 DATABASE_ID，SDK 调用处直接引用该常量。 */
var DATABASE_ID = 'tHLWn2tjAvknVD3h5lyWG5';   /* 收支记录表 */
var DATABASE_ID_HABIT = 'BxxY8CTvCuWpMWgHJJGq9S';   /* 习惯打卡表 */
var DATABASE_ID_PLAN = 'cPZx8ssc03WAmKOwFhBcPx';   /* 日程表 */
var DATABASE_ID_FITNESS = 'JNiZJHR3QXKBMNrmHc0nIj';   /* 身体数据记录表 */
var DATABASE_ID_SHOPPING = 'B2a4VCyYGokQUAqXRhAKVv';   /* 采购清单表 */
var DATABASE_ID_MEDIA = 'ukf8VPIPQtBQN71qyrtu6x';   /* 书影音收藏表 */
var DATABASE_ID_SUMMARY = 'HEEB4feB120kc8nx8iSTxW';   /* 今日概览参数表 */
var DB = {
  money:    DATABASE_ID,
  habit:    DATABASE_ID_HABIT,
  plan:     DATABASE_ID_PLAN,
  fitness:  DATABASE_ID_FITNESS,
  shopping: DATABASE_ID_SHOPPING,
  media:    DATABASE_ID_MEDIA,
  summary:  DATABASE_ID_SUMMARY
};

var META = {
  money:    { title:'收支记录表',   fields:{date:'日期',flow:'收支方向',cat:'分类',amount:'金额',note:'备注'} },
  habit:    { title:'习惯打卡表',   fields:{date:'日期',name:'习惯',value:'数值',mode:'打卡方式',target:'目标值',unit:'单位'} },
  plan:     { title:'日程表',       fields:{date:'日期',title:'内容',list:'类型',status:'状态',start:'开始时间',end:'结束时间',pri:'优先级',done:'完成'} },
  fitness:  { title:'身体数据记录表',fields:{date:'日期',weight:'体重',fat:'体脂率',note:'备注'} },
  shopping: { title:'采购清单表',   fields:{name:'物品名称',qty:'数量',price:'预估价格',bought:'是否已买',cat:'分类',note:'备注'} },
  media:    { title:'书影音收藏表', fields:{title:'标题',type:'类型',status:'状态',rating:'评分',review:'短评',cover:'封面',doneDate:'完成日期'} },
  summary:  { title:'今日概览参数表',fields:{key:'参数',value:'数值',unit:'单位',note:'备注'} }
};

var EXPENSE_CATS = ['吃饭','交通','购物','娱乐','房租','看病','学习','其他'];
var INCOME_CATS  = ['工资','奖金','兼职','理财','其他'];
var CAT_COLORS   = ['#b65f42','#627a67','#7d5b75','#a57c45','#5f7188','#c58d69','#879a75','#8e8478'];
var DEFAULT_HABITS = [
  {name:'喝水', mode:'counter', target:8, unit:'杯'},
  {name:'睡觉', mode:'number',  target:7, unit:'小时'},
  {name:'运动', mode:'check',   target:1, unit:'次'},
  {name:'看书', mode:'check',   target:1, unit:'次'},
  {name:'冥想', mode:'check',   target:1, unit:'次'}
];
var DEFAULT_PLAN = [
  {title:'力量训练 2 次', group:'运动', note:'每次 30–40 分钟'},
  {title:'中低强度有氧 3 次', group:'运动', note:'快走、骑行或游泳'},
  {title:'每餐一掌心蛋白质', group:'饮食', note:'鱼、蛋、瘦肉或豆制品'},
  {title:'午晚餐蔬菜占一半', group:'饮食', note:'优先深色蔬菜'},
  {title:'睡够 7 小时', group:'恢复', note:'恢复也是减脂计划'}
];

/* ---------- 数据仓库：全部来自云端 ---------- */
var store = {
  money: [], habit: [], plan: [], fitness: [], shopping: [], media: [], summary: [],
  loaded: false, refreshing: false, lastSync: null, clock: null
};
var view = { money:'all', planner:'all', shopping:'pending', media:'wall', mediaStatus:'all' };
var settings = { budget:5000, height:165, target:55, start:60, age:30, sex:'女', activity:1.375, name:'小笑肖', tagline:'把生活安放得井井有条', avatar:'笑' };
var lastError = null;
var pendingMediaFile = null;

/* ---------- 工具 ---------- */
function $(id){ return document.getElementById(id); }
function pad(n){ return n<10 ? '0'+n : ''+n; }
function isoDate(d){ d = d || new Date(); return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()); }
function shiftDate(days, base){ var d = new Date(base||new Date()); d.setDate(d.getDate()+days); return isoDate(d); }
function dayKey(v){
  if(!v) return '';
  var s = String(v);
  var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? m[1]+'-'+m[2]+'-'+m[3] : '';
}
function num(v, def){ var n = parseFloat(v); return isFinite(n) ? n : (def===undefined?0:def); }
function esc(v){ return String(v===null||v===undefined?'':v).replace(/[&<>"']/g,function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
/* 图片地址白名单：仅允许云存储 https 与本地 data 图，杜绝 javascript: 等注入 */
function safeUrl(u){
  var raw = String(u||'').trim();
  if (!raw) return '';
  var low = raw.toLowerCase();
  if (low.indexOf('https:') === 0 && raw.length > 12) return raw;
  if (low.indexOf('https%3a') === 0) return raw;
  if (low.indexOf('data:image/png;base64,') === 0) return raw;
  if (low.indexOf('data:image/jpeg;base64,') === 0) return raw;
  if (low.indexOf('data:image/jpg;base64,') === 0) return raw;
  if (low.indexOf('data:image/gif;base64,') === 0) return raw;
  if (low.indexOf('data:image/webp;base64,') === 0) return raw;
  return '';
}
function money(v){ var n = num(v); return '¥' + n.toLocaleString('zh-CN',{maximumFractionDigits:2}); }
function icon(id){ return '<svg aria-hidden="true"><use href="#'+id+'"/></svg>'; }
function todayStr(){ return isoDate(); }
function monthKey(d){ d = d? new Date(d): new Date(); return d.getFullYear()+'-'+pad(d.getMonth()+1); }
function catColor(c){ var i = EXPENSE_CATS.indexOf(c); return CAT_COLORS[(i<0?7:i)%CAT_COLORS.length]; }

var toastTimer;
function toast(msg, isErr){
  var el = $('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){ el.className = 'toast'; }, 2800);
}
function showErr(msg){
  lastError = msg;
  $('errText').textContent = msg;
  $('errBanner').classList.add('show');
  setSync('err', '同步异常');
}
function clearErr(){
  lastError = null;
  $('errBanner').classList.remove('show');
}
function setSync(state, text){
  var pill = $('syncPill');
  pill.className = 'sync-pill ' + state;
  $('syncText').textContent = text;
}

/* ---------- SDK ---------- */
function db(){
  try {
    if (window.__SMART_PAGE__ && window.__SMART_PAGE__.database) return window.__SMART_PAGE__.database;
  } catch(e){}
  return null;
}

/* 每张表一个显式入口：DATABASE_ID 是当前表的硬编码常量，
   databaseId 直接以字面量形式写在 SDK 调用参数里，便于校验与排错。 */

function queryPage(kind, cursor){
  var API = window.__SMART_PAGE__.database;
  if (kind === 'money') {
    var DATABASE_ID = 'tHLWn2tjAvknVD3h5lyWG5';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  if (kind === 'habit') {
    var DATABASE_ID = 'BxxY8CTvCuWpMWgHJJGq9S';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  if (kind === 'plan') {
    var DATABASE_ID = 'cPZx8ssc03WAmKOwFhBcPx';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  if (kind === 'fitness') {
    var DATABASE_ID = 'JNiZJHR3QXKBMNrmHc0nIj';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  if (kind === 'shopping') {
    var DATABASE_ID = 'B2a4VCyYGokQUAqXRhAKVv';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  if (kind === 'media') {
    var DATABASE_ID = 'ukf8VPIPQtBQN71qyrtu6x';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  if (kind === 'summary') {
    var DATABASE_ID = 'HEEB4feB120kc8nx8iSTxW';
    var o = { databaseId: DATABASE_ID, pageSize: 200 };
    if (cursor) o.startCursor = cursor;
    return API.query(o);
  }
  return Promise.reject(new Error('未知数据表：' + kind));
}

/* 拉取整表（完整分页，绝不把单页当全量） */
function pullAll(kind, acc, cursor, guard){
  acc = acc || [];
  guard = guard || 0;
  if (guard > 60) return Promise.resolve(acc);
  return queryPage(kind, cursor).then(function(res){
    var rows = (res && res.results) || [];
    var merged = acc.concat(rows);
    var next = res && res.nextCursor;
    if (res && res.hasMore && next && next !== cursor && rows.length) {
      return pullAll(kind, merged, next, guard+1);
    }
    return merged;
  }, function(err){
    if (acc.length) return acc;
    throw err;
  });
}

/* ---------- 归一化 ---------- */
function normMoney(r){
  var f = META.money.fields;
  var flow = String(r[f.flow]||'').trim();
  var note = String(r[f.note]||'').trim();
  if (flow !== '收入' && flow !== '支出') flow = note.indexOf('收入：')===0 ? '收入' : '支出';
  return {
    id: r.record_id, date: dayKey(r[f.date]), flow: flow,
    cat: String(r[f.cat]||'其他').trim() || '其他',
    amount: Math.abs(num(r[f.amount])),
    note: note.replace(/^收入：/,'')
  };
}
function normHabit(r){
  var f = META.habit.fields;
  return {
    id: r.record_id, date: dayKey(r[f.date]),
    name: String(r[f.name]||'').trim(),
    value: num(r[f.value]),
    mode: String(r[f.mode]||'').trim(),
    target: num(r[f.target], 0),
    unit: String(r[f.unit]||'').trim()
  };
}
function normPlan(r){
  var f = META.plan.fields;
  var status = String(r[f.status]||'').trim();
  var done = r[f.done] === true || status === '已完成';
  return {
    id: r.record_id, date: dayKey(r[f.date]),
    title: String(r[f.title]||'').trim(),
    list: String(r[f.list]||'生活').trim() || '生活',
    status: done ? '已完成' : '待完成', done: done,
    start: String(r[f.start]||'').trim(),
    end: String(r[f.end]||'').trim(),
    pri: String(r[f.pri]||'normal').trim() || 'normal'
  };
}
function normFitness(r){
  var f = META.fitness.fields;
  return {
    id: r.record_id, date: dayKey(r[f.date]),
    weight: num(r[f.weight]), fat: num(r[f.fat]),
    note: String(r[f.note]||'').trim()
  };
}
function normShopping(r){
  var f = META.shopping.fields;
  var bought = String(r[f.bought]||'').trim() === '已买';
  return {
    id: r.record_id,
    name: String(r[f.name]||'').trim(),
    qty: num(r[f.qty],1) || 1,
    price: num(r[f.price]),
    bought: bought,
    cat: String(r[f.cat]||'其他').trim() || '其他',
    note: String(r[f.note]||'').trim()
  };
}
function normMedia(r){
  var f = META.media.fields;
  var cover = '';
  var raw = r[f.cover];
  try { if (raw && raw.length && raw[0]) cover = raw[0].imageUrl || raw[0].url || ''; } catch(e){}
  return {
    id: r.record_id,
    title: String(r[f.title]||'').trim(),
    type: String(r[f.type]||'电影').trim() || '电影',
    status: String(r[f.status]||'想看').trim() || '想看',
    rating: num(r[f.rating]),
    review: String(r[f.review]||'').trim(),
    cover: cover,
    doneDate: dayKey(r[f.doneDate])
  };
}
function normSummary(r){
  var f = META.summary.fields;
  return { id: r.record_id, key: String(r[f.key]||'').trim(), value: String(r[f.value]||'').trim() };
}

/* ---------- 云端读写：按表分派，DATABASE_ID 为当前表常量 ---------- */
function addRecord(kind, props){
  var API = window.__SMART_PAGE__.database;
  if (kind === 'money')    { var DATABASE_ID = 'tHLWn2tjAvknVD3h5lyWG5';    return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  if (kind === 'habit')    { var DATABASE_ID = 'BxxY8CTvCuWpMWgHJJGq9S';    return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  if (kind === 'plan')     { var DATABASE_ID = 'cPZx8ssc03WAmKOwFhBcPx';     return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  if (kind === 'fitness')  { var DATABASE_ID = 'JNiZJHR3QXKBMNrmHc0nIj';  return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  if (kind === 'shopping') { var DATABASE_ID = 'B2a4VCyYGokQUAqXRhAKVv'; return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  if (kind === 'media')    { var DATABASE_ID = 'ukf8VPIPQtBQN71qyrtu6x';    return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  if (kind === 'summary')  { var DATABASE_ID = 'HEEB4feB120kc8nx8iSTxW';  return API.addRecord({ databaseId: DATABASE_ID, properties: props }); }
  return Promise.reject(new Error('未知数据表：' + kind));
}

function updateRecord(kind, recordId, props){
  var API = window.__SMART_PAGE__.database;
  if (kind === 'money')    { var DATABASE_ID = 'tHLWn2tjAvknVD3h5lyWG5';    return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  if (kind === 'habit')    { var DATABASE_ID = 'BxxY8CTvCuWpMWgHJJGq9S';    return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  if (kind === 'plan')     { var DATABASE_ID = 'cPZx8ssc03WAmKOwFhBcPx';     return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  if (kind === 'fitness')  { var DATABASE_ID = 'JNiZJHR3QXKBMNrmHc0nIj';  return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  if (kind === 'shopping') { var DATABASE_ID = 'B2a4VCyYGokQUAqXRhAKVv'; return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  if (kind === 'media')    { var DATABASE_ID = 'ukf8VPIPQtBQN71qyrtu6x';    return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  if (kind === 'summary')  { var DATABASE_ID = 'HEEB4feB120kc8nx8iSTxW';  return API.updateRecord({ databaseId: DATABASE_ID, recordId: recordId, properties: props }); }
  return Promise.reject(new Error('未知数据表：' + kind));
}

function deleteRecord(kind, recordId){
  var API = window.__SMART_PAGE__.database;
  if (kind === 'money')    { var DATABASE_ID = 'tHLWn2tjAvknVD3h5lyWG5';    return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  if (kind === 'habit')    { var DATABASE_ID = 'BxxY8CTvCuWpMWgHJJGq9S';    return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  if (kind === 'plan')     { var DATABASE_ID = 'cPZx8ssc03WAmKOwFhBcPx';     return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  if (kind === 'fitness')  { var DATABASE_ID = 'JNiZJHR3QXKBMNrmHc0nIj';  return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  if (kind === 'shopping') { var DATABASE_ID = 'B2a4VCyYGokQUAqXRhAKVv'; return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  if (kind === 'media')    { var DATABASE_ID = 'ukf8VPIPQtBQN71qyrtu6x';    return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  if (kind === 'summary')  { var DATABASE_ID = 'HEEB4feB120kc8nx8iSTxW';  return API.deleteRecord({ databaseId: DATABASE_ID, recordId: recordId }); }
  return Promise.reject(new Error('未知数据表：' + kind));
}

/* 失败包装：给出可重试的错误横幅，绝不静默 */
function guarded(promise, action){
  return promise.then(function(r){
    clearErr();
    return r;
  }, function(err){
    console.error('[小笑肖] '+action+'失败', err);
    showErr(action + '失败，数据未保存。请检查网络后点击重试。');
    toast(action + '失败，请重试', true);
    throw err;
  });
}

/* ---------- 全量刷新 ---------- */
function refreshAll(silent){
  if (store.refreshing) return Promise.resolve();
  store.refreshing = true;
  setSync('busy','正在同步云端');
  $('saveState').textContent = '同步中…';
  var keys = ['money','habit','plan','fitness','shopping','media','summary'];
  var jobs = keys.map(function(k){
    return pullAll(k).then(function(rows){
      return { k:k, rows:rows||[] };
    }, function(err){
      return { k:k, rows:null, err:err };
    });
  });
  return Promise.all(jobs).then(function(results){
    var failed = [];
    results.forEach(function(r){
      if (r.rows) {
        var list = r.rows.map(function(x){
          if (r.k==='money') return normMoney(x);
          if (r.k==='habit') return normHabit(x);
          if (r.k==='plan') return normPlan(x);
          if (r.k==='fitness') return normFitness(x);
          if (r.k==='shopping') return normShopping(x);
          if (r.k==='media') return normMedia(x);
          return normSummary(x);
        }).filter(function(x){ return x && (x.id || x.key); });
        store[r.k] = list;
      } else {
        failed.push(r.k);
      }
    });
    store.loaded = true;
    store.lastSync = new Date();
    applySummary();
    renderAll();
    store.refreshing = false;
    if (failed.length) {
      showErr('有 ' + failed.length + ' 张表读取失败（' + failed.map(function(k){ return META[k].title; }).join('、') + '），当前显示可能是旧数据。');
      setSync('err','部分表读取失败');
      $('saveState').textContent = '部分数据未同步';
    } else {
      clearErr();
      setSync('ok','云端已连接');
      $('saveState').textContent = '已同步 ' + pad(store.lastSync.getHours()) + ':' + pad(store.lastSync.getMinutes());
      if (!silent) toast('已与云端同步');
    }
  }, function(err){
    store.refreshing = false;
    showErr('云端数据读取失败，页面显示为空。请点击重试。');
    setSync('err','读取失败');
    $('saveState').textContent = '同步失败';
    renderAll();
  });
}

function applySummary(){
  var map = {};
  store.summary.forEach(function(s){ if (s.key) map[s.key] = s.value; });
  if (map['月度预算']) settings.budget = num(map['月度预算'], 5000);
  if (map['身高']) settings.height = num(map['身高'], 165);
  if (map['目标体重']) settings.target = num(map['目标体重'], 55);
  if (map['起始体重']) settings.start = num(map['起始体重'], 60);
  if (map['年龄']) settings.age = num(map['年龄'], 30);
  if (map['生理性别']) settings.sex = map['生理性别'];
  if (map['活动系数']) settings.activity = num(map['活动系数'], 1.375);
  if (map['页面名称']) settings.name = map['页面名称'];
  if (map['副标题']) settings.tagline = map['副标题'];
  applyBrand();
}

function applyBrand(){
  $('brandName').textContent = settings.name || '小笑肖';
  $('brandTagline').textContent = settings.tagline || '把生活安放得井井有条';
  $('brandAvatar').textContent = settings.avatar || '笑';
  document.title = (settings.name || '小笑肖') + ' · 在线生活工作台';
}

/* 更新 summary 表里的某个参数 */
function saveSetting(key, value, label){
  var exists = null;
  store.summary.forEach(function(s){ if (s.key === key) exists = s; });
  var props = {};
  props[META.summary.fields.key] = { text: key };
  props[META.summary.fields.value] = { text: String(value) };
  var p = exists ? updateRecord('summary', exists.id, props) : addRecord('summary', props);
  return guarded(p, label || '保存设置');
}

/* =========================================================
   渲染层
   ========================================================= */
function renderAll(){
  try { renderDashboard(); } catch(e){ console.error('dashboard', e); }
  try { renderMoney(); } catch(e){ console.error('money', e); }
  try { renderHabits(); } catch(e){ console.error('habits', e); }
  try { renderFitness(); } catch(e){ console.error('fitness', e); }
  try { renderPlanner(); } catch(e){ console.error('planner', e); }
  try { renderShopping(); } catch(e){ console.error('shopping', e); }
  try { renderMedia(); } catch(e){ console.error('media', e); }
}

/* ---------- 今日概览 ---------- */
function renderDashboard(){
  var today = todayStr(), mk = monthKey();
  var todayExp = store.money.filter(function(m){ return m.date===today && m.flow==='支出'; })
                            .reduce(function(s,m){ return s + m.amount; }, 0);
  var monthExp = store.money.filter(function(m){ return m.date.indexOf(mk)===0 && m.flow==='支出'; })
                            .reduce(function(s,m){ return s + m.amount; }, 0);
  $('ovExpense').textContent = money(todayExp);
  var pct = settings.budget>0 ? Math.round(monthExp/settings.budget*100) : 0;
  $('ovExpenseNote').textContent = '本月 ' + money(monthExp) + ' · 预算已用 ' + pct + '%';

  var pending = store.plan.filter(function(p){ return !p.done && p.date >= today; });
  $('ovTodo').textContent = String(pending.length);
  var overdue = store.plan.filter(function(p){ return !p.done && p.date < today; }).length;
  $('ovTodoNote').textContent = overdue ? (overdue + ' 项已逾期') : '今天与未来待完成';

  var doneCount = 0, totalCount = 0;
  habitGroups().forEach(function(h){
    totalCount++;
    if (h.todayVal >= h.target) doneCount++;
  });
  $('ovHabit').textContent = doneCount + '/' + totalCount;
  $('ovHabitNote').textContent = totalCount ? ('完成率 ' + Math.round(doneCount/totalCount*100) + '%') : '还没有习惯';

  var latest = latestWeight();
  $('ovWeight').textContent = latest ? (latest.weight.toFixed(1) + ' kg') : '—';
  $('ovWeightNote').textContent = latest ? ('距目标 ' + Math.abs(latest.weight - settings.target).toFixed(1) + ' kg') : '还没有记录';

  // 近期日程
  var up = store.plan.filter(function(p){ return !p.done; })
    .sort(function(a,b){ return (a.date+a.start).localeCompare(b.date+b.start); }).slice(0,5);
  $('ovTasks').innerHTML = up.length ? up.map(function(p){
    return '<div class="mini-row"><span class="pri ' + esc(p.pri) + '"></span><span class="t">' + esc(p.title) + '</span><span class="m">' + esc(fmtDay(p.date)) + (p.start?(' '+esc(p.start)):'') + '</span></div>';
  }).join('') : '<div class="empty">还没有待办，今天的空白也很珍贵</div>';

  // 习惯进度
  var hs = habitGroups();
  $('ovHabits').innerHTML = hs.length ? hs.map(function(h){
    var p = h.target>0 ? Math.min(100, Math.round(h.todayVal/h.target*100)) : 0;
    return '<div style="margin-bottom:11px"><div style="display:flex;justify-content:space-between;font-size:12.5px;margin-bottom:4px"><span>' + esc(h.name) + '</span><span style="color:var(--muted)">' + fmtNum(h.todayVal) + '/' + fmtNum(h.target) + ' ' + esc(h.unit) + '</span></div><div class="bar"><i style="width:' + p + '%"></i></div></div>';
  }).join('') : '<div class="empty">在「习惯健康」里添加第一个习惯</div>';

  // 本月结构
  var monthExpList = store.money.filter(function(m){ return m.date.indexOf(mk)===0 && m.flow==='支出'; });
  $('ovPie').innerHTML = pieHtml(groupSum(monthExpList), monthExp);

  // 待买与收藏
  var pend = store.shopping.filter(function(s){ return !s.bought; });
  var cost = pend.reduce(function(s,i){ return s + i.price*i.qty; }, 0);
  var watching = store.media.filter(function(m){ return m.status==='在看'; }).length;
  var want = store.media.filter(function(m){ return m.status==='想看'; }).length;
  $('ovSide').innerHTML =
    '<div class="mini-row"><span class="t">待买物品</span><span class="m">' + pend.length + ' 件</span></div>' +
    '<div class="mini-row"><span class="t">预计花费</span><span class="m">' + money(cost) + '</span></div>' +
    '<div class="mini-row"><span class="t">正在看 / 想看</span><span class="m">' + watching + ' / ' + want + '</span></div>' +
    (pend.length ? '<div class="mini-row"><span class="t" style="color:var(--muted);font-size:12px">' + esc(pend.slice(0,1)[0].name) + (pend.length>1?(' 等 ' + pend.length + ' 项'):'') + '</span></div>' : '');
}

function groupSum(list){
  var map = {}, total = 0;
  list.forEach(function(m){
    map[m.cat] = (map[m.cat]||0) + m.amount;
    total += m.amount;
  });
  var arr = Object.keys(map).map(function(k){ return { key:k, value:map[k] }; })
    .sort(function(a,b){ return b.value-a.value; });
  return { items:arr, total:total };
}

function pieHtml(grouped, total){
  if (!grouped.items.length) return '<div class="empty">本月还没有支出记录</div>';
  var acc = 0;
  var stops = grouped.items.map(function(it, i){
    var from = total>0 ? acc/total*100 : 0;
    acc += it.value;
    var to = total>0 ? acc/total*100 : 0;
    return catColor(it.key) + ' ' + from.toFixed(2) + '% ' + to.toFixed(2) + '%';
  });
  return '<div class="pie" style="background:conic-gradient(' + stops.join(',') + ')">' +
      '<div class="pie-center"><div><b>' + money(total) + '</b><span>本月支出</span></div></div></div>' +
    '<div class="legend">' + grouped.items.slice(0,8).map(function(it){
      return '<div class="legend-item"><i style="background:' + catColor(it.key) + '"></i><span>' + esc(it.key) + '</span><span class="p">' + (total>0?Math.round(it.value/total*100):0) + '%</span></div>';
    }).join('') + '</div>';
}

function fmtNum(v){
  var n = num(v);
  return (Math.round(n*10)/10).toString();
}
function fmtDay(d){
  var t = todayStr();
  if (d === t) return '今天';
  if (d === shiftDate(-1)) return '昨天';
  if (d === shiftDate(1)) return '明天';
  var p = d.split('-');
  return parseInt(p[1],10) + '月' + parseInt(p[2],10) + '日';
}

/* ---------- 记账 ---------- */
function renderMoney(){
  var mk = monthKey();
  var selects = $('moneyCategory');
  var flow = document.querySelector('#moneyForm [name="flow"]').value || 'expense';
  var cats = flow==='income' ? INCOME_CATS : EXPENSE_CATS;
  var cur = selects.value;
  selects.innerHTML = cats.map(function(c){ return '<option' + (c===cur?' selected':'') + '>' + esc(c) + '</option>'; }).join('');

  // 分类筛选下拉
  var allCats = {};
  store.money.forEach(function(m){ allCats[m.cat] = 1; });
  var mf = $('moneyFilter');
  var keep = mf.value;
  mf.innerHTML = '<option value="all">全部分类</option>' +
    Object.keys(allCats).map(function(c){ return '<option value="' + esc(c) + '"' + (c===keep?' selected':'') + '>' + esc(c) + '</option>'; }).join('');
  if (!mf.querySelector('[value="' + (window.CSS && CSS.escape ? CSS.escape(keep) : keep) + '"]')) mf.value = 'all';
  view.money = mf.value;

  var monthList = store.money.filter(function(m){ return m.date.indexOf(mk)===0; });
  var exp = monthList.filter(function(m){ return m.flow==='支出'; }).reduce(function(s,m){ return s+m.amount; },0);
  var inc = monthList.filter(function(m){ return m.flow==='收入'; }).reduce(function(s,m){ return s+m.amount; },0);
  $('mExpense').textContent = money(exp);
  $('mIncome').textContent = money(inc);
  $('mBalance').textContent = money(inc-exp);
  $('mBudgetLeft').textContent = money(Math.max(0, settings.budget-exp));
  $('budgetInput').value = settings.budget;

  // 近 6 个月柱状对比
  var cols = [];
  var now = new Date();
  for (var i=5; i>=0; i--){
    var d = new Date(now.getFullYear(), now.getMonth()-i, 1);
    var k = monthKey(d);
    var e = store.money.filter(function(m){ return m.date.indexOf(k)===0 && m.flow==='支出'; }).reduce(function(s,m){ return s+m.amount; },0);
    var n = store.money.filter(function(m){ return m.date.indexOf(k)===0 && m.flow==='收入'; }).reduce(function(s,m){ return s+m.amount; },0);
    cols.push({ label:(d.getMonth()+1)+'月', exp:e, inc:n, cur:i===0 });
  }
  var max = Math.max.apply(null, cols.map(function(c){ return Math.max(c.exp, c.inc); }).concat([1]));
  $('mBars').innerHTML = cols.map(function(c){
    return '<div class="col' + (c.cur?' cur':'') + '">' +
      '<b>' + (c.exp?Math.round(c.exp):'') + '</b>' +
      '<i style="height:' + Math.max(3, c.exp/max*84) + 'px"></i>' +
      '<span>' + c.label + '</span></div>';
  }).join('');

  $('mPie').innerHTML = pieHtml(groupSum(monthList.filter(function(m){ return m.flow==='支出'; })), exp);

  var list = store.money.slice().sort(function(a,b){ return b.date.localeCompare(a.date); });
  if (view.money !== 'all') list = list.filter(function(m){ return m.cat === view.money; });
  $('mCount').textContent = list.length + ' 条记录 · 合计 ' + money(list.reduce(function(s,m){ return s + (m.flow==='支出'?m.amount:0); },0));
  $('mList').innerHTML = list.length ? list.slice(0,120).map(function(m){
    return '<div class="rec">' +
      '<span class="ico' + (m.flow==='收入'?' inc':'') + '">' + icon(m.flow==='收入'?'i-plus':'i-wallet') + '</span>' +
      '<span class="body"><strong>' + esc(m.note || m.cat) + '</strong><small>' + esc(fmtDay(m.date)) + ' · ' + esc(m.cat) + ' · ' + esc(m.flow) + '</small></span>' +
      '<span class="amt ' + (m.flow==='收入'?'inc':'exp') + '">' + (m.flow==='收入'?'+':'-') + money(m.amount) + '</span>' +
      '<button class="icon-btn" data-action="del" data-table="money" data-id="' + esc(m.id) + '" aria-label="删除">' + icon('i-trash') + '</button>' +
      '</div>';
  }).join('') : '<div class="empty">还没有收支记录</div>';
}

/* ---------- 习惯 ---------- */
function habitGroups(){
  var map = {};
  var defs = {};
  DEFAULT_HABITS.forEach(function(d){ defs[d.name] = d; });
  store.habit.forEach(function(h){
    if (!h.name) return;
    if (!map[h.name]) {
      map[h.name] = { name:h.name, records:[], mode:h.mode||(defs[h.name]?defs[h.name].mode:'check'), target:h.target||(defs[h.name]?defs[h.name].target:1), unit:h.unit||(defs[h.name]?defs[h.name].unit:'') };
    }
    var g = map[h.name];
    if (h.mode) g.mode = h.mode;
    if (h.target) g.target = h.target;
    if (h.unit) g.unit = h.unit;
    g.records.push(h);
  });
  Object.keys(map).forEach(function(k){
    var g = map[k];
    g.byDate = {};
    g.records.forEach(function(r){ if (r.date) g.byDate[r.date] = r; });
    var today = g.byDate[todayStr()];
    g.todayVal = today ? today.value : 0;
    if (!g.target) g.target = 1;
  });
  // 没有任何数据时展示默认习惯骨架，避免空白页
  if (!Object.keys(map).length) {
    DEFAULT_HABITS.forEach(function(d){
      map[d.name] = { name:d.name, records:[], byDate:{}, mode:d.mode, target:d.target, unit:d.unit, todayVal:0, virtual:true };
    });
  }
  var order = DEFAULT_HABITS.map(function(d){ return d.name; });
  return Object.keys(map).map(function(k){ return map[k]; }).sort(function(a,b){
    var ia = order.indexOf(a.name), ib = order.indexOf(b.name);
    if (ia<0) ia = 99; if (ib<0) ib = 99;
    return ia - ib || a.name.localeCompare(b.name);
  });
}

function renderHabits(){
  var groups = habitGroups();
  $('habitList').innerHTML = groups.map(function(g){
    var done = g.todayVal >= g.target;
    var ctrl;
    if (g.mode === 'check') {
      ctrl = '<button class="round' + (done?' on':'') + '" data-action="habit-toggle" data-name="' + esc(g.name) + '" aria-label="切换打卡">' + (done?icon('i-check'):'') + '</button>' +
             '<span class="habit-val">' + (done?'已完成':'待打卡') + '</span>';
    } else if (g.mode === 'counter') {
      ctrl = '<button class="round" data-action="habit-minus" data-name="' + esc(g.name) + '" aria-label="减一">' + icon('i-minus') + '</button>' +
             '<span class="habit-val">' + fmtNum(g.todayVal) + '<small>/' + fmtNum(g.target) + ' ' + esc(g.unit) + '</small></span>' +
             '<button class="round' + (done?' on':'') + '" data-action="habit-plus" data-name="' + esc(g.name) + '" aria-label="加一">' + icon('i-plus') + '</button>';
    } else {
      ctrl = '<input class="num-input" type="number" step="0.1" min="0" inputmode="decimal" value="' + (g.todayVal||'') + '" data-action="habit-number" data-name="' + esc(g.name) + '" aria-label="填写数值">' +
             '<span class="habit-val" style="font-size:12px;color:var(--muted)">/ ' + fmtNum(g.target) + ' ' + esc(g.unit) + '</span>' +
             '<button class="round' + (done?' on':'') + '" data-action="habit-quick" data-name="' + esc(g.name) + '" aria-label="达标">' + icon('i-check') + '</button>';
    }
    return '<div class="habit-card"><div class="habit-top">' +
      '<span class="habit-name">' + esc(g.name) + '<em>' + (g.mode==='check'?'勾选':g.mode==='counter'?'计数':'数值') + '</em></span>' +
      '<span class="streak">' + icon('i-fire') + (g.virtual ? 0 : habitStreak(g)) + ' 天</span>' +
      '</div><div class="habit-ctrl">' + ctrl + '</div></div>';
  }).join('');

  // 热力图
  var days = [];
  for (var i=29; i>=0; i--) days.push(shiftDate(-i));
  var html = '<div class="heat">' + days.map(function(d){
    var cnt = 0, tot = 0;
    groups.forEach(function(g){
      if (g.virtual) return;
      tot++;
      var r = g.byDate[d];
      if (r && r.value >= g.target) cnt++;
    });
    var lv = tot ? Math.ceil(cnt/tot*4) : 0;
    return '<i class="' + (lv?'l'+lv:'') + '" title="' + d + ' · ' + cnt + '/' + tot + '"></i>';
  }).join('') + '</div>';
  var detail = groups.filter(function(g){ return !g.virtual; }).map(function(g){
    var cells = days.map(function(d){
      var r = g.byDate[d];
      var v = r ? r.value : 0;
      var lv = v<=0 ? 0 : (v>=g.target ? 4 : Math.max(1, Math.ceil(v/g.target*4)));
      return '<i class="' + (lv?'l'+lv:'') + '" title="' + d + ' · ' + fmtNum(v) + ' ' + esc(g.unit) + '"></i>';
    }).join('');
    return '<div class="heat-habit"><h4><span>' + esc(g.name) + '</span><span>' + (g.records.length) + ' 次记录</span></h4><div class="heat">' + cells + '</div></div>';
  }).join('');
  $('heatWrap').innerHTML = html + detail;
}

function habitStreak(g){
  var n = 0, cur = new Date();
  for (var i=0;i<365;i++){
    var k = isoDate(cur);
    var r = g.byDate[k];
    if (r && r.value >= g.target) n++;
    else if (i>0) break;
    cur.setDate(cur.getDate()-1);
  }
  return n;
}

/* ---------- 健身 ---------- */
function latestWeight(){
  var f = store.fitness.filter(function(x){ return x.weight>0; }).sort(function(a,b){ return a.date.localeCompare(b.date); });
  return f.length ? f[f.length-1] : null;
}

function renderFitness(){
  var list = store.fitness.filter(function(x){ return x.weight>0; }).sort(function(a,b){ return a.date.localeCompare(b.date); });
  drawWeightChart(list);

  var latest = list.length ? list[list.length-1] : null;
  $('fWeight').textContent = latest ? latest.weight.toFixed(1) + ' kg' : '—';
  if (latest && settings.height>0){
    var h = settings.height/100;
    var bmi = latest.weight/(h*h);
    var tag = esc(bmi<18.5?'偏瘦':bmi<24?'正常':bmi<28?'偏重':'肥胖');
    $('fBmi').innerHTML = bmi.toFixed(1) + '<small style="font-size:11px;color:var(--muted);margin-left:4px">' + tag + '</small>';
  } else { $('fBmi').textContent = '—'; }

  var prog = 0, left = 0;
  if (latest) {
    var span = settings.start - settings.target;
    left = latest.weight - settings.target;
    prog = span>0 ? Math.max(0, Math.min(100, (settings.start - latest.weight)/span*100)) : 0;
  }
  $('fProgress').textContent = latest ? Math.round(prog) + '%' : '—';
  $('fBar').style.width = prog + '%';
  $('fRange').textContent = '起始 ' + fmtNum(settings.start) + ' kg → 目标 ' + fmtNum(settings.target) + ' kg';
  $('fLeft').textContent = latest ? ('还差 ' + Math.abs(left).toFixed(1) + ' kg') : '';

  // 7 日均线与热量缺口估算
  var gap = estimateGap(list);
  $('fGap').textContent = gap===null ? '—' : (gap>0?'-':'+') + Math.abs(Math.round(gap)) + ' kcal';

  var show = store.fitness.slice().sort(function(a,b){ return b.date.localeCompare(a.date); });
  $('fCount').textContent = show.length + ' 条记录';
  $('fList').innerHTML = show.length ? show.slice(0,60).map(function(x){
    return '<div class="rec"><span class="ico">' + icon('i-fitness') + '</span>' +
      '<span class="body"><strong>' + x.weight.toFixed(1) + ' kg' + (x.fat?' · 体脂 ' + x.fat.toFixed(1) + '%':'') + '</strong>' +
      '<small>' + esc(fmtDay(x.date)) + (x.note?(' · ' + esc(x.note)):'') + '</small></span>' +
      '<button class="icon-btn" data-action="del" data-table="fitness" data-id="' + esc(x.id) + '" aria-label="删除">' + icon('i-trash') + '</button></div>';
  }).join('') : '<div class="empty">还没有身体数据，先记一次体重</div>';

  $('planList').innerHTML = weeklyPlan.length ? weeklyPlan.map(function(p, i){
    return '<div class="plan-item' + (p.done?' done':'') + '">' +
      '<button class="round" style="width:22px;height:22px;border-radius:6px' + (p.done?';background:var(--sage);border-color:var(--sage);color:#fff':'') + '" data-action="plan-toggle" data-idx="' + i + '" aria-label="切换">' + (p.done?icon('i-check'):'') + '</button>' +
      '<span class="t">' + esc(p.title) + (p.note?('<small style="color:var(--muted);font-size:11.5px"> · ' + esc(p.note) + '</small>'):'') + '</span>' +
      '<span class="g">' + esc(p.group) + '</span></div>';
  }).join('') : '<div class="empty">还没有训练计划</div>';
}

function estimateGap(list){
  if (list.length < 2) return null;
  var recent = list.slice(-8);
  var first = recent[0], last = recent[recent.length-1];
  var d1 = new Date(first.date), d2 = new Date(last.date);
  var days = Math.round((d2-d1)/86400000);
  if (days <= 0) return null;
  var delta = last.weight - first.weight;
  return delta * 7700 / days;
}

function drawWeightChart(list){
  var box = $('weightChart');
  if (!list.length) { box.innerHTML = '<div class="empty">还没有体重数据，记录后这里会出现曲线</div>'; return; }
  var W = 640, H = 190, pl = 34, pr = 12, pt = 14, pb = 24;
  var series = list.map(function(x){ return { date:x.date, v:x.weight }; });
  // 7 日均线（滚动平均）
  var ma = series.map(function(_, i){
    var from = Math.max(0, i-6);
    var seg = series.slice(from, i+1);
    return seg.reduce(function(s,x){ return s+x.v; },0)/seg.length;
  });
  var vals = series.map(function(x){ return x.v; }).concat(ma);
  var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
  if (max-min < 1) { max += .5; min -= .5; }
  var padY = (max-min)*0.12; min -= padY; max += padY;
  var n = series.length;
  function X(i){ return pl + (n<=1 ? (W-pl-pr)/2 : i/(n-1)*(W-pl-pr)); }
  function Y(v){ return pt + (1-(v-min)/(max-min))*(H-pt-pb); }

  var pts = series.map(function(x,i){ return X(i)+','+Y(x.v); });
  var line = 'M' + pts.join(' L');
  var area = line + ' L' + X(n-1)+','+(H-pb) + ' L' + X(0)+','+(H-pb) + ' Z';
  var maLine = 'M' + ma.map(function(v,i){ return X(i)+','+Y(v); }).join(' L');

  var grid = '';
  for (var g=0; g<=3; g++){
    var v = min + (max-min)*g/3;
    var y = Y(v);
    grid += '<line x1="'+pl+'" y1="'+y+'" x2="'+(W-pr)+'" y2="'+y+'" stroke="#e7ded1" stroke-width="1" stroke-dasharray="3 4"/>';
    grid += '<text x="'+(pl-6)+'" y="'+(y+3.5)+'" text-anchor="end" font-size="9" fill="#9a9184" stroke="none">'+v.toFixed(1)+'</text>';
  }
  var dots = series.map(function(x,i){
    return '<circle cx="'+X(i)+'" cy="'+Y(x.v)+'" r="2.4" fill="#fffdfa" stroke="#b65f42" stroke-width="1.4"/>';
  }).join('');
  var labels = '';
  [0, Math.floor((n-1)/2), n-1].filter(function(v,i,a){ return a.indexOf(v)===i; }).forEach(function(i){
    labels += '<text x="'+X(i)+'" y="'+(H-6)+'" text-anchor="middle" font-size="9" fill="#9a9184" stroke="none">'+series[i].date.slice(5)+'</text>';
  });

  var targetY = Y(settings.target);
  var targetLine = (settings.target >= min && settings.target <= max)
    ? '<line x1="'+pl+'" y1="'+targetY+'" x2="'+(W-pr)+'" y2="'+targetY+'" stroke="#627a67" stroke-width="1" stroke-dasharray="5 4" opacity=".7"/><text x="'+(W-pr)+'" y="'+(targetY-4)+'" text-anchor="end" font-size="9" fill="#627a67" stroke="none">目标 '+fmtNum(settings.target)+'</text>'
    : '';

  box.innerHTML = '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" style="width:100%;height:100%">' +
    '<defs><linearGradient id="wg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#b65f42" stop-opacity=".20"/><stop offset="100%" stop-color="#b65f42" stop-opacity="0"/></linearGradient></defs>' +
    grid + targetLine +
    '<path d="'+area+'" fill="url(#wg)" stroke="none"/>' +
    '<path d="'+line+'" fill="none" stroke="#b65f42" stroke-width="1.8"/>' +
    '<path d="'+maLine+'" fill="none" stroke="#4d3045" stroke-width="2.2" stroke-linejoin="round"/>' +
    dots + labels + '</svg>' +
    '<div style="position:absolute;top:2px;right:4px;font-size:9.5px;color:var(--muted)"><span style="color:#4d3045">━</span> 7 日均线 <span style="color:#b65f42">•</span> 每日体重</div>';
}

/* ---------- 日程 ---------- */
function renderPlanner(){
  var today = todayStr();
  Array.prototype.forEach.call($('plannerFilters').children, function(b){
    b.classList.toggle('solid', b.dataset.plannerFilter === view.planner);
  });
  var list = store.plan.slice();
  if (view.planner === 'pending') list = list.filter(function(p){ return !p.done; });
  if (view.planner === 'done') list = list.filter(function(p){ return p.done; });
  list.sort(function(a,b){
    if (a.done !== b.done) return a.done ? 1 : -1;
    return (a.date + (a.start||'')).localeCompare(b.date + (b.start||''));
  });
  $('plannerList').innerHTML = list.length ? list.map(function(p){
    var overdue = !p.done && p.date < today;
    var when = p.start ? (p.start + (p.end?('–'+p.end):'')) : '全天';
    return '<div class="task' + (p.done?' done':'') + '">' +
      '<button class="ck' + (p.done?' on':'') + '" data-action="task-toggle" data-id="' + esc(p.id) + '" aria-label="切换完成">' + (p.done?icon('i-check'):'') + '</button>' +
      '<span class="pri ' + esc(p.pri) + '"></span>' +
      '<span class="body"><strong>' + esc(p.title) + '</strong><small>' + esc(fmtDay(p.date)) + ' · ' + esc(p.list) + ' · ' + when + '</small></span>' +
      '<span class="when' + (overdue?' overdue':'') + '">' + (overdue?'已逾期':esc(p.date.slice(5))) + '</span>' +
      '<button class="icon-btn" data-action="del" data-table="plan" data-id="' + esc(p.id) + '" aria-label="删除">' + icon('i-trash') + '</button></div>';
  }).join('') : '<div class="empty">这个筛选下暂时没有日程</div>';
}

/* ---------- 采购 ---------- */
function renderShopping(){
  Array.prototype.forEach.call($('shoppingFilters').children, function(b){
    b.classList.toggle('solid', b.dataset.shoppingFilter === view.shopping);
  });
  var list = store.shopping.slice();
  if (view.shopping === 'pending') list = list.filter(function(s){ return !s.bought; });
  if (view.shopping === 'bought') list = list.filter(function(s){ return s.bought; });
  list.sort(function(a,b){ return (a.bought?1:0)-(b.bought?1:0); });
  $('shoppingList').innerHTML = list.length ? list.map(function(s){
    return '<div class="shop-item' + (s.bought?' bought':'') + '">' +
      '<button class="ck' + (s.bought?' on':'') + '" style="width:20px;height:20px;border-radius:6px;border:1.5px solid var(--line);display:grid;place-items:center;' + (s.bought?'background:var(--sage);border-color:var(--sage);color:#fff':'') + '" data-action="shop-toggle" data-id="' + esc(s.id) + '" aria-label="切换">' + (s.bought?icon('i-check'):'') + '</button>' +
      '<span class="n">' + esc(s.name) + '<small>' + s.qty + ' 件 · ' + esc(s.cat) + (s.note?(' · ' + esc(s.note)):'') + '</small></span>' +
      '<span class="p">' + (s.price ? money(s.price*s.qty) : '—') + '</span>' +
      '<button class="icon-btn" data-action="del" data-table="shopping" data-id="' + esc(s.id) + '" aria-label="删除">' + icon('i-trash') + '</button></div>';
  }).join('') : '<div class="empty">清单是空的，去添加第一件吧</div>';

  var pend = store.shopping.filter(function(s){ return !s.bought; });
  var bought = store.shopping.filter(function(s){ return s.bought; });
  $('sPending').textContent = pend.length;
  $('sCost').textContent = money(pend.reduce(function(a,b){ return a + b.price*b.qty; },0));
  $('sBought').textContent = bought.length;
  $('sSpent').textContent = money(bought.reduce(function(a,b){ return a + b.price*b.qty; },0));
}

/* ---------- 书影音 ---------- */
function renderMedia(){
  Array.prototype.forEach.call($('mediaViewToggle').children, function(b){
    b.classList.toggle('on', b.dataset.mediaView === view.media);
  });
  $('mediaStatusFilter').value = view.mediaStatus;
  var list = store.media.slice();
  if (view.mediaStatus !== 'all') list = list.filter(function(m){ return m.status === view.mediaStatus; });
  list.sort(function(a,b){ return (b.rating||0)-(a.rating||0) || b.title.localeCompare(a.title); });

  if (!list.length) {
    $('mediaWrap').innerHTML = '<div class="empty">还没有收藏条目</div>';
  } else if (view.media === 'wall') {
    $('mediaWrap').innerHTML = '<div class="wall">' + list.map(function(m){
      var ph = m.title.slice(0,2);
      return '<div class="cover">' +
        (safeUrl(m.cover) ? '<img src="' + esc(safeUrl(m.cover)) + '" alt="' + esc(m.title) + '" loading="lazy" onerror="this.style.display=\'none\'">' : '<span class="ph">' + esc(ph) + '</span>') +
        (m.rating ? '<span class="stars">★ ' + m.rating + '</span>' : '') +
        '<button class="del" data-action="del" data-table="media" data-id="' + esc(m.id) + '" aria-label="删除">' + icon('i-trash') + '</button>' +
        '<span class="meta"><b>' + esc(m.title) + '</b><i>' + esc(m.type) + ' · ' + esc(m.status) + '</i></span></div>';
    }).join('') + '</div>';
  } else {
    $('mediaWrap').innerHTML = '<div class="rec-list media-list">' + list.map(function(m){
      return '<div class="rec"><span class="ico">' + icon('i-media') + '</span>' +
        '<span class="body"><strong>' + esc(m.title) + (m.rating?('  <span style="color:var(--terra);font-size:11px">★'+m.rating+'</span>'):'') + '</strong>' +
        '<small>' + esc(m.type) + ' · ' + esc(m.status) + (m.review?(' · ' + esc(m.review)):'') + '</small></span>' +
        '<button class="icon-btn" data-action="del" data-table="media" data-id="' + esc(m.id) + '" aria-label="删除">' + icon('i-trash') + '</button></div>';
    }).join('') + '</div>';
  }

  var year = String(new Date().getFullYear());
  var finished = store.media.filter(function(m){ return m.status === '看完' && (m.doneDate||'').slice(0,4) === year; });
  var doing = store.media.filter(function(m){ return m.status === '在看'; });
  var rated = store.media.filter(function(m){ return m.rating > 0; });
  $('mdYear').textContent = finished.length || store.media.filter(function(m){ return m.status==='看完'; }).length;
  $('mdDoing').textContent = doing.length;
  $('mdAvg').textContent = rated.length ? (rated.reduce(function(s,m){ return s+m.rating; },0)/rated.length).toFixed(1) : '—';
  $('mdTotal').textContent = store.media.length;
  var byType = {};
  store.media.forEach(function(m){ byType[m.type] = (byType[m.type]||0) + 1; });
  $('mdTypes').textContent = Object.keys(byType).length ? Object.keys(byType).map(function(k){ return k + ' ' + byType[k]; }).join(' · ') : '';
}

/* =========================================================
   写操作（全部落云端，成功后再刷新视图）
   ========================================================= */
var weeklyPlan = DEFAULT_PLAN.map(function(p){ return { title:p.title, group:p.group, note:p.note, done:false }; });

function afterWrite(msg){
  clearErr();
  toast(msg || '已保存到云端');
  return refreshAll(true);
}

/* 新增/更新一条习惯打卡 */
function upsertHabit(name, date, value, def){
  var target = null;
  store.habit.forEach(function(h){ if (h.name === name && h.date === date) target = h; });
  var props = {};
  var f = META.habit.fields;
  props[f.date] = { date: date };
  props[f.name] = { text: name };
  props[f.value] = { number: num(value) };
  if (def) {
    props[f.mode] = { select: def.mode };
    props[f.target] = { number: num(def.target) };
    props[f.unit] = { text: def.unit };
  }
  var p = target ? updateRecord('habit', target.id, props) : addRecord('habit', props);
  return guarded(p, '保存打卡');
}

/* =========================================================
   表单输入与图片：全部不落本地
   本应用的数据唯一真源是云端 CSV 数据表。
   未提交的表单内容只存在于当前页面内存，刷新即消失——
   这是有意设计，用于保证「数据只在云端」，不做任何本地缓存。
   ========================================================= */
function clearDraft(){ /* 无本地缓存可清理：保持空实现，供调用点复用 */ }
function bindDraftCache(){ /* 不绑定本地草稿：所有输入仅存于当前页面内存 */ }
function restorePendingCover(){ /* 不做封面暂存恢复：图片需在本次会话内直接提交 */ }
function idbClear(){ return Promise.resolve(true); }

/* 封面选择：只保留内存引用，不写 IndexedDB／localStorage */
function bindCoverCache(){
  var input = document.querySelector('#mediaForm [name="cover"]');
  if (!input) return;
  input.addEventListener('change', function(){
    var f = input.files && input.files[0];
    if (!f) { pendingMediaFile = null; return; }
    if (f.size > 10*1024*1024) {
      toast('封面请小于 10MB', true);
      input.value = '';
      pendingMediaFile = null;
      return;
    }
    pendingMediaFile = f;
  });
}

/* =========================================================
   事件绑定
   ========================================================= */
function bindForms(){
  // 记账
  $('moneyForm').addEventListener('change', function(e){
    if (e.target.name === 'flow') renderMoney();
  });
  $('moneyForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var amount = num(fd.get('amount'));
    if (!(amount > 0)) { toast('请输入有效金额', true); return; }
    var btn = e.currentTarget.querySelector('[type="submit"]');
    btn.disabled = true;
    var f = META.money.fields;
    var props = {};
    props[f.date] = { date: fd.get('date') || todayStr() };
    props[f.flow] = { select: fd.get('flow') };
    props[f.cat] = { text: fd.get('category') };
    props[f.amount] = { currency: amount };
    props[f.note] = { text: String(fd.get('note')||'').trim() };
    guarded(addRecord('money', props), '保存收支')
      .then(function(){ clearDraft($('moneyForm')); $('moneyForm').reset(); setDateDefaults(); afterWrite('已记一笔'); })
      .catch(function(){})
      .then(function(){ btn.disabled = false; });
  });

  // 健身
  $('fitnessForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var w = num(fd.get('weight'));
    if (!(w > 0)) { toast('请填写体重', true); return; }
    var btn = e.currentTarget.querySelector('[type="submit"]');
    btn.disabled = true;
    var f = META.fitness.fields;
    var props = {};
    props[f.date] = { date: fd.get('date') || todayStr() };
    props[f.weight] = { number: w };
    var fat = num(fd.get('bodyFat'));
    if (fat > 0) props[f.fat] = { number: fat };
    props[f.note] = { text: String(fd.get('note')||'').trim() };
    guarded(addRecord('fitness', props), '保存身体数据')
      .then(function(){ clearDraft($('fitnessForm')); $('fitnessForm').reset(); setDateDefaults(); afterWrite('身体数据已记录'); })
      .catch(function(){})
      .then(function(){ btn.disabled = false; });
  });

  // 日程
  $('plannerForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var title = String(fd.get('title')||'').trim();
    if (!title) { toast('请填写日程内容', true); return; }
    var btn = e.currentTarget.querySelector('[type="submit"]');
    btn.disabled = true;
    var f = META.plan.fields;
    var props = {};
    props[f.date] = { date: fd.get('date') || todayStr() };
    props[f.title] = { text: title };
    props[f.list] = { text: fd.get('list') || '生活' };
    props[f.status] = { text: '待完成' };
    props[f.done] = { checkbox: false };
    props[f.start] = { text: String(fd.get('start')||'') };
    props[f.end] = { text: String(fd.get('end')||'') };
    props[f.pri] = { select: fd.get('priority') || 'normal' };
    guarded(addRecord('plan', props), '保存日程')
      .then(function(){ clearDraft($('plannerForm')); $('plannerForm').reset(); setDateDefaults(); afterWrite('日程已添加'); })
      .catch(function(){})
      .then(function(){ btn.disabled = false; });
  });

  // 采购
  $('shoppingForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var name = String(fd.get('name')||'').trim();
    if (!name) { toast('请填写物品名称', true); return; }
    var btn = e.currentTarget.querySelector('[type="submit"]');
    btn.disabled = true;
    var f = META.shopping.fields;
    var props = {};
    props[f.name] = { text: name };
    props[f.qty] = { number: Math.max(1, num(fd.get('quantity'),1)) };
    props[f.price] = { currency: num(fd.get('price')) };
    props[f.bought] = { text: '待买' };
    props[f.cat] = { select: fd.get('category') || '其他' };
    props[f.note] = { text: String(fd.get('note')||'').trim() };
    guarded(addRecord('shopping', props), '保存采购项')
      .then(function(){ clearDraft($('shoppingForm')); $('shoppingForm').reset(); afterWrite('已加入待买清单'); })
      .catch(function(){})
      .then(function(){ btn.disabled = false; });
  });

  // 书影音
  $('mediaForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var name = String(fd.get('name')||'').trim();
    if (!name) { toast('请填写标题', true); return; }
    var btn = e.currentTarget.querySelector('[type="submit"]');
    btn.disabled = true;
    var fileInput = e.currentTarget.querySelector('[name="cover"]');
    var file = fileInput.files && fileInput.files[0];
    var f = META.media.fields;
    var upped = Promise.resolve(null);
    if (file) {
      var d = db();
      if (!d || !d.uploadImage) { toast('云端暂不支持封面上传，已跳过封面', true); }
      else if (file.size > 10*1024*1024) { toast('封面请小于 10MB', true); btn.disabled = false; return; }
      else {
        upped = new Promise(function(res, rej){
          var rd = new FileReader();
          rd.onload = function(){ res(String(rd.result).split(',')[1] || ''); };
          rd.onerror = function(){ rej(new Error('读取图片失败')); };
          rd.readAsDataURL(file);
        }).then(function(b64){
          return window.__SMART_PAGE__.database.uploadImage({ data:b64, contentType:file.type, fileName:file.name });
        }).then(function(r){
          if (!r || !r.url) throw new Error('封面上传未返回地址');
          return r.url;
        });
      }
    }
    upped.then(function(coverUrl){
      var props = {};
      props[f.title] = { text: name };
      props[f.type] = { text: fd.get('type') || '电影' };
      props[f.status] = { text: fd.get('status') || '想看' };
      props[f.rating] = { number: num(fd.get('rating')) };
      props[f.review] = { text: String(fd.get('review')||'').trim() };
      if (coverUrl) props[f.cover] = { image: { images: [{ title:name, imageUrl:coverUrl }] } };
      if (fd.get('status') === '看完') props[f.doneDate] = { date: todayStr() };
      return guarded(addRecord('media', props), '保存收藏');
    }).then(function(){
      clearDraft($('mediaForm'));
      idbClear();
      pendingMediaFile = null;
      $('mediaForm').reset();
      afterWrite('已加入收藏');
    }).catch(function(err){
      if (err && err.message && err.message.indexOf('封面')>=0) {
        showErr('封面上传失败，本条未保存。可去掉封面后重试。');
        toast('封面上传失败', true);
      }
    }).then(function(){ btn.disabled = false; });
  });

  // 预算
  $('budgetInput').addEventListener('change', function(e){
    var v = Math.max(0, num(e.target.value));
    settings.budget = v;
    saveSetting('月度预算', v, '保存预算').then(function(){ return refreshAll(true); }).then(function(){ toast('预算已更新'); }).catch(function(){});
  });

  // 筛选
  $('moneyFilter').addEventListener('change', function(e){
    view.money = e.target.value;
    renderMoney();
  });
  $('plannerFilters').addEventListener('click', function(e){
    var b = e.target.closest('[data-planner-filter]');
    if (!b) return;
    view.planner = b.dataset.plannerFilter;
    renderPlanner();
  });
  $('shoppingFilters').addEventListener('click', function(e){
    var b = e.target.closest('[data-shopping-filter]');
    if (!b) return;
    view.shopping = b.dataset.shoppingFilter;
    renderShopping();
  });
  $('mediaStatusFilter').addEventListener('change', function(e){
    view.mediaStatus = e.target.value;
    renderMedia();
  });
  $('mediaViewToggle').addEventListener('click', function(e){
    var b = e.target.closest('[data-media-view]');
    if (!b) return;
    view.media = b.dataset.mediaView;
    renderMedia();
  });

  // 习惯新增
  $('habitType').addEventListener('change', function(e){
    var f = $('habitForm');
    if (e.target.value === 'check') { f.elements.target.value = 1; f.elements.unit.value = '次'; }
  });
  $('habitForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var name = String(fd.get('name')||'').trim();
    if (!name) { toast('请填写习惯名称', true); return; }
    if (store.habit.some(function(h){ return h.name === name; })) { toast('这个习惯已经存在', true); return; }
    var mode = fd.get('type');
    var target = mode==='check' ? 1 : Math.max(0.1, num(fd.get('target'),1));
    var unit = mode==='check' ? '次' : (String(fd.get('unit')||'').trim() || '次');
    upsertHabit(name, todayStr(), 0, { mode:mode, target:target, unit:unit })
      .then(function(){ e.currentTarget.reset(); e.currentTarget.elements.target.value = 1; e.currentTarget.elements.unit.value = '次'; return afterWrite('新习惯已加入'); })
      .then(function(){ renderHabitManage(); })
      .catch(function(){});
  });

  // 健身目标
  $('profileForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var vals = {
      '身高': num(fd.get('height'),165),
      '目标体重': num(fd.get('target'),55),
      '起始体重': num(fd.get('start'),60),
      '年龄': num(fd.get('age'),30),
      '生理性别': fd.get('sex') || '女',
      '活动系数': fd.get('activity') || '1.375'
    };
    Promise.all(Object.keys(vals).map(function(k){ return saveSetting(k, vals[k], '保存设置'); }))
      .then(function(){ closeSheet('profileSheet'); return afterWrite('目标设置已更新'); })
      .catch(function(){});
  });

  // 训练计划
  $('planForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var title = String(fd.get('title')||'').trim();
    if (!title) { toast('请填写计划内容', true); return; }
    weeklyPlan.push({ title:title, group:fd.get('group')||'运动', note:String(fd.get('note')||'').trim(), done:false });
    e.currentTarget.reset();
    renderFitness();
    renderPlanManage();
    toast('计划已加入');
  });

  // 外观
  $('brandForm').addEventListener('submit', function(e){
    e.preventDefault();
    var fd = new FormData(e.currentTarget);
    var name = String(fd.get('name')||'').trim() || '小笑肖';
    var avatar = String(fd.get('avatar')||'').trim() || '笑';
    var tagline = String(fd.get('tagline')||'').trim() || '把生活安放得井井有条';
    Promise.all([
      saveSetting('页面名称', name, '保存外观'),
      saveSetting('副标题', tagline, '保存外观')
    ]).then(function(){
      settings.avatar = avatar;
      applyBrand();
      closeSheet('brandSheet');
      afterWrite('外观已更新');
    }).catch(function(){});
  });
}

function bindEvents(){
  // 导航
  document.addEventListener('click', function(e){
    var nav = e.target.closest('[data-nav]');
    if (nav) { switchView(nav.dataset.nav); return; }
    var quick = e.target.closest('[data-quick-to]');
    if (quick) { switchView(quick.dataset.quickTo); return; }
    var act = e.target.closest('[data-action]');
    if (act) { handleAction(act, e); }
  });

  document.addEventListener('change', function(e){
    var t = e.target;
    if (t.dataset && t.dataset.action === 'habit-number') {
      handleHabitNumber(t);
    }
  });

  // ESC 关弹层
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') {
      ['habitSheet','profileSheet','planSheet','brandSheet'].forEach(closeSheet);
    }
  });

  // 弹层背景点击关闭
  ['habitSheet','profileSheet','planSheet','brandSheet'].forEach(function(id){
    $(id).addEventListener('click', function(e){
      if (e.target.id === id) closeSheet(id);
    });
  });
}

function handleAction(el, e){
  var a = el.dataset.action;
  var table = el.dataset.table;
  var id = el.dataset.id;

  if (a === 'refresh' || a === 'retry') { refreshAll(); return; }
  if (a === 'open-habit') { renderHabitManage(); openSheet('habitSheet'); return; }
  if (a === 'open-profile') { fillProfileForm(); openSheet('profileSheet'); return; }
  if (a === 'open-plan') { renderPlanManage(); openSheet('planSheet'); return; }
  if (a === 'open-brand') { fillBrandForm(); openSheet('brandSheet'); return; }
  if (a === 'close-sheet') { closeSheet(el.dataset.sheet); return; }

  if (a === 'del') {
    if (!id || !table) return;
    var label = el.closest('.rec, .task, .shop-item, .cover');
    if (!window.confirm('确定删除这条记录吗？删除后会同时从云端数据表移除。')) return;
    guarded(deleteRecord(table, id), '删除记录')
      .then(function(){ return afterWrite('已删除'); })
      .catch(function(){});
    return;
  }

  if (a === 'task-toggle') {
    var task = null;
    store.plan.forEach(function(p){ if (p.id === id) task = p; });
    if (!task) return;
    var f = META.plan.fields;
    var props = {};
    props[f.done] = { checkbox: !task.done };
    props[f.status] = { text: task.done ? '待完成' : '已完成' };
    guarded(updateRecord('plan', id, props), '更新日程')
      .then(function(){ return afterWrite(task.done ? '已改回待完成' : '完成一项'); })
      .catch(function(){});
    return;
  }

  if (a === 'shop-toggle') {
    var item = null;
    store.shopping.forEach(function(s){ if (s.id === id) item = s; });
    if (!item) return;
    var sf = META.shopping.fields;
    var sp = {};
    sp[sf.bought] = { text: item.bought ? '待买' : '已买' };
    guarded(updateRecord('shopping', id, sp), '更新采购项')
      .then(function(){ return afterWrite(item.bought ? '已改回待买' : '买到了'); })
      .catch(function(){});
    return;
  }

  if (a === 'plan-toggle') {
    var idx = parseInt(el.dataset.idx, 10);
    if (!weeklyPlan[idx]) return;
    weeklyPlan[idx].done = !weeklyPlan[idx].done;
    renderFitness();
    return;
  }

  // 习惯相关
  var name = el.dataset.name;
  if (a === 'habit-toggle' || a === 'habit-plus' || a === 'habit-minus' || a === 'habit-quick') {
    var groups = habitGroups();
    var g = null;
    groups.forEach(function(x){ if (x.name === name) g = x; });
    if (!g) return;
    var v = g.todayVal;
    if (a === 'habit-toggle') v = g.todayVal >= g.target ? 0 : g.target;
    if (a === 'habit-quick')  v = g.todayVal >= g.target ? 0 : g.target;
    if (a === 'habit-plus')   v = g.todayVal + 1;
    if (a === 'habit-minus')  v = Math.max(0, g.todayVal - 1);
    var def = { mode:g.mode, target:g.target, unit:g.unit };
    guarded(upsertHabit(name, todayStr(), v, g.virtual ? def : null), '保存打卡')
      .then(function(){ return afterWrite(v >= g.target ? (name + ' 已完成') : '打卡已更新'); })
      .catch(function(){});
    return;
  }
}

function handleHabitNumber(input){
  var name = input.dataset.name;
  var val = Math.max(0, num(input.value));
  var groups = habitGroups();
  var g = null;
  groups.forEach(function(x){ if (x.name === name) g = x; });
  if (!g) return;
  guarded(upsertHabit(name, todayStr(), val, g.virtual ? { mode:g.mode, target:g.target, unit:g.unit } : null), '保存打卡')
    .then(function(){ return afterWrite('数值已保存'); })
    .catch(function(){});
}

function renderHabitManage(){
  var groups = habitGroups().filter(function(g){ return !g.virtual; });
  $('habitManageList').innerHTML = groups.length ? groups.map(function(g){
    return '<div class="manage-row"><span class="m"><strong>' + esc(g.name) + '</strong><small>' +
      (g.mode==='check'?'勾选打卡':g.mode==='counter'?'计数累加':'数值填写') + ' · 目标 ' + fmtNum(g.target) + ' ' + esc(g.unit) + ' · ' + g.records.length + ' 条记录</small></span>' +
      '<button class="icon-btn" data-action="del-habit" data-name="' + esc(g.name) + '" aria-label="删除习惯">' + icon('i-trash') + '</button></div>';
  }).join('') : '<div class="empty">还没有自定义习惯</div>';
  // 绑定删除习惯（整组记录）
  Array.prototype.forEach.call($('habitManageList').querySelectorAll('[data-action="del-habit"]'), function(btn){
    btn.addEventListener('click', function(){
      var nm = btn.dataset.name;
      if (!window.confirm('删除习惯「' + nm + '」及其全部打卡记录？此操作会同时清理云端数据。')) return;
      var recs = store.habit.filter(function(h){ return h.name === nm; });
      Promise.all(recs.map(function(r){ return deleteRecord('habit', r.id); }))
        .then(function(){ return afterWrite('习惯已删除'); })
        .then(function(){ renderHabitManage(); })
        .catch(function(){ showErr('删除习惯失败，请重试。'); });
    });
  });
}

function renderPlanManage(){
  $('planManageList').innerHTML = weeklyPlan.length ? weeklyPlan.map(function(p, i){
    return '<div class="manage-row"><span class="m"><strong>' + esc(p.title) + '</strong><small>' + esc(p.group) + (p.note?(' · ' + esc(p.note)):'') + '</small></span>' +
      '<button class="icon-btn" data-action="del-plan" data-idx="' + i + '" aria-label="删除计划">' + icon('i-trash') + '</button></div>';
  }).join('') : '<div class="empty">还没有计划</div>';
  Array.prototype.forEach.call($('planManageList').querySelectorAll('[data-action="del-plan"]'), function(btn){
    btn.addEventListener('click', function(){
      weeklyPlan.splice(parseInt(btn.dataset.idx,10), 1);
      renderFitness(); renderPlanManage();
    });
  });
}

function fillProfileForm(){
  var f = $('profileForm');
  f.elements.height.value = settings.height;
  f.elements.target.value = settings.target;
  f.elements.start.value = settings.start;
  f.elements.age.value = settings.age;
  f.elements.sex.value = settings.sex;
  f.elements.activity.value = String(settings.activity);
}
function fillBrandForm(){
  var f = $('brandForm');
  f.elements.name.value = settings.name || '小笑肖';
  f.elements.avatar.value = settings.avatar || '笑';
  f.elements.tagline.value = settings.tagline || '把生活安放得井井有条';
}
function openSheet(id){ $(id).hidden = false; }
function closeSheet(id){ var el = $(id); if (el) el.hidden = true; }

function switchView(name){
  var target = $('view-' + name);
  if (!target) return;
  Array.prototype.forEach.call(document.querySelectorAll('.view'), function(v){ v.classList.toggle('active', v === target); });
  Array.prototype.forEach.call(document.querySelectorAll('[data-nav]'), function(n){ n.classList.toggle('active', n.dataset.nav === name); });
  $('viewTitle').textContent = target.dataset.title || '今日概览';
  if (location.hash !== '#' + name) {
    try { history.replaceState(null, '', '#' + name); } catch(e){}
  }
  window.scrollTo({ top:0, behavior:'smooth' });
  if (name === 'fitness') { try { renderFitness(); } catch(e){} }
}

function setDateDefaults(){
  Array.prototype.forEach.call(document.querySelectorAll('input[type="date"]'), function(i){
    if (!i.value) i.value = todayStr();
  });
}

/* =========================================================
   双向同步：轮询云端，外部改表后自动刷新
   ========================================================= */
function startSync(){
  var POLL = 20000;
  store.clock = setInterval(function(){
    if (document.hidden) return;
    if (store.refreshing) return;
    refreshAll(true).then(function(){
      store.clockTick = true;
    }, function(){});
  }, POLL);
  document.addEventListener('visibilitychange', function(){
    if (!document.hidden && store.loaded) refreshAll(true);
  });
}

/* =========================================================
   启动：先渲染完整 UI，再异步拉取云端
   ========================================================= */
function init(){
  var now = new Date();
  var wd = ['星期日','星期一','星期二','星期三','星期四','星期五','星期六'];
  $('todayLabel').textContent = (now.getMonth()+1) + ' 月 ' + now.getDate() + ' 日 · ' + wd[now.getDay()];

  setDateDefaults();
  bindDraftCache();
  bindCoverCache();
  restorePendingCover();
  applyBrand();
  // 首屏：立刻用空数据渲染骨架，杜绝白屏
  renderAll();
  bindForms();
  bindEvents();

  var hash = (location.hash || '').replace('#','');
  switchView($('view-' + hash) ? hash : 'dashboard');

  if (!db()) {
    showErr('云端连接尚未就绪，页面已正常显示。请刷新页面重试。');
    setSync('err','未连接云端');
    return;
  }
  setSync('busy','正在同步云端');
  refreshAll(true).then(function(){ startSync(); }, function(){ startSync(); });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
})();
