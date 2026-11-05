/**
 * Auto-save draft inspections to the server.
 *
 * Watches the inspection form for changes and periodically POSTs the form
 * data to the autosave endpoint. Displays a short status message after each
 * save attempt.
 */
(function () {
  "use strict";

  const AUTOSAVE_DELAY_MS = 3000;

  const form = document.querySelector("form[data-autosave-url]");
  if (!form) return;

  const autosaveUrl = form.dataset.autosaveUrl;
  const statusEl = document.querySelector("[data-testid='autosave-status']");
  let saveTimeout = null;
  let lastSavedAt = null;

  function setStatus(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message ? " — " + message : "";
    statusEl.classList.toggle("has-text-grey", !isError);
    statusEl.classList.toggle("has-text-danger", isError);
  }

  function performAutosave() {
    if (!form) return;

    const data = new FormData(form);
    data.append("action", "save_draft");

    setStatus("Saving…", false);

    fetch(autosaveUrl, {
      method: "POST",
      body: data,
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.error || "Autosave failed.");
        }
        lastSavedAt = new Date();
        setStatus("Draft saved", false);
      })
      .catch((error) => {
        setStatus(error.message || "Autosave failed", true);
      });
  }

  function scheduleAutosave() {
    if (saveTimeout) {
      window.clearTimeout(saveTimeout);
    }
    saveTimeout = window.setTimeout(performAutosave, AUTOSAVE_DELAY_MS);
  }

  form.addEventListener("input", scheduleAutosave);
  form.addEventListener("change", scheduleAutosave);

  // Cancel any pending autosave when the form is submitted normally; the
  // submit action already persists the inspection and a racing autosave could
  // overwrite a finalize with a draft state.
  form.addEventListener("submit", () => {
    if (saveTimeout) {
      window.clearTimeout(saveTimeout);
      saveTimeout = null;
    }
  });

  // Save immediately when the user leaves the page, if there is a pending change.
  window.addEventListener("beforeunload", () => {
    if (saveTimeout) {
      window.clearTimeout(saveTimeout);
      // Synchronous fetch is deprecated in many browsers; best effort.
      if (navigator.sendBeacon && form) {
        const data = new FormData(form);
        data.append("action", "save_draft");
        navigator.sendBeacon(autosaveUrl, data);
      }
    }
  });
})();
