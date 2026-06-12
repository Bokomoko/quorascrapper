/** qsbk control panel — movable window, session-scoped stats. */
(function () {
  var SERVE_BASE = "";
  var SERVE_HEALTH = "";
  var SERVE_CHECK = "";
  var SERVE_UPSERT = "";
  var HEALTH_POLL_MS = 4000;
  var embedded = /[?&]embedded=1/.test(location.search);
  var PROFILE_CACHE_KEY = "profileStatsCache";
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

  function rowsForServe(rows) {
    return rows.map(function (row) {
      var out = { url: row.answer_url || row.url };
      if (row.question_title) out.question_title = row.question_title;
      if (row.question_url) out.question_url = row.question_url;
      if (row.answer_preview) out.answer_preview = row.answer_preview;
      if (row.seen_at) out.seen_at = row.seen_at;
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
    return String(n);
  }

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  var statusEl = document.getElementById("status");
  var maxEl = document.getElementById("max");
  var outputEl = document.getElementById("output");
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

  var profileState = {
    total: null,
    fetchPromise: null,
  };

  var session = {
    active: false,
    startedAt: null,
    intervalId: null,
    found: 0,
    max: 100,
    recovering: false,
    newCount: null,
    skippedCount: null,
    skippedMongo: null,
  };

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
    session.found = 0;
    session.max = parseInt(maxEl.value, 10) || 100;
    session.recovering = false;
    session.newCount = null;
    session.skippedCount = null;
    session.skippedMongo = null;
    if (session.intervalId) {
      clearInterval(session.intervalId);
      session.intervalId = null;
    }
    sessionPanel.classList.remove("active");
    sessionElapsed.textContent = "0:00";
    sessionDetail.textContent = "0 / " + session.max + " · 0.0 answers/min";
    sessionStarted.textContent = "";
    if (sessionEta) sessionEta.textContent = "";
    renderDedupeLine();
  }

  function applyClassifyReport(report) {
    session.newCount = report.new_count || 0;
    session.skippedCount = report.skipped_count || 0;
    session.skippedMongo = report.skipped_mongo || 0;
    renderDedupeLine();
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
    sessionElapsed.textContent = formatDuration(elapsed);
    sessionDetail.textContent =
      session.found +
      " / " +
      session.max +
      " · " +
      formatRate(session.found, elapsed) +
      " answers/min" +
      (session.recovering ? " · recovering…" : "");
    if (sessionEta) {
      sessionEta.textContent =
        session.found >= session.max
          ? "ETA now"
          : "ETA " + formatEta(session.found, session.max, elapsed);
    }
  }

  function beginSession(maxResults) {
    resetSessionUI();
    session.active = true;
    session.startedAt = Date.now();
    session.found = 0;
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

  function sessionSummary(found) {
    if (!session.startedAt) return "";
    var elapsed = Date.now() - session.startedAt;
    return (
      " · session " +
      formatDuration(elapsed) +
      " · " +
      formatRate(found, elapsed) +
      " answers/min"
    );
  }

  function scheduleLiveClassify(rows) {
    if (!liveClassifyEnabled() || !rows || !rows.length || !session.active) return;
    if (classifyTimer) clearTimeout(classifyTimer);
    classifyTimer = setTimeout(function () {
      classifyTimer = null;
      if (classifyInFlight || !session.active) return;
      classifyInFlight = true;
      checkAnswersWithServe(rows)
        .then(function (report) {
          applyClassifyReport(report);
          renderSession();
        })
        .catch(function (err) {
          console.warn("[qsbk] live classify:", err.message || err);
        })
        .finally(function () {
          classifyInFlight = false;
        });
    }, 450);
  }

  chrome.runtime.onMessage.addListener(function (msg) {
    if (msg.type !== "progress" || !session.active) return;
    session.found = msg.found || 0;
    session.recovering = !!msg.recovering;
    renderSession();
    setStatus(session.recovering ? "Pagination slow — nudging scroll…" : "Collecting answers…");
    if (msg.rows && msg.rows.length) scheduleLiveClassify(msg.rows);
  });

  function isAnswersPage(url) {
    return !!(url && url.indexOf("quora.com") !== -1 && url.indexOf("/answers") !== -1);
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
    var n = Math.max(1, Math.min(5000, Math.floor(profileState.total)));
    maxEl.value = String(n);
    setStatus("Max set to " + n + " (profile total)");
  }

  function setProfileTotalDisplay(total, loading) {
    profilePanel.classList.add("visible");
    if (loading) {
      profileTotalEl.textContent = "Profile answer count…";
      return;
    }
    if (total != null) {
      profileTotalEl.innerHTML =
        'Profile total: <span class="profile-total-num" title="Click to set max answers">' +
        formatCount(total) +
        "</span> answers";
      return;
    }
    profileTotalEl.textContent = "Profile answer count unavailable";
  }

  function hideProfilePanel() {
    profilePanel.classList.remove("visible");
    profileState.total = null;
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
      setProfileTotalDisplay(cached, false);
      return cached;
    }

    setProfileTotalDisplay(null, true);
    var fromActive = await readStatsFromTab(tab.id);
    if (fromActive != null) {
      profileState.total = fromActive;
      writeProfileCache(profileUrl, fromActive);
      setProfileTotalDisplay(fromActive, false);
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
        setProfileTotalDisplay(total, false);
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
    setProfileTotalDisplay(null, false);
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

  async function checkAnswersWithServe(rows) {
    var response = await fetch(SERVE_CHECK, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ answers: rowsForServe(rows) }),
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
    console.info("[qsbk] POST /check", rows.length, "in →", body.new_count, "new,", body.skipped_count, "skipped");
    return body;
  }

  async function refreshServeHealth() {
    updateServeAvailability(await checkServeHealth());
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

  async function publishNewToKafka(newRows) {
    if (!newRows.length) {
      return { published: 0, skipped: 0, skipped_mongo: 0 };
    }
    return sendToKafka(newRows);
  }

  async function sendToKafka(rows) {
    var payload = rowsForServe(rows);
    console.info("[qsbk] POST /upsert", payload.length, "new answers");
    var response = await fetch(SERVE_UPSERT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ answers: payload }),
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
    console.info("[qsbk] /upsert response", body);
    return body;
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

      var response = await chrome.tabs.sendMessage(tab.id, {
        type: "startScrape",
        maxResults: maxResults,
      });

      if (!response || !response.ok) {
        setStatus((response && response.error) || "Scrape failed — reload the Quora tab.");
        return;
      }

      var rows = response.rows || [];
      var meta = response.meta || {};
      session.found = rows.length;
      renderSession();

      if (!rows.length) {
        setStatus("No answers found. Are you logged in?" + sessionSummary(0));
        return;
      }

      var elapsedMs = Date.now() - session.startedAt;
      meta.session_started_at = new Date(session.startedAt).toISOString();
      meta.session_elapsed_ms = elapsedMs;
      meta.session_elapsed_human = formatDuration(elapsedMs);
      meta.session_answers_per_minute = parseFloat(formatRate(rows.length, elapsedMs));
      meta.session_collected = rows.length;
      meta.session_max = maxResults;

      var exportRows = rows;
      var classify = null;

      if (output === "kafka" && !serveAvailable) {
        setStatus("Kafka requires qsbk serve — run: qsbk serve");
        return;
      }

      if (serveAvailable || output === "kafka") {
        setStatus("Checking answers with qsbk serve…");
        classify = await checkAnswersWithServe(rows);
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
          var publishReport = await publishNewToKafka(exportRows);
          if (publishReport.published != null) {
            meta.session_new_count = publishReport.published;
            session.newCount = publishReport.published;
            renderDedupeLine();
          }
        }
        destLabel =
          "Kafka (" +
          (meta.session_new_count != null ? meta.session_new_count : 0) +
          " new, " +
          (meta.session_skipped_count || 0) +
          " skipped)";
      }

      setStatus(
        "Session done — " +
          rows.length +
          " collected → " +
          destLabel +
          sessionSummary(rows.length) +
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
      startBtn.disabled = false;
    }
  });

  initPanel();
})();
