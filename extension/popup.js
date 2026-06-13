/** qsbk control panel — movable window, session-scoped stats. */
(function () {
  var SERVE_BASE = "";
  var SERVE_HEALTH = "";
  var SERVE_CHECK = "";
  var SERVE_UPSERT = "";
  var SERVE_KNOWN = "";
  var HEALTH_POLL_MS = 4000;
  var embedded = /[?&]embedded=1/.test(location.search);
  var PROFILE_CACHE_KEY = "profileStatsCache";
  var PROFILE_CURSOR_KEY = "qsbkProfileCursor";
  var PROFILE_CACHE_TTL_MS = 60 * 60 * 1000;

  function toCsv(rows) {
    var lines = ["question_title,answer_url,question_url,answer_preview,seen_at"];
    rows.forEach(function (row) {
      var esc = function (v) {
        return '"' + String(v || "").replace(/"/g, '""') + '"';
      };
      lines.push(
        [
          esc(row.question_title),
          esc(row.answer_url || row.url),
          esc(row.question_url),
          esc(row.answer_preview),
          esc(row.seen_at),
        ].join(",")
      );
    });
    return lines.join("\n");
  }

  function toJsonDocument(rows, meta, profileUrl) {
    return JSON.stringify(
      {
        exported_at: new Date().toISOString(),
        profile_url: profileUrl || "",
        count: rows.length,
        stop_reason: (meta && meta.stop_reason) || "unknown",
        meta: meta || {},
        answers: rows,
      },
      null,
      2
    );
  }

  // Keep request bodies well under serve's 10MB cap. Full-content rows
  // (answer_text) are published in modest batches; classification only needs URLs.
  var SERVE_BATCH = 100;

  function chunk(arr, size) {
    var out = [];
    for (var i = 0; i < arr.length; i += size) {
      out.push(arr.slice(i, i + size));
    }
    return out;
  }

  function rowsForCheck(rows) {
    return rows.map(function (row) {
      var out = { url: row.answer_url || row.url };
      if (row.seen_at) out.seen_at = row.seen_at;
      return out;
    });
  }

  function rowsForServe(rows, identity) {
    identity = identity || {};
    return rows.map(function (row) {
      var out = { url: row.answer_url || row.url };
      if (row.question_title) out.question_title = row.question_title;
      if (row.question_url) out.question_url = row.question_url;
      if (row.answer_preview) out.answer_preview = row.answer_preview;
      if (row.seen_at) out.seen_at = row.seen_at;
      // Richer fields from the GraphQL method (absent in scroll mode).
      if (row.aid) out.aid = row.aid;
      if (row.answer_text) out.answer_text = row.answer_text;
      if (row.num_upvotes != null) out.num_upvotes = row.num_upvotes;
      if (row.num_views != null) out.num_views = row.num_views;
      if (row.num_comments != null) out.num_comments = row.num_comments;
      if (row.creation_time != null) out.creation_time = row.creation_time;
      // Profile identity: prefer the per-row stamp from collectViaGraphql,
      // fall back to the popup-derived identity (covers scroll mode too).
      // serve derives userid from profile_url; we don't send a collection name.
      var pn = row.profile_name || identity.profile_name;
      if (pn) out.profile_name = pn;
      var pu = row.profile_url || identity.profile_url;
      if (pu) out.profile_url = pu;
      var pac =
        row.profile_answer_count != null
          ? row.profile_answer_count
          : identity.profile_answer_count;
      if (pac != null) out.profile_answer_count = pac;
      var pdn = row.profile_display_name || identity.profile_display_name;
      if (pdn) out.profile_display_name = pdn;
      return out;
    });
  }

  function pad2(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function formatDuration(ms) {
    var totalSec = Math.max(0, Math.floor(ms / 1000));
    var h = Math.floor(totalSec / 3600);
    var m = Math.floor((totalSec % 3600) / 60);
    var s = totalSec % 60;
    if (h > 0) return h + ":" + pad2(m) + ":" + pad2(s);
    return m + ":" + pad2(s);
  }

  function formatRate(found, elapsedMs) {
    if (!elapsedMs || found <= 0) return "0.0";
    return (found / (elapsedMs / 60000)).toFixed(1);
  }

  function formatLocalTime(ts) {
    return new Date(ts).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function formatEta(found, max, elapsedMs) {
    if (found <= 0) return "calculating…";
    if (found >= max) return "now";
    var rate = found / (elapsedMs / 60000);
    if (rate <= 0) return "calculating…";
    var remaining = max - found;
    return formatLocalTime(Date.now() + (remaining / rate) * 60000);
  }

  function formatCount(n) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString();
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  var statusEl = document.getElementById("status");
  var maxEl = document.getElementById("max");
  var outputEl = document.getElementById("output");
  var methodEl = document.getElementById("method");
  var forceEl = document.getElementById("force");
  var startBtn = document.getElementById("start");
  var runMinBtn = document.getElementById("run-minimized");
  var statsBlock = document.getElementById("stats-block");
  var statSaved = document.getElementById("stat-saved");
  var statNew = document.getElementById("stat-new");
  var statTotal = document.getElementById("stat-total");
  var sessionElapsed = document.getElementById("session-elapsed");
  var sessionRate = document.getElementById("session-rate");
  var sessionEta = document.getElementById("session-eta");
  var sessionExtra = document.getElementById("session-extra");
  var sessionStarted = document.getElementById("session-started");
  var dragHandle = document.getElementById("drag-handle");
  var serveStatusEl = document.getElementById("serve-status");

  var targetTabId = null;
  var serveAvailable = false;
  var healthPollId = null;
  var contextDead = false;

  // After the extension is reloaded/updated, this in-page panel iframe is
  // orphaned: chrome.runtime.id goes undefined and any chrome.* call throws
  // "Extension context invalidated". Detect that, stop our timers, and tell the
  // user to refresh — instead of spamming the console from interval callbacks.
  function extensionAlive() {
    try {
      return !!(chrome && chrome.runtime && chrome.runtime.id);
    } catch (e) {
      return false;
    }
  }

  function isContextInvalidated(err) {
    var msg = (err && (err.message || err)) || "";
    return /Extension context invalidated|context invalidated|message port closed/i.test(
      String(msg)
    );
  }

  function handleDeadContext() {
    if (contextDead) return;
    contextDead = true;
    if (typeof healthPollId === "number") {
      clearInterval(healthPollId);
      healthPollId = null;
    }
    try {
      setStatus("Extension was reloaded — refresh this Quora tab to reconnect.");
    } catch (e) {
      /* DOM may be gone too */
    }
  }

  var profileState = {
    total: null,
    saved: null,
    fetchPromise: null,
  };

  // Tracks whether the Max input has already been auto-filled for the current
  // profile, so we prefill exactly once per profile (reset on profile change).
  var maxAutoFilled = false;

  // Canonical-ish profile URL for the tab currently in view. Used to scope
  // known/check/saved lookups to this profile's own collection so dedup never
  // reads the global legacy "answers" collection. serve canonicalizes it.
  var activeProfileUrl = null;

  var session = {
    active: false,
    startedAt: null,
    collectingSince: null,
    scrapeElapsedMs: null,
    intervalId: null,
    found: 0,
    scrolled: 0,
    max: 100,
    recovering: false,
    resumePending: false,
    newCount: null,
    skippedCount: null,
    skippedMongo: null,
  };

  function sessionProcessed() {
    return session.found + (session.scrolled || 0);
  }

  function sessionRateElapsedMs() {
    if (session.scrapeElapsedMs != null) return session.scrapeElapsedMs;
    if (session.collectingSince != null) return Date.now() - session.collectingSince;
    if (session.startedAt != null) return Date.now() - session.startedAt;
    return 0;
  }

  function sessionNewRate() {
    return formatRate(session.found, sessionRateElapsedMs());
  }

  function sessionThroughputRate() {
    return formatRate(sessionProcessed(), sessionRateElapsedMs());
  }

  var classifyTimer = null;
  var classifyInFlight = false;

  function liveClassifyEnabled() {
    return serveAvailable && (outputEl.value === "kafka" || outputEl.value === "json" || outputEl.value === "csv");
  }

  function preferKafkaOutput() {
    if (serveAvailable && outputEl.value !== "kafka") {
      outputEl.value = "kafka";
    }
  }

  // Numeric "new this session": the dedup/publish count when known, otherwise
  // the raw collected count. Single source of truth so the "New" stat and the
  // "X of Y target" progress line can never disagree.
  function sessionNewCount() {
    return session.newCount != null ? session.newCount : session.found || 0;
  }

  // "New (this session)" figure for the stats grid. Dash before a run.
  function sessionNewDisplay() {
    if (session.startedAt == null) return "—";
    return formatCount(sessionNewCount());
  }

  // Repaint the three stat numbers (Saved / New / Total). `loading` shows a
  // spinner-ish "…" for the profile total while it is still being fetched.
  function renderStats(loading) {
    if (statSaved) {
      if (!serveAvailable) {
        statSaved.textContent = "—";
      } else {
        statSaved.textContent =
          profileState.saved != null ? formatCount(profileState.saved) : "…";
      }
    }
    if (statNew) statNew.textContent = sessionNewDisplay();
    if (statTotal) {
      if (profileState.total != null) {
        statTotal.textContent = formatCount(profileState.total);
        prefillMaxFromTotal();
      } else {
        statTotal.textContent = loading ? "…" : "—";
      }
    }
  }

  // Secondary session line: target progress + skipped/recover/resume notes.
  function renderSessionExtra() {
    if (!sessionExtra) return;
    var bits = [];
    if (session.startedAt != null) {
      bits.push(
        formatCount(sessionNewCount()) + " of " + formatCount(session.max) + " target"
      );
    }
    if (session.skippedCount != null && session.skippedCount > 0) {
      bits.push(formatCount(session.skippedCount) + " already saved");
    }
    if (session.scrolled > 0) {
      bits.push(formatCount(session.scrolled) + " scrolled past");
    }
    if (session.resumePending) bits.push("seeking resume…");
    if (session.recovering) bits.push("recovering…");
    sessionExtra.textContent = bits.join(" · ");
    sessionExtra.style.display = bits.length ? "block" : "none";
  }

  // Kept name for existing call sites; now refreshes the unified stats grid
  // and the secondary session line instead of a standalone dedupe row.
  function renderDedupeLine() {
    renderStats();
    renderSessionExtra();
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function stopReasonHint(meta) {
    if (!meta || !meta.stop_reason) return "";
    if (meta.stop_reason === "pagination_stuck") {
      return " Pagination stuck — scroll manually, then scrape again.";
    }
    if (meta.stop_reason === "resume_not_found") {
      return " Resume marker not found — continued from top (reload /answers if stuck).";
    }
    if (meta.stop_reason === "max_reached") return "";
    return " Stopped: " + meta.stop_reason + ".";
  }

  function download(filename, text, mime) {
    var blob = new Blob([text], { type: mime });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function resetSessionUI() {
    session.active = false;
    session.startedAt = null;
    session.collectingSince = null;
    session.scrapeElapsedMs = null;
    session.found = 0;
    session.scrolled = 0;
    session.max = parseInt(maxEl.value, 10) || 100;
    session.recovering = false;
    session.resumePending = false;
    session.newCount = null;
    session.skippedCount = null;
    session.skippedMongo = null;
    if (session.intervalId) {
      clearInterval(session.intervalId);
      session.intervalId = null;
    }
    if (statsBlock) statsBlock.classList.remove("session-active");
    if (sessionElapsed) sessionElapsed.textContent = "0:00";
    if (sessionRate) sessionRate.textContent = "";
    if (sessionStarted) sessionStarted.textContent = "";
    if (sessionEta) sessionEta.textContent = "";
    renderDedupeLine();
  }

  function applyClassifyReport(report) {
    session.newCount = report.new_count || 0;
    session.skippedCount = report.skipped_count || 0;
    session.skippedMongo = report.skipped_mongo || 0;
    renderDedupeLine();
    if (session.active) renderProfilePanel(false);
  }

  function answerSlug(url) {
    if (!url) return "";
    var m = String(url).match(/\/answer\/([^/?#]+)/);
    return m ? m[1] : "";
  }

  function rowsMatchingNew(allRows, newItems) {
    var byUrl = {};
    var bySlug = {};
    (allRows || []).forEach(function (row) {
      var url = row.answer_url || row.url;
      if (url) byUrl[url] = row;
      var slug = answerSlug(url);
      if (slug) bySlug[slug] = row;
    });

    return (newItems || [])
      .map(function (item) {
        if (byUrl[item.url]) return byUrl[item.url];
        var slug = answerSlug(item.url);
        if (slug && bySlug[slug]) return bySlug[slug];
        return {
          url: item.url,
          answer_url: item.url,
          question_title: item.question_title || "",
          question_url: item.question_url || "",
          answer_preview: item.answer_preview || "",
          seen_at: item.seen_at || new Date().toISOString(),
        };
      })
      .filter(function (row) {
        return row && (row.answer_url || row.url);
      });
  }

  function renderSession() {
    if (!session.active || !session.startedAt) return;
    var elapsed = Date.now() - session.startedAt;
    var rateElapsed = sessionRateElapsedMs();
    if (sessionElapsed) sessionElapsed.textContent = formatDuration(elapsed);
    var rateLabel = session.scrolled > 0 ? sessionThroughputRate() : sessionNewRate();
    if (sessionRate) sessionRate.textContent = rateLabel + "/min";
    if (sessionEta) {
      sessionEta.textContent =
        session.found >= session.max
          ? "ETA now"
          : "ETA " + formatEta(session.found, session.max, rateElapsed);
    }
    renderStats();
    renderSessionExtra();
  }

  function beginSession(maxResults) {
    resetSessionUI();
    session.active = true;
    session.startedAt = Date.now();
    session.collectingSince = null;
    session.scrapeElapsedMs = null;
    session.found = 0;
    session.scrolled = 0;
    session.max = maxResults;
    session.recovering = false;
    if (liveClassifyEnabled()) {
      session.newCount = 0;
      session.skippedCount = 0;
      session.skippedMongo = 0;
    } else {
      session.newCount = null;
      session.skippedCount = null;
      session.skippedMongo = null;
    }

    console.info("[qsbk] session started at", new Date(session.startedAt).toISOString());

    if (statsBlock) {
      statsBlock.classList.add("visible");
      statsBlock.classList.add("session-active");
    }
    if (sessionStarted) {
      sessionStarted.textContent = "Started " + formatLocalTime(session.startedAt);
    }
    if (sessionEta) sessionEta.textContent = "ETA calculating…";
    renderDedupeLine();
    renderSession();
    session.intervalId = setInterval(renderSession, 250);
  }

  function endSession() {
    session.active = false;
    if (session.intervalId) {
      clearInterval(session.intervalId);
      session.intervalId = null;
    }
    renderSession();
  }

  function sessionSummary() {
    if (!session.startedAt) return "";
    var elapsed = session.scrapeElapsedMs != null ? session.scrapeElapsedMs : Date.now() - session.startedAt;
    var rate = session.scrolled > 0 ? sessionThroughputRate() : sessionNewRate();
    return " · session " + formatDuration(elapsed) + " · " + rate + " answers/min";
  }

  function scheduleLiveClassify(rows) {
    if (contextDead || !extensionAlive()) return;
    if (!liveClassifyEnabled() || !rows || !rows.length || !session.active) return;
    if (classifyTimer) clearTimeout(classifyTimer);
    classifyTimer = setTimeout(function () {
      classifyTimer = null;
      if (classifyInFlight || !session.active || contextDead) return;
      classifyInFlight = true;
      checkAnswersWithServe(rows)
        .then(function (report) {
          applyClassifyReport(report);
          renderSession();
        })
        .catch(function (err) {
          if (isContextInvalidated(err)) {
            handleDeadContext();
          } else {
            console.warn("[qsbk] live classify:", err.message || err);
          }
        })
        .finally(function () {
          classifyInFlight = false;
        });
    }, 450);
  }

  chrome.runtime.onMessage.addListener(function (msg) {
    if (msg.type !== "progress" || !session.active) return;
    session.found = msg.newFound != null ? msg.newFound : msg.found || 0;
    session.scrolled = msg.scrolled || 0;
    session.recovering = !!msg.recovering;
    session.resumePending = !!msg.resumePending;
    if (!session.resumePending && !session.collectingSince) {
      session.collectingSince = Date.now();
    }
    if (msg.streamed) {
      session.newCount = msg.published || 0;
      renderDedupeLine();
    }
    renderSession();
    if (session.resumePending) {
      setStatus("Fast-scrolling to last saved answer…");
    } else if (session.recovering) {
      setStatus("Pagination slow — nudging scroll…");
    } else if (msg.streamed) {
      setStatus(
        "Collecting + publishing… " +
          formatCount(msg.published || 0) +
          " sent / " +
          formatCount(msg.found || 0) +
          " collected"
      );
    } else {
      setStatus("Collecting new answers…");
    }
    if (msg.rows && msg.rows.length) scheduleLiveClassify(msg.rows);
  });

  function isAnswersPage(url) {
    return !!(url && url.indexOf("quora.com") !== -1 && url.indexOf("/answers") !== -1);
  }

  function readProfileCursor(profileUrl) {
    return new Promise(function (resolve) {
      chrome.storage.local.get([PROFILE_CURSOR_KEY], function (data) {
        var cursors = (data && data[PROFILE_CURSOR_KEY]) || {};
        resolve(cursors[profileUrl] || null);
      });
    });
  }

  function clearProfileCursor(profileUrl) {
    if (!profileUrl) return;
    chrome.storage.local.get([PROFILE_CURSOR_KEY], function (data) {
      var cursors = (data && data[PROFILE_CURSOR_KEY]) || {};
      delete cursors[profileUrl];
      var out = {};
      out[PROFILE_CURSOR_KEY] = cursors;
      chrome.storage.local.set(out);
    });
  }

  function writeProfileCursor(profileUrl, deepestUrl, deepestKey) {
    if (!profileUrl || !deepestUrl) return;
    chrome.storage.local.get([PROFILE_CURSOR_KEY], function (data) {
      var cursors = (data && data[PROFILE_CURSOR_KEY]) || {};
      cursors[profileUrl] = {
        afterUrl: deepestUrl,
        afterKey: deepestKey || answerSlug(deepestUrl),
        updatedAt: Date.now(),
      };
      chrome.storage.local.set({ qsbkProfileCursor: cursors });
    });
  }

  function profileUrlFromAnswers(url) {
    try {
      var u = new URL(url);
      u.pathname = u.pathname.replace(/\/answers\/?.*$/, "");
      u.search = "";
      u.hash = "";
      return u.href;
    } catch (e) {
      return null;
    }
  }

  // The raw profile slug from /profile/<slug>(/answers). Kept URL-encoded here;
  // profile_name decodes it for readability.
  function profileSlugFromUrl(url) {
    try {
      var u = new URL(url);
      var m = u.pathname.match(/\/profile\/([^/]+)/);
      return m ? m[1] : "";
    } catch (e) {
      return "";
    }
  }

  // Derive the readable profile identity stamped onto every answer payload.
  // The collection name is NOT computed here: serve derives a stable userid
  // (hash of the canonical profile_url) server-side and the subscriber routes
  // by that. We just send the canonical /profile/<slug> URL + readable fields.
  function buildProfileIdentity(tabUrl, total) {
    var profileUrl = profileUrlFromAnswers(tabUrl);
    var slug = profileSlugFromUrl(profileUrl || tabUrl);
    var name = slug;
    try {
      name = decodeURIComponent(slug);
    } catch (e) {
      /* keep raw slug */
    }
    var ident = {};
    if (name) ident.profile_name = name;
    if (profileUrl) ident.profile_url = profileUrl;
    if (total != null && !isNaN(total)) {
      ident.profile_answer_count = Math.floor(total);
    }
    return ident;
  }

  function waitForTabLoad(tabId, timeoutMs) {
    return new Promise(function (resolve, reject) {
      chrome.tabs.get(tabId, function (tab) {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (tab && tab.status === "complete") {
          resolve();
          return;
        }
        var timeout = setTimeout(function () {
          chrome.tabs.onUpdated.removeListener(listener);
          reject(new Error("profile tab load timeout"));
        }, timeoutMs || 30000);
        function listener(id, info) {
          if (id === tabId && info.status === "complete") {
            clearTimeout(timeout);
            chrome.tabs.onUpdated.removeListener(listener);
            resolve();
          }
        }
        chrome.tabs.onUpdated.addListener(listener);
      });
    });
  }

  async function ensureScraper(tabId) {
    try {
      var pong = await chrome.tabs.sendMessage(tabId, { type: "ping" });
      if (pong && pong.ok) return;
    } catch (e) {
      /* not injected */
    }
    await chrome.scripting.executeScript({
      target: { tabId: tabId },
      files: ["scrape.js", "marks.js"],
    });
  }

  async function resolveTargetTab() {
    if (targetTabId) {
      try {
        var pinned = await chrome.tabs.get(targetTabId);
        if (pinned && pinned.id && isAnswersPage(pinned.url)) return pinned;
      } catch (e) {
        targetTabId = null;
      }
    }
    var tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs[0] && isAnswersPage(tabs[0].url)) return tabs[0];
    var quoraTabs = await chrome.tabs.query({ url: ["*://*.quora.com/*", "*://quora.com/*"] });
    for (var i = 0; i < quoraTabs.length; i++) {
      if (isAnswersPage(quoraTabs[i].url)) return quoraTabs[i];
    }
    return null;
  }

  // Auto-fill the Max input with the owner's total once it resolves. The total
  // is now the GraphQL/relay-derived owner answer_count (profileState.total),
  // so Max prefills with the SAME corrected number shown in the TOTAL stat.
  // One-shot per profile (the maxAutoFilled guard is reset on profile change in
  // fetchProfileTotal, so switching profiles re-prefills with the new owner's
  // total) so a later stats repaint never clobbers a value the user typed, and
  // never fights an in-progress session. Falls back to the HTML default (100)
  // until the total is known.
  function prefillMaxFromTotal() {
    if (maxAutoFilled || session.active) return;
    if (profileState.total == null || isNaN(profileState.total)) return;
    maxEl.value = String(Math.max(1, Math.floor(profileState.total)));
    maxAutoFilled = true;
  }

  function profileSavedDisplay() {
    if (!serveAvailable) return null;
    // "saved" = answers permanently persisted for THIS profile. It is polled
    // live (incl. during a scrape) so it ticks up as the backend drains the
    // queue. Shown as the green "Saved" stat.
    return profileState.saved;
  }

  function renderProfilePanel(loading) {
    if (statsBlock) statsBlock.classList.add("visible");
    renderStats(loading);
  }

  function hideProfilePanel() {
    if (statsBlock) statsBlock.classList.remove("visible");
    profileState.total = null;
    profileState.saved = null;
    activeProfileUrl = null;
    maxAutoFilled = false;
  }

  function readProfileCache(profileUrl) {
    return new Promise(function (resolve) {
      chrome.storage.local.get([PROFILE_CACHE_KEY], function (data) {
        var cache = (data && data[PROFILE_CACHE_KEY]) || {};
        var entry = cache[profileUrl];
        if (!entry || !entry.answers) return resolve(null);
        if (Date.now() - entry.fetchedAt > PROFILE_CACHE_TTL_MS) return resolve(null);
        resolve(entry.answers);
      });
    });
  }

  function writeProfileCache(profileUrl, total) {
    chrome.storage.local.get([PROFILE_CACHE_KEY], function (data) {
      var cache = (data && data[PROFILE_CACHE_KEY]) || {};
      cache[profileUrl] = { answers: total, fetchedAt: Date.now() };
      chrome.storage.local.set({ profileStatsCache: cache });
    });
  }

  // Ask the content script for the OWNER's identity + total, derived from the
  // page's GraphQL/relay data (DOM fallback inside the content script). Returns
  // the full info object so the popup can both scope SAVED to the owner's
  // canonical profile_url and set TOTAL from the GraphQL answer_count.
  async function readOwnerInfoFromTab(tabId) {
    try {
      await ensureScraper(tabId);
      var response = await chrome.tabs.sendMessage(tabId, { type: "getProfileInfo" });
      if (response && response.ok && response.info) return response.info;
    } catch (e) {
      /* ignore */
    }
    return null;
  }

  async function fetchProfileTotal(tab) {
    if (!tab || !tab.url) return null;
    // Canonical owner URL from the /answers tab. Used to scope SAVED until the
    // content script confirms the owner (the two derive identically).
    var ownerUrl = profileUrlFromAnswers(tab.url);
    if (!ownerUrl) return null;
    // On a profile change, drop the previous profile's numbers and the
    // one-shot prefill guard so we never SHOW or auto-fill another profile's
    // total while the new one is still loading. (profileState is module-level
    // and the embedded panel survives tab navigation, so it would otherwise
    // keep displaying a stale total.)
    if (ownerUrl !== activeProfileUrl) {
      profileState.total = null;
      profileState.saved = null;
      maxAutoFilled = false;
    }
    // Scope SAVED to THIS owner right away so the periodic saved poll never
    // reads the global ("answers") collection while we resolve the owner.
    activeProfileUrl = ownerUrl;

    // Prefer FRESHNESS on open: read the CURRENT active tab's GraphQL/relay
    // owner info first so a stale per-profile cache entry (or a TTL-window
    // count from before a new ingest) never wins over the live page.
    renderProfilePanel(true);
    var info = await readOwnerInfoFromTab(tab.id);
    if (info) {
      // Pin SAVED scoping to the owner the content script actually resolved.
      if (info.profile_url) {
        ownerUrl = info.profile_url;
        activeProfileUrl = info.profile_url;
      }
      if (info.answer_count != null) {
        profileState.total = info.answer_count;
        writeProfileCache(ownerUrl, info.answer_count);
        // Prefill Max with this GraphQL-derived owner total (one-shot per
        // profile; renderProfilePanel→renderStats also calls it).
        prefillMaxFromTotal();
        renderProfilePanel(false);
        // Re-fetch SAVED now that the owner is scoped (0 for a fresh profile).
        refreshProfileSaved();
        return info.answer_count;
      }
    }

    // Active tab couldn't yield a number (not loaded / relay+DOM both empty) —
    // fall back to THIS owner's own cached value (scoped per profile URL)
    // before the expensive background-tab fetch.
    var cached = await readProfileCache(ownerUrl);
    if (cached != null) {
      profileState.total = cached;
      renderProfilePanel(false);
      return cached;
    }

    var bgTab = null;
    try {
      bgTab = await chrome.tabs.create({ url: ownerUrl, active: false });
      await waitForTabLoad(bgTab.id);
      await sleep(1500);
      var bgInfo = await readOwnerInfoFromTab(bgTab.id);
      if (bgInfo && bgInfo.answer_count != null) {
        if (bgInfo.profile_url) {
          ownerUrl = bgInfo.profile_url;
          activeProfileUrl = bgInfo.profile_url;
        }
        profileState.total = bgInfo.answer_count;
        writeProfileCache(ownerUrl, bgInfo.answer_count);
        prefillMaxFromTotal();
        renderProfilePanel(false);
        refreshProfileSaved();
        return bgInfo.answer_count;
      }
    } catch (e) {
      /* ignore */
    } finally {
      if (bgTab && bgTab.id) {
        try {
          await chrome.tabs.remove(bgTab.id);
        } catch (e2) {
          /* ignore */
        }
      }
    }
    renderProfilePanel(false);
    return null;
  }

  function loadProfileTotal(tab) {
    if (!tab || !isAnswersPage(tab.url)) {
      hideProfilePanel();
      return Promise.resolve(null);
    }
    if (profileState.fetchPromise) return profileState.fetchPromise;
    profileState.fetchPromise = fetchProfileTotal(tab).finally(function () {
      profileState.fetchPromise = null;
    });
    return profileState.fetchPromise;
  }

  // Enable "Scrape this tab" ONLY when the active target tab is a Quora profile
  // /answers page. Otherwise grey it out and explain why. Never overrides the
  // mid-run disabled state (the click handler owns that while a session runs).
  function updateScrapeGate(tab) {
    if (!startBtn) return false;
    if (session.active) return false;
    var ok = !!(tab && isAnswersPage(tab.url));
    startBtn.disabled = !ok;
    startBtn.title = ok
      ? "Scrape this Quora /answers page"
      : "Open a Quora profile /answers page to enable scraping.";
    return ok;
  }

  // Re-resolve the active target tab, then re-gate the Scrape button and
  // (re)load the per-profile total when the resolved profile changed. Called on
  // popup open and whenever the active/updated tab changes.
  function refreshTargetTab(opts) {
    opts = opts || {};
    return resolveTargetTab()
      .then(function (tab) {
        if (!tab || !tab.id) {
          updateScrapeGate(null);
          if (!session.active) {
            hideProfilePanel();
            if (opts.announce) {
              setStatus("Open a Quora /answers tab, then click the qsbk icon.");
            } else {
              setStatus("Scrape disabled — open a Quora profile /answers page.");
            }
          }
          return null;
        }
        targetTabId = tab.id;
        updateScrapeGate(tab);
        if (!session.active) {
          var profileUrl = profileUrlFromAnswers(tab.url);
          if (
            !profileState.fetchPromise &&
            (profileUrl !== activeProfileUrl || profileState.total == null)
          ) {
            loadProfileTotal(tab);
          }
          if (opts.announce) setStatus("Ready — session stats reset.");
        }
        return tab;
      })
      .catch(function () {
        return null;
      });
  }

  var tabWatchTimer = null;
  function scheduleTabRefresh() {
    if (contextDead || !extensionAlive()) return;
    if (tabWatchTimer) clearTimeout(tabWatchTimer);
    tabWatchTimer = setTimeout(function () {
      tabWatchTimer = null;
      refreshTargetTab();
    }, 250);
  }

  function watchActiveTabChanges() {
    try {
      chrome.tabs.onActivated.addListener(scheduleTabRefresh);
      chrome.tabs.onUpdated.addListener(function (id, info) {
        if (info && (info.status === "complete" || info.url)) scheduleTabRefresh();
      });
    } catch (e) {
      /* tabs API unavailable — gate still evaluated on open */
    }
  }

  function configureServeUrls(base) {
    var urls = window.qsbkServeConfig.serveUrls(base);
    SERVE_BASE = urls.base;
    SERVE_HEALTH = urls.ping;
    SERVE_CHECK = urls.check;
    SERVE_UPSERT = urls.upsert;
    SERVE_KNOWN = urls.known;
  }

  async function fetchKnownCount() {
    if (!SERVE_KNOWN) return null;
    // SAVED must ALWAYS be the current owner's own persisted count. Until the
    // owner's canonical profile_url is resolved, send NO request — querying
    // /known without a profile_url makes serve fall back to the global
    // ("answers") collection (~16k from the initial backfill), which would
    // wrongly show as this profile's "saved". A never-ingested profile then
    // correctly reads 0 (its own empty collection), not the global count.
    if (!activeProfileUrl) return null;
    try {
      // Scope the "saved" count to the active profile's own collection, and ask
      // for the cheap count-only response so we never download the full
      // URL/hash arrays (a profile can hold ~16k URLs) on every poll.
      var knownUrl = window.qsbkServeConfig.knownUrl(SERVE_BASE, activeProfileUrl, {
        countOnly: true,
      });
      var response = await fetch(knownUrl, { cache: "no-store" });
      if (!response.ok) return null;
      var data = await response.json();
      return data && typeof data.count === "number" ? data.count : null;
    } catch (e) {
      return null;
    }
  }

  async function refreshProfileSaved() {
    // Poll the Mongo-persisted count periodically — INCLUDING during an active
    // session — so "saved" ticks up live as the subscriber drains Kafka→Mongo.
    if (!serveAvailable) {
      if (!session.active) profileState.saved = null;
      renderProfilePanel(false);
      return;
    }
    var count = await fetchKnownCount();
    if (count != null) profileState.saved = count;
    renderProfilePanel(false);
  }

  function loadServeConfig(cb) {
    window.qsbkServeConfig.getServeBase(function (base) {
      configureServeUrls(base);
      if (cb) cb(base);
    });
  }

  async function checkServeHealth() {
    try {
      var response = await fetch(SERVE_HEALTH, { cache: "no-store" });
      if (!response.ok) return false;
      var data = await response.json();
      return !!(data && data.ok);
    } catch (e) {
      return false;
    }
  }

  function kafkaOption() {
    return outputEl.querySelector('option[value="kafka"]');
  }

  function updateServeAvailability(available) {
    serveAvailable = available;
    var opt = kafkaOption();
    if (opt) {
      opt.disabled = !available;
      opt.textContent = available
        ? "Kafka (via qsbk serve)"
        : "Kafka (start qsbk serve first)";
    }
    if (!available && outputEl.value === "kafka") {
      outputEl.value = "json";
    } else if (available) {
      preferKafkaOutput();
    }
    if (serveStatusEl) {
      serveStatusEl.textContent = available
        ? "qsbk serve: online (" + SERVE_BASE + ")"
        : "qsbk serve: offline (" + SERVE_BASE + ")";
      serveStatusEl.className = available ? "serve-online" : "serve-offline";
    }
  }

  async function checkAnswersWithServe(rows, force, profileUrl) {
    var pu = profileUrl || activeProfileUrl;
    var batches = chunk(rowsForCheck(rows), SERVE_BATCH);
    var merged = {
      new_count: 0,
      skipped_count: 0,
      skipped_mongo: 0,
      new: [],
      skipped_urls: [],
    };
    for (var i = 0; i < batches.length; i++) {
      var body = { answers: batches[i], force: !!force };
      // Scope dedup to this profile's own collection (serve canonicalizes).
      if (pu) body.profile_url = pu;
      var response = await fetch(SERVE_CHECK, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(body),
      });
      var body = {};
      try {
        body = await response.json();
      } catch (e) {
        /* ignore */
      }
      if (!response.ok) {
        throw new Error(body.error || "Serve check failed (" + response.status + ")");
      }
      merged.new_count += body.new_count || 0;
      merged.skipped_count += body.skipped_count || 0;
      merged.skipped_mongo += body.skipped_mongo || 0;
      if (body.new && body.new.length) merged.new = merged.new.concat(body.new);
      if (body.skipped_urls && body.skipped_urls.length) {
        merged.skipped_urls = merged.skipped_urls.concat(body.skipped_urls);
      }
    }
    console.info(
      "[qsbk] POST /check",
      rows.length,
      "in (" + batches.length + " batch(es)) →",
      merged.new_count,
      "new,",
      merged.skipped_count,
      "skipped"
    );
    return merged;
  }

  async function refreshServeHealth() {
    if (contextDead) return;
    if (!extensionAlive()) {
      handleDeadContext();
      return;
    }
    try {
      updateServeAvailability(await checkServeHealth());
      await refreshProfileSaved();
    } catch (err) {
      if (isContextInvalidated(err)) handleDeadContext();
      else throw err;
    }
  }

  function startServeHealthPoll() {
    refreshServeHealth();
    if (healthPollId) clearInterval(healthPollId);
    healthPollId = setInterval(refreshServeHealth, HEALTH_POLL_MS);
  }

  function stopServeHealthPoll() {
    if (healthPollId) {
      clearInterval(healthPollId);
      healthPollId = null;
    }
  }

  async function publishNewToKafka(newRows, force, identity) {
    if (!newRows.length) {
      return { published: 0, skipped: 0, skipped_mongo: 0 };
    }
    return sendToKafka(newRows, force, identity);
  }

  async function sendToKafka(rows, force, identity) {
    var batches = chunk(rowsForServe(rows, identity), SERVE_BATCH);
    var totals = { published: 0, skipped: 0, skipped_mongo: 0, urls: [] };
    var profileUrl = (identity && identity.profile_url) || activeProfileUrl;
    console.info(
      "[qsbk] POST /upsert",
      rows.length,
      "answers in",
      batches.length,
      "batch(es)",
      force ? "(force)" : ""
    );
    for (var i = 0; i < batches.length; i++) {
      var body = { answers: batches[i], force: !!force };
      // Scope publish-side dedup to this profile's own collection.
      if (profileUrl) body.profile_url = profileUrl;
      var response = await fetch(SERVE_UPSERT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(body),
      });
      var body = {};
      try {
        body = await response.json();
      } catch (e) {
        /* ignore */
      }
      if (!response.ok) {
        throw new Error(body.error || "qsbk serve returned " + response.status);
      }
      totals.published += body.published || 0;
      totals.skipped += body.skipped || 0;
      totals.skipped_mongo += body.skipped_mongo || 0;
      if (body.urls && body.urls.length) totals.urls = totals.urls.concat(body.urls);
      if (session.active) {
        setStatus(
          "Publishing… " + totals.published + "/" + rows.length + " sent to Kafka"
        );
      }
    }
    console.info("[qsbk] /upsert done", totals);
    return totals;
  }

  async function initPanel() {
    resetSessionUI();
    var version =
      chrome.runtime && chrome.runtime.getManifest
        ? chrome.runtime.getManifest().version
        : null;
    var verEl = document.getElementById("ext-version");
    if (verEl && version) {
      verEl.textContent = "v" + version;
      verEl.style.cssText = "font-weight:400;font-size:11px;color:#6b7280;";
    }
    // Always-visible version (the drag-handle is hidden in embedded panel mode).
    var verFooter = document.getElementById("ext-version-footer");
    if (verFooter && version) {
      verFooter.textContent = "qsbk v" + version;
    }
    if (embedded && dragHandle) {
      dragHandle.classList.add("hidden");
    }
    // Start gated OFF until we confirm the active tab is a /answers page.
    updateScrapeGate(null);

    await new Promise(function (resolve) {
      loadServeConfig(resolve);
    });
    startServeHealthPoll();

    window.addEventListener("beforeunload", stopServeHealthPoll);

    var stored = await chrome.storage.session.get(["qsbkTargetTabId"]);
    targetTabId = stored.qsbkTargetTabId || null;

    watchActiveTabChanges();
    await refreshTargetTab({ announce: true });
  }

  startBtn.addEventListener("click", async function () {
    var tab = await resolveTargetTab();
    if (!tab || !tab.id) {
      setStatus("No Quora /answers tab found.");
      return;
    }
    if (!isAnswersPage(tab.url)) {
      setStatus("Target tab must be a Quora profile Answers page.");
      return;
    }

    var maxResults = parseInt(maxEl.value, 10) || 100;
    var output = outputEl.value;

    startBtn.disabled = true;
    beginSession(maxResults);
    setStatus("Connecting to tab…");

    try {
      await ensureScraper(tab.id);
      setStatus("Collecting answers…");

      var method = methodEl && methodEl.value === "scroll" ? "scroll" : "graphql";
      var force = !!(forceEl && forceEl.checked);
      // Stream publish: in API mode with Kafka output, the content script POSTs
      // /upsert in batches as it collects, instead of buffering everything and
      // publishing at the end. Survives interruptions and bounds memory.
      var streamPublish = method === "graphql" && output === "kafka" && serveAvailable;
      var profileUrl = profileUrlFromAnswers(tab.url);
      if (profileUrl) activeProfileUrl = profileUrl;
      var profileIdentity = buildProfileIdentity(tab.url, profileState.total);
      var cursor = profileUrl ? await readProfileCursor(profileUrl) : null;
      var response = await chrome.tabs.sendMessage(tab.id, {
        type: "startScrape",
        mode: method,
        maxResults: maxResults,
        skipKnown: serveAvailable && !force,
        resumeAfterKey: force ? null : cursor && cursor.afterKey ? cursor.afterKey : null,
        serveUpsertUrl: streamPublish ? SERVE_UPSERT : null,
        force: force,
        profile_name: profileIdentity.profile_name || null,
        profile_url: profileIdentity.profile_url || null,
        profile_answer_count:
          profileIdentity.profile_answer_count != null
            ? profileIdentity.profile_answer_count
            : null,
      });

      if (!response || !response.ok) {
        setStatus((response && response.error) || "Scrape failed — reload the Quora tab.");
        return;
      }

      var rows = response.rows || [];
      var meta = response.meta || {};

      // Streamed publish: the content script already pushed everything to Kafka
      // (rows comes back empty). Report the published totals and finish.
      if (meta.streamed) {
        session.found = meta.collected || 0;
        session.newCount = meta.published || 0;
        session.scrolled = meta.skipped_known || 0;
        session.scrapeElapsedMs = sessionRateElapsedMs();
        renderDedupeLine();
        renderSession();
        await refreshProfileSaved();
        var errNote =
          meta.publish_errors > 0 ? " (" + meta.publish_errors + " batch error(s))" : "";
        setStatus(
          "Session done — published " +
            formatCount(meta.published || 0) +
            " of " +
            formatCount(meta.collected || 0) +
            " collected to Kafka" +
            (meta.skipped_known ? ", skipped " + formatCount(meta.skipped_known) + " known" : "") +
            errNote +
            sessionSummary() +
            stopReasonHint(meta)
        );
        console.info("[qsbk] streamed session finished", meta);
        return;
      }

      session.found = rows.length;
      session.scrolled = meta.skipped_known || session.scrolled || 0;
      session.scrapeElapsedMs = sessionRateElapsedMs();
      renderSession();

      if (!rows.length) {
        if (meta.stop_reason === "resume_not_found" && profileUrl) {
          clearProfileCursor(profileUrl);
        }
        if (meta.skipped_known > 0 || meta.stop_reason === "pagination_stuck") {
          setStatus(
            "No new answers this run — scrolled " +
              formatCount(meta.skipped_known || 0) +
              " saved, pagination stalled." +
              stopReasonHint(meta) +
              sessionSummary() +
              " Reload /answers, scroll manually, then scrape again."
          );
        } else {
          setStatus("No answers found. Are you logged in?" + sessionSummary());
        }
        return;
      }

      if (meta.stop_reason === "resume_not_found" && profileUrl) {
        clearProfileCursor(profileUrl);
      }

      var elapsedMs = session.scrapeElapsedMs;
      meta.session_started_at = new Date(session.startedAt).toISOString();
      meta.session_elapsed_ms = elapsedMs;
      meta.session_elapsed_human = formatDuration(elapsedMs);
      meta.session_answers_per_minute = parseFloat(
        session.scrolled > 0 ? sessionThroughputRate() : sessionNewRate()
      );
      meta.session_collected = rows.length;
      meta.session_skipped_known = session.scrolled;
      meta.session_max = maxResults;

      var exportRows = rows;
      var classify = null;

      if (output === "kafka" && !serveAvailable) {
        setStatus("Kafka requires qsbk serve — run: qsbk serve");
        return;
      }

      if (serveAvailable || output === "kafka") {
        setStatus("Checking answers with qsbk serve…");
        classify = await checkAnswersWithServe(rows, force, profileUrl);
        applyClassifyReport(classify);
        exportRows = rowsMatchingNew(rows, classify.new || []);
        meta.session_new_count = classify.new_count;
        meta.session_skipped_count = classify.skipped_count;
        meta.session_skipped_mongo = classify.skipped_mongo;
      }

      var stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      var base = "qsbk-answers-" + stamp;
      var destLabel = "";
      if (output === "json") {
        download(base + ".json", toJsonDocument(exportRows, meta, tab.url), "application/json");
        destLabel = serveAvailable
          ? "JSON (" + exportRows.length + " new, " + (classify.skipped_count || 0) + " skipped)"
          : "JSON (" + exportRows.length + " rows)";
      } else if (output === "csv") {
        download(base + ".csv", toCsv(exportRows), "text/csv");
        destLabel = serveAvailable
          ? "CSV (" + exportRows.length + " new, " + (classify.skipped_count || 0) + " skipped)"
          : "CSV (" + exportRows.length + " rows)";
      } else if (output === "kafka") {
        if (exportRows.length) {
          setStatus("Sending " + exportRows.length + " new answers to Kafka…");
          var publishReport = await publishNewToKafka(exportRows, force, profileIdentity);
          if (publishReport.published != null) {
            meta.session_new_count = publishReport.published;
            session.newCount = publishReport.published;
            renderDedupeLine();
          }
          await refreshProfileSaved();
        }
        destLabel =
          "Kafka (" +
          (meta.session_new_count != null ? meta.session_new_count : 0) +
          " new, " +
          (meta.session_skipped_count || 0) +
          " skipped)";
      }

      if (
        profileUrl &&
        meta.deepest_url &&
        rows.length > 0 &&
        meta.stop_reason !== "pagination_stuck"
      ) {
        writeProfileCursor(profileUrl, meta.deepest_url, meta.deepest_key);
      }

      var collectedLabel =
        meta.skip_known && meta.skipped_known
          ? rows.length + " new (" + formatCount(meta.skipped_known) + " already saved, skipped)"
          : rows.length + " collected";

      setStatus(
        "Session done — " +
          collectedLabel +
          " → " +
          destLabel +
          sessionSummary() +
          stopReasonHint(meta)
      );

      console.info("[qsbk] session finished", {
        collected: rows.length,
        output: output,
        elapsed_ms: elapsedMs,
        stop_reason: meta.stop_reason,
      });
    } catch (err) {
      setStatus("Error: " + (err.message || err));
      console.error("[qsbk] session error:", err);
    } finally {
      if (classifyTimer) {
        clearTimeout(classifyTimer);
        classifyTimer = null;
      }
      endSession();
      await refreshProfileSaved();
      // Re-enable respecting the is-answers-page gate so we never leave a
      // non-/answers tab with an active Scrape button after a run finishes.
      updateScrapeGate(await resolveTargetTab());
    }
  });

  if (runMinBtn) {
    runMinBtn.addEventListener("click", async function () {
      var tab = await resolveTargetTab();
      if (!tab || !tab.id) {
        setStatus("No Quora /answers tab to move to a background window.");
        return;
      }
      runMinBtn.disabled = true;
      try {
        // chrome.windows from this embedded iframe can be unreliable, so route
        // the detach through the service worker. It moves the Quora tab into
        // its own minimized, unfocused window; the in-page panel rides along,
        // so an in-flight scrape keeps running out of the way.
        var resp = await chrome.runtime.sendMessage({
          type: "runMinimized",
          tabId: tab.id,
        });
        if (resp && resp.ok) {
          setStatus("Moved to a minimized background window — scraping keeps running there.");
        } else {
          setStatus("Could not minimize: " + ((resp && resp.error) || "unknown error"));
        }
      } catch (err) {
        if (isContextInvalidated(err)) {
          handleDeadContext();
        } else {
          setStatus("Could not minimize: " + (err.message || err));
        }
      } finally {
        runMinBtn.disabled = false;
      }
    });
  }

  initPanel();
})();
