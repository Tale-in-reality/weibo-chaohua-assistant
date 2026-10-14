/* 微博超话助手 · 前端逻辑 */

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

const esc = (s) => String(s ?? '').replace(/[&<>"]/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(path, opts = {}) {
  // X-Requested-With 是后端防 CSRF 的凭据（第三方网页无法自定义这个头）
  const o = { headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }, ...opts };
  if (o.body && typeof o.body !== 'string') o.body = JSON.stringify(o.body);
  let r;
  try {
    r = await fetch(path, o);
  } catch (e) {
    // fetch 直接 reject = 连不上后端（服务没起来 / 端口被占 / 进程已死）
    throw new Error('连不上本地后端 —— 服务可能没起来（端口被占？），重启 app 试试');
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

let _toastTimer;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.classList.remove('show'), 2800);
}

/* ---------------- 主题：黑场 / 场灯 ---------------- */

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  const l = $('#theme-label');
  if (l) l.textContent = t === 'light' ? '场灯' : '黑场';
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  try { localStorage.setItem('theme', next); } catch (e) { /* 忽略 */ }
  applyTheme(next);
}

async function quitApp() {
  if (!confirm('退出「微博超话助手」？\n定时抓取 / 推送也会一并停止。')) return;
  try {
    await api('/api/quit', { method: 'POST' });   // 关窗口 + 停托盘 + 结束进程
  } catch (e) { /* 进程可能已退出，忽略 */ }
  // 兜底提示（正常情况窗口此时已被关掉）
  document.body.innerHTML =
    '<div class="empty" style="margin:80px auto;max-width:420px">已退出，可关闭此窗口。</div>';
}

/* ---- 点 × 的选择框（由后端 evaluate_js 唤起） ---- */

function showCloseDialog() {
  const m = $('#close-modal');
  if (m) m.hidden = false;
}

function closeCancel() {
  const m = $('#close-modal');
  if (m) m.hidden = true;
}

async function closeChoose(action) {
  const remember = $('#close-remember').checked;
  $('#close-modal').hidden = true;
  try {
    await api('/api/window/close', { method: 'POST', body: { action, remember } });
  } catch (e) { /* 退出时连接会断，忽略 */ }
}

