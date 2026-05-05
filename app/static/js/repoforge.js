(function () {
  function activateHashTab() {
    var hash = window.location.hash;
    if (!hash) return;
    document.querySelectorAll(".tabs .tab").forEach(function (tab) {
      tab.classList.toggle("is-active", tab.getAttribute("href") === hash);
    });
  }

  function refreshLogs() {
    var panel = document.querySelector("[data-refresh-url]");
    var logView = document.getElementById("log-view");
    if (!panel || !logView) return;
    var url = panel.getAttribute("data-refresh-url");
    if (!url) return;

    window.setInterval(function () {
      fetch(url, { headers: { "X-Requested-With": "fetch" } })
        .then(function (response) {
          if (!response.ok) throw new Error("Log refresh failed");
          return response.text();
        })
        .then(function (text) {
          logView.textContent = text;
          logView.scrollTop = logView.scrollHeight;
        })
        .catch(function () {});
    }, 5000);
  }

  window.addEventListener("hashchange", activateHashTab);
  document.addEventListener("DOMContentLoaded", function () {
    activateHashTab();
    refreshLogs();
  });
})();
