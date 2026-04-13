const fs = require('fs');
const path = require('path');

function loadPlaywright(repoRoot) {
  const candidates = [
    path.resolve(repoRoot, 'output', 'playwright', 'm11', 'node', 'node_modules', 'playwright'),
    path.resolve(repoRoot, 'output', 'playwright', 'm7', 'node', 'node_modules', 'playwright'),
    'playwright',
  ];

  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (error) {
      // try next
    }
  }
  throw new Error('Unable to load Playwright from known locations.');
}

const repoRoot = path.resolve(__dirname, '..');
const artifactDir = process.env.PLAYWRIGHT_ARTIFACT_DIR
  ? path.resolve(process.env.PLAYWRIGHT_ARTIFACT_DIR)
  : path.resolve(repoRoot, 'output', 'playwright', 'm13');
const screenshotPath = path.resolve(artifactDir, 'm13-e2e.png');
const resultPath = path.resolve(artifactDir, 'browser-result.json');
const APP_BASE_URL = process.env.APP_BASE_URL || 'http://127.0.0.1:5175';
const API_BASE_URL = process.env.API_BASE_URL || 'http://127.0.0.1:8013';
const uploadDir = path.resolve(artifactDir, 'uploads');
const { chromium } = loadPlaywright(repoRoot);

function resolveSampleSource() {
  const candidates = [
    process.env.PLAYWRIGHT_SAMPLE_SOURCE
      ? path.resolve(process.env.PLAYWRIGHT_SAMPLE_SOURCE)
      : null,
    path.resolve(repoRoot, 'output', 'playwright', 'm8', 'sample.png'),
    path.resolve(repoRoot, 'output', 'tmp-coco8', '000000000009.jpg'),
    path.resolve(repoRoot, 'output', 'tmp-coco8', '000000000025.jpg'),
  ].filter(Boolean);

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  throw new Error(`Sample image missing. Checked: ${candidates.join(', ')}`);
}

const sampleSource = resolveSampleSource();