/* 首屏前定色：先读本地偏好，没有再跟随系统 */
let SAVED_THEME = null;
try { SAVED_THEME = localStorage.getItem('theme'); } catch (e) { /* 忽略 */ }
applyTheme(
  (SAVED_THEME === 'light' || SAVED_THEME === 'dark') ? SAVED_THEME
    : (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
);

/* ---------------- 导航 ---------------- */

const PAGES = {
  dashboard: loadDashboard, write: loadWrite,
  captions: () => showCaptionTab(_capTab),   // 文案库：未确认 ⇄ 已确认
  style: loadStyle,
  terms: () => showTermTab(_termTab),            // 术语：未确认 ⇄ 已确认
  events: () => showEventTab(_eventStatus),      // 事件：未确认 ⇄ 已确认
  push: loadPush, settings: loadSettings,
};
let _focusEvent = null;          // 深链 #events/<id> 要展开并高亮的事件

function go(page) {
  $$('#nav a').forEach((a) => a.classList.toggle('active', a.dataset.page === page));
  $$('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + page));
  (PAGES[page] || (() => {}))();
}

document.addEventListener('DOMContentLoaded', () => {
  $$('#nav a').forEach((a) => (a.onclick = () => go(a.dataset.page)));
  // 支持 #events/<id> 深链（推送弹窗点进来直达某条）
  const [page, arg] = (location.hash || '#dashboard').slice(1).split('/');
  if (page === 'events' && arg) _focusEvent = Number(arg) || null;
  go(page || 'dashboard');
  // 每次打开 app 都核一遍登录态和已选超话，避免显示陈旧状态
  qrCheckLogin();
  refreshChaohua();
  checkSetup(true);        // 缺环境（没装 Ollama / 没拉模型）就自动弹首启向导
  startFetchWatch();       // 打开后就盯一会儿 —— 定时/开机补抓一开始就能看到进度
  window.addEventListener('hashchange', () => {
    const [p, a] = (location.hash || '#dashboard').slice(1).split('/');
    if (p === 'events' && a) _focusEvent = Number(a) || null;
    go(p || 'dashboard');
  });
});

/* ---------------- 概览 ---------------- */

async function loadDashboard() {
  let d;
  try { d = await api('/api/dashboard'); } catch (e) { toast('加载失败：' + e.message); return; }
  const c = d.counts;
  const next = d.next_runs.push ? d.next_runs.push.slice(11, 16) : '—';
  const S = d.settings || {};
  const chao = S.weibo_container_name || '';
  const lastFetch = d.last_fetch ? d.last_fetch.slice(5, 16) : '从未';
  const autoOn = S.weibo_fetch_enabled === '1';
  $('#dash-status').innerHTML =
    `<span>文案<b>${c.captions}</b></span>`
    + `<span>术语<b>${c.terms}</b></span>`
    + `<span>事件<b>${c.events}</b></span>`
    + `<span>今日新增<b>${c.events_today}</b></span>`
    + `<span>待确认<b>${c.pending_events}</b></span>`
    + `<span>当前超话<b>${esc(chao || '未选')}</b></span>`
    + `<span>自动抓取<b>${autoOn ? '开' : '关'}</b></span>`
    + `<span>上次抓取<b>${esc(lastFetch)}</b></span>`
    + `<span>下次推送<b>${esc(next)}</b></span>`;

  // 抓取没开 / 没配好 —— 这是「推送一直没动静」的头号原因，必须显眼提示
  const cfgBox = $('#dash-fetchcfg');
  if (cfgBox) {
    const configured = !!(S.weibo_cookie && S.weibo_containerid);
    if (autoOn) {
      cfgBox.hidden = true;
    } else if (!configured) {
      cfgBox.hidden = false;
      cfgBox.innerHTML = '<label>定时抓取还没配置</label>'
        + '<div class="desc">要自动抓超话，得先在「推送」页扫码登录（<b>用小号</b>）并选定超话。'
        + '抓到新帖才会生成事件与速览，<b>推送才有内容</b>。</div>'
        + '<div class="actions"><button class="primary" onclick="go(\'push\')">去配置抓取</button></div>';
    } else {
      cfgBox.hidden = false;
      cfgBox.innerHTML = '<label>⚠ 定时抓取未开启</label>'
        + '<div class="desc">超话要<b>抓取</b>才有新帖 → 才会生成事件与速览 → <b>推送才有内容</b>。'
        + '现在「自动抓取」是关的（它和「桌面推送」是两个独立开关），所以不会自动更新，推送也一直没有新东西可推。</div>'
        + '<div class="actions">'
        + '<button class="primary" onclick="enableAutoFetch()">开启定时抓取（并立刻补抓一次）</button>'
        + '<button class="ghost" onclick="go(\'settings\')">去设置</button>'
        + '</div>';
    }
  }

  const todo = [];
  if (c.pending_events) todo.push(['待确认事件 ' + c.pending_events, '自动总结出的事件，等你确认或删除', 'events']);
  if (c.candidates) todo.push(['待校准候选 ' + c.candidates, '给抽取出的候选词写释义——含义你说了算', 'review']);
  if (c.pending_posts) todo.push(['未处理帖 ' + c.pending_posts, '去「推送」页跑一次总结', 'push']);
  $('#dash-todo').innerHTML = todo.length
    ? todo.map((x) => `<div class="item"><div class="body"><div class="title">${esc(x[0])}</div>`
      + `<div class="desc">${esc(x[1])}</div></div>`
      + `<div class="ops"><button class="tiny" onclick="go('${x[2]}')">前往</button></div></div>`).join('')
    : '<div class="empty">没有待办的 Cue。一切都已确认。</div>';

  const m = d.model;
  $('#dash-model').innerHTML = m.ok
    ? `模型：<b>${esc(m.model)}</b> ${m.model_ready ? '<span class="tag likely">已就绪</span>' : '<span class="tag maybe">未找到该模型</span>'}`
    : `未连上 Ollama（${esc(m.url)}）。请先启动 Ollama，并拉取模型：<code>ollama pull qwen2.5:7b-instruct</code>`;
}

/* ---------------- 首启环境向导（Ollama / 模型 / WebView2） ---------------- */

let SETUP = null;         // 最近一次 /api/setup/check 结果
let _setupTimer = null;   // 安装/下载进度轮询

async function checkSetup(auto) {
  try { SETUP = await api('/api/setup/check'); } catch (e) { SETUP = null; }
  renderSetup();
  renderEnvCard();
  // 有正在跑的任务 → 接着轮询进度
  try {
    const st = await api('/api/setup/status');
    if (st && st.task && !st.done) startSetupPoll();
  } catch (e) { /* 忽略 */ }
  if (auto && SETUP && SETUP.needs_setup && !SETUP.wizard_done) showWizard();
}

function recheckSetup() {
  toast('检测中…');
  checkSetup(false).then(() => toast('已重新检测'));
}

function showWizard() { const w = $('#setup-wizard'); if (w) w.hidden = false; }
function hideWizard() { const w = $('#setup-wizard'); if (w) w.hidden = true; }

async function skipWizard() {
  try { await api('/api/setup/done', { method: 'POST', body: { done: true } }); } catch (e) { /* 忽略 */ }
  hideWizard();
}

async function finishWizard() {
  try { await api('/api/setup/done', { method: 'POST', body: { done: true } }); } catch (e) { /* 忽略 */ }
  hideWizard();
  toast('环境已就绪');
}

function _stepRow(ok, title, desc) {
  const mark = ok ? '<span class="ok">✔</span>' : '<span class="no">✖</span>';
  return `<div class="item"><div class="body"><div class="title">${mark} ${esc(title)}</div>`
    + `<div class="desc">${esc(desc)}</div></div></div>`;
}

function renderSetup() {
  const steps = $('#setup-steps');
  const actions = $('#setup-actions');
  if (!steps || !actions || !SETUP) return;
  const s = SETUP;

  steps.innerHTML =
    _stepRow(s.ollama_running, '本地模型运行时（Ollama）',
      s.ollama_running ? '正在运行'
        : (s.ollama_installed ? '已安装，但没在运行 —— 启动 Ollama 再重新检测'
          : '还没安装 —— 点下面「一键下载并安装」'))
    + _stepRow(s.model_present, `模型 ${s.model}`,
      s.model_present ? '已就绪'
        : (s.ollama_running ? '还没下载 —— 点下面「一键下载模型」' : '等 Ollama 就绪后再下载'))
    + (s.webview2 ? '' : _stepRow(false, 'WebView2 运行时',
      '缺失（Win10/11 一般自带；缺失请装 Microsoft Edge WebView2 Runtime）'));

  const btns = [];
  if (!s.ollama_running) {
    const opts = (s.ollama_mirrors || ['官方'])
      .map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
    btns.push('<span class="desc" style="margin-right:6px">下载源</span>'
      + `<select id="setup-mirror" style="max-width:210px">${opts}</select>`);
    btns.push('<button class="primary" onclick="setupInstallOllama()">① 一键下载并安装 Ollama</button>');
    btns.push('<button onclick="recheckSetup()">我已自行安装，重新检测</button>');
  } else if (!s.model_present) {
    const opts = [s.default_model, ...(s.alt_models || [])]
      .map((m, i) => `<option value="${esc(m)}"${i === 0 ? ' selected' : ''}>${esc(m)}</option>`).join('');
    btns.push('<span class="desc" style="margin-right:6px">选模型</span>'
      + `<select id="setup-model" style="max-width:210px">${opts}</select>`);
    btns.push('<button class="primary" onclick="setupPullModel()">② 一键下载模型</button>');
  } else {
    btns.push('<button class="primary" onclick="finishWizard()">✓ 全部就绪，开始使用</button>');
  }
  btns.push('<button class="ghost" id="setup-cancel" onclick="setupCancel()" hidden>取消下载</button>');
  actions.innerHTML = btns.join('');
}

function renderEnvCard() {
  const el = $('#s-env-status');
  if (!el) return;
  if (!SETUP) { el.textContent = '检测失败（后端可能没起来，重启 app 试试）'; return; }
  const s = SETUP;
  el.textContent = [
    `Ollama：${s.ollama_running ? '运行中' : (s.ollama_installed ? '已装未运行' : '未安装')}`,
    `模型 ${s.model}：${s.model_present ? '就绪' : '未就绪'}`,
    `WebView2：${s.webview2 ? '已装' : '缺失'}`,
  ].join('　|　') + (s.needs_setup ? '　—— 建议走一遍「打开环境向导」' : '　—— 一切就绪');
}

async function setupInstallOllama() {
  const mirror = ($('#setup-mirror') || {}).value || '';
  const r = await api('/api/setup/install_ollama', { method: 'POST', body: { mirror } });
  if (!r.ok) { toast(r.error || '启动失败'); return; }
  startSetupPoll();
}

async function setupPullModel() {
  const model = ($('#setup-model') || {}).value || (SETUP && SETUP.default_model) || '';
  const r = await api('/api/setup/pull_model', { method: 'POST', body: { model } });
  if (!r.ok) { toast(r.error || '启动失败'); return; }
  startSetupPoll();
}

function setupCancel() {
  api('/api/setup/cancel', { method: 'POST' }).catch(() => { /* 忽略 */ });
  toast('正在取消…');
}

function startSetupPoll() {
  if (_setupTimer) return;
  const cancelBtn = $('#setup-cancel');
  if (cancelBtn) cancelBtn.hidden = false;
  _setupTimer = setInterval(async () => {
    let st;
    try { st = await api('/api/setup/status'); } catch (e) { return; }
    const bar = $('#setup-bar');
    if (bar) {
      bar.hidden = false;
      const i = bar.querySelector('i');
      if (i) i.style.width = (st.done ? 100 : (st.percent || 0)) + '%';
    }
    const msg = $('#setup-msg');
    if (msg) msg.textContent = st.error ? ('✖ ' + st.error)
      : ((st.phase || '') + (st.message ? ' · ' + st.message : ''));
    if (st.done) {
      clearInterval(_setupTimer); _setupTimer = null;
      if (bar) bar.hidden = true;
      const cb = $('#setup-cancel'); if (cb) cb.hidden = true;
      if (!st.error) {
        toast('完成');
        await checkSetup(false);
        renderSetup();
      }
    }
  }, 1000);
}

/* ---------------- 写文案 ---------------- */

let TEMPLATES = [];

let _termsCache = [];

async function loadWrite() {
  TEMPLATES = await api('/api/templates');
  $('#w-template').innerHTML = TEMPLATES
    .map((t) => `<option value="${t.id}">${esc(t.name)} · ${esc(t.tpl_type)}</option>`).join('');
  onTemplateChange();
  onTemp();
  onLen();
  loadCues();
  try { _termsCache = await api('/api/terms'); } catch (e) { _termsCache = []; }
  loadRefSongs();
  try {
    const s = await api('/api/settings');
    VISION = {
      enabled: s.vision_enabled === '1',
      configured: !!(s.vision_base_url && s.vision_api_key && s.vision_model),
    };
    updateVisionBtn();
  } catch (e) { /* 忽略：识图非必需 */ }
}

function currentTpl() {
  const id = Number($('#w-template').value);
  return TEMPLATES.find((t) => t.id === id) || {};
}

function onTemplateChange() {
  $('#w-tpl-content').value = currentTpl().content || '';
}

function insertStylePlaceholder() {
  const ta = $('#w-tpl-content');
  if (ta.value.includes('{style}')) { toast('模板里已经有 {style} 了'); return; }
  ta.value = ta.value.trimEnd() + '\n\n{style}';
  toast('已插入 {style} —— 生成时会展开成风格档案，记得点「保存到当前模板」');
}

/* ---- 氛围预设：色片按钮 ---- */
function presetMood(v) {
  const el = $('#w-mood');
  const cur = el.value.trim();
  el.value = cur ? (cur.includes(v) ? cur : cur + '、' + v) : v;
}

/* ---- 推子：温度 / 长度 ---- */
function onTemp() {
  const r = $('#w-temp');
  const min = Number(r.min), max = Number(r.max), v = Number(r.value);
  r.style.setProperty('--v', ((v - min) / (max - min)) * 100 + '%');
  $('#w-temp-val').textContent = v.toFixed(2);
  // 温度是抽象值 —— 给个能看懂的说法
  const lvl = v < 0.55 ? '很稳（贴风格样本，几乎不发挥）'
    : v < 0.8 ? '偏稳（像本人，变化少）'
    : v < 1.0 ? '正常（像本人，略有变化）'
    : v < 1.2 ? '偏放飞（用词更跳）'
    : '放飞（容易跑偏，慎用）';
  const d = $('#w-temp-desc');
  if (d) d.textContent = lvl;
}

function onLen() {
  const r = $('#w-len');
  const min = Number(r.min), max = Number(r.max), v = Number(r.value);
  r.style.setProperty('--v', ((v - min) / (max - min)) * 100 + '%');
  $('#w-len-val').textContent = v + ' 字';
}

/* ---- 术语提示：写要点时按关键词给词典建议，点一下插进去 ---- */
function onPointsInput() {
  const hint = $('#w-term-hint');
  if (!hint) return;
  const text = $('#w-points').value;
  if (!text.trim()) { hint.innerHTML = ''; return; }
  const hits = _termsCache.filter((t) =>
    t.term && (text.includes(t.term) || (t.meaning || '').includes(text.slice(-6))))
    .slice(0, 6);
  hint.innerHTML = hits.length
    ? '词典里可能有用的词：' + hits.map((t) =>
      `<button class="tiny ghost" title="${esc(t.meaning)}" onclick="insertTerm('${esc(t.term)}')">${esc(t.term)}</button>`).join(' ')
    : '';
}

function insertTerm(term) {
  const pts = $('#w-points');
  const cur = pts.value.trim();
  pts.value = cur && !cur.includes(term) ? cur + ' ' + term : cur || term;
  onPointsInput();
}

/* ---- Cue 库：上光时能调用的梗与事件 ---- */
async function loadCues() {
  const el = $('#w-cues');
  try {
    const [terms, ev] = await Promise.all([api('/api/terms'), api('/api/events?limit=5')]);
    const events = ev.items || [];        // /api/events 返回的是分页对象，不是数组
    const rows = [];
    terms.slice(0, 4).forEach((t) => rows.push(
      `<div class="item"><div class="body"><div class="title">${esc(t.term)} <span class="tag">${esc(t.term_type)}</span></div>`
      + `<div class="desc">${esc(t.meaning)}</div></div></div>`));
    events.slice(0, 3).forEach((e) => rows.push(
      `<div class="item"><div class="body"><div class="title">${esc(e.title)} ${e.status === 'pending' ? '<span class="tag pending">待确认</span>' : ''}</div>`
      + `<div class="desc">${esc(e.description)}</div></div></div>`));
    el.innerHTML = rows.length ? rows.join('')
      : '<div class="empty">还没有 Cue。去「术语词典」「事件库」喂进梗与事件——这里是上光时能调用的灯。</div>';
  } catch (e) {
    el.innerHTML = '<div class="empty">Cue 库读取失败</div>';
  }
}

async function saveTemplate() {
  const tpl = currentTpl();
  if (!tpl.id) return;
  await api('/api/templates/' + tpl.id, {
    method: 'PUT',
    body: { name: tpl.name, tpl_type: tpl.tpl_type, content: $('#w-tpl-content').value },
  });
  toast('模板已保存');
  TEMPLATES = await api('/api/templates');
}

async function saveTemplateAs() {
  const name = prompt('新模板名称：');
  if (!name) return;
  await api('/api/templates', {
    method: 'POST',
    body: { name, tpl_type: '返图', content: $('#w-tpl-content').value },
  });
  toast('已另存');
  await loadWrite();
}

async function deleteTemplate() {
  const tpl = currentTpl();
  if (!tpl.id) return;                                      // 不弹确认（用户要求）
  await api('/api/templates/' + tpl.id, { method: 'DELETE' });
  toast('已删除');
  await loadWrite();
}

/* 长任务计时：按钮上每秒跳秒数。
   不这么做的话界面一动不动，看着像卡死 —— 用户会顺手关窗口，
   而关闭行为若设了「直接退出」，一关整个 app 就没了。 */
let _busyTimer = null;
function startBusy(btn, base) {
  const t0 = Date.now();
  stopBusy();
  _busyTimer = setInterval(() => {
    const sec = Math.round((Date.now() - t0) / 1000);
    btn.dataset.base = base;
    btn.textContent = base + ' ' + sec + 's';
    const hint = $('#w-busy-hint');
    if (hint) {
      hint.textContent = sec >= 8
        ? ('本地模型正在跑（已 ' + sec + ' 秒）—— 慢是正常的，**跑完之前别关窗口**')
        : '';
    }
  }, 1000);
}
function stopBusy(btn) {
  if (_busyTimer) { clearInterval(_busyTimer); _busyTimer = null; }
  if (btn && btn.dataset.base) btn.textContent = btn.dataset.base;
  const hint = $('#w-busy-hint');
  if (hint) hint.textContent = '';
}

async function genCaption() {
  const btn = $('#w-gen');
  btn.disabled = true;
  startBusy(btn, '上光中…');
  $('#w-beam').classList.add('on');
  try {
    const tpl = currentTpl();
    const res = await api('/api/caption/generate', {
      method: 'POST',
      body: {
        template_content: $('#w-tpl-content').value,
        target: $('#w-target').value,
        media_type: $('#w-media').value,
        mood: $('#w-mood').value,
        points: $('#w-points').value,
        caption_type: tpl.tpl_type || '返图',
        temperature: Number($('#w-temp').value || 0.9),
        ref_song: ($('#w-ref-song') || {}).value || '',
        max_chars: Number($('#w-len').value || 60),
        image_description: $('#w-desc').value.trim(),
        image_exif: EXIF_STR,
      },
    });
    $('#w-stage-empty').style.display = 'none';
    $('#w-result-box').style.display = '';
    $('#w-result').value = res.text;
    const u = res.used || {};
    $('#w-used').innerHTML =
      `联想术语：${u.terms && u.terms.length ? esc(u.terms.join('、')) : '无'} ｜ ` +
      `联想事件：${u.events && u.events.length ? esc(u.events.join('、')) : '无'} ｜ ` +
      `风格样本：${u.samples || 0} 条 ｜ 识图：${u.image ? '已用描述' : '未用'}` +
      (u.ref_song ? ` ｜ 参考歌曲：《${esc(u.ref_song)}》${u.ref_count} 条` : '');
  } catch (e) {
    toast('生成失败：' + e.message);
  } finally {
    btn.disabled = false;
    stopBusy(btn);
    btn.textContent = '上光 · 生成文案';
    $('#w-beam').classList.remove('on');
  }
}

async function saveGenerated() {
  const content = $('#w-result').value.trim();
  if (!content) { toast('没有内容'); return; }
  await api('/api/captions', { method: 'POST', body: { content, caption_type: '返图', source: 'generated' } });
  toast('已存入文案库');
}

function copyResult() {
  navigator.clipboard.writeText($('#w-result').value).then(() => toast('已复制'));
}

/* ---- 照片识图（Stage 1，可选）—— 支持多张，识图结果合并成一段 ---- */

let IMGS = [];          // [{b64, mime}]
let EXIF_STR = '';
const MAX_IMGS = 6;

// 识图是否可用（由设置页/写文案页加载设置时更新）。未配置时按钮不再禁用，
// 而是点击弹引导 —— 让用户明确知道「去哪填」。
let VISION = { enabled: false, configured: false };

// 国产/常见服务商预设：一键把「地址 + 模型」填好，用户只需填自己的 Key。
// 模型 id 可能随时间变化 —— 改这里即可，不用动后端。
const VISION_PRESETS = [
  {
    id: 'zhipu', name: '智谱 GLM（有免费额度，推荐先试）',
    url: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4v-flash',
    help: '① 打开 open.bigmodel.cn → 注册/登录 → 左侧「API Keys」新建一个 Key。'
      + '② 把它粘到下面「API Key」。③ 模型用 glm-4v-flash（免费）或 glm-4v-plus。',
  },
  {
    id: 'dashscope', name: '通义千问 VL（阿里云百炼）',
    url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-vl-plus',
    help: '① 打开 bailian.console.aliyun.com → 开通「百炼」→「API-KEY」新建。'
      + '② 粘到下面「API Key」。③ 模型 qwen-vl-plus 或 qwen-vl-max。',
  },
  {
    id: 'ark', name: '豆包（火山方舟）',
    url: 'https://ark.cn-beijing.volces.com/api/v3',
    model: '',
    help: '① 打开 console.volcengine.com/ark → 开通 →「API Key 管理」新建。'
      + '② 在「在线推理」建一个接入点，把它给的接入点 ID（ep- 开头）填进下面「识图模型」。'
      + '③ 地址和 Key 分别粘到下面。',
  },
  {
    id: 'siliconflow', name: '硅基流动 SiliconFlow',
    url: 'https://api.siliconflow.cn/v1',
    model: 'Qwen/Qwen2.5-VL-72B-Instruct',
    help: '① 打开 siliconflow.cn → 注册 →「API 密钥」新建。'
      + '② 粘到下面「API Key」。③ 模型选一个带 VL 的（如 Qwen/Qwen2.5-VL-72B-Instruct）。',
  },
  {
    id: 'custom', name: '其它 OpenAI 兼容中转站（手动填）',
    url: '', model: '',
    help: '填你中转站的地址（通常以 /v1 结尾）、密钥，以及它的视觉模型名。',
  },
];

function updateVisionBtn() {
  const b = $('#w-vision-btn');
  if (!b) return;
  const ready = VISION.enabled && VISION.configured;
  b.classList.toggle('needs-config', !ready);
  b.title = ready ? '' : '识图还没配置：点一下看怎么设置';
}

/* ---- 识图引导：未配置时点「识图」弹这个，并能一键跳到设置页对应卡片 ---- */

function showVisionGuide() { const m = $('#vision-guide-modal'); if (m) m.hidden = false; }
function closeVisionGuide() { const m = $('#vision-guide-modal'); if (m) m.hidden = true; }

function goVisionSettings() {
  closeVisionGuide();
  go('settings');
  const card = $('#card-vision');
  if (card) {
    card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    card.classList.add('flash');
    setTimeout(() => card.classList.remove('flash'), 1700);
  }
}

function _readAsDataURL(file) {
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(String(fr.result));
    fr.onerror = rej;
    fr.readAsDataURL(file);
  });
}

