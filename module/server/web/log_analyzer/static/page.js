/**
 * OAS 日志分析器页面逻辑（零依赖，配合 parser.js 使用）。
 *
 * 两种数据来源:
 *  - 服务端模式: OAS WebUI 内打开（/log_analyzer/page），经 /log_analyzer/api/* 取日志，
 *    错误截图复用 /logs/errors/* 接口；
 *  - 本地模式: 直接打开页面或服务不可达时，拖入/选择日志文件解析。
 *  - ?url=相对路径: 直接抓取一个日志文本（离线自测/分享用）。
 */
(function () {
  'use strict';

  var P = window.OASLogParser;
  var $ = function (id) { return document.getElementById(id); };

  var ROW_H = 26;      // 普通行高
  var SEC_H = 30;      // 小节头高

  var S = {
    mode: null,            // 'server' | 'local'
    serverItems: [],       // 服务端日志文件列表
    fileName: '',
    parsed: null,
    scope: -1,             // 时间线任务过滤, -1 为全部
    filter: 'all',
    inlineQuery: '',
    selected: -1,
    collapsed: new Set(),  // 折叠的 section 下标
    display: [],           // 时间线可见行
    prefix: [],            // 行高前缀和
    totalH: 0,
    searchResults: [],
    errorDirs: [],         // 服务端错误目录（当前文件对应的日期+实例）
    errorDetailCache: new Map(),
    showRaw: false
  };

  // ================================================================ 启动 ====
  init();

  function init() {
    bindChrome();
    var url = new URLSearchParams(location.search).get('url');
    if (url) {
      fetch(url).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
        .then(function (t) { loadFromText(t, url.split('/').pop() || url); })
        .catch(function (e) { enterLocalMode('读取 ' + url + ' 失败: ' + e.message); });
      return;
    }
    fetch('/log_analyzer/api/logs').then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) { enterServerMode(data); })
      .catch(function () { enterLocalMode(); });
  }

  function bindChrome() {
    // 顶部 tab
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (btn) {
      btn.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        var tab = btn.getAttribute('data-tab');
        ['analyze', 'search', 'stats'].forEach(function (v) { $('view-' + v).hidden = v !== tab; });
        if (tab === 'analyze') renderWindow();
        if (tab === 'search' && !S.searchResults.length) $('searchInput').focus();
      });
    });
    // 过滤 chips
    Array.prototype.forEach.call(document.querySelectorAll('#filterChips .chip'), function (chip) {
      chip.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('#filterChips .chip'), function (c) { c.classList.remove('active'); });
        chip.classList.add('active');
        S.filter = chip.getAttribute('data-f');
        rebuildDisplay();
      });
    });
    $('inlineQuery').addEventListener('input', debounce(function () {
      S.inlineQuery = $('inlineQuery').value.trim();
      rebuildDisplay();
    }, 250));
    $('taskAllBtn').addEventListener('click', function () { setScope(-1); });
    $('showRawToggle').addEventListener('change', function () {
      S.showRaw = $('showRawToggle').checked;
      rebuildDisplay();
    });
    // 本地文件
    $('openFileBtn').addEventListener('click', function () { $('fileInput').click(); });
    $('fileInput').addEventListener('change', function () {
      if ($('fileInput').files.length) readLogFile($('fileInput').files[0]);
    });
    // 拖拽
    ['dragenter', 'dragover'].forEach(function (ev) {
      window.addEventListener(ev, function (e) {
        if (!e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types, 'Files') < 0) return;
        e.preventDefault();
        $('dragMask').hidden = false;
      });
    });
    ['dragleave', 'drop'].forEach(function (ev) {
      window.addEventListener(ev, function (e) {
        e.preventDefault();
        if (ev === 'drop' && e.dataTransfer.files.length) readLogFile(e.dataTransfer.files[0]);
        $('dragMask').hidden = true;
      });
    });
    // 虚拟列表
    bindVirtualList($('timeline'), renderTimelineWindow);
    bindVirtualList($('searchResults'), renderSearchWindow);
    window.addEventListener('resize', function () { renderTimelineWindow(); renderSearchWindow(); });
    // 搜索
    $('searchBtn').addEventListener('click', doSearch);
    $('searchInput').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(); });
    $('historySelect').addEventListener('change', function () {
      if (!$('historySelect').value) return;
      $('searchInput').value = $('historySelect').value;
      doSearch();
    });
    // 服务端控件
    $('loadBtn').addEventListener('click', loadServerLog);
    $('scriptSelect').addEventListener('change', fillDateSelect);
  }

  // ====================================================== 数据加载入口 ====
  function enterServerMode(data) {
    S.mode = 'server';
    S.serverItems = (data && data.items) || [];
    if (!S.serverItems.length) { enterLocalMode('服务端暂无日志文件'); return; }
    $('scriptSelect').hidden = false;
    $('dateSelect').hidden = false;
    $('loadBtn').hidden = false;
    var scripts = [];
    S.serverItems.forEach(function (it) { if (scripts.indexOf(it.script) < 0) scripts.push(it.script); });
    $('scriptSelect').innerHTML = scripts.map(function (s) {
      return '<option value="' + escAttr(s) + '">' + escHtml(s) + '</option>';
    }).join('');
    fillDateSelect();
    loadServerLog(); // 默认加载最新一份
  }

  function enterLocalMode(errText) {
    S.mode = 'local';
    $('dropzone').hidden = false;
    $('dropStatus').textContent = errText || '';
    ['scriptSelect', 'dateSelect', 'loadBtn'].forEach(function (id) { $(id).hidden = true; });
  }

  function fillDateSelect() {
    var script = $('scriptSelect').value;
    var dates = [];
    S.serverItems.forEach(function (it) { if (it.script === script) dates.push(it); });
    dates.sort(function (a, b) { return a.date < b.date ? 1 : -1; });
    $('dateSelect').innerHTML = dates.map(function (it) {
      return '<option value="' + escAttr(it.file) + '">' + escHtml(it.date) + ' (' + fmtSize(it.size) + ')</option>';
    }).join('');
  }

  function loadServerLog() {
    var file = $('dateSelect').value;
    if (!file) return;
    $('dropStatus').textContent = '';
    fetch('/log_analyzer/api/log?file=' + encodeURIComponent(file))
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
      .then(function (t) { loadFromText(t, file); })
      .catch(function (e) {
        enterLocalMode('');
        $('dropStatus').textContent = '加载 ' + file + ' 失败: ' + e.message;
      });
  }

  function readLogFile(file) {
    var reader = new FileReader();
    reader.onload = function () { loadFromText(String(reader.result), file.name); };
    reader.readAsText(file, 'utf-8');
  }

  function loadFromText(text, name) {
    var parsed = P.buildSectionRanges(P.parseLogText(text, name));
    S.parsed = parsed;
    S.fileName = name;
    S.scope = -1;
    S.filter = 'all';
    S.inlineQuery = '';
    S.selected = -1;
    S.collapsed.clear();
    S.searchResults = [];
    $('inlineQuery').value = '';
    Array.prototype.forEach.call(document.querySelectorAll('#filterChips .chip'), function (c) {
      c.classList.toggle('active', c.getAttribute('data-f') === 'all');
    });
    $('fileChip').hidden = false;
    $('fileChip').textContent = name;
    $('fileChip').title = name;
    $('metaBar').hidden = false;
    $('dropzone').hidden = true;
    var st = parsed.stats;
    $('metaText').textContent = name + ' · ' + parsed.lineCount + ' 行 · ' + parsed.records.length + ' 条记录 · 任务 ' +
      st.taskTotal + '（成功 ' + st.taskSuccess + ' / 失败 ' + st.taskFailed + '）· 错误记录 ' + st.errorCount + ' · 解析 ' + parsed.parseMs + 'ms';
    renderTasks();
    rebuildDisplay();
    renderStats();
    // 服务端模式: 拉取错误目录供详情页关联截图
    S.errorDirs = [];
    if (S.mode === 'server' && location.protocol.indexOf('http') === 0) {
      var m = /^(\d{4}-\d{2}-\d{2})_(.+)\.txt$/.exec(name);
      if (m) {
        fetch('/logs/errors?date=' + m[1] + '&script_name=' + encodeURIComponent(m[2]))
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (d) { if (d && d.items) { S.errorDirs = d.items; if (S.selected >= 0) renderDetail(); } })
          .catch(function () { /* 截图关联为可选能力 */ });
      }
    }
  }

  // ================================================================ 任务 ====
  function renderTasks() {
    var d = S.parsed;
    var html = ['<div class="task-card' + (S.scope === -1 ? ' active' : '') + '" data-idx="-1"><div class="t1">全部任务</div>' +
      '<div class="t2"><span>' + d.stats.taskTotal + ' 个任务</span></div></div>'];
    d.tasks.forEach(function (t, i) {
      var dur;
      if (t.startMs !== null && t.endMs !== null) dur = fmtDur(t.endMs - t.startMs);
      else dur = t.status === 'running' ? '进行中' : '未结束';
      var secs = 0;
      for (var k = 0; k < d.sections.length; k++) if (d.sections[k].taskIndex === i) secs++;
      html.push(
        '<div class="task-card' + (S.scope === i ? ' active' : '') + '" data-idx="' + i + '">' +
        '<div class="t1"><span class="status-dot st-' + t.status + '"></span>' + escHtml(t.name) +
        '<span style="margin-left:auto" class="muted">#' + (i + 1) + '</span></div>' +
        '<div class="t2"><span>' + (t.startMs !== null ? escHtml(timeOf(t.startRec)) : '-') + '</span>' +
        '<span>' + dur + '</span><span>' + secs + ' 节点</span></div>' +
        (t.errorTitle ? '<div class="t3" title="' + escAttr(t.errorTitle) + '">' + escHtml(t.errorTitle) + '</div>' : '') +
        '</div>');
    });
    $('taskList').innerHTML = html.join('');
    Array.prototype.forEach.call($('taskList').querySelectorAll('.task-card'), function (card) {
      card.addEventListener('click', function () { setScope(+card.getAttribute('data-idx')); });
    });
  }

  function setScope(idx) {
    S.scope = idx;
    S.collapsed.clear();
    S.selected = -1;
    renderTasks();
    rebuildDisplay();
    if (idx >= 0) scrollToRec(S.parsed.tasks[idx].startRec, false);
    renderDetail();
  }

  // ============================================================ 时间线 ====
  function rebuildDisplay() {
    var d = S.parsed;
    var rows = [];
    if (!d) { S.display = []; S.prefix = []; renderTimelineWindow(); return; }
    var from = 0, to = d.records.length - 1;
    if (S.scope >= 0) {
      var t = d.tasks[S.scope];
      from = t.startRec;
      to = t.endRec !== null ? t.endRec : d.records.length - 1;
    }
    // section 下标 -> rec 的映射，便于折叠判断
    var secStartRecs = d.sections.map(function (s) { return s.rec; });
    var collapsedUntil = -1;
    var cat = S.filter;
    var q = S.inlineQuery.toLowerCase();
    var i, secIdx = 0;
    // 找到 from 之前最近的 section
    while (secIdx < d.sections.length && d.sections[secIdx].rec < from) secIdx++;
    var taskByHr = {};
    if (S.scope < 0) {
      d.tasks.forEach(function (t) { taskByHr[t.startRec + 1] = t; });
    } else {
      taskByHr[from + 1] = d.tasks[S.scope];
    }
    var visibleRec = function (r) {
      if (cat === 'action' && r.kind !== 'click' && r.kind !== 'swipe') return false;
      if (cat === 'reco' && r.kind !== 'metric' && r.kind !== 'ui') return false;
      if (cat === 'warn' && r.kind !== 'warn') return false;
      if (cat === 'error' && r.kind !== 'error') return false;
      if (q && r.msg.toLowerCase().indexOf(q) < 0) return false;
      return true;
    };
    // 过滤激活时隐藏没有可见记录的空小节
    var filterActive = cat !== 'all' || !!q;
    var secVisible = null;
    if (filterActive) {
      secVisible = [];
      for (i = 0; i < d.sections.length; i++) secVisible.push(false);
      var si = 0;
      while (si < d.sections.length && d.sections[si].rec < from) si++;
      for (var k2 = from; k2 <= to; k2++) {
        var rr = d.records[k2];
        if (rr.kind === 'hr' || rr.echo) continue;
        while (si < d.sections.length && d.sections[si].rec <= k2) si++;
        if (si > 0 && visibleRec(rr)) secVisible[si - 1] = true;
      }
    }
    for (i = from; i <= to; i++) {
      var r = d.records[i];
      if (r.echo) continue;
      var isSec = r.kind === 'hr';
      if (isSec) {
        var secNo = secIdx; // 当前 section 下标
        secIdx++;
        if (filterActive && !secVisible[secNo]) continue;
        var collapsed = S.collapsed.has(secNo);
        rows.push({ h: SEC_H, type: 'sec', rec: i, sec: secNo, task: taskByHr[i] || null, collapsed: collapsed });
        collapsedUntil = collapsed ? (d.sections[secNo].endRec !== undefined ? d.sections[secNo].endRec : to) : -1;
        continue;
      }
      if (collapsedUntil >= i) continue;
      if (!visibleRec(r)) continue;
      rows.push({ h: ROW_H, type: 'rec', rec: i });
    }
    S.display = rows;
    var prefix = [0];
    for (i = 0; i < rows.length; i++) prefix.push(prefix[i] + rows[i].h);
    S.prefix = prefix;
    S.totalH = prefix[rows.length];
    $('tlSpacer').style.height = S.totalH + 'px';
    renderTimelineWindow();
  }

  function bindVirtualList(el, renderFn) {
    el.addEventListener('scroll', debounce(renderFn, 10));
    el._renderFn = renderFn;
  }

  function renderTimelineWindow() { renderWindowFor($('timeline'), S.display, S.prefix, rowHtml, onRowClick); }
  function renderSearchWindow() {
    renderWindowFor($('searchResults'), S.searchResults, searchPrefix(), searchRowHtml, onSearchRowClick);
  }

  function searchPrefix() {
    var prefix = [0];
    for (var i = 0; i < S.searchResults.length; i++) prefix.push(prefix[i] + ROW_H);
    return prefix;
  }

  function renderWindowFor(el, rows, prefix, htmlFn, clickFn) {
    var windowEl = el.querySelector('.vlist-window');
    var total = rows.length;
    if (!total) {
      windowEl.innerHTML = '';
      return;
    }
    var top = el.scrollTop;
    var h = el.clientHeight || 400;
    // 前缀和定位起始行
    var lo = 0, hi = total - 1, start = 0;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (prefix[mid] <= top) { start = mid; lo = mid + 1; } else hi = mid - 1;
    }
    var end = start;
    while (end < total && prefix[end] < top + h) end++;
    end = Math.min(total, end + 5);
    start = Math.max(0, start - 5);
    var buf = [];
    for (var k = start; k < end; k++) buf.push(htmlFn(rows[k], k, prefix[k]));
    windowEl.style.transform = 'translateY(' + prefix[start] + 'px)';
    windowEl.innerHTML = buf.join('');
    Array.prototype.forEach.call(windowEl.children, function (row) {
      row.addEventListener('click', function () { clickFn(row); });
    });
  }

  function rowHtml(row, idx, top) {
    var d = S.parsed;
    if (row.type === 'sec') {
      var r = d.records[row.rec];
      var title = r.hr.title || '（无标题）';
      var badge = '';
      if (row.task) {
        var cls = row.task.status === 'success' ? 'badge-ok' : row.task.status === 'running' ? 'badge-run' : 'badge-fail';
        var label = row.task.status === 'success' ? '成功' : row.task.status === 'running' ? '进行中' : '失败';
        var dur = row.task.startMs !== null && row.task.endMs !== null ? ' ' + fmtDur(row.task.endMs - row.task.startMs) : '';
        badge = '<span class="badge ' + cls + '">' + label + dur + '</span>';
      }
      return '<div class="vrow section' + (row.collapsed ? ' collapsed' : '') + '" data-kind="sec" data-rec="' + row.rec + '" data-sec="' + row.sec + '" style="top:0">' +
        '<span class="rule-arrow">' + (row.collapsed ? '▸' : '▾') + '</span>' +
        '<span class="rule">' + (r.hr.level === 2 ? '──' : '══') + '</span>' +
        '<span>' + escHtml(title) + '</span>' +
        '<span class="rule">' + (r.hr.level === 2 ? '──' : '══') + '</span>' + badge +
        '<span class="muted" style="margin-left:auto;font-weight:400">' + (timeOf(row.rec) || '') + '</span></div>';
    }
    var rec = d.records[row.rec];
    var lineCol = S.showRaw ? '<span class="ln">L' + rec.line + '</span>' : '';
    var time = rec.tsText ? '<span class="t">' + rec.tsText.slice(0, 12) + '</span>' : '<span class="t"></span>';
    return '<div class="vrow k-' + rec.kind + (row.rec === S.selected ? ' selected' : '') + '" data-kind="rec" data-rec="' + row.rec + '">' +
      time + '<span class="dot"></span>' + lineCol +
      '<span class="msg" title="' + escAttr(rec.msg.split('\n')[0].slice(0, 400)) + '">' + escHtml(rec.msg.split('\n')[0]) + '</span>' +
      '<span class="src">' + escHtml(rec.src) + '</span></div>';
  }

  function onRowClick(rowEl) {
    var kind = rowEl.getAttribute('data-kind');
    var rec = +rowEl.getAttribute('data-rec');
    if (kind === 'sec') {
      var sec = +rowEl.getAttribute('data-sec');
      if (S.collapsed.has(sec)) S.collapsed.delete(sec); else S.collapsed.add(sec);
      rebuildDisplay();
      return;
    }
    select(rec);
  }

  function select(rec) {
    S.selected = rec;
    renderTimelineWindow();
    renderDetail();
  }

  function scrollToRec(rec, selectIt) {
    if (selectIt !== false) S.selected = rec;
    var idx = -1;
    for (var i = 0; i < S.display.length; i++) {
      if (S.display[i].rec === rec) { idx = i; break; }
    }
    if (idx < 0) {
      // 目标被过滤/折叠隐藏: 放宽条件后重试
      S.filter = 'all';
      S.inlineQuery = '';
      $('inlineQuery').value = '';
      S.collapsed.clear();
      Array.prototype.forEach.call(document.querySelectorAll('#filterChips .chip'), function (c) {
        c.classList.toggle('active', c.getAttribute('data-f') === 'all');
      });
      rebuildDisplay();
      for (i = 0; i < S.display.length; i++) if (S.display[i].rec === rec) { idx = i; break; }
      if (idx < 0) return;
    }
    var el = $('timeline');
    el.scrollTop = Math.max(0, S.prefix[idx] - el.clientHeight / 3);
    renderTimelineWindow();
  }

  // ================================================================ 详情 ====
  function renderDetail() {
    var d = S.parsed;
    var body = $('detailBody');
    if (!d || S.selected < 0 || !d.records[S.selected]) {
      body.innerHTML = '<div class="empty-tip">在时间线中选择一条记录查看详情</div>';
      $('detailHint').textContent = '';
      return;
    }
    var r = d.records[S.selected];
    var task = findTaskOf(S.selected);
    $('detailHint').textContent = task ? '所属任务: ' + task.name : '';
    var kindLabel = P.KIND_LABEL[r.kind] || r.kind;
    var html =
      '<div class="d-block"><div class="kv">' +
      '<span>时间</span><b>' + escHtml(r.dateText + ' ' + r.tsText) + '</b>' +
      '<span>级别</span><b>' + escHtml(r.level || '-') + '</b>' +
      '<span>类别</span><b>' + escHtml(kindLabel) + '</b>' +
      '<span>来源</span><b>' + escHtml(r.src || '-') + '</b>' +
      '<span>行号</span><b>' + r.line + (r.rawLines.length > 1 ? ' ~ ' + (r.line + r.rawLines.length - 1) : '') + '</b>' +
      (task ? '<span>任务</span><b>' + escHtml(task.name) + '（' + statusLabel(task.status) + '）</b>' : '') +
      '</div></div>' +
      '<div class="d-block"><div class="d-title">消息</div><pre class="d-msg">' + escHtml(r.msg) + '</pre></div>' +
      '<div class="d-block"><div class="d-title">上下文 <span class="muted">（前后各 8 条，点击跳转）</span></div><div class="d-ctx">' + ctxHtml(d, S.selected) + '</div></div>' +
      '<div class="d-block" id="shotBlock"><div class="d-title">错误截图</div><div id="shotBox" class="muted">…</div></div>';
    body.innerHTML = html;
    body.scrollTop = 0;
    Array.prototype.forEach.call(body.querySelectorAll('.d-ctx-row'), function (row) {
      row.addEventListener('click', function () { scrollToRec(+row.getAttribute('data-rec')); renderDetail(); });
    });
    renderShots(task, r);
  }

  function ctxHtml(d, rec) {
    var out = [];
    for (var i = Math.max(0, rec - 8); i <= Math.min(d.records.length - 1, rec + 8); i++) {
      var r = d.records[i];
      out.push('<div class="d-ctx-row' + (i === rec ? ' current' : '') + '" data-rec="' + i + '">' +
        '<span>' + (r.tsText || ''.slice(0)) + '</span><span class="m">' + escHtml(r.msg.split('\n')[0].slice(0, 90)) + '</span></div>');
    }
    return out.join('');
  }

  function renderShots(task, rec) {
    var box = $('shotBox');
    if (!box) return;
    if (!S.errorDirs.length || !task || task.status !== 'failed') {
      $('shotBlock').style.display = 'none';
      return;
    }
    var anchor = rec.tsMs || (task.errorRec >= 0 ? S.parsed.records[task.errorRec].tsMs : null) || task.endMs || task.startMs;
    if (anchor === null) { $('shotBlock').style.display = 'none'; return; }
    var cands = S.errorDirs.filter(function (it) { return Math.abs(it.timestamp_ms - anchor) <= 10 * 60 * 1000; })
      .sort(function (a, b) { return Math.abs(a.timestamp_ms - anchor) - Math.abs(b.timestamp_ms - anchor); })
      .slice(0, 2);
    if (!cands.length) { $('shotBlock').style.display = 'none'; return; }
    var pending = cands.length;
    cands.forEach(function (it) {
      getErrorDetail(it.id).then(function (detail) {
        pending--;
        if (!detail || !detail.images || !detail.images.length) {
          if (pending <= 0 && !box.querySelector('img')) { $('shotBlock').style.display = 'none'; }
          return;
        }
        var wrap = document.createElement('div');
        var title = document.createElement('div');
        title.className = 'muted';
        title.style.margin = '4px 0';
        title.textContent = it.id + '（' + new Date(it.timestamp_ms).toLocaleString() + '）';
        var grid = document.createElement('div');
        grid.className = 'shots';
        detail.images.slice(0, 6).forEach(function (img) {
          var a = document.createElement('a');
          a.href = img.url;
          a.target = '_blank';
          var el = document.createElement('img');
          el.src = img.url;
          el.loading = 'lazy';
          el.title = img.name;
          a.appendChild(el);
          grid.appendChild(a);
        });
        wrap.appendChild(title);
        wrap.appendChild(grid);
        var slot = box.querySelector('.slot-pending');
        if (slot) slot.replaceWith(wrap); else box.appendChild(wrap);
      }).catch(function () {
        pending--;
        if (pending <= 0 && !box.querySelector('img')) $('shotBlock').style.display = 'none';
      });
    });
    box.innerHTML = cands.map(function () { return '<div class="slot-pending muted">加载中…</div>'; }).join('');
  }

  function getErrorDetail(id) {
    if (S.errorDetailCache.has(id)) return Promise.resolve(S.errorDetailCache.get(id));
    return fetch('/logs/errors/' + encodeURIComponent(id)).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (d) { S.errorDetailCache.set(id, d); return d; });
  }

  // ================================================================ 搜索 ====
  function doSearch() {
    var d = S.parsed;
    var q = $('searchInput').value;
    var meta = $('searchMeta');
    if (!d) { meta.textContent = '请先加载日志'; return; }
    if (!q) { meta.textContent = '输入关键字后点击搜索'; return; }
    saveHistory(q);
    var t0 = performance.now();
    var matcher;
    if ($('reToggle').checked) {
      try {
        matcher = new RegExp(q, $('caseToggle').checked ? 'i' : '');
      } catch (e) {
        meta.textContent = '正则表达式无效: ' + e.message;
        return;
      }
    } else {
      var lower = $('caseToggle').checked ? q.toLowerCase() : q;
      matcher = { test: function (s) { return ($('caseToggle').checked ? s.toLowerCase() : s).indexOf(lower) >= 0; } };
    }
    var results = [];
    for (var i = 0; i < d.records.length && results.length < 5000; i++) {
      if (d.records[i].echo) continue;
      if (matcher.test(d.records[i].msg)) results.push({ h: ROW_H, type: 'hit', rec: i });
    }
    S.searchResults = results;
    $('srSpacer').style.height = results.length * ROW_H + 'px';
    meta.textContent = '共 ' + results.length + ' 条结果' + (results.length >= 5000 ? '（已截断）' : '') + '，耗时 ' + (performance.now() - t0).toFixed(0) + 'ms';
    renderSearchWindow();
  }

  function searchRowHtml(row, idx, top) {
    var r = S.parsed.records[row.rec];
    return '<div class="vrow k-' + r.kind + '" data-kind="hit" data-rec="' + row.rec + '">' +
      '<span class="ln">L' + r.line + '</span><span class="t">' + (r.tsText || '') + '</span><span class="dot"></span>' +
      '<span class="msg">' + escHtml(r.msg.split('\n')[0]) + '</span>' +
      '<span class="src">' + escHtml(r.src) + '</span></div>';
  }

  function onSearchRowClick(rowEl) {
    var rec = +rowEl.getAttribute('data-rec');
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === 'analyze');
    });
    ['analyze', 'search', 'stats'].forEach(function (v) { $('view-' + v).hidden = v !== 'analyze'; });
    S.scope = -1;
    renderTasks();
    scrollToRec(rec);
  }

  function saveHistory(q) {
    var list = [];
    try { list = JSON.parse(localStorage.getItem('oas_log_analyzer_history') || '[]'); } catch (e) { /* 忽略 */ }
    list = list.filter(function (x) { return x !== q; });
    list.unshift(q);
    list = list.slice(0, 15);
    try { localStorage.setItem('oas_log_analyzer_history', JSON.stringify(list)); } catch (e) { /* 忽略 */ }
    var sel = $('historySelect');
    sel.hidden = false;
    sel.innerHTML = '<option value="">历史: ' + list.length + '</option>' +
      list.map(function (x) { return '<option value="' + escAttr(x) + '">' + escHtml(x) + '</option>'; }).join('');
  }

  // ================================================================ 统计 ====
  function renderStats() {
    var d = S.parsed;
    if (!d) return;
    var st = d.stats;
    var totalClicks = st.clicks.reduce(function (n, c) { return n + c.count; }, 0);
    $('statCards').innerHTML =
      card(st.taskTotal, '任务总数', '') +
      card(st.taskSuccess, '成功', 'num-ok') +
      card(st.taskFailed, '失败', 'num-fail') +
      card(st.taskRunning, '进行中', 'num-run') +
      card(st.errorCount, '错误记录', 'num-fail') +
      card(totalClicks, '点击动作', '') +
      card(st.notifyCount, '通知', 'num-warn');
    // 任务表
    var rows = d.tasks.map(function (t, i) {
      var dur = t.startMs !== null && t.endMs !== null ? ((t.endMs - t.startMs) / 1000).toFixed(1) + 's' : '-';
      return '<tr data-task="' + i + '"><td class="mono">' + (i + 1) + '</td>' +
        '<td><span class="status-dot st-' + t.status + '"></span> ' + escHtml(t.name) + '</td>' +
        '<td>' + statusLabel(t.status) + '</td>' +
        '<td class="mono">' + escHtml(timeOf(t.startRec) || '-') + '</td>' +
        '<td class="mono">' + dur + '</td>' +
        '<td class="muted" title="' + escAttr(t.errorTitle || '') + '">' + escHtml((t.errorTitle || '').slice(0, 60)) + '</td></tr>';
    }).join('');
    $('taskTable').innerHTML = '<table class="stats"><thead><tr><th>#</th><th>任务</th><th>状态</th><th>开始</th><th>耗时</th><th>错误</th></tr></thead><tbody>' + rows + '</tbody></table>';
    Array.prototype.forEach.call($('taskTable').querySelectorAll('tr[data-task]'), function (tr) {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', function () {
        Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (b) {
          b.classList.toggle('active', b.getAttribute('data-tab') === 'analyze');
        });
        ['analyze', 'search', 'stats'].forEach(function (v) { $('view-' + v).hidden = v !== 'analyze'; });
        setScope(+tr.getAttribute('data-task'));
      });
    });
    barChart($('clickBars'), st.clicks.slice(0, 15));
    barChart($('srcBars'), st.srcs.slice(0, 10));
    barChart($('levelBars'), st.levels);
  }

  function card(num, label, cls) {
    return '<div class="card"><div class="num ' + cls + '">' + num + '</div><div class="lbl">' + label + '</div></div>';
  }

  function barChart(el, items) {
    if (!items.length) { el.innerHTML = '<div class="empty-tip">无数据</div>'; return; }
    var max = items[0].count || 1;
    el.innerHTML = items.map(function (it) {
      return '<div class="bar-row" title="' + escAttr(it.name) + '"><span class="name">' + escHtml(it.name) + '</span>' +
        '<span class="track"><span class="fill" style="width:' + (it.count / max * 100).toFixed(1) + '%"></span></span>' +
        '<span class="cnt">' + it.count + '</span></div>';
    }).join('');
  }

  // ================================================================ 工具 ====
  function timeOf(rec) {
    var r = S.parsed.records[rec];
    return r && r.tsText ? r.tsText.slice(0, 8) : '';
  }

  function findTaskOf(rec) {
    var tasks = S.parsed.tasks;
    for (var i = 0; i < tasks.length; i++) {
      if (rec >= tasks[i].startRec && (tasks[i].endRec === null || rec <= tasks[i].endRec)) return tasks[i];
    }
    return null;
  }

  function statusLabel(st) {
    return st === 'success' ? '成功' : st === 'running' ? '进行中' : '失败';
  }

  function fmtDur(ms) {
    var s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
  }

  function fmtSize(n) {
    if (n > 1048576) return (n / 1048576).toFixed(1) + 'MB';
    if (n > 1024) return (n / 1024).toFixed(0) + 'KB';
    return n + 'B';
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function escAttr(s) { return escHtml(s); }

  function debounce(fn, ms) {
    var t = null;
    return function () {
      var args = arguments, self = this;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }
})();
