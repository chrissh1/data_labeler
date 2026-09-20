import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const [debugOrigin, appOrigin, outputDirectory] = process.argv.slice(2);
const targets = await (await fetch(`${debugOrigin}/json/list`)).json();
const target = targets.find(item => item.type === 'page' && item.url.startsWith(appOrigin));
assert(target, 'Isolated test tab must exist');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});
let nextId = 0;
const pending = new Map();
let onLoad;
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.method === 'Page.loadEventFired') onLoad?.();
  const request = pending.get(message.id);
  if (!request) return;
  pending.delete(message.id);
  clearTimeout(request.timeout);
  if (message.error) request.reject(new Error(message.error.message));
  else request.resolve(message.result);
});
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    const timeout = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out`)); }, 8000);
    pending.set(id, { resolve, reject, timeout });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression, userGesture = false) {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
async function navigate(path) {
  const loaded = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Page did not load')), 8000);
    onLoad = () => { clearTimeout(timeout); resolve(); };
  });
  await send('Page.navigate', { url: appOrigin + path });
  await loaded;
}
async function capture(name) {
  const { data } = await send('Page.captureScreenshot', { format: 'png' });
  await writeFile(join(outputDirectory, name + '.png'), Buffer.from(data, 'base64'));
}
try {
  await mkdir(outputDirectory, { recursive: true });
  await send('Page.enable');
  await navigate('/');
  await send('Emulation.setDeviceMetricsOverride', { width: 1100, height: 850, deviceScaleFactor: 1, mobile: false });
  await capture('task-desktop');
  for (const width of [320, 375, 414, 768]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 850, deviceScaleFactor: 1, mobile: false });
    await capture(`task-${width}`);
    await evaluate('document.querySelector("#view-instructions").click()');
    await capture(`tutorial-${width}`);
    await evaluate('document.querySelector("#tutorial-done").click()');
  }
  const resultsLoaded = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Results did not load')), 8000);
    onLoad = () => { clearTimeout(timeout); resolve(); };
  });
  await evaluate('document.querySelector("#results-link").click()', true);
  await resultsLoaded;
  assert.equal(await evaluate('location.pathname'), '/results', 'Results must load in the same tab');
  const opened = await (await fetch(`${debugOrigin}/json/list`)).json();
  assert(!opened.some(item => item.id !== target.id && item.url.startsWith(appOrigin)), 'Navigation must not create a second tab');
  await send('Emulation.setDeviceMetricsOverride', { width: 1100, height: 850, deviceScaleFactor: 1, mobile: false });
  await capture('results-desktop');
  await send('Emulation.setDeviceMetricsOverride', { width: 320, height: 850, deviceScaleFactor: 1, mobile: false });
  await capture('results-mobile');
  console.log(`PASS: Results opened in the same tab; screenshots saved to ${outputDirectory}`);
} finally {
  socket.close();
}