function _shrink(src, max) {
  return new Promise((res) => {
    const im = new Image();
    im.onload = () => {
      const sc = Math.min(1, (max || 1568) / Math.max(im.width, im.height));
      const c = document.createElement('canvas');
      c.width = Math.round(im.width * sc);
      c.height = Math.round(im.height * sc);
      c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
      res(c.toDataURL('image/jpeg', 0.85));
    };
    im.src = src;
  });
}

async function onPickImage() {
  const files = Array.from($('#w-image').files || []).slice(0, MAX_IMGS);
  if (!files.length) return;
  const box = $('#w-image-preview');
  box.hidden = false;
  box.innerHTML = '';
  $('#w-desc').value = '';
  $('#w-exif').textContent = '';
  EXIF_STR = '';
  IMGS = [];
  for (const f of files) {
    const src = await _readAsDataURL(f);
    const im = new Image();
    im.src = src;
    box.appendChild(im);
    const jpeg = await _shrink(src, 1568);      // 缩到最长边 1568、转 JPEG
    IMGS.push({ b64: jpeg.split(',')[1], mime: 'image/jpeg' });
  }
  toast(files.length > MAX_IMGS ? `最多 ${MAX_IMGS} 张，已取前 ${MAX_IMGS} 张` : `已选 ${IMGS.length} 张`);
}

function clearImage() {
  IMGS = []; EXIF_STR = '';
  $('#w-image').value = '';
  const box = $('#w-image-preview');
  box.hidden = true;
  box.innerHTML = '';
  $('#w-desc').value = '';
  $('#w-exif').textContent = '';
}

async function describeImage() {
  if (!IMGS.length) { toast('请先选择照片'); return; }
  if (!(VISION.enabled && VISION.configured)) { showVisionGuide(); return; }
  const btn = $('#w-vision-btn');
  const n = IMGS.length;
  btn.disabled = true;
  const parts = [];
  const exifs = [];
  try {
    for (let i = 0; i < n; i++) {
      btn.textContent = `识图中… ${i + 1}/${n}`;
      if (!_busyTimer) startBusy(btn, `识图中… ${i + 1}/${n}`);
      const r = await api('/api/vision/describe', {
        method: 'POST', body: { image_base64: IMGS[i].b64, mime: IMGS[i].mime },
      });
      if (r.description) {
        parts.push(n > 1 ? `【第 ${i + 1} 张】${r.description}` : r.description);
      }
      if (r.exif) exifs.push(r.exif);
      $('#w-desc').value = parts.join('\n\n');   // 边识边显示
    }
    EXIF_STR = exifs.join('；');
    $('#w-exif').textContent = EXIF_STR ? ('拍摄参数：' + EXIF_STR) : '（这些图没有可读的拍摄参数）';
    toast(n > 1 ? `识图完成（${n} 张已合并成一段）` : '识图完成，可修改描述后再生成');
  } catch (e) {
    toast('识图失败：' + e.message);
  } finally {
    btn.disabled = false;
    stopBusy(btn);
    btn.textContent = '识图';
  }
}

async function loadRefSongs() {
  const sel = $('#w-ref-song');
  if (!sel) return;
  try {
    const songs = await api('/api/captions/songs');
    sel.innerHTML = '<option value="">（不参考歌曲）</option>' + songs
      .map((s) => `<option value="${esc(s.song)}">🎵 ${esc(s.song)}（${s.c} 条）</option>`).join('');
  } catch (e) { /* 忽略 */ }
}

/* ---------------- 文案库 ---------------- */

let _capTab = 'pending';      // 文案库当前页签：pending / confirmed

function showCaptionTab(which) {
  _capTab = which;
  const isPending = which === 'pending';
  $('#tab-c-pending').classList.toggle('active', isPending);
  $('#tab-c-done').classList.toggle('active', !isPending);
  $('#c-act-confirm').hidden = !isPending;
  loadCaptions();
  refreshCaptionCounts();
}

async function refreshCaptionCounts() {
  try {
    const c = await api('/api/captions/counts');
    $('#tab-c-pending-n').textContent = c.pending;
    $('#tab-c-done-n').textContent = c.confirmed;
  } catch (e) { /* 忽略 */ }
}

async function loadCaptions() {
  let list = [];
  try { list = await api('/api/captions?status=' + _capTab); }
  catch (e) { toast('加载失败：' + e.message); return; }
  try { _songs = await api('/api/captions/songs'); } catch (e) { _songs = []; }

  if (_capTab === 'pending') {
    $('#c-list').innerHTML = list.length
      ? list.map((c) => captionItem(c, false)).join('')
      : '<div class="empty">没有待确认的文案。用上面的「从微博导入」抓一批，核对后再确认。</div>';
    $('#c-count').textContent = `本页 ${list.length} 条`;
  } else {
    // 已确认分两块：普适（写文案学语气用）+ 歌曲文案（按歌分组，只作参考）
    const general = list.filter((c) => c.scope !== 'song');
    const bySong = {};
    list.filter((c) => c.scope === 'song').forEach((c) => {
      const k = c.song || '（未命名）';
      (bySong[k] = bySong[k] || []).push(c);
    });
    const names = Object.keys(bySong);
    let html = `<div class="card"><label>普适文案 · ${general.length} 条</label>
      <div class="desc">写文案时的风格样本就取自这里（学语气）。</div>
      <div class="list">${general.length
        ? general.map((c) => captionItem(c, true)).join('')
        : '<div class="empty">还没有普适文案。</div>'}</div></div>`;
    html += `<div class="card"><label>歌曲文案 · ${list.length - general.length} 条</label>
      <div class="desc">绑定某首歌的文案。<b>不参与写文案的风格</b>；在「写文案」里选了那首歌时，才作为参考注入。</div>`;
    html += names.length
      ? names.map((n) => `<div class="desc" style="margin-top:12px">🎵 <b>${esc(n)}</b>（${bySong[n].length} 条）</div>
          <div class="list">${bySong[n].map((c) => captionItem(c, true)).join('')}</div>`).join('')
      : '<div class="empty">还没有歌曲文案 —— 在下面把某条改成「归到某首歌」即可。</div>';
    html += '</div>';
    $('#c-list').innerHTML = html;
    $('#c-count').textContent = `普适 ${general.length} · 歌曲 ${list.length - general.length}`;
  }
  if (!$('#c-imp-from').value || !$('#c-imp-to').value) setRecentRange(180);   // 首次进来给个默认范围
  refreshCaptionCounts();
  // 进这个页时，后台若还有导入在跑，把进度接上（切走再切回来不会断）
  try {
    const s = await api('/api/weibo/import_status');
    if (s.running || s.done) {
      renderImportProgress(s);
      if (s.running && !_impTimer) _impTimer = setInterval(pollImport, 2000);
    }
  } catch (e) { /* 忽略 */ }
}

