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

  function rowsForServe(rows) {
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
  var sessionPanel = document.getElementById("session-panel");
  var sessionElapsed = document.getElementById("session-elapsed");
  var sessionDetail = document.getElementById("session-detail");
  var sessionDedupe = document.getElementById("session-dedupe");
  var sessionStarted = document.getElementById("session-started");
  var sessionEta = document.getElementById("session-eta");
  var profilePanel = document.getElementById("profile-panel");
  var profileTotalEl = document.getElementById("profile-total");
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

  function dedupeSummary() {
    if (session.newCount == null && session.skippedCount == null) return "";
    return session.newCount + " new · " + session.skippedCount + " skipped (MongoDB)";
  }

  function renderDedupeLine() {
    if (!sessionDedupe) return;
    var text = dedupeSummary();
    sessionDedupe.textContent = text;
    sessionDedupe.style.display = text ? "block" : "none";
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
    sessionPanel.classList.remove("active");
    sessionElapsed.textContent = "0:00";
    sessionDetail.textContent = "0 new / " + session.max + " · 0.0/min";
    sessionStarted.textContent = "";
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
    sessionElapsed.textContent = formatDuration(elapsed);
    var rateLabel = session.scrolled > 0 ? sessionThroughputRate() : sessionNewRate();
    var detail =
      session.found +
      " new / " +
      session.max +
      " · " +
      rateLabel +
      "/min";
    if (session.scrolled > 0) detail += " · " + formatCount(session.scrolled) + " skipped";
    if (session.resumePending) detail += " · seeking resume…";
    if (session.recovering) detail += " · recovering…";
    sessionDetail.textContent = detail;
    if (sessionEta) {
      sessionEta.textContent =
        session.found >= session.max
          ? "ETA now"
          : "ETA " + formatEta(session.found, session.max, rateElapsed);
    }
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

    sessionPanel.classList.add("active");
    sessionStarted.textContent = "Started " + formatLocalTime(session.startedAt);
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
    renderSession();
    if (session.resumePending) {
      setStatus("Fast-scrolling to last saved answer…");
    } else if (session.recovering) {
      setStatus("Pagination slow — nudging scroll…");
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

  function applyProfileTotalToMax() {
    if (profileState.total == null || isNaN(profileState.total)) return;
    var n = Math.max(1, Math.floor(profileState.total));
    maxEl.value = String(n);
    setStatus("Max set to " + n + " (profile total)");
  }

  function profileSavedDisplay() {
    if (!serveAvailable) return null;
    if (session.active && session.skippedCount != null) return session.skippedCount;
    return profileState.saved;
  }

  function renderProfilePanel(loading) {
    profilePanel.classList.add("visible");
    if (loading && profileState.total == null) {
      profileTotalEl.textContent = "Profile answer count…";
      return;
    }
    var chunks = [];
    if (profileState.total != null) {
      chunks.push(
        '<span class="profile-total-num" title="Click to set max answers">' +
          formatCount(profileState.total) +
          "</span> on Quora"
      );
    } else if (!loading) {
      chunks.push("Profile count unavailable");
    }
    var saved = profileSavedDisplay();
    if (serveAvailable) {
      var savedText = saved != null ? formatCount(saved) + " saved" : "… saved";
      chunks.push(
        '<span class="profile-saved" title="Already in MongoDB">' + savedText + "</span>"
      );
    }
    if (!chunks.length) {
      profileTotalEl.textContent = loading ? "Profile answer count…" : "—";
      return;
    }
    profileTotalEl.innerHTML = chunks.join(" · ");
  }

  function hideProfilePanel() {
    profilePanel.classList.remove("visible");
    profileState.total = null;
    profileState.saved = null;
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

  async function readStatsFromTab(tabId) {
    try {
      await ensureScraper(tabId);
      var response = await chrome.tabs.sendMessage(tabId, { type: "getProfileStats" });
      if (response && response.ok && response.stats && response.stats.answers != null) {
        return response.stats.answers;
      }
    } catch (e) {
      /* ignore */
    }
    return null;
  }

  async function fetchProfileTotal(tab) {
    if (!tab || !tab.url) return null;
    var profileUrl = profileUrlFromAnswers(tab.url);
    if (!profileUrl) return null;

    var cached = await readProfileCache(profileUrl);
    if (cached != null) {
      profileState.total = cached;
      renderProfilePanel(false);
      return cached;
    }

    renderProfilePanel(true);
    var fromActive = await readStatsFromTab(tab.id);
    if (fromActive != null) {
      profileState.total = fromActive;
      writeProfileCache(profileUrl, fromActive);
      renderProfilePanel(false);
      return fromActive;
    }

    var bgTab = null;
    try {
      bgTab = await chrome.tabs.create({ url: profileUrl, active: false });
      await waitForTabLoad(bgTab.id);
      await sleep(1500);
      var total = await readStatsFromTab(bgTab.id);
      if (total != null) {
        profileState.total = total;
        writeProfileCache(profileUrl, total);
        renderProfilePanel(false);
        return total;
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
    try {
      var response = await fetch(SERVE_KNOWN, { cache: "no-store" });
      if (!response.ok) return null;
      var data = await response.json();
      return data && typeof data.count === "number" ? data.count : null;
    } catch (e) {
      return null;
    }
  }

  async function refreshProfileSaved() {
    if (!serveAvailable) {
      if (!session.active) profileState.saved = null;
      renderProfilePanel(false);
      return;
    }
    if (session.active && session.skippedCount != null) {
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

  async function checkAnswersWithServe(rows, force) {
    var batches = chunk(rowsForCheck(rows), SERVE_BATCH);
    var merged = {
      new_count: 0,
      skipped_count: 0,
      skipped_mongo: 0,
      new: [],
      skipped_urls: [],
    };
    for (var i = 0; i < batches.length; i++) {
      var response = await fetch(SERVE_CHECK, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ answers: batches[i], force: !!force }),
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

  async function publishNewToKafka(newRows, force) {
    if (!newRows.length) {
      return { published: 0, skipped: 0, skipped_mongo: 0 };
    }
    return sendToKafka(newRows, force);
  }

  async function sendToKafka(rows, force) {
    var batches = chunk(rowsForServe(rows), SERVE_BATCH);
    var totals = { published: 0, skipped: 0, skipped_mongo: 0, urls: [] };
    console.info(
      "[qsbk] POST /upsert",
      rows.length,
      "answers in",
      batches.length,
      "batch(es)",
      force ? "(force)" : ""
    );
    for (var i = 0; i < batches.length; i++) {
      var response = await fetch(SERVE_UPSERT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ answers: batches[i], force: !!force }),
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

  profileTotalEl.addEventListener("click", function (ev) {
    if (ev.target && ev.target.classList.contains("profile-total-num")) {
      applyProfileTotalToMax();
    }
  });

  async function initPanel() {
    resetSessionUI();
    var verEl = document.getElementById("ext-version");
    if (verEl && chrome.runtime && chrome.runtime.getManifest) {
      verEl.textContent = "v" + chrome.runtime.getManifest().version;
      verEl.style.cssText = "font-weight:400;font-size:11px;color:#6b7280;";
    }
    if (embedded && dragHandle) {
      dragHandle.classList.add("hidden");
    }
    await new Promise(function (resolve) {
      loadServeConfig(resolve);
    });
    startServeHealthPoll();

    window.addEventListener("beforeunload", stopServeHealthPoll);

    var stored = await chrome.storage.session.get(["qsbkTargetTabId"]);
    targetTabId = stored.qsbkTargetTabId || null;

    var tab = await resolveTargetTab();
    if (!tab || !tab.id) {
      hideProfilePanel();
      setStatus("Open a Quora /answers tab, then click the qsbk icon.");
      return;
    }
    targetTabId = tab.id;
    setStatus("Ready — session stats reset.");
    loadProfileTotal(tab);
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
      var profileUrl = profileUrlFromAnswers(tab.url);
      var cursor = profileUrl ? await readProfileCursor(profileUrl) : null;
      var response = await chrome.tabs.sendMessage(tab.id, {
        type: "startScrape",
        mode: method,
        maxResults: maxResults,
        skipKnown: serveAvailable && !force,
        resumeAfterKey: force ? null : cursor && cursor.afterKey ? cursor.afterKey : null,
      });

      if (!response || !response.ok) {
        setStatus((response && response.error) || "Scrape failed — reload the Quora tab.");
        return;
      }

      var rows = response.rows || [];
      var meta = response.meta || {};
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
        classify = await checkAnswersWithServe(rows, force);
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
          var publishReport = await publishNewToKafka(exportRows, force);
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
      startBtn.disabled = false;
    }
  });

  initPanel();
})();
