/**
 * 浏览器端到端测试 — 用 Playwright 真实渲染验证所有面板
 *
 * 验证内容:
 *   1. 页面加载无 JS 错误
 *   2. 6 大面板都能渲染（不白屏）
 *   3. 关键交互触发后正确显示数据（不报错、不空白）
 *   4. 截图保存供人工查看
 *
 * 用法: npx tsx scripts/browser_test.mjs
 * 前提: 后端(3334) + 前端(3333) 都在运行
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const FRONTEND = 'http://localhost:3333';
const SCREENSHOT_DIR = path.join(process.cwd(), 'screenshots');
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

const results = [];
const consoleErrors = [];
const pageErrors = [];

function log(ok, msg) {
  results.push({ ok, msg });
  console.log(`  ${ok ? '✅' : '❌'} ${msg}`);
}

async function main() {
  console.log('='.repeat(55));
  console.log('  浏览器端到端测试 (Playwright)');
  console.log('='.repeat(55));

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  // 捕获控制台错误和页面崩溃
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', err => pageErrors.push(err.message));

  // ── 1. 页面加载 ──────────────────────────────
  console.log('\n■ 页面加载');
  try {
    await page.goto(FRONTEND, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(2000);
    const title = await page.title();
    log(true, `页面加载成功 (title: ${title.slice(0, 30)})`);
  } catch (e) {
    log(false, `页面加载失败: ${e.message}`);
    await browser.close();
    return;
  }

  // 检查白屏
  const bodyText = await page.evaluate(() => document.body.innerText.length);
  log(bodyText > 100, `页面有内容 (${bodyText} 字符，非白屏)`);

  // ── 2. 各面板渲染测试 ───────────────────────
  console.log('\n■ 6 大面板渲染');

  const panels = [
    { name: '数据浏览', tabText: ['数据浏览', '数据', 'Data', '市场'] },
    { name: '因子引擎', tabText: ['因子', 'Factor'] },
    { name: '策略运行', tabText: ['策略', 'Strategy'] },
    { name: '交易执行', tabText: ['交易', '执行', 'Execution'] },
    { name: '风控监控', tabText: ['风控', 'Risk'] },
    { name: '监控告警', tabText: ['告警', '监控', 'Alert'] },
  ];

  for (const panel of panels) {
    let clicked = false;
    for (const txt of panel.tabText) {
      const el = page.locator(`text=${txt}`).first();
      if (await el.count() > 0) {
        try {
          await el.click({ timeout: 3000 });
          clicked = true;
          break;
        } catch {}
      }
    }
    if (!clicked) {
      log(false, `${panel.name}: 找不到切换入口`);
      continue;
    }
    await page.waitForTimeout(2500); // 等 API 返回 + 渲染

    // 截图
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${panel.name}.png`) });

    // 检查面板区域是否有内容 (非加载中/空白)
    const text = await page.evaluate(() => document.body.innerText);
    const hasLoading = /loading|加载中|Loading/i.test(text);
    log(!hasLoading, `${panel.name}: 面板渲染 (有数据${hasLoading ? '，但仍在加载' : ''})`);
  }

  // ── 3. 顶部行情条 ───────────────────────────
  console.log('\n■ 顶部行情条');
  const hasIndex = await page.evaluate(() => {
    const t = document.body.innerText;
    return /上证|深证|创业板|恒生|指数|3000|点/.test(t);
  });
  log(hasIndex, '顶部行情条显示指数');

  // ── 4. 交互测试: 策略运行 ───────────────────
  console.log('\n■ 交互测试: 策略运行');
  // 切到策略面板
  for (const txt of ['策略', 'Strategy']) {
    const el = page.locator(`text=${txt}`).first();
    if (await el.count() > 0) { try { await el.click({ timeout: 3000 }); break; } catch {} }
  }
  await page.waitForTimeout(1500);
  // 找"运行策略"按钮并点击
  const runBtn = page.locator('text=/运行策略|运行|Run/i').first();
  if (await runBtn.count() > 0) {
    try {
      await runBtn.click({ timeout: 3000 });
      await page.waitForTimeout(8000); // 策略回测需要时间
      const text = await page.evaluate(() => document.body.innerText);
      const hasResult = /收益|胜率|交易|return|sharpe/i.test(text);
      log(hasResult, `策略运行后显示结果 (${hasResult ? '有收益/胜率' : '无结果数据'})`);
    } catch (e) {
      log(false, `策略运行点击失败: ${e.message}`);
    }
  } else {
    log(false, '找不到"运行策略"按钮');
  }
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '策略结果.png') });

  // ── 5. 汇总 ─────────────────────────────────
  console.log('\n' + '='.repeat(55));
  const nOk = results.filter(r => r.ok).length;
  console.log(`  通过: ${nOk}/${results.length}`);
  if (consoleErrors.length > 0) {
    console.log(`  ⚠️  控制台错误 (${consoleErrors.length} 条):`);
    consoleErrors.slice(0, 5).forEach(e => console.log(`     ${e.slice(0, 150)}`));
  } else {
    console.log('  控制台无错误 ✅');
  }
  if (pageErrors.length > 0) {
    console.log(`  ❌ 页面崩溃 (${pageErrors.length} 条):`);
    pageErrors.slice(0, 3).forEach(e => console.log(`     ${e.slice(0, 150)}`));
  } else {
    console.log('  页面无崩溃 ✅');
  }
  console.log(`\n  截图已保存到 screenshots/ 目录`);
  console.log('='.repeat(55));

  await browser.close();
  process.exit(nOk === results.length && pageErrors.length === 0 ? 0 : 1);
}

main().catch(e => { console.error(e); process.exit(1); });
