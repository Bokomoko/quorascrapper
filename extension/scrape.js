/** qsbk content script — self-contained, no ES modules. */
(function () {
  if (window.__qsbkScrapeLoaded) return;
  window.__qsbkScrapeLoaded = true;

  var SCROLL_PAUSE_MS = 1500;
  var STAGNANT_LIMIT = 6;
  var RECOVERY_BURST = 3;
  var MAX_RECOVERY_ROUNDS = 4;
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

  async function scrollAndCollect(maxResults) {
    var records = {};
    var stagnant = 0;
    var lastCount = 0;
    var recoveryRounds = 0;
    var stopReason = "max_reached";
    var lastMetrics = pageMetrics();

    function markIngestedAnswers() {
      if (typeof window.qsbkMarkCached === "function") {
        window.qsbkMarkCached();
      }
    }

    while (running && Object.keys(records).length < maxResults) {
      mergeRecords(records, extractAnswerRecords());
      markIngestedAnswers();

      var found = Object.keys(records).length;
      try {
        chrome.runtime.sendMessage({
          type: "progress",
          found: found,
          max: maxResults,
          stagnant: stagnant,
          recovering: false,
          rows: Object.keys(records)
            .sort()
            .map(function (k) {
              return records[k];
            }),
        });
      } catch (e) {
        /* popup closed */
      }

      if (found >= maxResults) {
        stopReason = "max_reached";
        break;
      }

      window.scrollTo(0, document.body.scrollHeight);
      await sleep(SCROLL_PAUSE_MS);
      mergeRecords(records, extractAnswerRecords());
      markIngestedAnswers();

      var after = Object.keys(records).length;
      var metrics = pageMetrics();
      var grew =
        after > lastCount ||
        metrics.scrollHeight > lastMetrics.scrollHeight ||
        metrics.anchorCount > lastMetrics.anchorCount;

      if (!grew) {
        stagnant += 1;

        if (stagnant >= 2 && recoveryRounds < MAX_RECOVERY_ROUNDS) {
          try {
            chrome.runtime.sendMessage({
              type: "progress",
              found: after,
              max: maxResults,
              stagnant: stagnant,
              recovering: true,
              rows: Object.keys(records)
                .sort()
                .map(function (k) {
                  return records[k];
                }),
            });
          } catch (e2) {
            /* popup closed */
          }

          var recovered = await tryRecoverFromStall(lastMetrics);
          recoveryRounds += 1;
          mergeRecords(records, extractAnswerRecords());
          markIngestedAnswers();
          after = Object.keys(records).length;
          metrics = pageMetrics();

          if (
            recovered ||
            after > lastCount ||
            metrics.scrollHeight > lastMetrics.scrollHeight
          ) {
            stagnant = 0;
            lastCount = after;
            lastMetrics = metrics;
            continue;
          }
        }

        if (stagnant >= STAGNANT_LIMIT) {
          stopReason = "pagination_stuck";
          break;
        }
      } else {
        stagnant = 0;
        lastCount = after;
        lastMetrics = metrics;
      }
    }

    var rows = Object.keys(records)
      .sort()
      .slice(0, maxResults)
      .map(function (k) {
        return records[k];
      });

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
    var maxResults = Math.max(1, Math.min(5000, msg.maxResults || 100));

    scrollAndCollect(maxResults)
      .then(function (result) {
        running = false;
        sendResponse({ ok: true, rows: result.rows, meta: result.meta });
      })
      .catch(function (err) {
        running = false;
        sendResponse({ ok: false, error: String(err) });
      });

    return true;
  });
})();
