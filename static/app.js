// The notification bell is a <details> element, so it opens and closes with no
// script at all. This only adds the two behaviors <details> lacks: closing on a
// click anywhere outside it, and closing on Escape.
document.addEventListener("click", function (event) {
  document.querySelectorAll("details.bell[open]").forEach(function (bell) {
    if (!bell.contains(event.target)) bell.removeAttribute("open");
  });
});
document.addEventListener("keydown", function (event) {
  if (event.key !== "Escape") return;
  document.querySelectorAll("details.bell[open]").forEach(function (bell) {
    bell.removeAttribute("open");
    bell.querySelector("summary").focus();
  });
});

// Keep the bell fresh without a page reload: every 30 seconds, while this tab is visible and
// the bell is closed, ask the server for the bell's current HTML and swap it in only if it
// changed. A plain poll -- a claim changes status a few times over days, so nothing fancier
// (websockets, push) is worth it. Any failure is ignored; the next page load still works.
(function () {
  var INTERVAL_MS = 30000;
  function refreshBell() {
    var bell = document.querySelector("details.bell");
    if (!bell || bell.open || document.hidden) return;
    fetch("/notifications/bell", { credentials: "same-origin", cache: "no-store" })
      .then(function (response) { return response.status === 200 ? response.text() : null; })
      .then(function (html) {
        var current = document.querySelector("details.bell");
        if (!html || !current || current.open) return;
        if (current.outerHTML.replace(/\s+/g, " ").trim() === html.replace(/\s+/g, " ").trim()) return;
        current.outerHTML = html;
      })
      .catch(function () {});
  }
  if (document.querySelector("details.bell")) setInterval(refreshBell, INTERVAL_MS);
})();
