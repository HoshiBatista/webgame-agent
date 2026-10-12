import fs from 'node:fs';
import crypto from 'node:crypto';
import {chromium} from '/validator/node_modules/playwright/index.mjs';
const sha = value => crypto.createHash('sha256').update(value).digest('hex');
const html = fs.readFileSync('/input/game.html', 'utf8');
const config = JSON.parse(fs.readFileSync('/input/config.json', 'utf8'));
const checks = [], evidence = [];
const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE || undefined, args:['--no-sandbox','--disable-dev-shm-usage']});
const context = await browser.newContext({viewport:{width:598,height:771}, deviceScaleFactor:2});
const page = await context.newPage();
await page.route('**/*', route => route.request().url() === 'http://game.test/' ? route.fulfill({contentType:'text/html',body:html}) : route.abort());
await page.goto('http://game.test/');
await page.locator('#p2p-start').click();
await page.locator('#resize-move').click();
for (const [width,height] of [[598,771],[1512,949],[390,844],[598,771],[1512,949]]) {
  await page.setViewportSize({width,height});
  await page.waitForTimeout(150); // Allow ResizeObserver to converge; never reload the game.
  const state = await page.evaluate(() => {
    const canvas = document.querySelector('canvas'), box = canvas.getBoundingClientRect(), button = document.querySelector('#resize-move').getBoundingClientRect();
    return {width:innerWidth,height:innerHeight,documentHeight:document.documentElement.scrollHeight,canvasBottom:box.bottom,buttonBottom:button.bottom,buffer:[canvas.width,canvas.height],css:[box.width,box.height],dpr:devicePixelRatio,snapshot:window.__GAME_TEST__.snapshot()};
  });
  checks.push({name:`resize:${width}:${height}:${checks.length}`,passed:state.documentHeight <= height + 1 && state.buttonBottom <= height && state.canvasBottom < height && Math.abs(state.buffer[1]-state.css[1]*state.dpr) <= 1 && state.snapshot.moves === 1,detail:state});
  const name = `resize-${checks.length}-${width}.png`, bytes = await page.screenshot(); fs.writeFileSync('/evidence/'+name,bytes); evidence.push({path:name,bytes:bytes.length,sha256:sha(bytes)});
}
await browser.close();
process.stdout.write(JSON.stringify({passed:checks.every(c=>c.passed),checks,html_sha256:sha(html),script_sha256:sha(fs.readFileSync('/review/challenge.mjs')),runtime:config.runtime,validator_image_sha256:config.image,harness_files_sha256:config.harness_files_sha256,evidence_files:evidence}));
