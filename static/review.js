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
      // A decline needs a written reason; the server refuses one without it too.
      var reason = form.querySelector("[name=reason]");
      var needsReason = button.value === "DECLINED" && (!reason || reason.value.trim().length < 10);
      text.textContent =
        "Record “" + (button.dataset.outcome || button.textContent.trim()) + "” on " + form.dataset.claimId +
        "? It's saved under your name" +
        (button.value === "NEEDS_MORE_REVIEW" ? " and stays internal: the claimant isn't notified."
                                              : " and the claimant is notified straight away.") +
        (needsReason ? " A decline needs a written reason (at least 10 characters): add it in the Reason box first." : "");
      // Approving over open review findings needs the acknowledgement box; the server checks it too.
      var openFindings = parseInt(form.dataset.openFindings || "0", 10);
      var ack = form.querySelector("[name=acknowledge]");
      var needsAck = button.value === "APPROVED" && openFindings > 0 && !(ack && ack.checked);
      if (needsAck) {
        text.textContent += " " + openFindings + " review finding" + (openFindings === 1 ? " is" : "s are") +
          " still open: tick \u201cI've checked the open findings\u201d first.";
      }
      ok.disabled = needsReason || needsAck;
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
