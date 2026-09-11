/* 任务执行统计分析页逻辑 */
(function () {
  'use strict';

  var state = {
    scripts: [],
    tasks: [],
    records: [],
    page: 1,
    pageSize: 20,
  };

  var el = {
    scriptSelect: document.getElementById('scriptSelect'),
    taskSelect: document.getElementById('taskSelect'),
    startInput: document.getElementById('startInput'),
    endInput: document.getElementById('endInput'),
    refreshBtn: document.getElementById('refreshBtn'),
    statTotal: document.getElementById('statTotal'),
    statRate: document.getElementById('statRate'),
    statRateSub: document.getElementById('statRateSub'),
    statAvg: document.getElementById('statAvg'),
    statBattle: document.getElementById('statBattle'),
    recordBody: document.getElementById('recordBody'),
    pagerTotal: document.getElementById('pagerTotal'),
    pageSize: document.getElementById('pageSize'),
    pagePrev: document.getElementById('pagePrev'),
    pageNext: document.getElementById('pageNext'),
    pageNumbers: document.getElementById('pageNumbers'),
    gotoInput: document.getElementById('gotoInput'),
  };

  var charts = {
    trend: echarts.init(document.getElementById('trendChart')),
    pie: echarts.init(document.getElementById('pieChart')),
    bar: echarts.init(document.getElementById('barChart')),
  };

  window.addEventListener('resize', function () {
    Object.keys(charts).forEach(function (key) { charts[key].resize(); });
  });

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  function toLocalInputValue(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function toQueryValue(inputValue) {
    // 浏览器 datetime-local 在秒为 0 时会省略秒位，这里补齐
    var value = inputValue.replace('T', ' ');
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(value)) { value += ':00'; }
    return value;
  }

  function initDateRange() {
    var now = new Date();
    var dayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    var dayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
    el.startInput.value = toLocalInputValue(dayStart);
    el.endInput.value = toLocalInputValue(dayEnd);
  }

  function fmtMinutes(seconds) {
    if (!seconds || seconds < 0) { seconds = 0; }
    return (seconds / 60).toFixed(1) + 'm';
  }

  function fmtSeconds(seconds) {
    if (!seconds || seconds < 0) { seconds = 0; }
    return seconds.toFixed(1) + 's';
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function loadScripts() {
    return fetch('/task_statistics/api/scripts')
      .then(function (res) { return res.json(); })
      .then(function (data) {
        state.scripts = data.scripts || [];
        el.scriptSelect.innerHTML = '';
        if (!state.scripts.length) {
          var opt = document.createElement('option');
          opt.value = '';
          opt.textContent = '暂无实例日志';
          el.scriptSelect.appendChild(opt);
          el.scriptSelect.disabled = true;
          return;
        }
        state.scripts.forEach(function (name) {
          var opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          el.scriptSelect.appendChild(opt);
        });
      });
  }

  function renderStatCards(summary) {
    el.statTotal.textContent = summary.total_runs;
    el.statRate.textContent = summary.success_rate + '%';
    el.statRateSub.textContent = '成功 ' + summary.success_runs + ' / 失败 ' + summary.failed_runs;
    el.statAvg.textContent = summary.avg_duration_minutes;
    el.statBattle.textContent = summary.total_battle_count;
  }

  function emptyChartOption() {
    return {
      graphic: [{
        type: 'text', left: 'center', top: 'middle',
        style: { text: '暂无数据', fontSize: 14, fill: '#909399' },
      }],
    };
  }

  function renderTrend(summary) {
    var buckets = summary.trend || [];
    if (!buckets.length) {
      charts.trend.setOption(emptyChartOption(), { notMerge: true });
      return;
    }
    charts.trend.setOption({
      grid: { left: 42, right: 46, top: 30, bottom: 24 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: buckets.map(function (item) { return item.bucket; }),
        axisLabel: { fontSize: 10, interval: Math.max(0, Math.ceil(buckets.length / 12) - 1) },
        axisLine: { lineStyle: { color: '#dcdfe6' } },
        axisTick: { show: false },
      },
      yAxis: [
        { type: 'value', name: '执行次数', nameTextStyle: { fontSize: 10 }, minInterval: 1,
          axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: '#f0f2f8' } } },
        { type: 'value', name: '时长(分钟)', nameTextStyle: { fontSize: 10 },
          axisLabel: { fontSize: 10 }, splitLine: { show: false } },
      ],
      series: [
        {
          name: '执行次数', type: 'line', data: buckets.map(function (item) { return item.run_count; }),
          symbol: 'circle', symbolSize: 5, itemStyle: { color: '#5b8ff9' }, lineStyle: { color: '#5b8ff9', width: 2 },
        },
        {
          name: '平均时长(分钟)', type: 'line', yAxisIndex: 1,
          data: buckets.map(function (item) { return item.avg_duration_minutes; }),
          symbol: 'circle', symbolSize: 5, itemStyle: { color: '#5ad8a6' }, lineStyle: { color: '#5ad8a6', width: 2 },
        },
      ],
    }, { notMerge: true });
  }

  function renderPie(summary) {
    var data = (summary.distribution || []).map(function (item) {
      return { name: item.task, value: item.run_count };
    });
    if (!data.length) {
      charts.pie.setOption(emptyChartOption(), { notMerge: true });
      return;
    }
    charts.pie.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} 次 ({d}%)' },
      legend: {
        type: 'scroll', orient: 'vertical', left: 0, top: 'middle',
        height: 240, textStyle: { fontSize: 11 }, itemWidth: 12, itemHeight: 8,
        pageIconSize: 8,
      },
      series: [{
        type: 'pie', radius: '62%', center: ['62%', '50%'],
        data: data,
        label: { fontSize: 11, formatter: '{b}' },
        labelLine: { length: 8, length2: 8 },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0, 0, 0, 0.2)' } },
      }],
    }, { notMerge: true });
  }

  function renderBar(summary) {
    var data = summary.ranking || [];
    if (!data.length) {
      charts.bar.setOption(emptyChartOption(), { notMerge: true });
      return;
    }
    charts.bar.setOption({
      grid: { left: 46, right: 16, top: 30, bottom: 66 },
      tooltip: { trigger: 'axis', valueFormatter: function (value) { return value + ' 分钟'; } },
      xAxis: {
        type: 'category',
        data: data.map(function (item) { return item.task; }),
        axisLabel: { fontSize: 10, rotate: 45 },
        axisLine: { lineStyle: { color: '#dcdfe6' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value', name: '总时长(分钟)', nameTextStyle: { fontSize: 10 },
        axisLabel: { fontSize: 10 }, splitLine: { lineStyle: { color: '#f0f2f8' } },
      },
      series: [{
        name: '总时长(分钟)', type: 'bar',
        data: data.map(function (item) { return item.total_minutes; }),
        itemStyle: { color: '#7b6ce0', borderRadius: [3, 3, 0, 0] },
        barMaxWidth: 22,
      }],
    }, { notMerge: true });
  }

  function renderTasks(summary) {
    var current = el.taskSelect.value;
    var options = ['<option value="">全部任务</option>'];
    (summary.tasks || []).forEach(function (name) {
      options.push('<option value="' + escapeHtml(name) + '">' + escapeHtml(name) + '</option>');
    });
    el.taskSelect.innerHTML = options.join('');
    if (current && (summary.tasks || []).indexOf(current) >= 0) {
      el.taskSelect.value = current;
    }
  }

  function renderPageNumbers(totalPages) {
    var current = state.page;
    var parts = [];
    function btn(page, text, cls) {
      return '<button class="page-num ' + (cls || '') + '" data-page="' + page + '">' + text + '</button>';
    }
    if (totalPages <= 7) {
      for (var i = 1; i <= totalPages; i++) {
        parts.push(btn(i, i, i === current ? 'active' : ''));
      }
    } else {
      parts.push(btn(1, 1, current === 1 ? 'active' : ''));
      if (current > 3) { parts.push(btn(0, '…', 'ellipsis')); }
      var from = Math.max(2, current - 1);
      var to = Math.min(totalPages - 1, current + 1);
      for (var j = from; j <= to; j++) {
        parts.push(btn(j, j, j === current ? 'active' : ''));
      }
      if (current < totalPages - 2) { parts.push(btn(0, '…', 'ellipsis')); }
      parts.push(btn(totalPages, totalPages, current === totalPages ? 'active' : ''));
    }
    el.pageNumbers.innerHTML = parts.join('');
    Array.prototype.forEach.call(el.pageNumbers.querySelectorAll('.page-num:not(.ellipsis)'), function (node) {
      node.addEventListener('click', function () {
        state.page = parseInt(node.getAttribute('data-page'), 10);
        renderRecords();
      });
    });
  }

  function renderRecords() {
    var records = state.records;
    var totalPages = Math.max(1, Math.ceil(records.length / state.pageSize));
    if (state.page > totalPages) { state.page = totalPages; }
    var start = (state.page - 1) * state.pageSize;
    var rows = records.slice(start, start + state.pageSize);

    el.pagerTotal.textContent = records.length;
    el.pagePrev.disabled = state.page <= 1;
    el.pageNext.disabled = state.page >= totalPages;
    if (document.activeElement !== el.gotoInput) { el.gotoInput.value = state.page; }
    el.gotoInput.max = totalPages;
    renderPageNumbers(totalPages);

    if (!rows.length) {
      el.recordBody.innerHTML = '<tr><td class="empty-row" colspan="8">暂无数据</td></tr>';
      return;
    }
    var badgeMap = { success: ['badge-success', '成功'], failed: ['badge-failed', '失败'], running: ['badge-running', '进行中'] };
    var html = rows.map(function (row) {
      var badge = badgeMap[row.status] || badgeMap.running;
      var endTime = row.status === 'running' ? '—' : (row.end_time || '—');
      return '<tr>' +
        '<td>' + escapeHtml(row.task) + '</td>' +
        '<td>' + escapeHtml(row.start_time) + '</td>' +
        '<td>' + escapeHtml(endTime) + '</td>' +
        '<td>' + fmtMinutes(row.duration_seconds) + '</td>' +
        '<td>' + fmtSeconds(row.avg_battle_seconds) + '</td>' +
        '<td>' + row.battle_count + '</td>' +
        '<td><span class="badge ' + badge[0] + '">' + badge[1] + '</span></td>' +
        '<td class="error-col" title="' + escapeHtml(row.error_type) + '">' +
          (row.error_type ? escapeHtml(row.error_type) : '—') + '</td>' +
        '</tr>';
    }).join('');
    el.recordBody.innerHTML = html;
  }

  function loadSummary() {
    var script = el.scriptSelect.value;
    if (!script) { return; }
    var params = new URLSearchParams({
      script: script,
      start: toQueryValue(el.startInput.value),
      end: toQueryValue(el.endInput.value),
      task: el.taskSelect.value || '',
    });
    return fetch('/task_statistics/api/summary?' + params.toString())
      .then(function (res) { return res.json(); })
      .then(function (summary) {
        renderStatCards(summary);
        renderTrend(summary);
        renderPie(summary);
        renderBar(summary);
        renderTasks(summary);
        state.records = summary.records || [];
        state.page = 1;
        renderRecords();
      })
      .catch(function () {
        el.recordBody.innerHTML = '<tr><td class="empty-row" colspan="8">数据加载失败，请重试</td></tr>';
      });
  }

  el.refreshBtn.addEventListener('click', loadSummary);
  el.scriptSelect.addEventListener('change', loadSummary);
  el.taskSelect.addEventListener('change', loadSummary);
  el.pageSize.addEventListener('change', function () {
    state.pageSize = parseInt(el.pageSize.value, 10);
    state.page = 1;
    renderRecords();
  });
  el.pagePrev.addEventListener('click', function () {
    if (state.page > 1) { state.page--; renderRecords(); }
  });
  el.pageNext.addEventListener('click', function () {
    var totalPages = Math.max(1, Math.ceil(state.records.length / state.pageSize));
    if (state.page < totalPages) { state.page++; renderRecords(); }
  });
  el.gotoInput.addEventListener('change', function () {
    var totalPages = Math.max(1, Math.ceil(state.records.length / state.pageSize));
    var target = parseInt(el.gotoInput.value, 10);
    if (isNaN(target)) { return; }
    state.page = Math.min(Math.max(1, target), totalPages);
    renderRecords();
  });

  initDateRange();
  loadScripts().then(loadSummary);
})();
