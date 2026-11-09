// sdpm MCP Apps bridge: JSON-RPC 2.0 over postMessage between a view and its host.
// No SDK and no network. Inlined into each view where the view's script asks for it.
(function () {
  "use strict";
  var nextId = 1;
  var pending = new Map();
  var toolResultHandlers = [];
  var lastToolResult = null;
  var lastHeight = 0;
  var bridge = { hostContext: {}, hostCapabilities: {} };

  function send(msg) {
    // The host's sandbox has an opaque origin, so no target origin can be named; replies are
    // accepted only from window.parent (see the listener below).
    window.parent.postMessage(msg, "*");
  }

  bridge.request = function (method, params) {
    var id = nextId++;
    send({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
    return new Promise(function (resolve, reject) {
      pending.set(id, { resolve: resolve, reject: reject });
    });
  };

  bridge.notify = function (method, params) {
    send({ jsonrpc: "2.0", method: method, params: params || {} });
  };

  // tools/call through the host; resolves with the CallToolResult (check isError).
  bridge.callTool = function (name, args) {
    return bridge.request("tools/call", { name: name, arguments: args || {} });
  };

  // Adds a user message to the conversation (starts the agent's next turn).
  bridge.sendMessage = function (text) {
    return bridge.request("ui/message", { role: "user", content: [{ type: "text", text: text }] });
  };

  bridge.canDisplay = function (mode) {
    var modes = bridge.hostContext.availableDisplayModes;
    return Array.isArray(modes) && modes.indexOf(mode) >= 0;
  };

  // Asks for a display mode the host offers; resolves with the mode now in effect.
  bridge.requestDisplayMode = function (mode) {
    if (!bridge.canDisplay(mode)) return Promise.resolve(bridge.hostContext.displayMode || "inline");
    return bridge.request("ui/request-display-mode", { mode: mode }).then(function (r) {
      var now = (r && r.mode) || mode;
      bridge.hostContext.displayMode = now;
      return now;
    });
  };

  bridge.onToolResult = function (fn) {
    toolResultHandlers.push(fn);
    if (lastToolResult) fn(lastToolResult);
  };

  bridge.reportSize = function () {
    var el = document.documentElement;
    if (el.scrollHeight === lastHeight) return;
    lastHeight = el.scrollHeight;
    bridge.notify("ui/notifications/size-changed", { width: el.scrollWidth, height: el.scrollHeight });
  };

  // Only the host (the parent frame) talks to this view.
  window.addEventListener("message", function (ev) {
    if (ev.source !== window.parent) return;
    var m = ev.data;
    if (!m || m.jsonrpc !== "2.0") return;
    if (m.id != null && !m.method) {
      var p = pending.get(m.id);
      if (!p) return;
      pending.delete(m.id);
      if (m.error) p.reject(new Error(m.error.message || "error"));
      else p.resolve(m.result);
      return;
    }
    if (m.method === "ui/notifications/tool-result") {
      lastToolResult = m.params || {};
      toolResultHandlers.forEach(function (fn) { fn(lastToolResult); });
      return;
    }
    if (m.method === "ui/notifications/host-context-changed") {
      Object.assign(bridge.hostContext, m.params || {});
      return;
    }
    if (m.id != null && m.method) send({ jsonrpc: "2.0", id: m.id, result: {} }); // ui/resource-teardown, ping
  });

  document.addEventListener("DOMContentLoaded", function () {
    new ResizeObserver(bridge.reportSize).observe(document.body);
  });

  bridge.ready = bridge.request("ui/initialize", {
    appInfo: { name: document.documentElement.dataset.app || "sdpm", version: "1" },
    appCapabilities: { availableDisplayModes: ["inline", "fullscreen"] },
    protocolVersion: "2026-01-26"
  }).then(function (r) {
    bridge.hostCapabilities = (r && r.hostCapabilities) || {};
    bridge.hostContext = (r && r.hostContext) || {};
    bridge.notify("ui/notifications/initialized", {});
    return r;
  });

  window.sdpmBridge = bridge;
})();
