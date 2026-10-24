// Claim form helpers. Everything here is a convenience on top of the server:
// app.py + validation.py re-check every field on submit, so a browser with
// this script disabled still gets the same rules, just after a round trip.
(function () {
  var form = document.getElementById("claim_form");
  if (!form) return;

  // Keep the per-type document hint in step with the selected tile.
  var hint = document.getElementById("claim_type_hint");
  form.querySelectorAll("input[name=claim_type]").forEach(function (radio) {
    radio.addEventListener("change", function () {
      hint.textContent = radio.dataset.hint;
    });
  });

  // Uploads: the limits <input accept> can't express (file count, size), plus
  // the type check itself, since accept only filters the picker.
  var files = document.getElementById("files");
  var list = document.getElementById("file_list");
  var box = document.getElementById("file_errors");
  var maxFiles = parseInt(form.dataset.maxFiles, 10);
  var maxBytes = parseInt(form.dataset.maxFileBytes, 10);
  var allowed = form.dataset.extensions.split(",");

  function check() {
    var problems = [];
    var chosen = Array.prototype.slice.call(files.files);
    if (chosen.length > maxFiles) {
      problems.push("That's " + chosen.length + " files. The limit is " + maxFiles + " per claim.");
    }
    chosen.forEach(function (f) {
      var dot = f.name.lastIndexOf(".");
      var ext = dot >= 0 ? f.name.slice(dot).toLowerCase() : "";
      if (allowed.indexOf(ext) < 0) problems.push(f.name + ": this file type isn't accepted.");
      if (f.size > maxBytes) problems.push(f.name + ": larger than " + Math.round(maxBytes / 1048576) + " MB.");
    });

    list.innerHTML = "";
    chosen.forEach(function (f) {
      var li = document.createElement("li");
      li.textContent = f.name + " (" + (f.size / 1024).toFixed(1) + " KB)";
      list.appendChild(li);
    });

    box.innerHTML = "";
    if (problems.length) {
      var ul = document.createElement("ul");
      problems.forEach(function (p) {
        var li = document.createElement("li");
        li.textContent = p;
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    box.hidden = problems.length === 0;
    // Blocks submission natively until the selection is fixed.
    files.setCustomValidity(problems.length ? problems[0] : "");
  }
  files.addEventListener("change", check);

  // Readiness: the button stays off until every part of the claim is in -- claim
  // type, policy ID, a valid incident date, a description and at least one
  // document. This is a form-only rule: the server still accepts a partial claim
  // from other clients (scripts, seed data) and answers NEEDS_INFORMATION, which
  // is how main.py's completeness checker is meant to be used.
  var panel = document.getElementById("readiness");
  var status = document.getElementById("ready_status");
  var button = document.getElementById("submit_button");
  var labels = {};
  panel.querySelectorAll("li[data-check]").forEach(function (li) {
    labels[li.dataset.check] = li;
  });
  var names = {
    claim_type: "claim type", policy_id: "policy ID", incident_date: "incident date",
    description: "description", files: "documents"
  };

  function valid(id) {
    var el = document.getElementById(id);
    return el.value.trim() !== "" && el.checkValidity();
  }

  var submitting = false;

  function readiness() {
    var state = {
      claim_type: !!form.querySelector("input[name=claim_type]:checked"),
      policy_id: valid("policy_id"),
      incident_date: valid("incident_date"),
      description: valid("description"),
      files: files.files.length > 0 && files.validity.valid
    };
    var missing = [];
    Object.keys(state).forEach(function (key) {
      labels[key].classList.toggle("done", state[key]);
      if (!state[key]) missing.push(names[key]);
    });
    var complete = missing.length === 0;
    button.disabled = !complete || submitting;
    button.textContent = submitting ? "Submitting…" : "Submit my claim";
    status.textContent = complete ? "Everything's here." : "Still needed: " + missing.join(", ") + ".";
    panel.classList.toggle("complete", complete);
  }

  panel.hidden = false;
  ["policy_id", "incident_date", "description"].forEach(function (id) {
    document.getElementById(id).addEventListener("input", readiness);
  });
  form.querySelectorAll("input[name=claim_type]").forEach(function (radio) {
    radio.addEventListener("change", readiness);
  });
  files.addEventListener("change", readiness);

  // One click, one claim: lock the button the moment the form is sent, so a
  // double-click (or an impatient second click) can't file it twice.
  form.addEventListener("submit", function () {
    submitting = true;
    button.disabled = true;
    button.textContent = "Submitting…";
  });
  // Coming back via the browser's Back button restores this page as it was left.
  window.addEventListener("pageshow", function () {
    submitting = false;
    readiness();
  });
  readiness();
})();
