/** qsbk content script — self-contained, no ES modules. */
(function () {
  if (window.__qsbkScrapeLoaded) return;
  window.__qsbkScrapeLoaded = true;

  var SCROLL_PAUSE_MS = 1500;
  var FAST_SCROLL_PAUSE_MS = 450;
  var STAGNANT_LIMIT = 10;
  var RESUME_STAGNANT_LIMIT = 24;
  var RECOVERY_BURST = 3;
  var MAX_RECOVERY_ROUNDS = 6;
  var PRUNE_ENABLED = false;
  var running = false;

  function sleep(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function normalizeAnswerUrl(href, baseUrl) {
    if (!href || href.indexOf("/answer/") === -1) return null;
    try {
      var u = new URL(href, baseUrl);
      u.hash = "";
      u.search = "";
      return u.href;
    } catch (e) {
      return null;
    }
  }

  function normalizeQuestionUrl(href, baseUrl) {
    if (!href) return "";
    try {
      var u = new URL(href, baseUrl);
      if (u.pathname.indexOf("/question/") === -1 && u.pathname.indexOf("/answer/") === -1) {
        return "";
      }
      u.hash = "";
      u.search = "";
      return u.href;
    } catch (e) {
      return "";
    }
  }

  function isProfileAnswerUrl(url) {
    return /\/profile\/[^/]+\/answer\/\d+/i.test(url || "");
  }

  function answerUrlScore(url) {
    if (!url || url.indexOf("/answer/") === -1) return 0;
    if (isProfileAnswerUrl(url)) return 3;
    if (/\/answer\/\d+/i.test(url)) return 2;
    return 1;
  }

  function bestAnswerUrlFromBlock(block, baseUrl) {
    if (!block) return null;
    var best = null;
    var bestScore = 0;
    block.querySelectorAll('a[href*="/answer/"]').forEach(function (anchor) {
      var url = normalizeAnswerUrl(anchor.getAttribute("href"), baseUrl);
      if (!url) return;
      var score = answerUrlScore(url);
      if (score > bestScore) {
        bestScore = score;
        best = url;
      }
    });
    return best;
  }

  function collectAnswerBlocks() {
    var blocks = [];
    var seen = typeof WeakSet !== "undefined" ? new WeakSet() : null;
    document.querySelectorAll('a[href*="/answer/"]').forEach(function (anchor) {
      var block = findAnswerBlock(anchor);
      if (!block) return;
      if (seen) {
        if (seen.has(block)) return;
        seen.add(block);
      } else if (blocks.indexOf(block) !== -1) {
        return;
      }
      blocks.push(block);
    });
    return blocks;
  }

  function textOf(el) {
    if (!el) return "";
    return (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
  }

  function findAnswerBlock(anchor) {
    var node = anchor;
    for (var i = 0; i < 12 && node; i++) {
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

  function questionFromBlock(block) {
    if (!block) return { title: "", url: "" };
    var titleEl =
      block.querySelector(".puppeteer_test_question_title") ||
      block.querySelector('[class*="question_title"]');
    var qLink =
      block.querySelector('a[href*="/question/"]') ||
      (titleEl && titleEl.closest && titleEl.closest("a[href]")) ||
      (titleEl && titleEl.querySelector && titleEl.querySelector("a[href]"));
    return {
      title: textOf(titleEl),
      url: qLink ? normalizeQuestionUrl(qLink.getAttribute("href"), location.href) : "",
    };
  }

  function answerPreviewFromBlock(block) {
    if (!block) return "";
    var previewEl =
      block.querySelector(".puppeteer_test_answer_content .q-text") ||
      block.querySelector(".spacing_log_answer_content .q-text") ||
      block.querySelector(".puppeteer_test_answer_content") ||
      block.querySelector(".spacing_log_answer_content");
    return textOf(previewEl).slice(0, 500);
  }

  function extractAnswerRecords(baseUrl) {
    baseUrl = baseUrl || location.href;
    var byUrl = {};
    collectAnswerBlocks().forEach(function (block) {
      var answerUrl = bestAnswerUrlFromBlock(block, baseUrl);
      if (!answerUrl || byUrl[answerUrl]) return;

      var question = questionFromBlock(block);
      byUrl[answerUrl] = {
        url: answerUrl,
        answer_url: answerUrl,
        question_title: question.title || "",
        question_url: question.url || "",
        answer_preview: answerPreviewFromBlock(block),
        seen_at: new Date().toISOString(),
      };
    });
    return byUrl;
  }

  function mergeRecords(into, records) {
    Object.keys(records).forEach(function (key) {
      if (!into[key]) into[key] = records[key];
    });
  }

  function answerKeyFromUrl(url) {
    if (!url) return null;
    var m = String(url).match(/\/answer\/([^/?#]+)/i);
    return m ? m[1].toLowerCase() : null;
  }

  function canonicalAnswerKey(url) {
    var normalized = normalizeAnswerUrl(url, url);
    if (!normalized) return null;
    try {
      var u = new URL(normalized);
      return u.origin.toLowerCase() + u.pathname.replace(/\/$/, "");
    } catch (e) {
      return null;
    }
  }

  function buildKnownLookup(payload) {
    var byUrl = {};
    var byKey = {};
    var urls = (payload && payload.urls) || [];
    var keys = (payload && payload.keys) || [];
    urls.forEach(function (u) {
      var c = canonicalAnswerKey(u);
      if (c) byUrl[c] = true;
      var k = answerKeyFromUrl(u);
      if (k) byKey[k] = true;
    });
    keys.forEach(function (k) {
      byKey[String(k).toLowerCase()] = true;
    });
    return { byUrl: byUrl, byKey: byKey };
  }

  function isKnownAnswer(url, known) {
    if (!known || !url) return false;
    var key = answerKeyFromUrl(url);
    if (key && known.byKey[key]) return true;
    var curl = canonicalAnswerKey(url);
    return !!(curl && known.byUrl[curl]);
  }

  function loadKnownLookup(profileUrl) {
    return new Promise(function (resolve) {
      if (!window.qsbkServeConfig) {
        resolve(buildKnownLookup({}));
        return;
      }
      // Scope the known set to THIS profile's own collection so a re-scrape
      // only skips answers already saved for this profile (not the global
      // legacy "answers" collection). serve canonicalizes the URL.
      var scopeUrl = profileUrl || location.href;
      window.qsbkServeConfig.getServeBase(function (base) {
        var knownUrl = window.qsbkServeConfig.knownUrl(base, scopeUrl);
        fetch(knownUrl, { cache: "no-store" })
          .then(function (response) {
            return response.ok ? response.json() : null;
          })
          .then(function (payload) {
            if (payload) {
              resolve(buildKnownLookup(payload));
              return;
            }
            chrome.storage.local.get(["knownAnswerPayload"], function (data) {
              resolve(buildKnownLookup((data && data.knownAnswerPayload) || {}));
            });
          })
          .catch(function () {
            chrome.storage.local.get(["knownAnswerPayload"], function (data) {
              resolve(buildKnownLookup((data && data.knownAnswerPayload) || {}));
            });
          });
      });
    });
  }

  function removableBlockRoot(block) {
    if (!block) return null;
    return (
      block.closest("article") ||
      block.closest('[class*="Answer"]') ||
      block.closest('[class*="answer"]') ||
      block
    );
  }

  function pruneDomAbove(records, known) {
    if (!PRUNE_ENABLED) return 0;
    var cutoff = -window.innerHeight * 1.5;
    var removed = 0;
    var seen = typeof WeakSet !== "undefined" ? new WeakSet() : null;
    collectAnswerBlocks().forEach(function (block) {
      var rect = block.getBoundingClientRect();
      if (rect.bottom > cutoff) return;
      var answerUrl = bestAnswerUrlFromBlock(block, location.href);
      if (!answerUrl) return;
      if (!records[answerUrl] && !isKnownAnswer(answerUrl, known)) return;
      var root = removableBlockRoot(block);
      if (!root || !root.parentElement) return;
      if (seen) {
        if (seen.has(root)) return;
        seen.add(root);
      }
      root.remove();
      removed += 1;
    });
    return removed;
  }

  function pageHasResumeMarker(resumeAfterKey) {
    if (!resumeAfterKey) return true;
    var key = resumeAfterKey.toLowerCase();
    var anchors = document.querySelectorAll('a[href*="/answer/"]');
    for (var i = 0; i < anchors.length; i++) {
      var href = anchors[i].getAttribute("href") || "";
      var answerKey = answerKeyFromUrl(href);
      if (answerKey && answerKey === key) return true;
    }
    return false;
  }

  function countSkippedOnly(records, known, seenSkippedKeys) {
    var skippedKnown = 0;
    collectAnswerBlocks().forEach(function (block) {
      var answerUrl = bestAnswerUrlFromBlock(block, location.href);
      if (!answerUrl || records[answerUrl]) return;
      var skipKey = answerKeyFromUrl(answerUrl);
      if (!skipKey || seenSkippedKeys[skipKey]) return;
      if (!isKnownAnswer(answerUrl, known)) return;
      seenSkippedKeys[skipKey] = true;
      skippedKnown += 1;
    });
    return skippedKnown;
  }

  function collectNewRecords(records, known, skipKnown, seenSkippedKeys) {
    var added = 0;
    var skippedKnown = 0;
    var deepestUrl = null;
    collectAnswerBlocks().forEach(function (block) {
      var answerUrl = bestAnswerUrlFromBlock(block, location.href);
      if (!answerUrl) return;
      deepestUrl = answerUrl;
      if (records[answerUrl]) return;
      if (skipKnown && isKnownAnswer(answerUrl, known)) {
        var skipKey = answerKeyFromUrl(answerUrl);
        if (skipKey && !seenSkippedKeys[skipKey]) {
          seenSkippedKeys[skipKey] = true;
          skippedKnown += 1;
        }
        return;
      }
      var question = questionFromBlock(block);
      records[answerUrl] = {
        url: answerUrl,
        answer_url: answerUrl,
        question_title: question.title || "",
        question_url: question.url || "",
        answer_preview: answerPreviewFromBlock(block),
        seen_at: new Date().toISOString(),
      };
      added += 1;
    });
    return { added: added, skippedKnown: skippedKnown, deepestUrl: deepestUrl };
  }

  function pageMetrics() {
    return {
      scrollHeight: document.body.scrollHeight,
      anchorCount: document.querySelectorAll('a[href*="/answer/"]').length,
    };
  }

  function normalizeCountText(txt) {
    if (!txt) return null;
    txt = txt.replace(/\u00a0/g, " ").trim();
    var mil = txt.match(/([0-9]+)[.,]?([0-9]+)?\s*mil/i);
    if (mil) {
      var whole = parseInt(mil[1], 10);
      var frac = mil[2];
      if (frac) {
        return whole * 1000 + parseInt(frac, 10) * Math.pow(10, 3 - frac.length);
      }
      return whole * 1000;
    }
    var k = txt.match(/([0-9]+(?:\.[0-9]+)?)\s*[kK]\b/);
    if (k) {
      return Math.round(parseFloat(k[1]) * 1000);
    }
    txt = txt.replace(/,/g, "");
    var digits = txt.match(/\d+/g);
    if (digits) {
      return parseInt(digits.join(""), 10);
    }
    return null;
  }

  function extractProfileStats() {
    var stats = { answers: null, questions: null };

    var meta = document.querySelector('meta[property="og:description"]');
    if (meta) {
      var content = meta.getAttribute("content") || "";
      var answersMatch =
        content.match(/(\d+[\.,]?\d*(?:\s*mil)?)\s+respostas/i) ||
        content.match(/(\d+[\.,]?\d*(?:\s*(?:K|k|mil))?)\s+answers/i);
      var questionsMatch =
        content.match(/(\d+[\.,]?\d*(?:\s*mil)?)\s+perguntas/i) ||
        content.match(/(\d+[\.,]?\d*(?:\s*(?:K|k|mil))?)\s+questions/i);
      if (answersMatch) stats.answers = normalizeCountText(answersMatch[1]);
      if (questionsMatch) stats.questions = normalizeCountText(questionsMatch[1]);
    }

    if (stats.answers == null) {
      var labelNodes = document.querySelectorAll("div, span");
      for (var i = 0; i < labelNodes.length; i++) {
        var label = textOf(labelNodes[i]).toLowerCase();
        if (
          label === "respostas" ||
          label === "answers" ||
          (label.indexOf("answer") !== -1 && label.length < 24)
        ) {
          var prev = labelNodes[i].previousElementSibling;
          if (prev) {
            var n = normalizeCountText(textOf(prev));
            if (n != null) {
              stats.answers = n;
              break;
            }
          }
        }
      }
    }

    if (stats.answers == null) {
      document.querySelectorAll('a[href*="/answers"]').forEach(function (anchor) {
        if (stats.answers != null) return;
        var n = normalizeCountText(textOf(anchor));
        if (n != null && n > 0) stats.answers = n;
      });
    }

    return stats;
  }

  window.qsbkExtractProfileStats = extractProfileStats;

  // Best-effort human display name for the profile (optional). Reads og:title
  // or the document title and strips the trailing " - Quora"/" | Quora" suffix.
  function extractProfileDisplayName() {
    var title = "";
    var meta = document.querySelector('meta[property="og:title"]');
    if (meta) title = meta.getAttribute("content") || "";
    if (!title) title = document.title || "";
    title = title.replace(/\s*[-|]\s*Quora\s*$/i, "").trim();
    return title || "";
  }

  window.qsbkExtractProfileDisplayName = extractProfileDisplayName;

  function findLoadMoreButton() {
    var candidates = document.querySelectorAll("button, a, div[role='button']");
    for (var i = 0; i < candidates.length; i++) {
      var label = textOf(candidates[i]).toLowerCase();
      if (
        label.indexOf("more answer") !== -1 ||
        label.indexOf("mais resposta") !== -1 ||
        label.indexOf("ver mais") !== -1 ||
        label === "more"
      ) {
        return candidates[i];
      }
    }
    return null;
  }

  async function tryRecoverFromStall(metricsBefore) {
    var h = document.body.scrollHeight;
    window.scrollTo(0, Math.max(0, h * 0.65));
    await sleep(400);
    for (var i = 0; i < RECOVERY_BURST; i++) {
      window.scrollBy(0, Math.floor(window.innerHeight * 0.85));
      await sleep(350);
    }
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(SCROLL_PAUSE_MS);

    var more = findLoadMoreButton();
    if (more && typeof more.click === "function") {
      more.click();
      await sleep(SCROLL_PAUSE_MS * 2);
    }

    var after = pageMetrics();
    return (
      after.scrollHeight > metricsBefore.scrollHeight ||
      after.anchorCount > metricsBefore.anchorCount
    );
  }

  function recordsAsRows(records) {
    return Object.keys(records)
      .sort()
      .map(function (k) {
        return records[k];
      });
  }

  /* ---------------------------------------------------------------------------
   * GraphQL API collection (no scrolling).
   *
   * Quora's /answers tab is backed by a Relay persisted query
   * (UserProfileAnswersMostRecent_RecentAnswers_Query) at
   * POST /graphql/gql_para_POST. It uses an integer offset cursor: endCursor
   * from each response feeds the next request's `after` until
   * pageInfo.hasNextPage is false. The content script shares the page's
   * cookies, so a same-origin fetch is authenticated automatically.
   * ------------------------------------------------------------------------ */
  var GQL_QUERY_NAME = "UserProfileAnswersMostRecent_RecentAnswers_Query";
  var GQL_CONNECTION_KEY = "recentPublicAndPinnedAnswersConnection";
  var GQL_DEFAULT_HASH =
    "0c7ab9ef87775512e02d48001ab55778e196125cf361e0e351d4eb5c8d8cac3a";
  var GQL_PAGE_SIZE = 20;
  var GQL_EMPTY_PAGE_LIMIT = 3;
  // Deep pagination over many hundreds of pages can trip Quora rate limiting,
  // surfacing as a network-level "Failed to fetch". Retry transient failures
  // with exponential backoff and pace requests slightly to stay under the radar.
  var GQL_MAX_RETRIES = 4;
  var GQL_RETRY_BASE_MS = 1000;
  var GQL_PAGE_DELAY_MS = 150;
  // When streaming to serve, publish in batches of this size as we collect, so
  // large backfills don't buffer everything in memory and survive interruptions.
  var GQL_PUBLISH_BATCH = 100;

  function gqlPageHtml() {
    return document.documentElement ? document.documentElement.innerHTML : "";
  }

  function extractPageContext() {
    var html = gqlPageHtml();
    var uid = html.match(/"rootQueryVariables"\s*:\s*\{\s*"uid"\s*:\s*(\d+)/);
    var formkey = html.match(/"formkey"\s*:\s*"([0-9a-fA-F]+)"/);
    var revision = html.match(/"revision"\s*:\s*"([\w-]+)"/);
    return {
      uid: uid ? parseInt(uid[1], 10) : null,
      formkey: formkey ? formkey[1] : null,
      revision: revision ? revision[1] : null,
    };
  }

  function qtextToPlain(qtext) {
    if (!qtext) return "";
    var doc = qtext;
    if (typeof qtext === "string") {
      try {
        doc = JSON.parse(qtext);
      } catch (e) {
        return qtext.trim();
      }
    }
    if (!doc || !doc.sections) return "";
    return doc.sections
      .map(function (section) {
        return (section.spans || [])
          .map(function (span) {
            return span.text || "";
          })
          .join("");
      })
      .join("\n")
      .trim();
  }

  function mapNodeToRecord(node) {
    if (!node) return null;
    var url = node.url || node.permaUrl;
    if (!url) return null;
    var question = node.question || {};
    var answerText = qtextToPlain(node.content);
    return {
      url: url,
      answer_url: url,
      aid: node.aid != null ? String(node.aid) : null,
      question_title: qtextToPlain(question.title),
      question_url: question.url || "",
      answer_preview: answerText.slice(0, 500),
      answer_text: answerText,
      num_upvotes: node.numUpvotes,
      num_views: node.numViews,
      num_comments: node.numDisplayComments,
      creation_time: node.creationTime,
      seen_at: new Date().toISOString(),
    };
  }

  // GraphQL answer URLs use the "question-slug/answer/author-slug" form, so the
  // shared answerKeyFromUrl() (which reads the segment after /answer/) collapses
  // to the same author slug for every answer. The per-answer canonical pathname
  // is still unique, so known-detection here keys on that only — never on the
  // degenerate author-slug key.
  function gqlIsKnown(url, known) {
    if (!known || !url) return false;
    var canonical = canonicalAnswerKey(url);
    return !!(canonical && known.byUrl[canonical]);
  }

  function answersConnectionFrom(resp) {
    var user = (resp && resp.data && resp.data.user) || {};
    var conn = user[GQL_CONNECTION_KEY];
    if (conn && conn.edges) return conn;
    for (var key in user) {
      if (user[key] && user[key].edges && user[key].pageInfo) return user[key];
    }
    return null;
  }

  async function fetchAnswersPage(ctx, after, first, queryHash) {
    var headers = { "content-type": "application/json", "quora-formkey": ctx.formkey };
    if (ctx.revision) headers["quora-revision"] = ctx.revision;
    var variables = { uid: ctx.uid, first: first, answerFilterTid: null };
    if (after != null) variables.after = after;
    var body = JSON.stringify({
      queryName: GQL_QUERY_NAME,
      variables: variables,
      extensions: { hash: queryHash },
    });
    var r;
    try {
      r = await fetch(location.origin + "/graphql/gql_para_POST?q=" + GQL_QUERY_NAME, {
        method: "POST",
        credentials: "include",
        headers: headers,
        body: body,
      });
    } catch (e) {
      // Network-level failure ("Failed to fetch") — usually transient/throttling.
      var netErr = new Error("network: " + ((e && e.message) || e));
      netErr.retriable = true;
      throw netErr;
    }
    if (!r.ok) {
      var httpErr = new Error("HTTP " + r.status);
      httpErr.retriable = r.status === 429 || r.status >= 500;
      throw httpErr;
    }
    return r.json();
  }

  async function fetchAnswersPageRetry(ctx, after, first, queryHash) {
    var lastErr;
    for (var attempt = 0; attempt <= GQL_MAX_RETRIES; attempt++) {
      try {
        return await fetchAnswersPage(ctx, after, first, queryHash);
      } catch (e) {
        lastErr = e;
        if (!e || !e.retriable || attempt === GQL_MAX_RETRIES) throw e;
        var delay = GQL_RETRY_BASE_MS * Math.pow(2, attempt);
        console.warn(
          "[qsbk gql] transient fetch error at after=" + after +
            " (attempt " + (attempt + 1) + "/" + (GQL_MAX_RETRIES + 1) +
            "), backing off " + delay + "ms:",
          (e && e.message) || e
        );
        await sleep(delay);
      }
    }
    throw lastErr;
  }

  async function collectViaGraphql(maxResults, options) {
    options = options || {};
    var known = options.known || buildKnownLookup({});
    var skipKnown = options.skipKnown !== false;
    var queryHash = options.queryHash || GQL_DEFAULT_HASH;
    var pageSize = options.pageSize || GQL_PAGE_SIZE;

    var ctx = extractPageContext();
    console.info(
      "[qsbk gql] start — uid=" + ctx.uid +
        " formkey=" + (ctx.formkey ? "yes" : "MISSING") +
        " revision=" + (ctx.revision ? "yes" : "no") +
        " maxResults=" + maxResults +
        " skipKnown=" + skipKnown +
        " pageSize=" + pageSize
    );
    if (!ctx.uid || !ctx.formkey) {
      console.error(
        "[qsbk gql] context_missing — could not read uid/formkey from the page. " +
          "Are you on a /profile/<user>/answers page while logged in?"
      );
      return {
        rows: [],
        meta: {
          stop_reason: "context_missing",
          collected: 0,
          requested: maxResults,
          mode: "graphql",
          skip_known: skipKnown,
        },
      };
    }

    var serveUpsertUrl = options.serveUpsertUrl || null;
    var streaming = !!serveUpsertUrl;
    var force = !!options.force;

    // Readable profile identity stamped onto every record. serve derives the
    // routing userid from profile_url server-side, so we send no collection
    // name here. name/url/count come from the popup (startScrape message);
    // display name is read here from the live page DOM.
    var profileFields = {};
    if (options.profile_name) profileFields.profile_name = options.profile_name;
    if (options.profile_url) profileFields.profile_url = options.profile_url;
    if (options.profile_answer_count != null)
      profileFields.profile_answer_count = options.profile_answer_count;
    var displayName = extractProfileDisplayName();
    if (displayName) profileFields.profile_display_name = displayName;

    var seen = {};
    var rowsOut = streaming ? null : [];
    var publishBuffer = [];
    var seenSkippedKeys = {};
    var collected = 0;
    var published = 0;
    var publishBatches = 0;
    var publishErrors = 0;
    var skippedKnown = 0;
    var after = null;
    var pages = 0;
    var emptyPages = 0;
    var deepestUrl = null;
    var stopReason = "max_reached";

    console.info("[qsbk gql] streaming publish: " + (streaming ? "on" : "off") + " force=" + force);

    async function publishOneBatch(batch) {
      publishBatches += 1;
      try {
        var resp = await fetch(serveUpsertUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
          // Top-level profile_url scopes serve's publish-side dedup to this
          // profile's own collection (force=false re-scrapes); per-row
          // profile_url still drives subscriber routing.
          body: JSON.stringify({
            answers: batch,
            force: force,
            profile_url: profileFields.profile_url || undefined,
          }),
        });
        if (resp.ok) {
          var body = await resp.json();
          published += (body && body.published) || 0;
        } else {
          publishErrors += 1;
          console.warn("[qsbk gql] /upsert batch HTTP " + resp.status);
        }
      } catch (e) {
        publishErrors += 1;
        console.warn("[qsbk gql] /upsert batch failed:", (e && e.message) || e);
      }
    }

    async function drainPublish(finalFlush) {
      if (!streaming) return;
      while (
        publishBuffer.length >= GQL_PUBLISH_BATCH ||
        (finalFlush && publishBuffer.length > 0)
      ) {
        await publishOneBatch(publishBuffer.splice(0, GQL_PUBLISH_BATCH));
      }
    }

    function sendProgress() {
      try {
        chrome.runtime.sendMessage({
          type: "progress",
          found: collected,
          newFound: collected,
          scrolled: skippedKnown,
          published: published,
          streamed: streaming,
          max: maxResults,
          stagnant: 0,
          recovering: false,
          resumePending: false,
          pruned: 0,
        });
      } catch (e) {
        /* popup closed */
      }
    }

    while (running && collected < maxResults) {
      var resp;
      try {
        resp = await fetchAnswersPageRetry(ctx, after, pageSize, queryHash);
      } catch (e) {
        // Exhausted retries (or non-retriable). Keep/flush what we have rather
        // than discarding the whole run.
        stopReason = "api_error:" + String((e && e.message) || e);
        console.error(
          "[qsbk gql] fetch failed at after=" + after +
            " after retries — stopping with " + collected + " collected:",
          e
        );
        break;
      }

      var conn = answersConnectionFrom(resp);
      if (!conn) {
        stopReason = "no_connection";
        console.error(
          "[qsbk gql] no answers connection in response (query hash may be stale):",
          resp
        );
        break;
      }

      var edges = conn.edges || [];
      var addedThisPage = 0;
      for (var i = 0; i < edges.length; i++) {
        if (collected >= maxResults) break;
        var record = mapNodeToRecord(edges[i] && edges[i].node);
        if (!record) continue;
        Object.assign(record, profileFields);
        deepestUrl = record.url;
        if (seen[record.url]) continue;
        if (skipKnown && gqlIsKnown(record.url, known)) {
          var skipKey = canonicalAnswerKey(record.url);
          if (skipKey && !seenSkippedKeys[skipKey]) {
            seenSkippedKeys[skipKey] = true;
            skippedKnown += 1;
          }
          continue;
        }
        seen[record.url] = true;
        collected += 1;
        addedThisPage += 1;
        if (streaming) {
          publishBuffer.push(record);
        } else {
          rowsOut.push(record);
        }
      }

      pages += 1;
      var pageInfoLog = conn.pageInfo || {};
      console.info(
        "[qsbk gql] page " + pages +
          " — edges=" + edges.length +
          " new=" + addedThisPage +
          " collected=" + collected +
          " published=" + published +
          " skippedKnown=" + skippedKnown +
          " hasNext=" + pageInfoLog.hasNextPage
      );

      // Stream out full batches as we go (bounds memory; survives interruption).
      await drainPublish(false);
      if (typeof window.qsbkMarkCached === "function") window.qsbkMarkCached();
      sendProgress();

      // Reverse-chronological feed: a run of all-known pages means we have
      // caught up with what's already ingested — stop rather than scan history.
      if (skipKnown && addedThisPage === 0) {
        emptyPages += 1;
        if (emptyPages >= GQL_EMPTY_PAGE_LIMIT) {
          stopReason = "all_known";
          break;
        }
      } else {
        emptyPages = 0;
      }

      var pageInfo = conn.pageInfo || {};
      if (!pageInfo.hasNextPage) {
        stopReason = "exhausted";
        break;
      }
      var nextAfter = pageInfo.endCursor;
      if (nextAfter == null || String(nextAfter) === String(after)) {
        stopReason = "cursor_stalled";
        break;
      }
      after = String(nextAfter);
      if (GQL_PAGE_DELAY_MS > 0) await sleep(GQL_PAGE_DELAY_MS);
    }

    // Flush any remaining buffered answers.
    await drainPublish(true);
    sendProgress();

    var rows = streaming ? [] : rowsOut.slice(0, maxResults);
    console.info(
      "[qsbk gql] done — stop_reason=" + stopReason +
        " collected=" + collected +
        " published=" + published +
        " publishErrors=" + publishErrors +
        " skippedKnown=" + skippedKnown +
        " pages=" + pages
    );
    if (typeof window.qsbkRefreshMarks === "function") {
      await window.qsbkRefreshMarks();
    }

    return {
      rows: rows,
      meta: {
        stop_reason: stopReason,
        collected: collected,
        requested: maxResults,
        skipped_known: skippedKnown,
        skip_known: skipKnown,
        mode: "graphql",
        streamed: streaming,
        published: published,
        publish_batches: publishBatches,
        publish_errors: publishErrors,
        pages: pages,
        deepest_url: deepestUrl,
        deepest_key: deepestUrl ? answerKeyFromUrl(deepestUrl) : null,
      },
    };
  }

  window.qsbkCollectViaGraphql = collectViaGraphql;

  async function scrollAndCollect(maxResults, options) {
    options = options || {};
    var known = options.known || buildKnownLookup({});
    var skipKnown = options.skipKnown !== false;
    var resumeAfterKey = options.resumeAfterKey || null;
    var records = {};
    var stagnant = 0;
    var lastCount = 0;
    var recoveryRounds = 0;
    var stopReason = "max_reached";
    var lastMetrics = pageMetrics();
    var scrolledKnown = 0;
    var seenSkippedKeys = {};
    var prunedTotal = 0;
    var resumeReached = !resumeAfterKey;
    var lastProgressCount = -1;
    var deepestUrl = null;

    function markIngestedAnswers() {
      if (typeof window.qsbkMarkCached === "function") {
        window.qsbkMarkCached();
      }
    }

    function sendProgress(opts) {
      var found = Object.keys(records).length;
      var payload = {
        type: "progress",
        found: found,
        newFound: found,
        scrolled: scrolledKnown,
        max: maxResults,
        stagnant: stagnant,
        recovering: !!opts.recovering,
        resumePending: !resumeReached,
        pruned: prunedTotal,
      };
      if (found !== lastProgressCount || opts.forceRows) {
        payload.rows = recordsAsRows(records);
        lastProgressCount = found;
      }
      try {
        chrome.runtime.sendMessage(payload);
      } catch (e) {
        /* popup closed */
      }
    }

    function ingestPass() {
      var batch = collectNewRecords(records, known, skipKnown, seenSkippedKeys);
      scrolledKnown += batch.skippedKnown;
      if (batch.deepestUrl) deepestUrl = batch.deepestUrl;
      if (PRUNE_ENABLED) prunedTotal += pruneDomAbove(records, known);
      return batch;
    }

    function metricsGrew(before, after, batch) {
      return (
        after > before ||
        (batch && batch.skippedKnown > 0) ||
        metrics.scrollHeight > lastMetrics.scrollHeight ||
        metrics.anchorCount > lastMetrics.anchorCount
      );
    }

    while (running && Object.keys(records).length < maxResults) {
      if (!resumeReached) {
        var resumeMetrics = pageMetrics();
        if (pageHasResumeMarker(resumeAfterKey)) {
          resumeReached = true;
          stagnant = 0;
          if (PRUNE_ENABLED) prunedTotal += pruneDomAbove({}, known);
        } else {
          window.scrollTo(0, document.body.scrollHeight);
          await sleep(FAST_SCROLL_PAUSE_MS);
          var resumeSkipped = countSkippedOnly(records, known, seenSkippedKeys);
          scrolledKnown += resumeSkipped;
          if (PRUNE_ENABLED) prunedTotal += pruneDomAbove({}, known);
          var resumeAfterMetrics = pageMetrics();
          sendProgress({ recovering: false, forceRows: false });
          if (
            resumeSkipped > 0 ||
            resumeAfterMetrics.scrollHeight > resumeMetrics.scrollHeight ||
            resumeAfterMetrics.anchorCount > resumeMetrics.anchorCount
          ) {
            stagnant = 0;
          } else {
            stagnant += 1;
          }
          if (stagnant >= RESUME_STAGNANT_LIMIT) {
            stopReason = "resume_not_found";
            resumeReached = true;
            stagnant = 0;
          } else {
            continue;
          }
        }
      }

      ingestPass();
      markIngestedAnswers();
      sendProgress({ recovering: false });

      var found = Object.keys(records).length;
      if (found >= maxResults) {
        stopReason = "max_reached";
        break;
      }

      var pauseMs = SCROLL_PAUSE_MS;
      if (skipKnown && scrolledKnown > 0 && found === lastCount) {
        pauseMs = FAST_SCROLL_PAUSE_MS;
      }

      window.scrollTo(0, document.body.scrollHeight);
      await sleep(pauseMs);
      var batch = ingestPass();
      markIngestedAnswers();

      var after = Object.keys(records).length;
      var metrics = pageMetrics();
      var grew = metricsGrew(lastCount, after, batch);

      sendProgress({ recovering: false });

      if (!grew) {
        stagnant += 1;

        if (stagnant >= 2 && recoveryRounds < MAX_RECOVERY_ROUNDS) {
          sendProgress({ recovering: true, forceRows: true });

          var recovered = await tryRecoverFromStall(lastMetrics);
          recoveryRounds += 1;
          var recoveryBatch = ingestPass();
          markIngestedAnswers();
          after = Object.keys(records).length;
          metrics = pageMetrics();

          if (
            recovered ||
            metricsGrew(lastCount, after, recoveryBatch) ||
            metrics.scrollHeight > lastMetrics.scrollHeight
          ) {
            stagnant = 0;
            lastCount = after;
            lastMetrics = metrics;
            continue;
          }
        }

        var stuckLimit = STAGNANT_LIMIT;
        if (skipKnown && after === 0 && scrolledKnown > 0) {
          stuckLimit = STAGNANT_LIMIT + 6;
        }

        if (stagnant >= stuckLimit) {
          stopReason = "pagination_stuck";
          break;
        }
      } else {
        stagnant = 0;
        lastCount = after;
        lastMetrics = metrics;
      }
    }

    var rows = recordsAsRows(records).slice(0, maxResults);

    if (typeof window.qsbkRefreshMarks === "function") {
      await window.qsbkRefreshMarks();
    } else {
      markIngestedAnswers();
    }

    return {
      rows: rows,
      meta: {
        stop_reason: stopReason,
        stagnant_passes: stagnant,
        recovery_attempts: recoveryRounds,
        collected: rows.length,
        requested: maxResults,
        skipped_known: scrolledKnown,
        pruned_nodes: prunedTotal,
        skip_known: skipKnown,
        resume_after_key: resumeAfterKey || null,
        deepest_url: deepestUrl,
        deepest_key: deepestUrl ? answerKeyFromUrl(deepestUrl) : null,
      },
    };
  }

  chrome.runtime.onMessage.addListener(function (msg, _sender, sendResponse) {
    if (msg.type === "ping") {
      sendResponse({ ok: true });
      return false;
    }

    if (msg.type === "getProfileStats") {
      sendResponse({ ok: true, stats: extractProfileStats() });
      return false;
    }

    if (msg.type !== "startScrape") return false;

    if (running) {
      sendResponse({ ok: false, error: "Scrape already running on this tab." });
      return false;
    }

    running = true;
    window.__qsbkScrapeRunning = true;
    var maxResults = Math.max(1, parseInt(msg.maxResults, 10) || 100);
    var skipKnown = msg.skipKnown !== false;
    var resumeAfterKey = msg.resumeAfterKey || null;
    var mode = msg.mode === "graphql" ? "graphql" : "scroll";

    loadKnownLookup(msg.profile_url || location.href)
      .then(function (known) {
        if (mode === "graphql") {
          return collectViaGraphql(maxResults, {
            known: known,
            skipKnown: skipKnown,
            queryHash: msg.queryHash || null,
            pageSize: msg.pageSize || null,
            serveUpsertUrl: msg.serveUpsertUrl || null,
            force: !!msg.force,
            profile_name: msg.profile_name || null,
            profile_url: msg.profile_url || null,
            profile_answer_count:
              msg.profile_answer_count != null ? msg.profile_answer_count : null,
          });
        }
        return scrollAndCollect(maxResults, {
          known: known,
          skipKnown: skipKnown,
          resumeAfterKey: resumeAfterKey,
        });
      })
      .then(function (result) {
        running = false;
        window.__qsbkScrapeRunning = false;
        sendResponse({ ok: true, rows: result.rows, meta: result.meta });
      })
      .catch(function (err) {
        running = false;
        window.__qsbkScrapeRunning = false;
        sendResponse({ ok: false, error: String(err) });
      });

    return true;
  });
})();
