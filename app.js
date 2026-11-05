// Your Sprouts - small helpers for the phone app
(function () {
  // Ask "are you sure?" before important buttons
  document.querySelectorAll("form[data-confirm]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!confirm(f.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  // + / - buttons for packet count
  document.querySelectorAll(".step").forEach(function (b) {
    b.addEventListener("click", function () {
      var input = document.getElementById("packets");
      var v = parseInt(input.value || "0", 10) + parseInt(b.getAttribute("data-step"), 10);
      input.value = Math.max(0, Math.min(999, v));
    });
  });

  // Copy secret ID
  document.querySelectorAll("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () {
      var text = b.getAttribute("data-copy");
      var label = b.textContent;
      var done = function () {
        b.textContent = document.body.classList.contains("lang-te") ? "కాపీ అయింది!" : "Copied!";
        setTimeout(function () { b.textContent = label; }, 1800);
      };
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () {});
      else { var box = document.getElementById("secretBox"); window.getSelection().selectAllChildren(box); document.execCommand("copy"); done(); }
    });
  });

  // Prevent double-submits
  document.querySelectorAll("form[method=post]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (e.defaultPrevented) return;
      f.querySelectorAll("button[type=submit]").forEach(function (b) { setTimeout(function () { b.disabled = true; }, 0); });
    });
  });

  // Install as phone app
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
  var deferred = null;
  var btn = document.getElementById("installBtn");
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    if (btn) btn.hidden = false;
  });
  if (btn) btn.addEventListener("click", function () {
    if (!deferred) return;
    deferred.prompt();
    deferred.userChoice.finally(function () { deferred = null; btn.hidden = true; });
  });
})();
