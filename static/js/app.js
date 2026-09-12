/* ==========================================================================
   Gym Log - client side. No framework, no build step, no CDN.
   Everything degrades to plain form posts if this file fails to load.
   ========================================================================== */

(function () {
  "use strict";

  var page = window.GYM_PAGE || "";

  /* Small helpers ------------------------------------------------------ */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key);
      else localStorage.setItem(key, value);
    } catch (e) { /* private mode - just carry on without persistence */ }
    return null;
  }

  /* Haptics -------------------------------------------------------------

     iOS has never implemented navigator.vibrate. What does work: clicking the
     LABEL of a native <input type="checkbox" switch> (Safari 17.4+) runs the
     control's own feedback and fires the Taptic Engine. It has to happen
     synchronously inside a real gesture, so we call it from pointerdown -
     which also makes it feel instant rather than lagging the tap. */

  var hapticLabel = $("#haptic-lb");
  var canVibrate = typeof navigator.vibrate === "function";
  var canSwitch = (function () {
    try {
      var probe = document.createElement("input");
      probe.type = "checkbox";
      return "switch" in probe;
    } catch (e) { return false; }
  })();

  function tap() {
    if (canVibrate) { try { navigator.vibrate(10); } catch (e) {} return; }
    if (canSwitch && hapticLabel) { try { hapticLabel.click(); } catch (e) {} }
  }

  /* Confirm destructive form submits ----------------------------------- */

  document.addEventListener("submit", function (ev) {
    var message = ev.target && ev.target.dataset && ev.target.dataset.confirm;
    if (message && !window.confirm(message)) ev.preventDefault();
  });

  /* Auto-dismiss flash messages ---------------------------------------- */

  $$(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity .3s, transform .3s";
      el.style.opacity = "0";
      el.style.transform = "translateY(-10px)";
      setTimeout(function () { el.remove(); }, 320);
    }, 3200);
  });

  /* ====================================================================
     PICKER - tap exercises in the order you will train them
     ==================================================================== */

  if (page === "picker") {
    var grid = $("#grid");
    var orderInput = $("#order");
    var fabWrap = $("#fabwrap");
    var fabCount = $("#fabcount");
    var form = $("#pickform");

    if (grid && orderInput) {
      var bpField = form && form.querySelector('[name="body_part"]');
      var bodyPart = (bpField && bpField.value) || "x";
      // Editing an old session must not share a draft slot with today's
      // unsubmitted pick, so the workout id goes in the key when present.
      var editing = grid.dataset.preselect ? "edit" + (form.action.match(/\/workout\/(\d+)\//) || [])[1] : "new";
      var draftKey = "gymlog:draft:" + document.body.dataset.date + ":" + bodyPart + ":" + editing;
      var picked = [];

      function render() {
        $$(".tile", grid).forEach(function (tile) {
          var id = parseInt(tile.dataset.id, 10);
          var at = picked.indexOf(id);
          var on = at !== -1;
          tile.setAttribute("aria-pressed", on ? "true" : "false");
          var badge = $(".order", tile);
          if (badge) badge.textContent = on ? String(at + 1) : "";
        });

        orderInput.value = picked.join(",");
        if (fabCount) fabCount.textContent = String(picked.length);
        if (fabWrap) fabWrap.hidden = picked.length === 0;

        // The "tap them in order" hint has done its job once you have.
        var hint = $("#hint");
        if (hint) hint.hidden = picked.length > 0;

        store(draftKey, picked.length ? picked.join(",") : null);
      }

      function toggle(id) {
        var at = picked.indexOf(id);
        if (at === -1) picked.push(id);
        else picked.splice(at, 1);
        render();
      }

      grid.addEventListener("pointerdown", function (ev) {
        if (ev.target.closest(".tile")) tap();
      }, { passive: true });

      grid.addEventListener("click", function (ev) {
        var tile = ev.target.closest(".tile");
        if (!tile) return;
        toggle(parseInt(tile.dataset.id, 10));
      });

      /* Restore: an edit-in-progress wins, otherwise an unsubmitted draft. */
      var preselect = (grid.dataset.preselect || "").trim();
      var source = preselect || store(draftKey) || "";
      if (source) {
        var known = {};
        $$(".tile", grid).forEach(function (t) { known[t.dataset.id] = true; });
        picked = source.split(",")
          .filter(function (s) { return s && known[s]; })
          .map(function (s) { return parseInt(s, 10); });
      }
      render();

      /* Clear the saved draft once the session is actually created. */
      if (form) {
        form.addEventListener("submit", function () { store(draftKey, null); });
      }

      /* "Repeat this session" - preselect last time's exercises in order. */
      var repeatBtn = $("[data-repeat]");
      if (repeatBtn) {
        repeatBtn.addEventListener("click", function () {
          var ids = {};
          $$(".tile", grid).forEach(function (t) { ids[t.dataset.id] = true; });
          picked = repeatBtn.dataset.repeat.split(",")
            .filter(function (s) { return s && ids[s]; })
            .map(function (s) { return parseInt(s, 10); });
          render();
          var details = repeatBtn.closest("details");
          if (details) details.open = false;
          grid.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }
    }

    /* Tile density - 3 big tiles per row, or 4 small ones so a long list
       fits on one screen with no scrolling. */
    var densityBtn = $("#density");
    if (densityBtn && grid) {
      var applyDensity = function (cols) {
        grid.classList.toggle("cols4", cols === "4");
        var label = $("#density-label");
        if (label) label.textContent = cols === "4" ? "4" : "3";
      };
      var saved = store("gymlog:cols") || "3";
      applyDensity(saved);
      densityBtn.addEventListener("click", function () {
        var next = grid.classList.contains("cols4") ? "3" : "4";
        store("gymlog:cols", next);
        applyDensity(next);
      });
    }
  }

  /* ====================================================================
     SESSION - tick exercises off as you finish them
     ==================================================================== */

  if (page === "session") {
    var steps = $("#steps");

    if (steps) {
      steps.addEventListener("pointerdown", function (ev) {
        if (ev.target.closest(".step")) tap();
      }, { passive: true });

      steps.addEventListener("click", function (ev) {
        var step = ev.target.closest(".step");
        if (!step || step.dataset.busy === "1") return;

        step.dataset.busy = "1";
        var wasDone = step.classList.contains("done");

        /* Flip immediately - the gym wifi is not the user's problem. */
        step.classList.toggle("done");
        updateProgress();

        fetch(step.dataset.url, {
          method: "POST",
          headers: { "X-Requested-With": "fetch" },
          credentials: "same-origin"
        })
          .then(function (r) {
            if (!r.ok) throw new Error(r.status);
            return r.json();
          })
          .then(function (data) {
            var stamp = $(".stamp", step);
            if (stamp) {
              stamp.textContent = data.done_at
                ? "Done " + data.clock
                : (stamp.dataset.idle || "Tap when finished");
            }
          })
          .catch(function () {
            /* Roll back so the screen never lies about what is saved. */
            step.classList.toggle("done", wasDone);
            updateProgress();
            alert("Could not save that - check your connection and try again.");
          })
          .then(function () { step.dataset.busy = "0"; });
      });
    }

    function updateProgress() {
      var all = $$(".step");
      var done = all.filter(function (s) { return s.classList.contains("done"); }).length;
      var bar = $("#progress");
      if (bar) bar.style.width = all.length ? (done / all.length * 100) + "%" : "0%";
      var count = $("#fabcount");
      if (count) count.textContent = done + "/" + all.length;
      var label = $("#donecount");
      if (label) label.textContent = done + " of " + all.length + " done";
    }

    /* Live elapsed time since the session started. */
    var elapsed = $("#elapsed");
    if (elapsed) {
      var started = new Date(elapsed.dataset.start);
      var tick = function () {
        var mins = Math.max(0, Math.round((Date.now() - started.getTime()) / 60000));
        if (isNaN(mins)) { elapsed.textContent = ""; return; }
        elapsed.textContent = mins < 60
          ? mins + " min in"
          : Math.floor(mins / 60) + "h " + (mins % 60) + "m in";
      };
      tick();
      setInterval(tick, 30000);
    }
  }

  /* ====================================================================
     EXERCISE FORM - show the photo you just picked before uploading
     ==================================================================== */

  if (page === "form") {
    var input = $("#photoinput");
    if (input) {
      input.addEventListener("change", function () {
        var file = input.files && input.files[0];
        if (!file) return;
        var label = $("#filelabel");
        var preview = $("#preview");
        var blank = $("#preview-blank");

        if (label) label.textContent = file.name;

        /* HEIC will not render in an <img>, so only preview what we can. */
        if (!/^image\/(jpeg|png|gif|webp)$/i.test(file.type)) return;

        var url = URL.createObjectURL(file);
        if (preview) {
          preview.src = url;
          preview.hidden = false;
          preview.onload = function () { URL.revokeObjectURL(url); };
        }
        // Inline display:grid beats the UA [hidden] rule, so clear it directly.
        if (blank) blank.style.display = "none";
      });
    }
  }

  /* ====================================================================
     LOGIN - PIN pad
     ==================================================================== */

  if (page === "login") {
    var pin = "";
    var value = $("#pinvalue");
    var dots = $("#dots");

    // The field is a real text input so the page still works without this
    // script. Now that the keypad is running, get it out of the way.
    if (value) {
      value.type = "hidden";
      value.removeAttribute("style");
    }

    function paint() {
      if (!dots) return;
      dots.innerHTML = "";
      for (var i = 0; i < Math.max(4, pin.length); i++) {
        var dot = document.createElement("i");
        if (i < pin.length) dot.className = "on";
        dots.appendChild(dot);
      }
      if (value) value.value = pin;
    }

    $$(".pinpad button[data-k]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var key = btn.dataset.k;
        if (key === "del") pin = pin.slice(0, -1);
        else if (pin.length < 12) pin += key;
        paint();
      });
    });

    paint();
  }
})();
