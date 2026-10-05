/**
 * OAS 日志解析内核（零依赖，浏览器 / Node 通用）。
 *
 * 解析对象: log/YYYY-MM-DD_<脚本名>.txt（ALAS 系 Rich 日志）。
 * 行格式:
 *   2026-10-06 01:10:42.033 | script.py:0623 | INFO | [脚本] 启动调度循环: xxx
 *   + Rich 自动换行的续行（不以时间戳开头）
 *   + hr 分隔线（无时间戳）: ═══ / ─── 标题 ─── / <<< 标题 >>>
 *
 * 关键锚点（与 module/server/task_statistics_router.py 保持一致）:
 *   任务开始: [脚本] 调度: 开始任务 `TaskName`
 *   任务结束: [脚本] 调度: 任务 `TaskName` 执行结束
 *   失败判定: 段内出现 ERROR/CRITICAL、[错误] 块、保存错误现场、RequestHumanTakeover
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------- 正则 ----
  var LINE_RE = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}\.\d{3})\s*\|\s*(\S+)\s*\|\s*([A-Z]+)\s*\|\s?([^\n]*)$/;
  var HR_EQ_EMPTY = /^═{8,}\s*$/;
  var HR_EQ_TITLE = /^═{8,}\s*(.*?)\s*═{8,}\s*$/;
  var HR_DASH_EMPTY = /^─{8,}\s*$/;
  var HR_DASH_TITLE = /^─{8,}\s*(.*?)\s*─{8,}\s*$/;
  var HR3_RE = /^<<<\s*(.+?)\s*>>>$/;
  var TASK_START_RE = /^(?:\[脚本\]\s*)?调度[:：]\s*开始任务\s*`([^`]+)`/;
  var TASK_END_RE = /^(?:\[脚本\]\s*)?调度[:：]\s*任务\s*`([^`]+)`\s*执行结束/;
  var TASK_START_LEGACY_RE = /^Start task\s*`([^`]+)`/;
  var TASK_END_LEGACY_RE = /^(?<name>[A-Za-z0-9_]+)\s+task ended\b/;
  var ERR_TITLE_RE = /^\[错误\]\s*(.*)$/;
  var CLICK_RE = /^\[[\d.]+m?s\]\s*(?:点击|按下|弹起)\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)(?:\s*@\s*(\S+))?/;
  var SWIPE_RE = /^\[[\d.]+m?s\]\s*(?:滑动|拖动)\b/;
  var METRIC_RE = /^\[[^\]]+?\s\d+\.\d+s\]\s*\[/;
  var UI_RE = /^\[UI\]\s|已到达页面|已到达界面/;
  var NOTIFY_RE = /^\[通知\]/;
  // 需要按换行拼接的续行（多行消息 / 堆栈 / error_context 四行块）
  var NL_CONT_RE = /^(?:[│├└]|Traceback|  File |\s{2,}\S|原因：|影响：|建议：|异常：|\[错误\]|[A-Za-z_.]+(?:Error|Exception)\b|RequestHumanTakeover)/;
  var FAIL_SAVE_RE = /正在保存错误现场/;
  var TAKEOVER_RE = /RequestHumanTakeover/;

  // ---------------------------------------------------------------- 工具 ----
  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  function parseTs(dateText, timeText) {
    var m = /^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$/.exec(timeText);
    if (!m) return null;
    var d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateText);
    if (!d) return null;
    return new Date(+d[1], +d[2] - 1, +d[3], +m[1], +m[2], +m[3], +m[4]).getTime();
  }

  function classify(msg, level) {
    if (level === 'ERROR' || level === 'CRITICAL' || ERR_TITLE_RE.test(msg)) return 'error';
    if (level === 'WARNING') return 'warn';
    if (CLICK_RE.test(msg)) return 'click';
    if (SWIPE_RE.test(msg)) return 'swipe';
    if (METRIC_RE.test(msg)) return 'metric';
    if (NOTIFY_RE.test(msg)) return 'notify';
    if (UI_RE.test(msg)) return 'ui';
    return 'info';
  }

  function extractClick(msg) {
    var m = CLICK_RE.exec(msg);
    if (!m) return null;
    return { x: +m[1], y: +m[2], name: m[3] || '' };
  }

  function hrRecord(rec, level, title) {
    rec.hr = { level: level, title: title };
    rec.kind = 'hr';
  }

  // ------------------------------------------------------------ 主解析 ----
  /**
   * @param {string} text 日志全文
   * @param {string} [fileName] 文件名（仅用于展示）
   * @returns {object} 解析结果，结构见文件头注释
   */
  function parseLogText(text, fileName) {
    var t0 = (global.performance && performance.now && performance.now()) || Date.now();
    var lines = text.split(/\r?\n/);
    var records = [];
    var sections = [];

    var i, line;
    for (i = 0; i < lines.length; i++) {
      line = lines[i];

      // ---- hr 分隔线（无时间戳） ----
      if (HR_EQ_EMPTY.test(line)) {
        // hr0 三连: ═ / ── 标题 ── / ═
        if (i + 2 < lines.length && HR_DASH_TITLE.test(lines[i + 1]) && HR_EQ_EMPTY.test(lines[i + 2])) {
          var t0title = lines[i + 1].replace(HR_DASH_TITLE, '$1');
          var rec0 = newRecord(i + 1, [lines[i], lines[i + 1], lines[i + 2]], null, null, null, '', t0title);
          hrRecord(rec0, 0, t0title);
          records.push(rec0);
          i += 2;
          continue;
        }
        var recE = newRecord(i + 1, [line], null, null, null, '', '');
        hrRecord(recE, 0, '');
        records.push(recE);
        continue;
      }
      var mEq = HR_EQ_TITLE.exec(line);
      if (mEq) {
        var rec1 = newRecord(i + 1, [line], null, null, null, '', mEq[1]);
        hrRecord(rec1, 1, mEq[1]);
        records.push(rec1);
        continue;
      }
      var mDash = HR_DASH_TITLE.exec(line) || (HR_DASH_EMPTY.test(line) ? ['', ''] : null);
      if (mDash) {
        var rec2 = newRecord(i + 1, [line], null, null, null, '', mDash[1]);
        hrRecord(rec2, 2, mDash[1]);
        records.push(rec2);
        continue;
      }

      // ---- 普通记录行 ----
      var m = LINE_RE.exec(line);
      if (m) {
        var rec = newRecord(i + 1, [line], m[1], m[2], m[3], m[4], m[5]);
        finishRecord(rec);
        records.push(rec);
        continue;
      }

      // ---- 续行 ----
      if (!line.trim()) {
        // 空行: 紧跟上一条记录时属于同一条多行消息（如堆栈空行）；文件头尾的散空行忽略
        if (records.length) {
          var last = records[records.length - 1];
          if (i - (last.line - 1) === last.rawLines.length) {
            last.msg += '\n';
            last.rawLines.push(line);
          }
        }
        continue;
      }
      if (records.length) {
        var prev = records[records.length - 1];
        if (NL_CONT_RE.test(line)) {
          prev.msg += '\n' + line.replace(/\s+$/, '');
        } else {
          prev.msg = prev.msg.replace(/\s+$/, '') + ' ' + line.replace(/^\s+/, '').replace(/\s+$/, '');
        }
        prev.rawLines.push(line);
      }
      // 无可归属续行（文件头部的散行）直接丢弃
    }

    // hr3: <<< 标题 >>>（普通记录行里的伪 hr）
    for (i = 0; i < records.length; i++) {
      var r = records[i];
      var m3 = r.kind === 'info' && r.level === 'INFO' ? HR3_RE.exec(r.msg) : null;
      if (m3) {
        hrRecord(r, 3, m3[1]);
        // hr() level=3 下一行通常紧跟 [标题] attr 行，无冗余问题
      }
      // hr1/hr2 规则线后紧跟的同名 INFO 行属于 hr 的回显，折叠掉
      if (r.kind === 'info' && r.level === 'INFO' && i > 0) {
        var p = records[i - 1];
        if (p.hr && (p.hr.level === 1 || p.hr.level === 2) && p.hr.title && r.msg === p.hr.title) {
          r.echo = true;
        }
      }
    }

    // ---- 汇总 sections（hr 标记扁平表） ----
    for (i = 0; i < records.length; i++) {
      if (records[i].kind === 'hr') sections.push({ rec: i, title: records[i].hr.title, level: records[i].hr.level });
    }

    // ---- 任务段 ----
    var tasks = buildTasks(records);
    // section -> task 归属
    var taskIndex = 0;
    var secTaskOf = [];
    for (i = 0; i < sections.length; i++) {
      while (taskIndex < tasks.length && tasks[taskIndex].endRec !== null && tasks[taskIndex].endRec < sections[i].rec) taskIndex++;
      var inside = taskIndex < tasks.length && sections[i].rec >= tasks[taskIndex].startRec &&
        (tasks[taskIndex].endRec === null || sections[i].rec <= tasks[taskIndex].endRec);
      secTaskOf.push(inside ? taskIndex : -1);
    }
    for (i = 0; i < sections.length; i++) sections[i].taskIndex = secTaskOf[i];

    var stats = buildStats(records, tasks);

    return {
      fileName: fileName || '',
      lineCount: lines.length,
      parseMs: Math.round((((global.performance && performance.now && performance.now()) || Date.now()) - t0) * 10) / 10,
      records: records,
      sections: sections,
      tasks: tasks,
      stats: stats
    };
  }

  function newRecord(lineNo, rawLines, dateText, timeText, src, level, msg) {
    return {
      line: lineNo,
      rawLines: rawLines,
      dateText: dateText,
      timeText: timeText,
      tsMs: dateText ? parseTs(dateText, timeText) : null,
      tsText: timeText || '',
      src: src || '',
      level: level || '',
      msg: msg.replace(/\s+$/, ''),
      hr: null,
      kind: 'info',
      click: null,
      echo: false
    };
  }

  function finishRecord(rec) {
    rec.kind = classify(rec.msg, rec.level);
    rec.click = rec.kind === 'click' ? extractClick(rec.msg) : null;
  }

  // ------------------------------------------------------------ 任务段 ----
  function buildTasks(records) {
    var tasks = [];
    var open = null;
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      var ms = TASK_START_RE.exec(r.msg) || TASK_START_LEGACY_RE.exec(r.msg);
      if (ms && r.level === 'INFO') {
        if (open) closeTask(open, i - 1, 'interrupted');
        open = {
          name: ms[1],
          startRec: i,
          endRec: null,
          startMs: r.tsMs,
          endMs: null,
          status: 'running',
          errorTitle: null,
          errorRec: -1,
          failedMarkerRec: -1
        };
        tasks.push(open);
        continue;
      }
      var me = TASK_END_RE.exec(r.msg);
      var legacyEnd = !me ? TASK_END_LEGACY_RE.exec(r.msg) : null;
      if ((me || legacyEnd) && open) {
        var name = me ? me[1] : legacyEnd[1];
        if (name === open.name) {
          closeTask(open, i, 'success');
          open.endMs = r.tsMs;
          open = null;
        }
        continue;
      }
      if (open && open.failedMarkerRec < 0 && isFailureMarker(r)) {
        open.failedMarkerRec = i;
        open.errorTitle = extractErrorTitle(r);
        open.errorRec = i;
      }
    }
    // 文件末尾仍打开的段：记录到 EOF 的为进行中
    if (open) open.endRec = records.length - 1;
    // 有失败标记但正常走到「执行结束」的段按失败处理（对齐 task_statistics 语义）
    for (i = 0; i < tasks.length; i++) {
      if (tasks[i].status === 'success' && tasks[i].failedMarkerRec >= 0) tasks[i].status = 'failed';
    }
    return tasks;
  }

  function closeTask(task, endRec, status) {
    task.endRec = endRec;
    if (status === 'interrupted') {
      // 段内没走到「执行结束」→ 按失败处理（对齐 task_statistics 语义）；
      // 段内已有具体错误标题时保留原标题
      task.status = 'failed';
      if (!task.errorTitle) task.errorTitle = '任务未正常结束（缺少执行结束标记）';
    } else {
      task.status = status;
    }
  }

  function isFailureMarker(rec) {
    return rec.level === 'ERROR' || rec.level === 'CRITICAL' ||
      ERR_TITLE_RE.test(rec.msg) || FAIL_SAVE_RE.test(rec.msg) || TAKEOVER_RE.test(rec.msg);
  }

  function extractErrorTitle(rec) {
    var m = ERR_TITLE_RE.exec(rec.msg);
    if (m && m[1]) return m[1].split('\n')[0].slice(0, 120);
    return rec.msg.split('\n')[0].slice(0, 120);
  }

  // ------------------------------------------------------------ 统计 ----
  function buildStats(records, tasks) {
    var clicks = new Map();
    var srcs = new Map();
    var levels = new Map();
    var kinds = new Map();
    var errors = [];
    var notifyCount = 0;
    for (var i = 0; i < records.length; i++) {
      var r = records[i];
      if (r.echo) continue;
      levels.set(r.level, (levels.get(r.level) || 0) + 1);
      kinds.set(r.kind, (kinds.get(r.kind) || 0) + 1);
      if (r.src) {
        var f = r.src.split(':')[0];
        srcs.set(f, (srcs.get(f) || 0) + 1);
      }
      if (r.kind === 'click' && r.click && r.click.name) {
        var c = clicks.get(r.click.name) || { count: 0, first: r.tsText, last: r.tsText };
        c.count++;
        c.last = r.tsText;
        clicks.set(r.click.name, c);
      }
      if (r.kind === 'error') errors.push(i);
      if (r.kind === 'notify') notifyCount++;
    }
    var success = 0, failed = 0, running = 0;
    var totalDur = 0;
    for (i = 0; i < tasks.length; i++) {
      var t = tasks[i];
      if (t.status === 'success') success++;
      else if (t.status === 'running') running++;
      else failed++;
      if (t.startMs !== null && t.endMs !== null) totalDur += Math.max(0, t.endMs - t.startMs);
    }
    return {
      taskTotal: tasks.length,
      taskSuccess: success,
      taskFailed: failed,
      taskRunning: running,
      taskTotalMs: totalDur,
      errorCount: errors.length,
      notifyCount: notifyCount,
      errors: errors,
      clicks: Array.from(clicks.entries()).map(function (kv) { return { name: kv[0], count: kv[1].count, first: kv[1].first, last: kv[1].last }; })
        .sort(function (a, b) { return b.count - a.count; }),
      srcs: Array.from(srcs.entries()).map(function (kv) { return { name: kv[0], count: kv[1] }; })
        .sort(function (a, b) { return b.count - a.count; }),
      levels: Array.from(levels.entries()).map(function (kv) { return { name: kv[0], count: kv[1] }; })
        .sort(function (a, b) { return b.count - a.count; })
    };
  }

  // -------------------------------------------------------- 展示辅助 ----
  /**
   * 计算每个 section 的记录区间 [startRec, endRec)，供时间线折叠使用。
   */
  function buildSectionRanges(parsed) {
    var secs = parsed.sections;
    var n = parsed.records.length;
    for (var i = 0; i < secs.length; i++) {
      secs[i].endRec = (i + 1 < secs.length ? secs[i + 1].rec : n) - 1;
      secs[i].count = Math.max(0, secs[i].endRec - secs[i].rec);
    }
    return parsed;
  }

  var KIND_LABEL = {
    info: '信息', click: '点击', swipe: '滑动', metric: '识别', ui: '界面',
    error: '错误', warn: '警告', notify: '通知', hr: '节点'
  };

  var API = {
    parseLogText: parseLogText,
    buildSectionRanges: buildSectionRanges,
    KIND_LABEL: KIND_LABEL
  };

  global.OASLogParser = API;
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})(typeof window !== 'undefined' ? window : globalThis);
