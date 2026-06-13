// MV3 service worker — toggle in-page floating panel on the Quora tab.
(function () {
  chrome.runtime.onInstalled.addListener(function () {
    console.info("qsbk extension installed");
  });

  function toggleOnTab(tab) {
    if (!tab || tab.id == null) return;
    chrome.storage.session.set({ qsbkTargetTabId: tab.id });
    chrome.tabs.sendMessage(tab.id, { type: "togglePanel" }, function () {
      if (chrome.runtime.lastError) {
        chrome.scripting.executeScript(
          { target: { tabId: tab.id }, files: ["panel-shell.js"] },
          function () {
            chrome.tabs.sendMessage(tab.id, { type: "togglePanel" });
          }
        );
      }
    });
  }

  chrome.action.onClicked.addListener(function (tab) {
    toggleOnTab(tab);
  });

  // Detach a Quora tab into its own minimized, unfocused window so scraping
  // keeps running in the background. chrome.windows needs no extra permission.
  // Some Chrome builds reject focused:false combined with state:"minimized",
  // so fall back to a plain minimized create if the first attempt errors.
  function runMinimized(tabId, sendResponse) {
    if (tabId == null) {
      sendResponse({ ok: false, error: "no target tab" });
      return;
    }
    chrome.windows.create({ tabId: tabId, state: "minimized", focused: false }, function (win) {
      if (chrome.runtime.lastError) {
        chrome.windows.create({ tabId: tabId, state: "minimized" }, function (win2) {
          if (chrome.runtime.lastError) {
            sendResponse({ ok: false, error: chrome.runtime.lastError.message });
          } else {
            sendResponse({ ok: true, windowId: win2 && win2.id });
          }
        });
      } else {
        sendResponse({ ok: true, windowId: win && win.id });
      }
    });
  }

  chrome.runtime.onMessage.addListener(function (msg, _sender, sendResponse) {
    if (msg && msg.type === "runMinimized") {
      runMinimized(msg.tabId, sendResponse);
      return true; // keep the message channel open for the async response
    }
    return false;
  });
})();
