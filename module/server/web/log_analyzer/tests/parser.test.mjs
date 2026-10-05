/**
 * 解析内核自测：node tests/parser.test.mjs [log1.txt log2.txt ...]
 * 不传参数时默认解析仓库 log/ 下最新的两份实例日志。
 * 仅依赖 Node 内置模块，用于离线验证解析结果与锚点统计。
 */
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { parseLogText, buildSectionRanges } = require('../static/parser.js');

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..', '..', '..');

function defaultLogs() {
  const logDir = path.join(repoRoot, 'log');
  const files = fs.readdirSync(logDir)
    .filter((f) => /^\d{4}-\d{2}-\d{2}_.+\.txt$/.test(f))
    .map((f) => ({ f, m: fs.statSync(path.join(logDir, f)).mtimeMs }))
    .sort((a, b) => b.m - a.m)
    .filter((x, i, arr) => arr.findIndex((y) => y.f.split('_').slice(1).join('_')) === i)
    .slice(0, 2);
  return files.map((x) => path.join(logDir, x.f));
}

const logFiles = process.argv.slice(2).length ? process.argv.slice(2) : defaultLogs();
let failures = 0;

function check(cond, label) {
  if (cond) {
    console.log(`  ✅ ${label}`);
  } else {
    failures++;
    console.error(`  ❌ ${label}`);
  }
}

for (const file of logFiles) {
  const base = path.basename(file);
  console.log(`\n━━━ ${base} ━━━`);
  const text = fs.readFileSync(file, 'utf8');
  const parsed = buildSectionRanges(parseLogText(text, base));
  const { records, sections, tasks, stats } = parsed;

  console.log(`  行数 ${parsed.lineCount}, 记录 ${records.length}, hr 小节 ${sections.length}, 解析耗时 ${parsed.parseMs}ms`);

  // 原文行数守恒：所有记录的 rawLines 合计应等于非空行里被归档的行数（宽松校验: 记录覆盖的最后行号）
  const covered = records.length ? records[records.length - 1].line + records[records.length - 1].rawLines.length - 1 : 0;
  check(covered >= parsed.lineCount - 2, `记录覆盖到文件末尾 (covered=${covered}, total=${parsed.lineCount})`);

  // 时间戳行守恒：日志中匹配时间戳格式的行数 == 记录中带时间戳的记录数 + 被并入 msg 的时间戳文本行
  const rawTsLines = (text.match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \|/gm) || []).length;
  const recTs = records.filter((r) => r.tsMs !== null).length;
  const embeddedTs = records.reduce((n, r) => n + (r.rawLines.filter((l) => /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \|/.test(l)).length - (r.tsMs !== null ? 1 : 0)), 0);
  check(rawTsLines === recTs + embeddedTs, `时间戳行守恒 (原文 ${rawTsLines} = 记录 ${recTs} + 嵌入 ${embeddedTs})`);

  // 任务段与原文锚点一致
  const rawStarts = (text.match(/调度[:：]\s*开始任务\s*`/g) || []).length;
  check(tasks.length === rawStarts, `任务段数量一致 (解析 ${tasks.length} = 原文 ${rawStarts})`);

  // 每个"成功/失败"任务开始处紧跟的 hr0 标题应为任务名大写
  let hr0Match = 0, hr0Total = 0;
  for (const t of tasks) {
    const nxt = records[t.startRec + 1];
    if (nxt && nxt.kind === 'hr' && nxt.hr.level === 0) {
      hr0Total++;
      if (nxt.hr.title === t.name.toUpperCase()) hr0Match++;
    }
  }
  check(hr0Total === 0 || hr0Match === hr0Total, `任务开始后的 hr0 标题匹配 (${hr0Match}/${hr0Total})`);

  // 状态合法性 + 时长非负
  check(tasks.every((t) => ['success', 'failed', 'running'].includes(t.status)), '任务状态取值合法');
  check(tasks.every((t) => t.startMs === null || t.endMs === null || t.endMs >= t.startMs), '任务时长非负');

  console.log('  任务列表:');
  for (const t of tasks) {
    const dur = t.startMs !== null && t.endMs !== null ? ((t.endMs - t.startMs) / 1000).toFixed(1) + 's' : '-';
    const err = t.errorTitle ? `  ← ${t.errorTitle}` : '';
    console.log(`    [${t.status.padEnd(7)}] #${t.startRec} ${t.name}  耗时 ${dur}${err}`);
  }
  console.log(`  错误记录 ${stats.errorCount}, 通知 ${stats.notifyCount}, 点击资产种类 ${stats.clicks.length}`);
  console.log(`  点击 Top5: ${stats.clicks.slice(0, 5).map((c) => `${c.name}×${c.count}`).join(', ')}`);
  console.log(`  来源 Top5: ${stats.srcs.slice(0, 5).map((c) => `${c.name}×${c.count}`).join(', ')}`);

  // 续行合并抽查：含换行的记录 msg 展示
  const multiline = records.filter((r) => r.msg.includes('\n'));
  console.log(`  多行消息记录 ${multiline.length} 条${multiline.length ? '，例如:' : ''}`);
  for (const r of multiline.slice(0, 2)) {
    console.log(`    ── #${r.line} ${r.src} ${r.level}\n${r.msg.split('\n').slice(0, 6).map((l) => '       ' + l).join('\n')}`);
  }
}

console.log(failures ? `\n❌ ${failures} 项校验未通过` : '\n✅ 全部校验通过');
process.exit(failures ? 1 : 0);
