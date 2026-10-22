"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

async function check(qrAvailable, qrError = "", phase = "ready") {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      checked: false, disabled: false, events: {}, style: {},
      classList: {toggle() {}, add() {}, remove() {}},
      addEventListener(name, callback) { this.events[name] = callback; },
      setAttribute() {}, removeAttribute() {}, replaceChildren() {},
      querySelector() { return element(id + "-child"); }
    });
    return elements.get(id);
  };
  const server = {value: "ios", addEventListener() {}};
  const state = {phase, qr_available: qrAvailable, qr_error: qrError,
    remaining_seconds: 0, has_qr: false, download_ready: false};
  vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {
    document: {getElementById: element, querySelector: selector =>
      selector.startsWith("meta") ? {content: "synthetic-csrf"} : server,
      querySelectorAll: () => [server]},
    window: {addEventListener() {}, dispatchEvent() {}, setInterval() {}, setTimeout() {}},
    performance: {now: () => 0}, CustomEvent: class {},
    fetch: async () => ({ok: true, json: async () => state})
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(element("start-button").disabled, true);
  element("consent").checked = true;
  element("consent").events.change();
  assert.equal(element("start-button").disabled, !qrAvailable || phase !== "ready");
  if (!qrAvailable) {
    assert.match(element("field-hint").textContent, qrError === "LOCAL_PROFILE_INVALID"
      ? /扫码配置未通过校验/ : /扫码配置缺失/);
    element("tab-file").events.click();
    element("capture-file").events.change({target: {files: [{name: "synthetic.json", size: 2}]}});
    assert.equal(element("start-button").disabled, false);
  }
}

(async () => {
  await check(true);
  await check(false, "LOCAL_PROFILE_REQUIRED");
  await check(false, "LOCAL_PROFILE_INVALID");
  await check(true, "", "generating");
  console.log("扫码按钮勾选、缺失提示、配置校验失败、文件导入和忙碌状态通过");
})().catch(error => { console.error(error); process.exitCode = 1; });
