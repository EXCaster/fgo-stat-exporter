"use strict";
// 人工页面与延迟响应用于验证切服，不发出网络请求。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = (value, ok = true) => ({ok, json: async () => value});

async function page(initial, hooks = {}) {
  let state = {generation: 5, source: "qr", server: "ios", phase: "waiting_scan",
    can_switch_server: true, qr_available: true, has_qr: true, ...initial};
  const elements = new Map(), requests = [], timers = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      checked: id === "consent", disabled: false, hidden: false, events: {}, style: {},
      classList: {toggle() {}, add() {}, remove() {}},
      addEventListener(name, callback) { this.events[name] = callback; },
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; }, replaceChildren() {},
      querySelector(selector) { return element(id + selector); }
    });
    return elements.get(id);
  };
  const radios = ["ios", "android"].map(value => ({value, checked: value === state.server,
    events: {}, addEventListener(name, callback) { this.events[name] = callback; }}));
  const select = value => { for (const input of radios) input.checked = input.value === value; };
  const context = {
    document: {getElementById: element, querySelector: selector =>
      selector.startsWith("meta") ? {content: "synthetic-csrf"} : radios.find(input => input.checked),
      querySelectorAll: () => radios},
    window: {addEventListener() {}, dispatchEvent() {}, setInterval() {},
      setTimeout(callback) { timers.push(callback); }},
    performance: {now: () => 0}, CustomEvent: class {},
    fetch: async (path, options) => {
      requests.push({path, options});
      const override = await hooks.fetch?.(path, options);
      if (override) return override;
      if (path === "/api/state") return response(state);
      const value = JSON.parse(options.body);
      if (path === "/api/server") {
        state = {...state, generation: state.generation + 1, source: "", phase: "cleared",
          server: value.server, has_qr: false, can_switch_server: false};
      } else if (path === "/api/start") {
        state = {...state, generation: state.generation + 1, source: "qr", phase: "generating",
          server: value.server, has_qr: false, can_switch_server: true};
      } else throw new Error("出现未预期的请求");
      return response(state);
    }
  };
  vm.runInNewContext(source, context);
  await settle();
  return {element, radios, select, requests, timers,
    posts: () => requests.filter(item => item.options.method === "POST"),
    async change(value) { select(value); await radios.find(input => input.value === value).events.change(); }};
}

async function run() {
  let cases = 0;
  for (const phase of ["generating", "waiting_scan", "waiting_confirm"])
    for (const [first, second] of [["ios", "android"], ["android", "ios"]]) {
      const view = await page({phase, server: first});
      assert.ok(view.radios.every(input => !input.disabled));
      assert.equal(view.element("start-button").disabled, true);
      await view.change(second);
      assert.equal(view.posts().length, 1);
      assert.equal(view.posts()[0].path, "/api/server");
      assert.deepEqual(JSON.parse(view.posts()[0].options.body), {server: second, generation: 5});
      assert.equal(view.element("qr-image").hidden, true);
      assert.equal(view.element("qr-image").src, undefined);
      assert.match(view.element("qr-emptyb").textContent, /原二维码已取消/);
      assert.equal(view.element("start-button").disabled, false);
      await view.element("start-button").events.click();
      assert.equal(view.posts().length, 2);
      assert.equal(view.posts()[1].path, "/api/start");
      assert.deepEqual(JSON.parse(view.posts()[1].options.body), {server: second, consent: true});
      cases++;
    }
  for (const phase of ["game_handoff", "game_initialization", "fetching_statistics", "filtering_statistics"]) {
    const view = await page({phase, can_switch_server: false, has_qr: false});
    assert.ok(view.radios.every(input => input.disabled));
    await view.change("android");
    assert.equal(view.posts().length, 0);
    cases++;
  }
  {
    const view = await page({}, {fetch: path => path === "/api/server"
      ? response({error: "OPERATION_NOT_READY"}, false) : undefined});
    await view.change("android");
    assert.ok(view.radios.find(input => input.value === "ios").checked);
    assert.equal(view.element("qr-image").hidden, false);
    assert.equal(view.element("error-code").textContent, "OPERATION_NOT_READY");
    cases++;
  }
  {
    const view = await page({});
    await view.change("ios");
    assert.equal(view.posts().length, 0);
    view.element("consent").checked = false;
    view.element("consent").events.change();
    assert.ok(view.radios.every(input => input.disabled));
    await view.change("android");
    assert.equal(view.posts().length, 0);
    assert.equal(view.element("error-code").textContent, "CONSENT_REQUIRED");
    cases++;
  }
  for (const mode of ["qr", "file"]) {
    const view = await page({phase: "complete", source: "file", has_qr: false, can_switch_server: false});
    view.element("tab-" + mode).events.click();
    await view.change("android");
    assert.equal(view.posts().length, 0);
    cases++;
  }
  {
    let holdState = false, resolveState, resolveSwitch;
    const old = {phase: "waiting_scan", source: "qr", server: "ios", generation: 5,
      can_switch_server: true, has_qr: true, qr_available: true};
    const view = await page(old, {fetch: (path) => {
      if (path === "/api/state" && holdState) return new Promise(resolve => { resolveState = resolve; });
      if (path === "/api/server") return new Promise(resolve => { resolveSwitch = resolve; });
    }});
    holdState = true;
    const polling = view.timers.shift()();
    await settle();
    const changing = view.change("android");
    await settle();
    assert.ok(view.radios.every(input => input.disabled));
    await view.change("ios");
    assert.equal(view.posts().length, 1);
    view.select("android");
    resolveState(response(old));
    await polling;
    assert.ok(view.radios.find(input => input.value === "android").checked);
    assert.equal(view.element("qr-image").hidden, true);
    resolveSwitch(response({...old, generation: 6, phase: "cleared", source: "",
      server: "android", has_qr: false, can_switch_server: false}));
    await changing;
    assert.equal(view.posts().length, 1);
    assert.equal(view.element("start-button").disabled, false);
    cases++;
  }
  console.log(JSON.stringify({cases, both_directions: true, manual_generation: true,
    old_poll_ignored: true, account_fetch_locked: true}));
}

run().catch(error => { console.error(error); process.exitCode = 1; });
