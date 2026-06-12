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
})();
