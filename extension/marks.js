/** Mark ingested answers: overlay check badge on author avatar. Polls qsbk serve. */
(function () {
  if (window.__qsbkMarksLoaded) return;
  window.__qsbkMarksLoaded = true;

  var SERVE_URL = "";
  var POLL_MS = 2500;

  function canonicalUrl(href, baseUrl) {
    if (!href) return null;
    try {
      var u = new URL(href, baseUrl || location.href);
      u.hash = "";
      u.search = "";
      return u.origin.toLowerCase() + u.pathname.replace(/\/$/, "");
    } catch (e) {
      return null;
    }
  }

  function answerKey(href, baseUrl) {
    var url = canonicalUrl(href, baseUrl);
    if (!url) return null;
    var m = url.match(/\/answer\/([^/?#]+)/i);
    return m ? m[1].toLowerCase() : null;
  }

  function findAnswerBlock(anchor) {
    var node = anchor;
    for (var i = 0; i < 14 && node; i++) {
      if (
        node.querySelector &&
        (node.querySelector(".puppeteer_test_question_title") ||
          node.querySelector('[class*="question_title"]') ||
          node.querySelector(".puppeteer_test_answer_content") ||
          node.querySelector(".spacing_log_answer_content"))
      ) {
        return node;
      }
      node = node.parentElement;
    }
    return anchor.closest ? anchor.closest("article") || anchor.parentElement : anchor.parentElement;
  }

  function authorImageInBlock(block) {
    if (!block) return null;
    return (
      block.querySelector('img.q-image[size="36"]') ||
      block.querySelector("img.q-image.qu-size--36") ||
      block.querySelector('img.q-image[alt*="perfil"]') ||
      block.querySelector('img.q-image[alt*="profile"]') ||
      block.querySelector("header img.q-image") ||
      block.querySelector("img.q-image")
    );
  }

  function badgeHostForImage(img) {
    return (
      img.closest('[class*="UserAvatar"]') ||
      img.closest('[class*="Avatar"]') ||
      img.parentElement
    );
  }

  function applyCheckBadge(block) {
    if (!block || block.dataset.qsbkChecked === "1") return false;
    var img = authorImageInBlock(block);
    if (!img) return false;

    var host = badgeHostForImage(img);
    if (!host) return false;
    if (host.querySelector(".qsbk-check-badge")) {
      block.dataset.qsbkChecked = "1";
      return false;
    }

    block.dataset.qsbkChecked = "1";
    host.style.position = host.style.position || "relative";

    var badge = document.createElement("span");
    badge.className = "qsbk-check-badge";
    badge.setAttribute("aria-label", "Already ingested");
    badge.textContent = "\u2713";
    badge.title = "Already ingested (qsbk)";
    badge.style.cssText =
      "position:absolute;right:-2px;bottom:-2px;width:18px;height:18px;" +
      "border-radius:50%;background:#059669;color:#fff;font-size:12px;" +
      "line-height:18px;text-align:center;font-weight:700;z-index:20;" +
      "box-shadow:0 0 0 2px #fff;pointer-events:none;";

    host.appendChild(badge);
    return true;
  }

  function buildKnownIndex(payload) {
    var byUrl = {};
    var byKey = {};
    var urls = (payload && payload.urls) || [];
    var keys = (payload && payload.keys) || [];

    urls.forEach(function (u) {
      var c = canonicalUrl(u, location.href);
      if (c) byUrl[c] = true;
      var k = answerKey(u, location.href);
      if (k) byKey[k] = true;
    });
    keys.forEach(function (k) {
      byKey[String(k).toLowerCase()] = true;
    });

    var last = payload && payload.last_ingested;
    if (last && last.url) {
      var lc = canonicalUrl(last.url, location.href);
      if (lc) byUrl[lc] = true;
      var lk = answerKey(last.url, location.href);
      if (lk) byKey[lk] = true;
    }

    return { byUrl: byUrl, byKey: byKey, payload: payload || {} };
  }

  function isKnownAnchor(anchor, known) {
    var href = anchor.getAttribute("href");
    if (!href || href.indexOf("/answer/") === -1) return false;
    var curl = canonicalUrl(href, location.href);
    if (curl && known.byUrl[curl]) return true;
    var key = answerKey(href, location.href);
    return !!(key && known.byKey[key]);
  }

  function markKnownOnPage(knownIndex) {
    if (!knownIndex) return 0;
    var marked = 0;
    document.querySelectorAll('a[href*="/answer/"]').forEach(function (anchor) {
      if (!isKnownAnchor(anchor, knownIndex)) return;
      var block = findAnswerBlock(anchor);
      if (applyCheckBadge(block)) marked += 1;
    });
    return marked;
  }

  async function fetchKnownPayload() {
    try {
      var response = await fetch(SERVE_URL, { cache: "no-store" });
      if (!response.ok) return null;
      return await response.json();
    } catch (e) {
      return null;
    }
  }

  var cachedIndex = null;
  var pollTimer = null;

  async function refreshMarks() {
    var payload = await fetchKnownPayload();
    if (payload === null) {
      return { ok: false, error: "qsbk serve not running", marked: 0 };
    }
    cachedIndex = buildKnownIndex(payload);
    try {
      chrome.storage.local.set({
        knownAnswerPayload: payload,
        knownSyncedAt: Date.now(),
      });
    } catch (e) {
      /* ignore */
    }
    var marked = markKnownOnPage(cachedIndex);
    return {
      ok: true,
      marked: marked,
      count: payload.count || 0,
      last_ingested: payload.last_ingested || null,
    };
  }

  function refreshFromCache() {
    return new Promise(function (resolve) {
      try {
        chrome.storage.local.get(["knownAnswerPayload"], function (data) {
          var payload = data.knownAnswerPayload || { urls: [], keys: [] };
          cachedIndex = buildKnownIndex(payload);
          resolve(markKnownOnPage(cachedIndex));
        });
      } catch (e) {
        resolve(0);
      }
    });
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(function () {
      refreshMarks().then(function (result) {
        if (!result.ok && cachedIndex) {
          markKnownOnPage(cachedIndex);
        }
      });
    }, POLL_MS);
  }

  function observeDom() {
    if (!window.MutationObserver) return;
    var pending = false;
    var observer = new MutationObserver(function () {
      if (pending || !cachedIndex) return;
      pending = true;
      requestAnimationFrame(function () {
        pending = false;
        markKnownOnPage(cachedIndex);
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  chrome.runtime.onMessage.addListener(function (msg, _sender, sendResponse) {
    if (msg.type === "refreshMarks") {
      refreshMarks().then(sendResponse);
      return true;
    }
    if (msg.type === "markCached") {
      refreshFromCache().then(function (marked) {
        sendResponse({ ok: true, marked: marked });
      });
      return true;
    }
    return false;
  });

  if (location.href.indexOf("/answers") !== -1) {
    window.qsbkServeConfig.getServeBase(function (base) {
      SERVE_URL = window.qsbkServeConfig.serveUrls(base).known;
      refreshMarks().then(function (result) {
        if (!result.ok) refreshFromCache();
        startPolling();
        observeDom();
      });
    });
  }

  window.qsbkRefreshMarks = refreshMarks;
  window.qsbkMarkCached = refreshFromCache;
})();