let _songs = [];        // 已确认的歌曲文案里出现过的歌名（给「归到某首歌」下拉用）

function scopePicker(c) {
  const cur = c.scope === 'song' ? (c.song || '') : '';
  const opts = ['<option value="">普适（学语气用）</option>']
    .concat(_songs.map((s) => `<option value="${esc(s.song)}"${s.song === cur ? ' selected' : ''}>🎵 ${esc(s.song)}</option>`))
    .concat(cur && !_songs.some((s) => s.song === cur)
      ? [`<option value="${esc(cur)}" selected>🎵 ${esc(cur)}</option>`] : [])
    .concat(['<option value="__new__">＋ 归到新歌…</option>']);
  return `<select class="tiny cap-scope" onchange="setCaptionScope(${c.id}, this.value)">${opts.join('')}</select>`;
}

function captionItem(c, showScope) {
  const pending = c.status === 'pending';
  return `<div class="item" data-id="${c.id}">
    <div class="body">
      <div class="desc cap-text">${esc(c.content)}</div>
      <div class="meta"><span class="tag">${esc(c.caption_type)}</span>
        ${c.tags ? `<span>${esc(c.tags)}</span>` : ''}
        ${c.posted_at ? `<span>${esc(c.posted_at.slice(0, 10))}</span>` : ''}
        ${c.scope === 'song' ? `<span class="tag accent">🎵 ${esc(c.song || '未命名')}</span>` : ''}
        ${c.source === 'generated' ? '<span class="tag accent">生成</span>' : ''}
        ${c.source === 'weibo' ? '<span class="tag likely">微博导入</span>' : ''}</div>
    </div>
    <div class="ops">
      ${pending ? `<button class="tiny primary" onclick="confirmCaption(${c.id})">确认</button>` : ''}
      ${showScope ? scopePicker(c) : ''}
      <button class="tiny danger" onclick="delCaption(${c.id})">删除</button>
    </div>
  </div>`;
}

async function setCaptionScope(cid, val) {
  let scope = 'general', song = '';
  if (val === '__new__') {
    const name = (prompt('归到哪首歌？输入歌名：') || '').trim();
    if (!name) { loadCaptions(); return; }     // 取消 → 还原下拉
    scope = 'song'; song = name;
  } else if (val) {
    scope = 'song'; song = val;
  }
  await api('/api/captions/' + cid, { method: 'PATCH', body: { scope, song } });
  toast(scope === 'song' ? `已归到《${song}》—— 不再参与风格，只作参考` : '已设为普适（会参与风格）');
  loadCaptions();
}

async function confirmCaption(id) {
  await api('/api/captions/' + id + '/confirm', { method: 'POST' });
  toast('已确认，进入风格来源');
  loadCaptions(); refreshCaptionCounts();
}

async function confirmAllCaptions() {
  if (!confirm('把全部「未确认」文案标为已确认？确认后才会参与写文案。')) return;
  const r = await api('/api/captions/confirm_all', { method: 'POST' });
  toast(`已确认 ${r.n} 条`);
  loadCaptions(); refreshCaptionCounts();
}

/* ---- 从微博导入文案 ---- */

async function useCurrentChaohua() {
  try {
    const s = await api('/api/settings');
    $('#c-imp-cid').value = s.weibo_containerid || '';
    toast(s.weibo_container_name ? ('已填入当前超话：' + s.weibo_container_name)
                                : '当前还没选超话，可去「推送」页选');
  } catch (e) { toast('读取失败：' + e.message); }
}

let _userPicks = [];
let _topicPicks = [];

function pickUserAt(i) {
  const c = _userPicks[i];
  if (!c) return;
  $('#c-imp-user').value = c.uid;
  $('#c-imp-status').textContent = `已选用户：${c.screen_name || '(无昵称)'}（uid ${c.uid}）`;
  $('#c-imp-picks').innerHTML = '';
}

function pickTopicAt(i) {
  const t = _topicPicks[i];
  if (!t) return;
  $('#c-imp-cid').value = t.containerid;
  toast('已选超话：' + (t.name || t.containerid));
}

async function resolveUser() {
  const q = $('#c-imp-user').value.trim();
  if (!q) { toast('先填用户昵称 / uid / 主页链接'); return; }
  const st = $('#c-imp-status');
  const picks = $('#c-imp-picks');
  st.textContent = '查找中…';
  picks.innerHTML = '';
  try {
    const r = await api('/api/weibo/resolve_user', { method: 'POST', body: { query: q } });
    if (!r.ok) { st.textContent = r.error || '查找失败'; return; }
    if (!r.candidates.length) { st.textContent = r.message || '没找到该用户'; return; }
    _userPicks = r.candidates;
    st.textContent = `找到 ${r.candidates.length} 个用户，点「选它」确定是哪个：`;
    picks.innerHTML = r.candidates.map((c, i) => `<div class="item"><div class="body">
        <div class="title">${esc(c.screen_name || '(无昵称)')}</div>
        <div class="desc">uid ${esc(c.uid)}</div>
      </div><div class="ops">
        <button class="tiny primary" onclick="pickUserAt(${i})">选它</button>
      </div></div>`).join('');
  } catch (e) { st.textContent = '查找失败：' + e.message; }
}

async function scanTopics() {
  const user = $('#c-imp-user').value.trim();
  if (!user) { toast('先填用户昵称 / uid / 主页链接'); return; }
  const st = $('#c-imp-status');
  const picks = $('#c-imp-picks');
  st.textContent = '扫描中…（翻 TA 的时间线，找出发过的超话）';
  picks.innerHTML = '';
  try {
    const r = await api('/api/weibo/scan_user_topics', { method: 'POST', body: {
      user, days: rangeDays(),
    }});
    if (!r.ok) { st.textContent = r.error || '扫描失败'; return; }
    if (!r.topics.length) { st.textContent = r.message || '没发现带超话的原创帖'; return; }
    _topicPicks = r.topics;
    st.textContent = `${r.message}。点一个填进上面的「超话 containerid」：`;
    picks.innerHTML = r.topics.map((t, i) => `<div class="item"><div class="body">
        <div class="title">${esc(t.name || '(未知名)')}</div>
        <div class="desc">${esc(t.containerid)} · 该窗口内发过 ${t.count} 条</div>
      </div><div class="ops">
        <button class="tiny primary" onclick="pickTopicAt(${i})">用它</button>
      </div></div>`).join('');
  } catch (e) { st.textContent = '扫描失败：' + e.message; }
}

function ymd(d) {          // 本地时区的 YYYY-MM-DD（别用 toISOString，会差一天）
  const p2 = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
}

function setRecentRange(days) {
  const to = new Date();
  const from = new Date(to.getTime() - days * 86400000);
  $('#c-imp-to').value = ymd(to);
  $('#c-imp-from').value = ymd(from);
  toast(`日期范围设为：${ymd(from)} ~ ${ymd(to)}`);
}

function rangeDays() {     // 用「从」日期换算回天数，供「扫描 TA 发过的超话」复用
  const from = $('#c-imp-from').value;
  if (!from) return 180;
  const d = Math.round((Date.now() - new Date(from + 'T00:00:00').getTime()) / 86400000);
  return Math.max(1, Math.min(d, 3650));
}

let _impTimer = null;
function stopImpPoll() { if (_impTimer) { clearInterval(_impTimer); _impTimer = null; } }

let _impCdEnd = 0;      // 休息结束的时间戳 —— 前端自己倒计时，数字每秒跳
let _impLast = null;

function impRunningText(s) {
  let t = `翻到第 ${s.page} 页 · 已扫 ${s.scanned} 条 · 入库 ${s.added} · 水贴 ${s.noise}`;
  if (_impCdEnd) {
    const left = Math.max(0, Math.ceil((_impCdEnd - Date.now()) / 1000));
    t += `　⏸ 休息中（${left} 秒后自动继续）`;
  }
  return t;
}

function renderImportProgress(s) {
  const st = $('#c-imp-status');
  const wrap = $('#c-imp-progress');
  const bar = $('#c-imp-bar');
  const txt = $('#c-imp-progress-text');
  const stopWrap = $('#c-imp-stop-wrap');
  const span = `已翻到 ${s.reached_date || '—'}　→　目标 ${s.cutoff_date || '—'}`;
  _impLast = s;

  if (s.running) {
    const pct = Math.round((s.progress || 0) * 100);
    wrap.hidden = false;
    stopWrap.hidden = false;
    bar.style.width = pct + '%';
    txt.textContent = `${span}　（${pct}%）`;
    _impCdEnd = s.cooldown ? Date.now() + s.cooldown * 1000 : 0;   // 本地接上倒计时
    st.textContent = impRunningText(s);
  } else {
    stopImpPoll();
    _impCdEnd = 0;
    stopWrap.hidden = true;
    if (s.done) {                       // 结束后留着，让你看到扫到哪天了
      bar.style.width = '100%';
      txt.textContent = span;
    }
    st.textContent = s.message || '导入已结束';
  }
}

// 倒计时每秒自己往下跳（只改那一行文字，不重新拉数据）
setInterval(() => {
  if (_impLast && _impLast.running && _impCdEnd) {
    $('#c-imp-status').textContent = impRunningText(_impLast);
  }
}, 1000);

async function stopImport() {
  const st = $('#c-imp-status');
  st.textContent = '正在停止…';
  try {
    const r = await api('/api/weibo/import_stop', { method: 'POST' });
    st.textContent = r.ok ? (r.message || '正在停止…') : ('停止失败：' + (r.error || '未知原因'));
  } catch (e) {
    st.textContent = '停止失败：' + e.message;
  }
}

async function pollImport() {
  try { renderImportProgress(await api('/api/weibo/import_status')); }
  catch (e) { /* 网络抖一下就跳过这次 */ }
}

async function importCaptions() {
  const st = $('#c-imp-status');
  const user = $('#c-imp-user').value.trim();
  if (!user) { toast('先填用户昵称 / uid / 主页链接'); return; }
  stopImpPoll();
  st.textContent = '正在启动…';
  try {
    const r = await api('/api/weibo/import_captions', { method: 'POST', body: {
      user,
      containerid: $('#c-imp-cid').value.trim(),
      date_from: $('#c-imp-from').value,
      date_to: $('#c-imp-to').value,
      cooldown: Number($('#c-imp-cooldown').value || 10),   // 空 → 10；显式填 0 才是 0
      caption_type: $('#c-imp-type').value.trim() || '返图',
    }});
    if (!r.ok) { st.textContent = '启动失败：' + (r.error || '未知原因'); return; }
    st.textContent = r.message;
    _impTimer = setInterval(pollImport, 2000);
    pollImport();
  } catch (e) {
    st.textContent = '启动失败：' + e.message;
  }
}