async function api(method, pathname, body) {
  const resp = await fetch(`${API_BASE_URL}${pathname}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  const payload = text ? JSON.parse(text) : null;
  if (!resp.ok) {
    throw new Error(`${method} ${pathname} failed: ${resp.status} ${JSON.stringify(payload)}`);
  }
  return payload;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
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

function ensureUploadFixtures() {
  if (!fs.existsSync(sampleSource)) {
    throw new Error(`Sample image missing: ${sampleSource}`);
  }
  fs.mkdirSync(uploadDir, { recursive: true });
  const files = [];
  for (let i = 1; i <= 12; i += 1) {
    const target = path.join(uploadDir, `fixture-${String(i).padStart(2, '0')}.png`);
    fs.copyFileSync(sampleSource, target);
    files.push(target);
  }
  return files;
}

(async () => {
  fs.mkdirSync(artifactDir, { recursive: true });
  const uploadFiles = ensureUploadFixtures();
  const createProject = await api('POST', '/api/projects', {
    name: `m13-e2e-${Date.now()}`,
    task_type: 'detection',
  });
  const projectId = Number(createProject.data.id);

  const browser = await launchBrowser();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1600 } });
  const page = await context.newPage();
  const pageErrors = [];
  const consoleMessages = [];
  const taskWebSockets = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  page.on('console', (message) => consoleMessages.push(`${message.type()}: ${message.text()}`));
  page.on('websocket', (websocket) => {
    const url = websocket.url();
    if (url.includes('/ws/tasks/')) {
      taskWebSockets.push(websocket);
    }
  });

  try {
    await page.goto(`${APP_BASE_URL}/projects/${projectId}`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('labels-input').waitFor({ state: 'visible', timeout: 15000 });

    await page.getByTestId('labels-input').fill('crack, scratch');
    await Promise.all([
      page.waitForResponse((resp) => resp.url().endsWith(`/api/projects/${projectId}/settings`) && resp.request().method() === 'PATCH'),
      page.getByTestId('labels-save-btn').click(),
    ]);

    await page.getByTestId('image-upload-input').setInputFiles(uploadFiles);
    await Promise.all([
      page.waitForResponse((resp) => resp.url().endsWith(`/api/projects/${projectId}/images/upload`) && resp.request().method() === 'POST'),
      page.getByRole('button', { name: 'Upload Images' }).click(),
    ]);

    const imageCount = await waitFor(async () => {
      const count = await page.locator('[data-testid^="image-card-"]').count();
      if (count < uploadFiles.length) {
        throw new Error(`image count is ${count}`);
      }
      return count;
    }, 15000, 'uploaded image list');

    await page.getByTestId('project-sam-checkpoint-input').fill('sam2.1');
    await page.getByTestId('quality-threshold-review-input').fill('0.71');
    await Promise.all([
      page.waitForResponse((resp) => resp.url().endsWith('/api/system/settings') && resp.request().method() === 'PATCH'),
      page.getByTestId('project-settings-save-btn').click(),
    ]);

    const settingsMessage = await waitFor(async () => {
      const text = (await page.getByTestId('settings-save-status').textContent() || '').trim();
      if (!text.includes('Saved settings.')) {
        throw new Error(`settings status is ${text}`);
      }
      return text;
    }, 10000, 'settings save status');

    const systemSettings = await api('GET', '/api/system/settings');
    if (Number(systemSettings.data.quality.threshold_review) !== 0.71) {
      throw new Error(`system quality threshold is ${systemSettings.data.quality.threshold_review}`);
    }
    if (String(systemSettings.data.sam.checkpoint) !== 'sam2.1') {
      throw new Error(`system sam checkpoint is ${systemSettings.data.sam.checkpoint}`);
    }

    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByTestId('project-sam-checkpoint-input').waitFor({ state: 'visible', timeout: 15000 });
    const samCheckpoint = await waitFor(async () => {
      const value = await page.getByTestId('project-sam-checkpoint-input').inputValue();
      if (value !== 'sam2.1') {
        throw new Error(`sam checkpoint is ${value}`);
      }
      return value;
    }, 10000, 'sam checkpoint after reload');
    const reviewThreshold = await waitFor(async () => {
      const value = await page.getByTestId('quality-threshold-review-input').inputValue();
      if (value !== '0.71') {
        throw new Error(`review threshold is ${value}`);
      }
      return value;
    }, 10000, 'review threshold after reload');
    if (samCheckpoint !== 'sam2.1') {
      throw new Error(`sam checkpoint after reload is ${samCheckpoint}`);
    }
    if (reviewThreshold !== '0.71') {
      throw new Error(`review threshold after reload is ${reviewThreshold}`);
    }

    await Promise.all([
      page.waitForResponse((resp) => resp.url().endsWith(`/api/projects/${projectId}/annotate`) && resp.request().method() === 'POST'),
      page.getByTestId('batch-annotate-btn').click(),
    ]);

    const websocket = await waitFor(async () => {
      const latest = taskWebSockets.at(-1) ?? null;
      if (!latest) {
        throw new Error('no task websocket opened yet');
      }
      return latest;
    }, 10000, 'task websocket');

    const transport = await waitFor(async () => {
      const text = (await page.getByTestId('batch-task-transport').textContent() || '').trim();
      if (!text.includes('websocket')) {
        throw new Error(`transport is ${text}`);
      }
      return text;
    }, 10000, 'task transport');

    const taskMeta = await waitFor(async () => {
      const text = (await page.getByTestId('batch-task-meta').textContent() || '').trim();
      if (!text.includes('SUCCESS')) {
        throw new Error(`task meta is ${text}`);
      }
      return text;
    }, 20000, 'task completion');

    if (pageErrors.length > 0) {
      throw new Error(`page errors: ${pageErrors.join(' | ')}`);
    }

    await page.screenshot({ path: screenshotPath, fullPage: true });
    const result = {
      ok: true,
      project_id: projectId,
      uploaded_images: imageCount,
      settings_message: settingsMessage,
      task_transport: transport,
      task_meta: taskMeta,
      websocket_url: websocket.url(),
      screenshot: screenshotPath,
    };
    fs.writeFileSync(resultPath, JSON.stringify(result, null, 2), 'utf8');
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    const bodyText = await page.locator('body').innerText().catch(() => '');
    console.error('console messages:\n' + consoleMessages.join('\n'));
    console.error('page errors:\n' + pageErrors.join('\n'));
    console.error('body excerpt:\n' + String(bodyText).slice(0, 2000));
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exitCode = 1;
});
