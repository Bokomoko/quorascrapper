/** Floating panel shell on the Quora page — drags independently of the browser window. */
(function () {
  if (window.__qsbkPanelShell) return;
  window.__qsbkPanelShell = true;

  var PANEL_ID = "qsbk-floating-panel";
  var STORAGE_KEY = "qsbkPanelPos";

  function loadPosition() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function savePosition(left, top) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ left: left, top: top }));
    } catch (e) {
      /* ignore */
    }
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function createPanel() {
    var root = document.createElement("div");
    root.id = PANEL_ID;
    root.style.cssText =
      "position:fixed;width:360px;height:560px;z-index:2147483646;" +
      "box-shadow:0 12px 40px rgba(0,0,0,.22);border-radius:10px;overflow:hidden;" +
      "background:#fff;border:1px solid #d1d5db;display:none;";

    var pos = loadPosition();
    root.style.top = (pos && pos.top != null ? pos.top : 72) + "px";
    root.style.left = (pos && pos.left != null ? pos.left : Math.max(16, window.innerWidth - 384)) + "px";

    var header = document.createElement("div");
    header.style.cssText =
      "cursor:move;padding:10px 12px;background:linear-gradient(#f3f4f6,#e5e7eb);" +
      "border-bottom:1px solid #d1d5db;font:600 13px system-ui,sans-serif;color:#111827;" +
      "display:flex;justify-content:space-between;align-items:center;";

    var title = document.createElement("span");
    title.textContent = "qsbk — drag here";

    var closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.textContent = "\u00d7";
    closeBtn.title = "Close panel";
    closeBtn.style.cssText =
      "cursor:pointer;border:none;background:transparent;font-size:18px;line-height:1;" +
      "padding:0 4px;color:#6b7280;";
    closeBtn.addEventListener("click", function (ev) {
      ev.stopPropagation();
      root.style.display = "none";
    });

    header.appendChild(title);
    header.appendChild(closeBtn);

    var iframe = document.createElement("iframe");
    iframe.src = chrome.runtime.getURL("popup.html?embedded=1");
    iframe.style.cssText = "width:100%;height:calc(100% - 41px);border:none;display:block;";

    header.addEventListener("mousedown", function (downEvent) {
      if (downEvent.target === closeBtn) return;
      downEvent.preventDefault();

      var rect = root.getBoundingClientRect();
      var offsetX = downEvent.clientX - rect.left;
      var offsetY = downEvent.clientY - rect.top;

      function onMove(ev) {
        var left = clamp(ev.clientX - offsetX, 0, window.innerWidth - rect.width);
        var top = clamp(ev.clientY - offsetY, 0, window.innerHeight - 48);
        root.style.left = left + "px";
        root.style.top = top + "px";
      }

      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        var r = root.getBoundingClientRect();
        savePosition(r.left, r.top);
      }

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    root.appendChild(header);
    root.appendChild(iframe);
    document.documentElement.appendChild(root);
    return root;
  }

  function getPanel() {
    return document.getElementById(PANEL_ID) || createPanel();
  }

  chrome.runtime.onMessage.addListener(function (msg, _sender, sendResponse) {
    if (msg.type !== "togglePanel") return false;
    var panel = getPanel();
    var show = panel.style.display === "none";
    panel.style.display = show ? "block" : "none";
    sendResponse({ ok: true, visible: show });
    return false;
  });
})();