async function addCaption() {
  const content = $('#c-one').value.trim();
  if (!content) { toast('没有内容'); return; }
  await api('/api/captions', {
    method: 'POST',
    body: { content, tags: $('#c-tags').value, caption_type: $('#c-type').value || '返图' },
  });
  toast('已添加');
  $('#c-one').value = '';
  loadCaptions();
}

async function delCaption(id) {
  await api('/api/captions/' + id, { method: 'DELETE' });   // 不弹确认（用户要求）
  loadCaptions(); refreshCaptionCounts();
}

async function deleteCaptionsInTab() {
  const isPending = _capTab === 'pending';
  const what = isPending ? '「未确认」文案' : '**全部已确认文案**（写文案的风格来源）';
  if (!confirm('删除' + what + '？不可恢复。')) return;
  const r = await api('/api/captions/delete_all?status=' + _capTab, { method: 'POST' });
  toast(`已删除 ${r.n} 条`);
  loadCaptions(); refreshCaptionCounts();
}

/* ---------------- 风格档案 ---------------- */

async function loadStyle() {
  try {
    const r = await api('/api/style');
    $('#st-profile').value = r.profile || '';
    $('#st-status').textContent = `文案库共 ${r.captions} 条` +
      (r.profile ? `，当前档案 ${r.profile.length} 字` : '，还没有风格档案');
  } catch (e) {
    $('#st-status').textContent = '加载失败：' + e.message;
  }
  try {
    const s = await api('/api/settings');
    $('#st-samples').value = s.style_samples || 8;
  } catch (e) { /* 忽略 */ }
}

async function genStyle() {
  const st = $('#st-status');
  const prog = $('#st-progress');
  st.textContent = '生成中…';
  prog.hidden = false;                 // 不确定进度条：模型是一次调用，没法报真实百分比
  try {
    const r = await api('/api/style/generate', { method: 'POST' });
    if (r.ok) {
      $('#st-profile').value = r.profile;
      st.textContent = `已生成 ${r.chars} 字（基于 ${r.captions} 条文案）`;
      toast('风格档案已更新');
    } else {
      st.textContent = '生成失败：' + (r.error || '未知原因');
    }
  } catch (e) {
    st.textContent = '生成失败：' + e.message;
  } finally {
    $('#st-progress').hidden = true;   // 成功/失败都要收掉进度条
  }
}

async function saveStyle() {
  await api('/api/style', { method: 'POST', body: { profile: $('#st-profile').value } });
  toast('风格档案已保存');
  loadStyle();
}

async function copyCaptions() {
  try {
    const r = await api('/api/style/captions_text');
    if (!r.count) { toast('文案库是空的，先录入一些'); return; }
    await navigator.clipboard.writeText(r.text);
    toast(`已复制 ${r.count} 条文案，粘给云端强模型吧`);
  } catch (e) {
    toast('复制失败：' + e.message);
  }
}

async function saveStyleSamples() {
  await api('/api/settings', { method: 'POST', body: { style_samples: $('#st-samples').value } });
  toast('已保存');
}

/* ---------------- 术语（未确认 / 已确认，双页切换） ---------------- */

const TERM_TYPES = ['黑话', '绰号', '应援', '事件指代'];
let _pending = [];        // 未确认候选缓存
let _termTab = 'pending';

function showTermTab(which) {
  _termTab = which;
  const isPending = which === 'pending';
  $('#tab-t-pending').classList.toggle('active', isPending);
  $('#tab-t-done').classList.toggle('active', !isPending);
  $('#t-pane-pending').hidden = !isPending;
  $('#t-pane-done').hidden = isPending;
  if (isPending) loadPendingTerms(); else loadTerms();
  refreshTermCounts();
}

async function refreshTermCounts() {
  try {
    const [pd, dn] = await Promise.all([
      api('/api/candidates?status=pending'), api('/api/terms'),
    ]);
    $('#tab-t-pending-n').textContent = pd.length;
    $('#tab-t-done-n').textContent = dn.length;
  } catch (e) { /* 忽略 */ }
}

/* ---- 未确认：填写页 ---- */

async function loadPendingTerms() {
  if ($('#t-pane-pending') && $('#t-pane-pending').hidden) return;   // 不在这个页就别白拉
  _pending = await api('/api/candidates?status=pending');
  const hint = $('#t-pending-hint');
  const el = $('#t-pending');
  if (!_pending.length) {
    hint.textContent = '';
    el.innerHTML = '<div class="empty">没有未确认的术语。用上面的按钮抽一批，或在「设置」打开「AI 自动识别术语」后抓取会自动产出。</div>';
    return;
  }
  hint.textContent = `共 ${_pending.length} 个。填好释义点「入库」；不需要的点「删除」。`;
  el.innerHTML = _pending.map(candItem).join('');
}

function candItem(c) {
  const badge = c.confidence
    ? `<span class="tag ${c.confidence === 'likely' ? 'likely' : 'maybe'}">${c.confidence === 'likely' ? '较可信' : '可能编造'}</span>`
    : '<span class="tag">未判断</span>';
  return `<div class="item" data-id="${c.id}" data-confidence="${c.confidence || ''}">
    <div class="body">
      <div class="title">${esc(c.phrase)} <span class="tag">频次 ${c.freq}</span> ${badge}</div>
      ${c.sample ? `<div class="desc">上下文：${esc(c.sample)}</div>` : ''}
      <label>释义（你说了算）</label>
      <textarea class="r-meaning" data-phrase="${esc(c.phrase)}" data-sample="${esc(c.sample)}"
        style="min-height:56px">${esc(c.suggested_meaning || '')}</textarea>
    </div>
    <div class="ops">
      <button class="tiny" onclick="suggest(${c.id}, this)">让模型填</button>
      <button class="tiny primary" onclick="promote(${c.id}, this)">入库</button>
      <button class="tiny danger" onclick="deleteCand(${c.id})">删除</button>
    </div>
  </div>`;
}

async function fetchCandidates() {
  toast('从文案库抽取中…');
  try {
    const r = await api('/api/candidates/fetch', { method: 'POST' });
    toast(r.message);
    loadPendingTerms(); refreshTermCounts();
  } catch (e) { toast('失败：' + e.message); }
}

async function extractTermsFromPosts() {
  toast('从超话帖抽取中…（要过一遍最近的帖子）');
  try {
    const r = await api('/api/terms/extract_from_posts', { method: 'POST' });
    toast(r.added ? `新增 ${r.added} 个候选术语` : '没有发现新的候选词');
    loadPendingTerms(); refreshTermCounts();
  } catch (e) { toast('失败：' + e.message); }
}

