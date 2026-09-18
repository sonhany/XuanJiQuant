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
 * 前提: 后端(8880) + 前端(8888) 都在运行
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const FRONTEND = 'http://localhost:8888';
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

  const enterButton = page.getByRole('button', { name: /进入工作台|进入量化终端/ });
  if (await enterButton.count() > 0) {
    await enterButton.click({ timeout: 5000 });
    await page.waitForTimeout(1800);
  }

  // ── 2. 各面板渲染测试 ───────────────────────
  console.log('\n■ 6 大面板渲染');

  const panels = [
    { name: '数据浏览', nav: '市场数据', heading: '数据浏览' },
    { name: '因子引擎', nav: '因子研究', heading: '因子引擎' },
    { name: '策略运行', nav: '策略运行', heading: 'F4 策略与组合验证' },
    { name: '交易执行', nav: '模拟执行', heading: 'F5 确定性模拟执行' },
    { name: '风控监控', nav: '风险监控', heading: '风险与审计' },
    { name: '监控告警', nav: '告警中心', heading: '告警中心' },
  ];

  for (const panel of panels) {
    const navButton = page.getByRole('complementary').getByRole('button', { name: panel.nav, exact: true });
    if (await navButton.count() === 0) {
      log(false, `${panel.name}: 找不到切换入口`);
      continue;
    }
    await navButton.click({ timeout: 3000 });
    await page.waitForTimeout(2500); // 等 API 返回 + 渲染

    // 截图
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, `${panel.name}.png`) });

    const hasHeading = await page.getByText(panel.heading, { exact: true }).count() > 0;
    log(hasHeading, `${panel.name}: ${hasHeading ? '真实页面已渲染' : `缺少标题“${panel.heading}”`}`);
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
  await page.getByRole('complementary').getByRole('button', { name: '策略运行', exact: true }).click({ timeout: 3000 });
  await page.waitForTimeout(1500);
  // 当前策略页默认打开“市场扫描”，先进入策略运行页签再验证回测命令。
  const runTab = page.getByRole('main').getByRole('button', { name: '诊断：策略回测', exact: true });
  if (await runTab.count() > 0) {
    await runTab.click({ timeout: 3000 });
    await page.waitForTimeout(500);
  }
  const runBtn = page.getByRole('button', { name: '运行策略', exact: true });
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
