const fs = require('fs');
const path = require('path');

function loadPlaywright(repoRoot) {
  const candidates = [
    path.resolve(repoRoot, 'output', 'playwright', 'm7', 'node', 'node_modules', 'playwright'),
    path.resolve(repoRoot, 'output', 'playwright', 'm6', 'node', 'node_modules', 'playwright'),
    'playwright',
  ];

  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      // Try the next location.
    }
  }

  throw new Error('Unable to load Playwright from known locations.');
}

const repoRoot = path.resolve(__dirname, '..');
const artifactDir = path.resolve(process.env.PLAYWRIGHT_ARTIFACT_DIR || path.resolve(repoRoot, 'output', 'playwright', 'm14'));
const contextPath = path.resolve(artifactDir, 'context.json');
const ctx = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
const { chromium } = loadPlaywright(repoRoot);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      await sleep(200);
    }
  }
  throw new Error(`${label} timed out${lastError ? `: ${lastError.message}` : ''}`);
}

async function launchBrowser() {
  try {
    return await chromium.launch({ channel: 'msedge', headless: true });
  } catch (error) {
    return await chromium.launch({ headless: true });
  }
}

(async () => {
  const browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', (error) => {
    pageErrors.push(String(error));
  });

  const tracePath = path.resolve(artifactDir, 'trace-m14.zip');
  const screenshotPath = path.resolve(artifactDir, 'm14-e2e.png');
  const resultPath = path.resolve(artifactDir, 'browser-result.json');

  await context.tracing.start({ screenshots: true, snapshots: true });

  try {
    await page.goto(ctx.project_url, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('finetune-start-btn').waitFor({ state: 'visible', timeout: 15000 });

    await waitFor(async () => {
      const text = (await page.getByTestId('active-model-tag').textContent() || '').trim();
      if (text !== 'base') {
        throw new Error(`active model is ${text}`);
      }
      return text;
    }, 10000, 'initial active model');

    await page.getByTestId('finetune-start-btn').click();

    const finalStatusText = await waitFor(async () => {
      const text = (await page.getByTestId('finetune-status').textContent() || '').trim();
      if (!text.includes('done')) {
        throw new Error(`status is ${text}`);
      }
      return text;
    }, 30000, 'finetune completion');

    const jobMatch = finalStatusText.match(/job=(\d+)/);
    if (!jobMatch) {
      throw new Error(`unable to parse job id from status: ${finalStatusText}`);
    }
    const jobId = Number(jobMatch[1]);

    const logText = await waitFor(async () => {
      const text = await page.getByTestId('finetune-log').textContent();
      const normalized = (text || '').trim();
      if (!normalized.includes('Launching LLaMA-Factory subprocess')) {
        throw new Error('finetune log is missing subprocess launch output');
      }
      if (!normalized.includes('train completed')) {
        throw new Error('finetune log is missing subprocess completion output');
      }
      return normalized;
    }, 15000, 'finetune log output');

    const runnerState = await waitFor(async () => {
      const text = (await page.textContent('body') || '').trim();
      if (!text.includes('runner=llamafactory')) {
        throw new Error('runner summary has not switched to llamafactory');
      }
      return text;
    }, 10000, 'runner summary');

    await page.getByTestId('finetune-activate-btn').click();

    const activeTag = await waitFor(async () => {
      const text = (await page.getByTestId('active-model-tag').textContent() || '').trim();
      if (text !== `lora:${jobId}`) {
        throw new Error(`active model is ${text}`);
      }
      return text;
    }, 10000, 'activated model tag');

    if (pageErrors.length > 0) {
      throw new Error(`page errors: ${pageErrors.join(' | ')}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });

    const result = {
      ok: true,
      project_id: ctx.project_id,
      image_id: ctx.image_id,
      job_id: jobId,
      active_model_tag: activeTag,
      runner_summary_seen: runnerState.includes('runner=llamafactory'),
      screenshot: screenshotPath,
      trace: tracePath,
      log_excerpt: logText.split('\n').slice(0, 10),
    };
    fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await context.tracing.stop({ path: tracePath });
    await browser.close();
  }
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