async function suggest(cid, btn) {
  const item = btn.closest('.item');
  const ta = item.querySelector('.r-meaning');
  btn.disabled = true; btn.textContent = '…';
  try {
    const r = await api('/api/candidates/suggest', {
      method: 'POST',
      body: { phrase: ta.dataset.phrase, sample: ta.dataset.sample },
    });
    item.dataset.confidence = r.confidence;
    ta.value = r.meaning || '';
    if (!r.meaning) toast('模型表示不认识这个词——请你自己填释义');
  } catch (e) {
    toast('失败：' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = '让模型填';
  }
}

async function promote(cid, btn) {
  const item = btn.closest('.item');
  const ta = item.querySelector('.r-meaning');
  const meaning = ta.value.trim();
  if (!meaning) { toast('请先填写释义'); return; }
  await api('/api/candidates/promote', {
    method: 'POST',
    body: {
      cand_id: cid, term: ta.dataset.phrase, meaning,
      confidence: item.dataset.confidence || 'manual',
    },
  });
  toast('已入库到「已确认」');
  loadPendingTerms(); refreshTermCounts();
}

async function deleteCand(cid) {
  await api('/api/candidates/' + cid + '/ignore', { method: 'POST' });
  loadPendingTerms(); refreshTermCounts();
}

async function deleteAllCandidates() {
  if (!confirm('删除全部「未确认」术语？它们只是候选，删掉不影响已入库的词条。')) return;
  const r = await api('/api/candidates/delete_all?status=pending', { method: 'POST' });
  toast(`已删除 ${r.n} 个未确认术语`);
  loadPendingTerms(); refreshTermCounts();
}

function cancelEditTerm() {
  $('#t-term').value = '';
  $('#t-meaning').value = '';
}

// 手动录入（未确认页顶部的表单）
async function addTerm() {
  const term = $('#t-term').value.trim();
  const meaning = $('#t-meaning').value.trim();
  if (!term || !meaning) { toast('术语和释义都要填'); return; }
  await api('/api/terms', { method: 'POST', body: { term, meaning, term_type: $('#t-type').value } });
  const dup = _pending.find((c) => c.phrase === term);   // 手填的词若在候选里，顺手把候选消掉
  if (dup) await api('/api/candidates/' + dup.id + '/ignore', { method: 'POST' });
  toast('已入库到「已确认」');
  $('#t-term').value = ''; $('#t-meaning').value = '';
  loadPendingTerms(); refreshTermCounts();
}

/* ---- 已确认：查看 / 就地改 ---- */

async function loadTerms() {
  if ($('#t-pane-done') && $('#t-pane-done').hidden) return;
  const q = ($('#dt-search').value || '').trim().toLowerCase();
  const ty = $('#dt-type').value || '';
  let list = await api('/api/terms');
  const total = list.length;
  if (ty) list = list.filter((t) => t.term_type === ty);
  if (q) list = list.filter((t) => ((t.term || '') + ' ' + (t.meaning || '')).toLowerCase().includes(q));
  $('#dt-count').textContent = total
    ? `共 ${total} 条词条${list.length !== total ? `，当前匹配 ${list.length} 条` : ''}`
    : '';
  $('#dt-list').innerHTML = list.length
    ? list.map(termRow).join('')
    : '<div class="empty">还没有词条。去「未确认」页确认几个，或手动录入。</div>';
}

function termRow(t) {
  // 「有问题」：AI 建议 / 低可信 / 无释义 —— 高亮，提醒核对
  const bad = !t.meaning || t.confidence === 'likely' || t.confidence === 'maybe_fabricated';
  const tag = !t.meaning ? '无释义' : t.confidence === 'maybe_fabricated' ? '可能编造'
    : t.confidence === 'likely' ? 'AI 建议' : '';
  return `<div class="item${bad ? ' warn' : ''}" data-id="${t.id}">
    <div class="body">
      <div class="title">${esc(t.term)} ${tag ? `<span class="tag maybe">${tag}</span>` : ''}
        <span class="tag">${esc(t.term_type)}</span></div>
      <div class="row">
        <div><label>释义</label>
          <textarea class="dt-meaning" style="min-height:52px">${esc(t.meaning || '')}</textarea></div>
        <div><label>类型</label>
          <select class="dt-type">${TERM_TYPES.map((x) =>
            `<option${x === t.term_type ? ' selected' : ''}>${x}</option>`).join('')}</select></div>
      </div>
    </div>
    <div class="ops">
      <button class="tiny primary" onclick="saveTermRow(${t.id})">保存</button>
      <button class="tiny danger" onclick="delTerm(${t.id})">删除</button>
    </div>
  </div>`;
}

async function saveTermRow(id) {
  const item = document.querySelector(`#dt-list .item[data-id="${id}"]`);
  if (!item) return;
  await api('/api/terms/' + id, { method: 'PATCH', body: {
    meaning: item.querySelector('.dt-meaning').value,
    term_type: item.querySelector('.dt-type').value,
    confidence: 'manual',                     // 人工改过 → 清掉「有问题」标记
  }});
  toast('已保存');
  loadTerms();
}

async function delTerm(id) {
  await api('/api/terms/' + id, { method: 'DELETE' });      // 不弹确认（用户要求）
  loadTerms(); refreshTermCounts();
}

async function deleteAllTerms() {
  if (!confirm('删除**全部**词条？这是「懂梗」的知识库，删了不可恢复。')) return;
  const r = await api('/api/terms/delete_all', { method: 'POST' });
  toast(`已删除 ${r.n} 条词条`);
  loadTerms(); refreshTermCounts();
}

/* ---------------- 事件（未确认 / 已确认，双页切换） ---------------- */

const SRC_LABEL = { manual: '手动', summarized: '自动总结', post: '帖子', digest: '速览' };
const PAGE_SIZE = 100;
let _eOffset = 0;
let _eventStatus = 'pending';
let _events = [];        // 已加载事件缓存

function shorten(s, n) { s = s || ''; return s.length > n ? s.slice(0, n) + '…' : s; }

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
const debouncedLoadEvents = debounce(() => loadEvents(0), 300);

function showEventTab(which) {
  _eventStatus = which;
  const isPending = which === 'pending';
  $('#tab-e-pending').classList.toggle('active', isPending);
  $('#tab-e-done').classList.toggle('active', !isPending);
  $('#e-act-confirm').hidden = !isPending;
  loadEvents(0);
  refreshEventCounts();
}

async function refreshEventCounts() {
  try {
    const [pd, cf] = await Promise.all([
      api('/api/events?status=pending&limit=1'), api('/api/events?status=confirmed&limit=1'),
    ]);
    $('#tab-e-pending-n').textContent = pd.total;
    $('#tab-e-done-n').textContent = cf.total;
  } catch (e) { /* 忽略 */ }
}

async function loadEvents(offset = 0) {
  const p = new URLSearchParams({
    limit: PAGE_SIZE, offset: String(offset),
    status: _eventStatus, source: $('#e-f-source').value,
    q: $('#e-search').value.trim(),
  });
  let r;
  try { r = await api('/api/events?' + p); }
  catch (e) { toast('加载失败：' + e.message); return; }

  const el = $('#e-list');
  const html = r.items.length
    ? r.items.map((e) => eventItem(e, _eventStatus === 'confirmed')).join('')
    : '<div class="empty">这里还没有事件。</div>';
  if (offset === 0) { el.innerHTML = html; _events = r.items; }
  else { el.insertAdjacentHTML('beforeend', html); _events = _events.concat(r.items); }

  _eOffset = offset + r.items.length;
  $('#e-count').textContent = `共 ${r.total} 条，已显示 ${_eOffset} 条` +
    (r.total > r.items.length && _eOffset < r.total ? '（点「加载更多」）' : '');
  $('#e-more-wrap').hidden = _eOffset >= r.total;

  if (_focusEvent) {                       // 深链 #events/<id>：展开并高亮
    const t = el.querySelector(`.item[data-id="${_focusEvent}"]`);
    if (t) {
      t.classList.add('open', 'flash');
      const full = t.querySelector('.full');
      if (full) full.hidden = false;
      t.scrollIntoView({ block: 'center' });
    }
    _focusEvent = null;
  }
}

function loadEventsMore() { loadEvents(_eOffset); }

function eventItem(e, editable) {
  const pending = e.status === 'pending';
  const src = SRC_LABEL[e.source] || e.source;
  const isDigest = e.source === 'digest';
  const body = editable
    // 已确认页：可读可写（就地改标题/说明/人物/梗）
    ? `<input type="text" class="ev-title" value="${esc(e.title)}" style="margin-bottom:6px">
       <textarea class="ev-desc" style="min-height:70px">${esc(e.description)}</textarea>
       <div class="row">
         <div><label>时间</label><input type="text" class="ev-date" value="${esc(e.event_date || '')}"></div>
         <div><label>涉及的人</label><input type="text" class="ev-people" value="${esc(e.people || '')}"></div>
       </div>
       <label>相关梗 / 词</label><input type="text" class="ev-terms" value="${esc(e.related_terms || '')}">`
    : `<div class="desc">${esc(shorten(e.description, 90))}</div>
       <div class="full" hidden>${esc(e.description)}</div>`;

  return `<div class="item${isDigest ? ' digest' : ''}" data-id="${e.id}">
    <div class="body">
      <div class="title${editable ? '' : ' clickable'}" ${editable ? '' : `onclick="toggleEvent(${e.id})"`}>
        ${editable ? esc(e.title) : esc(e.title)} ${pending ? '<span class="tag pending">待确认</span>' : ''}
        <span class="tag${isDigest ? ' accent' : ''}">${isDigest ? '置顶 · 速览' : esc(src)}</span>
        ${editable ? '' : '<span class="toggle">▾ 全文</span>'}
      </div>
      ${body}
      ${editable && e.event_date ? '' : `<div class="meta">
        ${e.event_date ? `<span>${esc(e.event_date)}</span>` : ''}
        ${e.people ? `<span>人：${esc(e.people)}</span>` : ''}
        ${e.related_terms ? `<span>梗：${esc(e.related_terms)}</span>` : ''}
      </div>`}
    </div>
    <div class="ops">
      ${editable ? `<button class="tiny primary" onclick="saveEventRow(${e.id})">保存</button>` : ''}
      ${pending ? `<button class="tiny primary" onclick="confirmEvent(${e.id})">确认</button>` : ''}
      <button class="tiny ghost" onclick="useEventForCaption(${e.id})">写文案</button>
      <button class="tiny danger" onclick="delEvent(${e.id})">删除</button>
    </div>
  </div>`;
}

async function saveEventRow(id) {
  const item = document.querySelector(`#e-list .item[data-id="${id}"]`);
  if (!item) return;
  const title = item.querySelector('.ev-title').value.trim();
  if (!title) { toast('标题不能空'); return; }
  await api('/api/events/' + id, { method: 'PATCH', body: {
    title,
    description: item.querySelector('.ev-desc').value,
    event_date: item.querySelector('.ev-date').value.trim(),
    people: item.querySelector('.ev-people').value.trim(),
    related_terms: item.querySelector('.ev-terms').value.trim(),
  }});
  toast('已保存');
  loadEvents(0);
}

function useEventForCaption(id) {
  const e = _events.find((x) => x.id === id);
  if (!e) return;
  const line = `${e.title}${e.description ? '：' + shorten(e.description, 120) : ''}`;
  const pts = $('#w-points');
  pts.value = pts.value.trim() ? pts.value.trim() + '\n' + line : line;
  go('write');
  toast('已把这条事件填进「要点」，可再补充后生成');
}

function toggleEvent(id) {
  const item = document.querySelector(`#e-list .item[data-id="${id}"]`);
  if (!item) return;
  const open = item.classList.toggle('open');
  const full = item.querySelector('.full');
  if (full) full.hidden = !open;
}

async function confirmAllEvents() {
  if (!confirm('把全部「未确认」事件标为已确认？')) return;
  const r = await api('/api/events/confirm_all', { method: 'POST' });
  toast(`已确认 ${r.n} 条`);
  loadEvents(0); refreshEventCounts();
}

async function deleteEventsInTab() {
  const isPending = _eventStatus === 'pending';
  const what = isPending ? '全部「未确认」事件' : '**全部已确认事件**';
  if (!confirm(`删除${what}？不可恢复。`)) return;
  const r = await api('/api/events/delete_all?status=' + _eventStatus, { method: 'POST' });
  toast(`已删除 ${r.n} 条`);
  loadEvents(0); refreshEventCounts();
}

async function addEvent() {
  const title = $('#e-title').value.trim();
  if (!title) { toast('事件标题必填'); return; }
  await api('/api/events', {
    method: 'POST',
    body: {
      title, event_date: $('#e-date').value, description: $('#e-desc').value,
      people: $('#e-people').value, related_terms: $('#e-terms').value,
    },
  });
  toast('已保存');
  ['#e-title', '#e-date', '#e-desc', '#e-people', '#e-terms'].forEach((s) => ($(s).value = ''));
  loadEvents(0); refreshEventCounts();
}

async function confirmEvent(id) {
  await api('/api/events/' + id, { method: 'PATCH', body: { status: 'confirmed' } });
  toast('已确认');
  loadEvents(0); refreshEventCounts();
}

async function delEvent(id) {
  await api('/api/events/' + id, { method: 'DELETE' });   // 不弹确认（用户要求）
  loadEvents(0); refreshEventCounts();
}
/* ---------------- 推送 ---------------- */

async function loadPush() {
  await loadPushLog();
  await loadPendingPosts();
  await qrCheckLogin();
  await refreshChaohua();
  startFetchWatch(10);      // 进推送页也看一眼有没有正在跑的抓取
}

/* ---------------- 扫码登录 ---------------- */

let _qrTimer = null;
let _lastCands = [];                       // 最近一次搜索结果（靠下标取，避免转义问题）
function qrStop() { if (_qrTimer) { clearInterval(_qrTimer); _qrTimer = null; } }

async function qrCheckLogin(force) {
  // force=true 时才真的去打微博（「刷新登录态」按钮）；平时走后端 10 分钟缓存
  const el = $('#q-login-status');
  el.className = 'wb-status';
  el.innerHTML = '<span class="led"></span><span class="who">检查登录态…</span>';
  try {
    const r = await api('/api/weibo/login_status' + (force ? '?force=true' : ''));
    if (!r.has_cookie) {
      el.innerHTML = '<span class="led"></span><span class="who">未登录</span>'
        + '<span class="sub">点「扫码登录」获取 cookie</span>';
      $('#q-cid').hidden = true;
    } else if (r.valid) {
      el.className = 'wb-status on';
      el.innerHTML = '<span class="led"></span>'
        + '<span class="who">' + esc(r.screen_name || '已登录') + '</span>'
        + '<span class="sub">uid ' + esc(r.uid || '') + ' · 登录态有效</span>';
      $('#q-cid').hidden = false;        // 登录有效才露出 containerid 查找
    } else {
      el.className = 'wb-status warn';
      el.innerHTML = '<span class="led"></span><span class="who">登录态已过期</span>'
        + '<span class="sub">请重新扫码</span>';
      $('#q-cid').hidden = true;
    }
  } catch (e) {
    el.innerHTML = '<span class="led"></span><span class="who">检查失败</span>'
      + '<span class="sub">' + esc(e.message) + '</span>';
  }
}

async function refreshChaohua() {
  const el = $('#q-current');
  let cid = '', cached = '';
  try {
    const s = await api('/api/settings');
    cid = s.weibo_containerid || '';
    cached = s.weibo_container_name || '';
  } catch (e) { /* ignore */ }
  if (!cid) {
    el.className = 'wb-status';
    el.innerHTML = '<span class="led"></span><span class="who">未选超话</span>'
      + '<span class="sub">下面搜一个，或到「设置 · 超话抓取」手填</span>';
    return;
  }
  // 名字已经缓存过就用缓存 —— 别每次开 app 都去打一次微博反查
  let name = cached;
  if (!name) {
    try {
      const r = await api('/api/weibo/resolve_chaohua', { method: 'POST', body: { containerid: cid } });
      if (r.ok) name = r.name;
    } catch (e) { /* ignore */ }
  }
  el.className = 'wb-status on';
  el.innerHTML = '<span class="led"></span>'
    + '<span class="who">' + esc(name || cid) + '</span>'
    + '<span class="sub">' + esc(cid) + '</span>'
    + '<span class="ops2"><button class="tiny ghost" onclick="clearChaohua()">清除</button></span>';
}

async function clearChaohua() {
  await api('/api/settings', { method: 'POST', body: { weibo_containerid: '', weibo_container_name: '' } });
  $('#s-weibo-containerid').value = '';
  toast('已清除超话选择');
  refreshChaohua();
}

async function qrStart() {
  const btn = $('#q-btn');
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '生成中…';
  qrStop();
  try {
    const r = await api('/api/weibo/qr/start', { method: 'POST' });
    if (!r.ok) { toast('取二维码失败：' + (r.error || '未知原因')); return; }
    const img = $('#q-img');
    img.innerHTML = '';
    const im = document.createElement('img');
    im.src = r.image;
    im.alt = '登录二维码';
    im.style.width = '180px';
    im.style.background = '#fff';
    img.appendChild(im);
    $('#q-box').hidden = false;
    $('#q-status').textContent = '请用微博 App 扫码（等待中…）';
    _qrTimer = setInterval(qrPoll, 2000);
  } catch (e) {
    toast('取二维码失败：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

async function qrPoll() {
  const status = $('#q-status');
  try {
    const r = await api('/api/weibo/qr/poll');
    if (r.status === 'waiting') {
      status.textContent = '请用微博 App 扫码（等待中…）';
    } else if (r.status === 'scanned') {
      status.textContent = '已扫码，请在手机上点确认';
    } else if (r.status === 'ok') {
      qrStop();
      $('#q-img').innerHTML = '';
      $('#q-box').hidden = true;
      if (r.verified) {
        $('#q-status').textContent = '';
        toast('登录成功，cookie 已保存');
      } else {
        // 登录流程走完了，但 m.weibo.cn 没认这个 cookie —— 露出清单好定位
        $('#q-status').textContent = (r.message || '未认可') +
          (r.cookies && r.cookies.length ? '  [' + r.cookies.join(', ') + ']' : '');
        toast('登录了，但未被 m.weibo.cn 认可，建议重扫');
      }
      loadSettings();                 // 设置页的 cookie 框也同步
      qrCheckLogin();                 // 刷新「登录态」状态条
      refreshChaohua();               // 刷新「当前超话」状态条
    } else {
      qrStop();
      let msg = r.error || '登录失败，请重试';
      if (r.cookies && r.cookies.length) msg += '  [' + r.cookies.join(', ') + ']';
      status.textContent = msg;
    }
  } catch (e) {
    qrStop();
    status.textContent = '轮询失败：' + e.message;
  }
}

async function findCid() {
  const kw = $('#q-kw').value.trim();
  if (!kw) { toast('请输入超话名称'); return; }
  const st = $('#q-cid-status');
  const list = $('#q-cid-list');
  st.textContent = '查找中…';
  list.innerHTML = '';
  try {
    const r = await api('/api/weibo/find_containerid', { method: 'POST', body: { keyword: kw } });
    if (!r.ok) { st.textContent = r.error || '查找失败'; return; }
    if (!r.candidates.length) { st.textContent = r.message || '没找到超话，换个更精确的名称试试'; return; }
    st.textContent = (r.message || '') + '（点「用它」选定；列表可滚动；抓不到帖子再改用浏览器复制的完整 containerid）';
    _lastCands = r.candidates;
    list.innerHTML = r.candidates.map((c, i) => `<div class="item"><div class="body">
        <div class="title">${esc(c.title || c.containerid)}</div>
        <div class="desc">${esc(c.containerid)} · 匹配 ${c.score}</div>
      </div><div class="ops">
        <button class="tiny" onclick="useCidAt(${i})">用它</button>
      </div></div>`).join('');
  } catch (e) {
    st.textContent = '查找失败：' + e.message;
  }
}

async function useCidAt(i) {
  const c = _lastCands[i];
  if (!c) return;
  await api('/api/settings', { method: 'POST', body: {
    weibo_containerid: c.containerid, weibo_container_name: c.title || '' } });
  $('#s-weibo-containerid').value = c.containerid;
  toast('已选超话：' + (c.title || c.containerid));
  refreshChaohua();                 // 立刻把「当前超话」状态条刷新出来
}

async function qrForget() {
  qrStop();
  await api('/api/settings', { method: 'POST', body: { weibo_cookie: '' } });
  $('#s-weibo-cookie').value = '';
  $('#q-img').innerHTML = '';
  $('#q-box').hidden = true;
  $('#q-cid').hidden = true;
  toast('已清除保存的 cookie');
  qrCheckLogin();
}

async function loadPendingPosts() {
  try {
    const d = await api('/api/dashboard');
    $('#p-posts-count').textContent = `当前未处理帖：${d.counts.pending_posts} 条`;
  } catch (e) { /* ignore */ }
}

async function ingestPosts() {
  const text = $('#p-posts').value.trim();
  if (!text) { toast('没有内容'); return; }
  const r = await api('/api/posts/ingest', { method: 'POST', body: { text } });
  toast(`已存入 ${r.added} 条帖`);
  $('#p-posts').value = '';
  loadPendingPosts();
}

async function loadPushLog() {
  const list = await api('/api/push/log');
  $('#p-log').innerHTML = list.length
    ? list.map((p) => `<div class="item"><div class="body">
        <div class="title">${esc(p.title)}</div>
        <div class="desc">${esc(p.body)}</div>
        <div class="meta"><span>${esc(p.created_at)}</span><span class="tag">${esc(p.channel)}</span></div>
      </div></div>`).join('')
    : '<div class="empty">还没有推送记录。</div>';
}

async function runJob(job) {
  toast('执行中…');
  try {
    const r = await api('/api/jobs/' + job + '/run', { method: 'POST' });
    toast(r.message || '完成');
    loadPushLog();
  } catch (e) { toast('失败：' + e.message); }
}

/* ---------------- 设置 ---------------- */

async function loadSettings() {
  const s = await api('/api/settings');
  $('#s-url').value = s.ollama_url || '';
  $('#s-model').value = s.model || '';
  $('#s-push-enabled').checked = s.push_enabled === '1';
  $('#s-push-interval').value = s.push_interval_min || 30;
  $('#s-sum-enabled').checked = s.summarize_enabled === '1';
  $('#s-sum-interval').value = s.summarize_interval_min || 60;
  $('#s-ai-terms').checked = s.ai_terms_enabled === '1';
  $('#s-autostart').checked = s.autostart === '1';
  $('#s-close-action').value = s.close_action || 'ask';
  $('#s-sms-enabled').checked = s.sms_enabled === '1';
  $('#s-vision-url').value = s.vision_base_url || '';
  $('#s-vision-key').value = s.vision_api_key || '';
  $('#s-vision-model').value = s.vision_model || '';
  $('#s-vision-enabled').checked = s.vision_enabled === '1';
  $('#s-vision-status').textContent = '';
  $('#s-vision-preset').value = '';
  $('#s-vision-help').textContent = '';
  renderVisionPresetOptions();
  renderVisionBadge();
  $('#s-weibo-cookie').value = s.weibo_cookie || '';
  $('#s-weibo-containerid').value = s.weibo_containerid || '';
  $('#s-fetch-enabled').checked = s.weibo_fetch_enabled === '1';
  $('#s-fetch-autosum').checked = s.weibo_autosummarize !== '0';   // 默认开
  $('#s-fetch-interval').value = s.weibo_fetch_interval_min || 60;
  $('#s-fetch-cooldown').value = (s.weibo_fetch_cooldown !== undefined
    && s.weibo_fetch_cooldown !== '') ? s.weibo_fetch_cooldown : 10;
  loadRuns();
  checkSetup(false);       // 刷新「环境检测」卡
}

async function saveSettings(keys) {
  const map = { ollama_url: '#s-url', model: '#s-model' };
  const body = {};
  keys.forEach((k) => (body[k] = $(map[k]).value.trim()));
  await api('/api/settings', { method: 'POST', body });
  toast('已保存');
}

async function saveAllSettings() {
  await api('/api/settings', {
    method: 'POST',
    body: {
      ollama_url: $('#s-url').value.trim(),
      model: $('#s-model').value.trim(),
      push_enabled: $('#s-push-enabled').checked ? '1' : '0',
      push_interval_min: $('#s-push-interval').value,
      summarize_enabled: $('#s-sum-enabled').checked ? '1' : '0',
      summarize_interval_min: $('#s-sum-interval').value,
      ai_terms_enabled: $('#s-ai-terms').checked ? '1' : '0',
      autostart: $('#s-autostart').checked ? '1' : '0',
      close_action: $('#s-close-action').value,
      sms_enabled: $('#s-sms-enabled').checked ? '1' : '0',
      vision_enabled: $('#s-vision-enabled').checked ? '1' : '0',
      vision_base_url: $('#s-vision-url').value.trim(),
      vision_api_key: $('#s-vision-key').value.trim(),
      vision_model: $('#s-vision-model').value.trim(),
      weibo_cookie: $('#s-weibo-cookie').value.trim(),
      weibo_containerid: $('#s-weibo-containerid').value.trim(),
      weibo_fetch_enabled: $('#s-fetch-enabled').checked ? '1' : '0',
      weibo_autosummarize: $('#s-fetch-autosum').checked ? '1' : '0',
      weibo_fetch_interval_min: $('#s-fetch-interval').value,
      weibo_fetch_cooldown: $('#s-fetch-cooldown').value,
    },
  });
  toast('已保存全部设置');
  loadRuns();
}

/* ---------------- 超话抓取 ---------------- */

function fetchSettingsBody() {
  return {
    weibo_cookie: $('#s-weibo-cookie').value.trim(),
    weibo_containerid: $('#s-weibo-containerid').value.trim(),
    weibo_fetch_enabled: $('#s-fetch-enabled').checked ? '1' : '0',
    weibo_autosummarize: $('#s-fetch-autosum').checked ? '1' : '0',
    weibo_fetch_interval_min: $('#s-fetch-interval').value,
    weibo_fetch_cooldown: $('#s-fetch-cooldown').value,
  };
}

async function saveFetchSettings() {
  await api('/api/settings', { method: 'POST', body: fetchSettingsBody() });
  toast('抓取设置已保存');
}

/* ---- 抓取进度（自动 / 手动共用一份状态）----
   定时抓取和「打开 app 时的补抓」都在后台跑，所以这里持续轮询，
   只要在跑就把进度显示出来 —— 打开 app 也能看见它在补抓。 */

let _fetchTimer = null;         // 轮询定时器
let _fetchWasRunning = false;   // 上一次轮询时是否在跑（用于识别「刚跑完」）
let _fetchWatchUntil = 0;       // 打开后这段时间内保持轮询（捕获开机补抓）

function fetchPhaseLabel(st) {
  if (st.phase === 'summarize') return '抓取完成，正在总结为事件与速览…';
  if (st.trigger === 'auto') return '正在自动抓取超话新帖…';
  return '正在抓取超话新帖…';
}

function renderFetchProgress(st) {
  const running = !!st.running;
  const pct = Math.round((st.progress || 0) * 100);

  const dash = $('#dash-fetch');
  if (dash) {
    dash.hidden = !running;
    if (running) {
      $('#dash-fetch-label').textContent = fetchPhaseLabel(st);
      $('#dash-fetch-bar').style.width = pct + '%';
      $('#dash-fetch-text').textContent = st.message || '';
    }
  }

  const wrap = $('#p-fetch-progress');
  if (wrap) {
    wrap.hidden = !running;
    if (running) {
      $('#p-fetch-bar').style.width = pct + '%';
      $('#p-fetch-progress-text').textContent = st.message || '';
    }
  }
  const stopWrap = $('#p-fetch-stop-wrap');
  if (stopWrap) stopWrap.hidden = !running;
}

function ensureFetchPolling() {
  if (_fetchTimer) return;
  _fetchTimer = setInterval(pollFetch, 1800);
  pollFetch();
}

function stopFetchPolling() {
  if (_fetchTimer) { clearInterval(_fetchTimer); _fetchTimer = null; }
}

function startFetchWatch(seconds = 150) {
  // 打开 app 后的一段时间内保持轮询，才能看到「开机补抓」（它在启动约 8 秒后开跑）
  _fetchWatchUntil = Date.now() + seconds * 1000;
  ensureFetchPolling();
}

function refreshAfterFetch() {
  try { loadDashboard(); } catch (e) { /* 不在概览页时忽略 */ }
  try { loadPendingPosts(); } catch (e) { /* 忽略 */ }
  try { loadPushLog(); } catch (e) { /* 忽略 */ }
  try { loadRuns(); } catch (e) { /* 忽略 */ }
}

async function pollFetch() {
  let st;
  try { st = await api('/api/fetch/status'); } catch (e) { return; }
  renderFetchProgress(st);

  if (st.running) {
    _fetchWasRunning = true;
    _fetchWatchUntil = 0;                 // 已经在跑 → 之后按 running 决定是否继续
    return;
  }

  if (_fetchWasRunning) {                 // 刚跑完，收尾
    _fetchWasRunning = false;
    const el = $('#p-fetch-status');
    if (el) el.textContent = st.message || '';
    if (st.error) toast('抓取失败：' + st.error);
    else if (st.added) toast(`抓到 ${st.added} 条新帖`);
    else toast('没有新帖');
    refreshAfterFetch();
  }
  if (Date.now() > _fetchWatchUntil) stopFetchPolling();
}

async function stopFetch() {
  try {
    await api('/api/fetch/stop', { method: 'POST' });
    toast('已请求停止，正在收尾…');
  } catch (e) { toast(e.message); }
}

async function enableAutoFetch() {
  // 概览页「一键开启」：打开自动抓取（后端会立刻按空档补抓一次）
  try {
    await api('/api/settings', { method: 'POST', body: { weibo_fetch_enabled: '1' } });
    const cb = $('#s-fetch-enabled');
    if (cb) cb.checked = true;          // 同步设置页的复选框
    toast('已开启定时抓取，正在补抓…');
    startFetchWatch(90);
    loadDashboard();
  } catch (e) {
    toast('开启失败：' + e.message);
  }
}

async function fetchNow() {
  const status = $('#p-fetch-status');
  const btn = $('#p-fetch-btn');
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = '抓取中…';
  status.textContent = '抓取中…（若开着自动总结，会慢一点）';
  _fetchWasRunning = true;      // 已知要跑，让轮询知道该做「跑完」的收尾
  _fetchWatchUntil = 0;
  ensureFetchPolling();
  try {
    await api('/api/settings', { method: 'POST', body: fetchSettingsBody() });  // 所见即所用
    const r = await api('/api/fetch/run', { method: 'POST' });
    // 进度与收尾由 pollFetch 渲染；这里只在「根本没跑起来」时兜底
    if (!r.ok) {
      const msg = '抓取失败：' + (r.error || '未知原因');
      status.textContent = msg;
      _fetchWasRunning = false;
    }
  } catch (e) {
    status.textContent = '抓取失败：' + e.message;
    _fetchWasRunning = false;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

/* ---- 识图预设 / 状态徽标 ---- */

function renderVisionPresetOptions() {
  const sel = $('#s-vision-preset');
  if (!sel) return;
  sel.innerHTML = '<option value="">（手动填写 / 或选一个服务商）</option>' +
    VISION_PRESETS.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('');
}

function applyVisionPreset() {
  const p = VISION_PRESETS.find((x) => x.id === $('#s-vision-preset').value);
  if (!p) { $('#s-vision-help').textContent = ''; return; }
  if (p.url) $('#s-vision-url').value = p.url;
  if (p.model) $('#s-vision-model').value = p.model;
  $('#s-vision-help').textContent = p.help;
  renderVisionBadge();
}

function renderVisionBadge() {
  const b = $('#s-vision-badge');
  if (!b) return;
  const url = ($('#s-vision-url').value || '').trim();
  const key = ($('#s-vision-key').value || '').trim();
  const model = ($('#s-vision-model').value || '').trim();
  const miss = [!url && '地址', !key && '密钥', !model && '模型'].filter(Boolean);
  if (!miss.length) { b.className = 'tag likely'; b.textContent = '已配置 ✓'; }
  else { b.className = 'tag maybe'; b.textContent = '未配置（还缺：' + miss.join('、') + '）'; }
}

async function saveVisionSettings() {
  const body = {
    vision_base_url: $('#s-vision-url').value.trim(),
    vision_api_key: $('#s-vision-key').value.trim(),
    vision_model: $('#s-vision-model').value.trim(),
    vision_enabled: $('#s-vision-enabled').checked ? '1' : '0',
  };
  await api('/api/settings', { method: 'POST', body });
  // 立刻同步「写文案」页的识图可用状态（不用来回切页）
  VISION = {
    enabled: body.vision_enabled === '1',
    configured: !!(body.vision_base_url && body.vision_api_key && body.vision_model),
  };
  updateVisionBtn();
  renderVisionBadge();
  toast(VISION.enabled && VISION.configured ? '识图设置已保存，可以用了' : '识图设置已保存');
}

async function pullVisionModels() {
  const status = $('#s-vision-status');
  const sel = $('#s-vision-model-sel');
  status.textContent = '拉取中…';
  try {
    const r = await api('/api/vision/models', {
      method: 'POST',
      body: {
        base_url: $('#s-vision-url').value.trim(),
        api_key: $('#s-vision-key').value.trim(),
      },
    });
    if (r.ok && r.models.length) {
      sel.innerHTML = '<option value="">（选择模型）</option>' +
        r.models.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
      status.textContent = `拉到 ${r.models.length} 个模型，从下拉里选一个（会填进「识图模型」）。`;
    } else {
      status.textContent = r.error || '拉取失败';
    }
  } catch (e) {
    status.textContent = '拉取失败：' + e.message;
  }
}

function pickVisionModel() {
  const v = $('#s-vision-model-sel').value;
  if (v) $('#s-vision-model').value = v;
}

async function checkModel() {
  const m = await api('/api/health');
  if (m.ok && m.models && m.models.length) {
    $('#s-model-sel').innerHTML = '<option value="">（从列表选一个）</option>' +
      m.models.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join('');
  }
  $('#s-model-status').innerHTML = m.ok
    ? `已连上 Ollama。可用模型：${esc((m.models || []).join('、'))}。当前：<b>${esc(m.model)}</b> ${m.model_ready ? '<span class="tag likely">就绪</span>' : '<span class="tag maybe">未找到该模型</span>'}`
    : `连不上 Ollama（${esc(m.url)}）。请确认 Ollama 已启动。`;
}

function pickModel() {
  const v = $('#s-model-sel').value;
  if (v) { $('#s-model').value = v; toast('已选择模型：' + v + '（记得保存）'); }
}

let _runs = [];         // 运行日志缓存
let _runsOpen = false;  // 是否展开全部

async function loadRuns() {
  try { _runs = await api('/api/runs'); } catch (e) { _runs = []; }
  renderRuns();
}

function renderRuns() {
  const el = $('#s-runs');
  const btn = $('#runs-toggle');
  if (!_runs.length) {
    el.innerHTML = '<div class="empty">还没有运行记录。</div>';
    if (btn) btn.hidden = true;
    return;
  }
  if (btn) {
    btn.hidden = _runs.length <= 3;                    // 不超过 3 条就没什么好展开的
    btn.textContent = _runsOpen ? '收起 ▴' : `展开全部（${_runs.length}）▾`;
  }
  const list = _runsOpen ? _runs : _runs.slice(0, 3);   // 默认只显示最新三条
  el.innerHTML = list.map((r) => `<div class="item"><div class="body">
      <div class="desc">[${esc(r.job)}] ${esc(r.detail)}</div>
      <div class="meta"><span>${esc(r.created_at)}</span><span class="tag">${esc(r.status)}</span></div>
    </div></div>`).join('');
}

function toggleRuns() {
  _runsOpen = !_runsOpen;
  renderRuns();
}

/* ---------------- 数据维护 ---------------- */

async function cleanupNow() {
  const el = $('#s-maint-status');
  el.textContent = '清理中…';
  try {
    const r = await api('/api/maintenance/cleanup', { method: 'POST' });
    const d = r.deleted || {};
    el.textContent = `已清理：日志 ${d.runs || 0} 条、推送记录 ${d.push_log || 0} 条、旧帖 ${d.posts || 0} 条`;
    loadRuns();
  } catch (e) {
    el.textContent = '清理失败：' + e.message;
  }
}

async function exportData() {
  const el = $('#s-maint-status');
  el.textContent = '导出中…';
  try {
    const data = await api('/api/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'weibo-chaohua-backup.json';
    a.click();
    URL.revokeObjectURL(a.href);
    el.textContent = '已导出（不含设置与登录 cookie）';
  } catch (e) {
    el.textContent = '导出失败：' + e.message;
  }
}
