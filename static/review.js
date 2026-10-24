// Adjuster review page: a confirm step before a decision is recorded. Decisions
// are final entries on the claim, so a stray click shouldn't file one. Without
// JavaScript the decision buttons post directly, exactly as before.
(function () {
  var form = document.getElementById("decision_form");
  var dialog = document.getElementById("confirm_dialog");
  if (!form || !dialog || typeof dialog.showModal !== "function") return;

  var text = document.getElementById("confirm_text");
  var ok = document.getElementById("confirm_ok");
  var cancel = document.getElementById("confirm_cancel");
  var pending = null;
  var sent = false;

  form.querySelectorAll("button[name=decision]").forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.preventDefault();
      if (sent) return;
      pending = button;
      text.textContent =
        "Record “" + button.textContent.trim() + "” on " + form.dataset.claimId +
        "? It's saved under your name and the claimant is notified straight away.";
      ok.className = "btn " + (button.value === "APPROVED" ? "approve" : button.value === "DECLINED" ? "decline" : "secondary");
      dialog.showModal();
      cancel.focus();
    });
  });

  cancel.addEventListener("click", function () {
    pending = null;
    dialog.close();
  });

  // One decision per confirm: lock everything the moment it's sent, so a
  // double-click can't record the same decision twice.
  ok.addEventListener("click", function () {
    if (!pending || sent) return;
    sent = true;
    ok.disabled = true;
    cancel.disabled = true;
    form.requestSubmit(pending);
  });

  // Back button restores the page as it was left; start fresh.
  window.addEventListener("pageshow", function () {
    sent = false;
    ok.disabled = false;
    cancel.disabled = false;
    if (dialog.open) dialog.close();
  });
})();
