(function () {
  var themeStorageKey = "repoforge-theme";

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function currentTheme() {
    try {
      return localStorage.getItem(themeStorageKey) || systemTheme();
    } catch (error) {
      return systemTheme();
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    });
  }

  function bindThemeToggle() {
    applyTheme(currentTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      button.addEventListener("click", function () {
        var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
        try {
          localStorage.setItem(themeStorageKey, next);
        } catch (error) {}
        applyTheme(next);
      });
    });
    if (window.matchMedia) {
      var media = window.matchMedia("(prefers-color-scheme: dark)");
      media.addEventListener("change", function () {
        try {
          if (localStorage.getItem(themeStorageKey)) return;
        } catch (error) {}
        applyTheme(systemTheme());
      });
    }
  }

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
    bindThemeToggle();
    activateHashTab();
    refreshLogs();
  });
})();
