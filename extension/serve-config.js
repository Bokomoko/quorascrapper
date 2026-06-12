/** Shared qsbk serve base URL (default: bokomint LAN host). */
(function (global) {
  var FALLBACK = "http://bokomint.local:8765";

  function normalizeBase(url) {
    return String(url || FALLBACK).replace(/\/+$/, "");
  }

  function loadDefaultBase(cb) {
    if (typeof chrome === "undefined" || !chrome.runtime || !chrome.runtime.getURL) {
      cb(FALLBACK);
      return;
    }
    var configUrl = chrome.runtime.getURL("config.json");
    fetch(configUrl, { cache: "no-store" })
      .then(function (r) {
        return r.ok ? r.json() : {};
      })
      .then(function (cfg) {
        cb(normalizeBase((cfg && cfg.serveBase) || FALLBACK));
      })
      .catch(function () {
        cb(FALLBACK);
      });
  }

  function getServeBase(cb) {
    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
      chrome.storage.local.get(["qsbkServeBase"], function (data) {
        if (data && data.qsbkServeBase) {
          cb(normalizeBase(data.qsbkServeBase));
          return;
        }
        loadDefaultBase(cb);
      });
      return;
    }
    loadDefaultBase(cb);
  }

  function serveUrls(base) {
    base = normalizeBase(base);
    return {
      base: base,
      ping: base + "/ping",
      check: base + "/check",
      upsert: base + "/upsert",
      known: base + "/known",
    };
  }

  global.qsbkServeConfig = {
    fallbackBase: FALLBACK,
    normalizeBase: normalizeBase,
    getServeBase: getServeBase,
    serveUrls: serveUrls,
  };
})(typeof window !== "undefined" ? window : self);
