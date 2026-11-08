"use strict";
const assert = require("assert");
const path = require("path");

class FakeElement {
  constructor(tagName) {
    this.tagName = String(tagName || "").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.id = "";
    this.textContent = "";
    this.innerHTML = "";
    this.isConnected = false;
    this.shadowRoot = null;
    this._attachedShadow = null;
  }
  appendChild(node) {
    if (node.parentNode) node.remove();
    this.children.push(node);
    node.parentNode = this;
    node.isConnected = true;
    return node;
  }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  replaceChildren(...nodes) {
    this.children.forEach(node => { node.parentNode = null; node.isConnected = false; });
    this.children = [];
    this.append(...nodes);
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(node => node !== this);
    this.parentNode = null;
    this.isConnected = false;
  }
  attachShadow({ mode } = {}) {
    this._attachedShadow = new FakeElement("shadow-root");
    this._attachedShadow.host = this;
    this._attachedShadow.isConnected = true;
    this.shadowRoot = mode === "open" ? this._attachedShadow : null;
    this._shadowMode = mode;
    return this._attachedShadow;
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatch(type, event = {}) { for (const listener of this.listeners[type] || []) listener({ type, target: this, ...event }); }
  closest() { return null; }
}

function walk(root) {
  const values = [root];
  for (const child of root.children || []) values.push(...walk(child));
  return values;
}

const documentElement = new FakeElement("html");
const body = new FakeElement("body");
documentElement.appendChild(body);
const document = {
  body,
  documentElement,
  fullscreenElement: null,
  title: "Firefox media fixture",
  createElement: tag => new FakeElement(tag),
  getElementById(id) { return walk(documentElement).find(node => node.id === id) || null; },
  addEventListener() {}
};
let timerId = 0;
const timers = new Map();
globalThis.setTimeout = (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; };
globalThis.clearTimeout = id => timers.delete(id);
globalThis.document = document;
globalThis.location = { href: "https://page.example/watch" };
const messages = [];
globalThis.browser = {
  runtime: {
    async sendMessage(message) {
      messages.push(message);
      if (message.type === "xdmGetLogicalCandidatesV2") return {
        candidates: [{
          logicalMediaId: "media-1", title: "Example video", url: "https://cdn.example/video.mp4",
          contentType: "video/mp4", streamKind: "video", contentLength: 5000000, durationMs: 60000
        }]
      };
      if (message.type === "xdmSendLogicalCandidatesV2" || message.type === "xdmSendLogicalCandidatesTo1DmV1") {
        return { ok: true, sentCount: 1 };
      }
      throw new Error("Unexpected browser message: " + message.type);
    }
  }
};
globalThis.XdmExtensionConfig = {
  themeMode: "dark",
  theme: {
    background: "#090B0F", surface: "#101318", raisedSurface: "#161A21", strongSurface: "#1C212A",
    text: "#E8EDF5", mutedText: "#ABB4C2", primary: "#7DB8FF", onPrimary: "#003259",
    primaryContainer: "#183B59", onPrimaryContainer: "#D2E8FF", outline: "#333A46",
    separator: "#252B35", success: "#79D49A", error: "#FFB4AB",
    fabSizePx: 56, fabCornerRadiusPx: 18, fabEdgeInsetPx: 16, fabActionGapPx: 10,
    motionFastMs: 140, motionStandardMs: 220
  }
};

require(path.join(__dirname, "..", "src", "main", "extension", "xdm-firefox", "fab.js"));
const api = globalThis.XdmLauncherUiV3;
assert(api, "v1.6.1 FAB API must be exported");
assert.strictEqual(api, globalThis.XdmLauncherUiV2, "V2 compatibility alias remains available");
assert.strictEqual(api.hostId, "__xdm_media_fab_host");

const xdmLink = "xdmdownload://capture?v=3&url=https%3A%2F%2Fcdn.example%2Fvideo.mp4&kind=video";
const oneDmLink = "intent://video.mp4#Intent;scheme=idmdownload;package=idm.internet.download.manager.plus;end";

assert(api.show({ target: "xdm", links: { xdm: xdmLink, oneDm: oneDmLink }, candidateCount: 4, streamKind: "hls" }));
let state = api.state();
assert.deepStrictEqual({ target: state.target, candidateCount: state.candidateCount, kind: state.kind }, { target: "xdm", candidateCount: 4, kind: "HLS" });
let host = document.getElementById(api.hostId);
assert(host && host._attachedShadow && host.shadowRoot === null && host._shadowMode === "closed", "FAB must keep privileged links inside a closed Shadow DOM");
let nodes = walk(host._attachedShadow);
const style = nodes.find(node => node.tagName === "STYLE");
assert(style.textContent.includes("env(safe-area-inset-bottom)"));
assert(style.textContent.includes("prefers-reduced-motion"));
assert(style.textContent.includes("width:56px;height:56px"));
assert(nodes.some(node => node.className === "xdm-badge" && node.textContent === "4"));
assert(nodes.some(node => node.className === "xdm-kind" && node.textContent === "HLS"));
const direct = nodes.find(node => node.className === "xdm-fab");
assert.strictEqual(direct.tagName, "A");
assert(String(direct.href).startsWith("xdmdownload://capture"));

assert(api.show({ target: "ask", links: { xdm: xdmLink, oneDm: oneDmLink }, candidateCount: 1, streamKind: "video" }));
host = document.getElementById(api.hostId);
nodes = walk(host._attachedShadow);
const askButton = nodes.find(node => node.className === "xdm-fab");
assert.strictEqual(askButton.tagName, "BUTTON");
assert.strictEqual(askButton.getAttribute("aria-haspopup"), "menu");
askButton.dispatch("click");
state = api.state();
assert.strictEqual(state.expanded, true);
host = document.getElementById(api.hostId);
nodes = walk(host._attachedShadow);
assert.strictEqual(nodes.filter(node => String(node.className).includes("xdm-choice")).length, 2);
assert.strictEqual(nodes.find(node => node.className === "xdm-menu").getAttribute("aria-hidden"), "false");

(async () => {
  assert(api.show({ target: "xdm", links: {}, candidateCount: 2, streamKind: "hls", pickerRequired: true }));
  host = document.getElementById(api.hostId);
  nodes = walk(host._attachedShadow);
  const pickerButton = nodes.find(node => node.className === "xdm-fab");
  assert.strictEqual(pickerButton.tagName, "BUTTON", "picker requires a button, never an automatic native link");
  assert.strictEqual(pickerButton.getAttribute("aria-haspopup"), "dialog");
  assert.strictEqual(nodes.filter(node => node.tagName === "A").length, 0, "no prebuilt media launch when selection is required");
  pickerButton.dispatch("click");
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(api.state().pickerOpen, true);
  nodes = walk(host._attachedShadow);
  const picker = nodes.find(node => node.className === "xdm-picker");
  assert(picker && picker.getAttribute("role") === "dialog", "media picker must show as dialog");
  const radio = nodes.find(node => node.className === "xdm-media-radio");
  assert(radio && radio.value === "media-1", "picker offers the logical media candidate");
  radio.checked = true;
  radio.dispatch("change");
  nodes = walk(host._attachedShadow);
  const sendToXdm = nodes.find(node => String(node.className).includes("xdm-picker-button-primary"));
  assert(sendToXdm && !sendToXdm.disabled, "send requires exactly one selected item");
  sendToXdm.dispatch("click");
  await new Promise(resolve => setImmediate(resolve));
  assert(messages.some(message => message.type === "xdmSendLogicalCandidatesV2" && message.logicalMediaIds.length === 1 && message.logicalMediaIds[0] === "media-1"));
  assert.strictEqual(api.state().pickerOpen, false);
  api.hide();
  assert.strictEqual(document.getElementById(api.hostId), null);
  assert.strictEqual(api.state(), null);
  console.log("Firefox v1.6.1 closed Shadow DOM FAB and single-choice picker tests passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
