// Real browser coverage of the trusted studio against an explicit API double.
// Preview is a harmless authored page. No generated JavaScript runs on this host.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { chromium } from 'playwright';

const studio = process.env.P2P_STUDIO_URL || 'http://127.0.0.1:5173';
const evidence = process.env.P2P_UI_EVIDENCE || '/tmp/prompt2play-studio-evidence';
fs.mkdirSync(evidence, {recursive: true});
const timestamp = n => `2026-10-11T12:00:${String(n).padStart(2, '0')}.000000Z`;
const usage = {input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, total_tokens: 0, calls: 0};
const hash = 'a'.repeat(64);
const checks = ['startup', 'surface', 'input', 'completion', 'restart', 'javascript_errors', 'external_requests', 'evidence', 'independent_acceptance'].flatMap(name => [1280, 390].map(width => ({name: `${name}:${width}`, status: 'passed', message: 'Authored API transport fixture', artifact_sha256: hash, check_kind: 'browser'})));
checks.push({name: 'mobile_layout:390', status: 'passed', message: 'Authored transport fixture', artifact_sha256: hash, check_kind: 'browser'});
const validation = {schema_version: 2, artifact: {html_sha256: hash, html_bytes: 0, files_sha256: {}, spec_sha256: hash}, status: 'passed', checks, errors: [], warnings: [], browser_contract_version: 3, validator_image_sha256: `sha256:${hash}`, suite_sha256: hash};
const versions = [];
let job = null, projects = [], runners = [], jobCount = 0;
let resumeRequests = 0, mutationTime = 27;
let issuedTokens = 0, expiredPreviewRequests = 0, failedDetailReads = 0, failNextDetail = false;
const expiredTokens = new Set();
function version(id, number, eligible, report = validation) {
  return {id, project_id: 'project-1', number, prompt: 'Authored flow request', summary: eligible ? 'Checked transport fixture' : 'Failed diagnostic candidate', created_at: timestamp(number), is_reference: false, validation: report, usage, spec: {}, download_url: `/api/versions/${id}/download/`, source_url: `/api/versions/${id}/source/`, eligible, preview_url: eligible ? `http://127.0.0.1:8001/preview/${id}/?token=authored-scoped-fixture` : null, files: {'game.js': 'Authored diagnostic source; never execute'}, html: '<!-- diagnostic transport data; never execute -->'};
}
function makeJob(input) {
  jobCount++;
  return {id: `job-${jobCount}`, project_id: 'project-1', kind: input.kind, prompt: input.prompt, provider: input.provider, model: input.model, status: 'queued', stage: 'plan', stage_fence: 0, progress: 0, base_version_id: input.base_version_id || null, result_version_id: null, runner_id: null, created_at: timestamp(10 + jobCount), updated_at: timestamp(10 + jobCount), error: '', max_repairs: input.max_repairs, budget_tokens: input.budget_tokens, usage};
}
function currentProject() {
  return {...projects[0], latest_version_id: 'version-1', latest_version_number: versions.length ? 1 : null, active_job: job && ['queued', 'running'].includes(job.status) ? job : null, latest_job: job};
}
const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? {executablePath: process.env.CHROMIUM_EXECUTABLE} : {})});
const context = await browser.newContext({viewport: {width: 1440, height: 1100}});
await context.tracing.start({screenshots: true, snapshots: true});
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.route('http://127.0.0.1:8001/**', route => {
  const token = new URL(route.request().url()).searchParams.get('token');
  const expired = expiredTokens.has(token) || token === 'authored-scoped-fixture';
  if (expired) expiredPreviewRequests++;
  return route.fulfill({status: expired ? 403 : 200, contentType: 'text/html', body: expired ? '<!doctype html><p>Expired preview token.</p>' : '<!doctype html><p>Trusted UI test preview transport.</p>'});
});
await page.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  let value;
  if (path === '/api/auth/session/') value = {authenticated: true, user: {id: 1, username: 'test-creator', is_staff: true}};
  else if (path === '/api/runners/' && request.method() === 'GET') value = runners;
  else if (path === '/api/runners/' && request.method() === 'POST') {
    const body = request.postDataJSON(); assert.equal(body.role, 'validator');
    const runner = {id: 'runner-validator', name: body.name, role: body.role, capabilities: {}, created_at: timestamp(0), last_seen: null, online: false, revoked: false};
    runners.push(runner); value = {runner, token: 'authored-one-time-token'};
  }
  else if (path === '/api/projects/' && request.method() === 'GET') value = projects;
  else if (path === '/api/projects/' && request.method() === 'POST') {
    const body = request.postDataJSON();
    value = {id: 'project-1', title: body.title, prompt: body.prompt, created_at: timestamp(0), updated_at: timestamp(0), latest_version_id: null, latest_version_number: null, active_job: null}; projects.push(value);
  } else if (path === '/api/projects/project-1/jobs/') {job = makeJob(request.postDataJSON()); value = job;}
  else if (path === '/api/projects/project-1/') value = currentProject();
  else if (path === '/api/projects/project-1/versions/') value = versions;
  else if (path.startsWith('/api/versions/')) {
    if (failNextDetail) {
      failNextDetail = false; failedDetailReads++;
      return route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({error: 'Authored scoped URL refresh failure'})});
    }
    value = versions.find(item => item.id === path.split('/')[3]);
    if (value?.eligible) value = {...value, preview_url: `http://127.0.0.1:8001/preview/${value.id}/?token=issued-${++issuedTokens}`};
  }
  else if (path.endsWith('/pause/')) { assert.equal(request.postDataJSON().stage_fence, job.stage_fence); job = {...job, status:'paused', pause_requested:false, stage_fence:job.stage_fence+1, updated_at:timestamp(++mutationTime)}; value = job; }
  else if (path.endsWith('/resume/')) { resumeRequests++; assert.equal(request.postDataJSON().stage_fence, job.stage_fence); job = {...job, status: 'queued', stage: 'plan', can_resume: false, error: '', resume_count: (job.resume_count || 0) + 1, stage_fence: job.stage_fence + 1, updated_at:timestamp(++mutationTime)}; value = job; }
  else if (path.endsWith('/cancel/')) {job = {...job, status: 'cancelled', stage_fence:(job.stage_fence || 0)+1, updated_at:timestamp(++mutationTime)}; value = job;}
  else if (path.endsWith('/events/')) value = [];
  else if (path.startsWith('/api/jobs/')) {
    if (job.id === 'job-1' && job.status === 'queued') {
      versions.push(version('version-1', 1, true)); job = {...job, status: 'completed', stage: 'done', progress: 100, result_version_id: 'version-1', updated_at: timestamp(20)};
    } else if (job.id === 'job-2' && job.status === 'queued' && resumeRequests === 0) {
      versions.push(version('version-2', 2, false, {...validation, status: 'failed', errors: ['Actual browser input gate failed'], checks: [{...checks[0], status: 'failed'}]}));
      job = {...job, status: 'failed', stage: 'validate', can_resume: true, stage_fence: 3, error: 'Candidate failed; last playable revision preserved', updated_at: timestamp(25)};
    }
    value = job;
  }
  if (value === undefined) return route.fulfill({status: 404, contentType: 'application/json', body: JSON.stringify({error: `Unexpected test API route ${path}`})});
  return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(value)});
});
try {
  await page.goto(studio);
  await page.getByLabel('Название проекта').fill('Creator acceptance');
  await page.getByLabel('Описание игры', {exact: true}).fill('Create an authored test-flow game.');
  await page.getByRole('button', {name: 'Создать игру', exact: true}).click();
  await page.locator('iframe').waitFor();
  assert.equal(await page.locator('iframe').getAttribute('srcdoc'), null);
  assert.match(await page.locator('iframe').getAttribute('src'), /:8001\/preview\/version-1/);
  assert.equal(await page.locator('iframe').getAttribute('sandbox'), 'allow-scripts');
  const previewReady = () => page.frameLocator('iframe').getByText('Trusted UI test preview transport.', {exact: true}).waitFor();
  await previewReady();
  const initialUrl = await page.locator('iframe').getAttribute('src');
  expiredTokens.add(new URL(initialUrl).searchParams.get('token'));
  await page.getByRole('button', {name: 'Перезапустить игру', exact: true}).click();
  await previewReady();
  const restartedUrl = await page.locator('iframe').getAttribute('src');
  assert.notEqual(restartedUrl, initialUrl, 'Restart mints a fresh scoped URL even when cached detail is expired');
  expiredTokens.add(new URL(restartedUrl).searchParams.get('token'));
  await page.getByRole('button', {name: 'Остановить предпросмотр и звук', exact: true}).click();
  assert.equal(await page.locator('iframe').count(), 0);
  await page.getByRole('button', {name: 'Запустить предпросмотр', exact: true}).click();
  await previewReady();
  const resumedUrl = await page.locator('iframe').getAttribute('src');
  assert.notEqual(resumedUrl, restartedUrl, 'Stop/start obtains a new scoped URL');
  expiredTokens.add(new URL(resumedUrl).searchParams.get('token'));
  await page.getByRole('tab', {name: 'Исходники', exact: true}).click();
  await page.getByRole('tab', {name: 'Игра', exact: true}).click();
  await previewReady();
  assert.notEqual(await page.locator('iframe').getAttribute('src'), resumedUrl, 'Reopening the game does not reuse an expired URL');
  failNextDetail = true;
  await page.getByRole('button', {name: 'Перезапустить игру', exact: true}).click();
  await page.getByText('Authored scoped URL refresh failure', {exact: true}).waitFor();
  assert.equal(await page.locator('iframe').count(), 0, 'Failed refresh never falls back to a cached URL');
  await page.getByRole('button', {name: 'Повторить', exact: true}).click();
  await previewReady();
  const stableUrl = await page.locator('iframe').getAttribute('src'), readsBeforePoll = issuedTokens;
  await page.waitForTimeout(7500);
  assert.equal(await page.locator('iframe').getAttribute('src'), stableUrl, 'Workspace polling preserves running gameplay');
  assert.equal(issuedTokens, readsBeforePoll, 'Workspace polling does not mint or reload preview tokens');
  assert.equal(expiredPreviewRequests, 0);
  assert.equal(failedDetailReads, 1, 'A failed refresh is bounded until explicit retry');
  await page.getByLabel('Запрос на изменение игры').fill('Change the accent color.');
  await page.getByRole('button', {name: 'Внести изменения', exact: true}).click();
  await page.getByText('Candidate failed; last playable revision preserved').waitFor();
  assert.match(await page.locator('iframe').getAttribute('src'), /version-1/, 'Failed revision preserves playable preview');
  await page.getByLabel('Выбранная версия').selectOption('version-2');
  await page.getByText('Игра не прошла проверки', {exact: true}).waitFor();
  assert.equal(await page.locator('iframe').count(), 0, 'Failed diagnostic candidate never executes');
  assert.equal(await page.getByRole('link', {name: 'Скачать HTML'}).count(), 0);
  await page.getByRole('tab', {name: 'Исходники', exact: true}).click();
  await page.getByText('Authored diagnostic source; never execute', {exact: false}).waitFor();
  await page.getByLabel('Выбранная версия').selectOption('version-1');
  await page.getByRole('tab', {name: 'Игра', exact: true}).click();
  await page.getByRole('button', {name: 'Продолжить после ошибки', exact: true}).click();
  await page.getByRole('button', {name: 'Отменить задание', exact: true}).waitFor();
  assert.equal(resumeRequests, 1, 'Continuation sends one explicitly authorized mutation');
  assert.equal(job.id, 'job-2', 'Continuation retains the same job');
  assert.match(await page.locator('iframe').getAttribute('src'), /version-1/, 'Continuation preserves the old playable preview');
  await page.getByRole('button', {name: 'Приостановить', exact: true}).click();
  await page.locator('.job-monitor').getByText('На паузе', {exact: true}).waitFor();
  assert.equal(await page.getByRole('button', {name: 'Внести изменения', exact: true}).isDisabled(), true);
  assert.match(await page.locator('iframe').getAttribute('src'), /version-1/);
  await page.screenshot({path: `${evidence}/paused-job.png`, fullPage: true});
  await page.getByRole('button', {name: 'Продолжить задание', exact: true}).click();
  await page.getByRole('button', {name: 'Приостановить', exact: true}).waitFor();
  assert.equal(resumeRequests, 2);
  assert.equal(job.id, 'job-2');
  await page.getByRole('button', {name: 'Отменить задание', exact: true}).click();
  await page.getByText('Отменено', {exact: true}).waitFor();
  await page.getByLabel('Запрос на изменение игры').fill('Another authored UI request.');
  await page.getByRole('button', {name: 'Внести изменения', exact: true}).click();
  await page.getByRole('button', {name: 'Отменить задание', exact: true}).click();
  await page.getByText('Отменено', {exact: true}).waitFor();
  assert.match(await page.locator('iframe').getAttribute('src'), /version-1/);
  await page.getByRole('link', {name: /^Исполнители/}).click();
  await page.getByRole('button', {name: 'Подключить исполнителя', exact: true}).click();
  await page.getByLabel('Название машины').fill('Browser acceptance');
  await page.getByLabel('Задача исполнителя').selectOption('validator');
  await page.getByRole('button', {name: 'Создать токен', exact: true}).click();
  await page.getByText(/prompt2play worker .*--role validator/, {exact: false}).waitFor();
  assert.equal(await page.getByLabel('Одноразово показанный токен исполнителя').getAttribute('type'), 'password');
  await page.getByRole('button', {name: 'Токен сохранён', exact: true}).click();
  assert.equal(await page.getByLabel('Одноразово показанный токен исполнителя').count(), 0);
  await page.getByText('Browser acceptance', {exact: true}).waitFor();
  assert.deepEqual(errors, []);
  await page.screenshot({path: `${evidence}/creator-flow.png`, fullPage: true});
  fs.writeFileSync(`${evidence}/result.json`, JSON.stringify({passed: true, browser: browser.version(), scope: 'Trusted studio with authored API double; no live model/backend/game execution', expired_preview_requests: expiredPreviewRequests, checks: ['submit', 'scoped preview', 'expired URL refreshed on restart, stop/start and reopening', 'refresh failure bounded and no stale URL fallback', 'running preview stable during workspace polling', 'failed revise preserves playable', 'failed candidate diagnostics', 'source selection', 'pause and resume same job', 'cancel', 'admin validator role registration', 'one-time token hidden after dismissal']}, null, 2));
  process.stdout.write('Creator browser flow passed (authored API double).\n');
} finally {
  await context.tracing.stop({path: `${evidence}/creator-flow.zip`});
  await browser.close();
}
