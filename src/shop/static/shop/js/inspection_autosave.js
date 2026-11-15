/**
 * Auto-save draft inspections to the server and to localStorage.
 *
 * - Backs up form state to localStorage on every change so drafts survive
 *   browser reloads, iPad sleep, and session expiration.
 * - Periodically POSTs to the server autosave endpoint.
 * - Shows a restore banner when locally saved changes are newer than the
 *   server-rendered form.
 *
 * Storage key: inspection-draft:<userPk>:<carPk>:<inspectionPk>
 * TTL: 30 minutes.
 */
(function () {
  "use strict";

  const AUTOSAVE_DELAY_MS = 1000;
  const LOCAL_STORAGE_TTL_MS = 30 * 60 * 1000;
  const STORAGE_KEY_PREFIX = "inspection-draft";

  const form = document.querySelector("form[data-autosave-url]");
  if (!form) return;

  const autosaveUrl = form.dataset.autosaveUrl;
  const stagedListUrl = form.dataset.stagedListUrl;
  const userPk = form.dataset.userPk;
  const carPk = form.dataset.carPk;
  const inspectionPk = form.dataset.inspectionPk;
  const statusEl = document.querySelector("[data-testid='autosave-status']");
  if (statusEl) {
    statusEl.setAttribute("role", "status");
    statusEl.setAttribute("aria-live", "polite");
    statusEl.setAttribute("aria-atomic", "true");
  }
  const restoreBanner = document.getElementById("inspection-restore-banner");
  const restoreButton = document.getElementById("inspection-restore-button");
  const discardButton = document.getElementById("inspection-discard-button");

  if (!userPk || !carPk || !inspectionPk) return;

  const storageKey = [STORAGE_KEY_PREFIX, userPk, carPk, inspectionPk].join(":");
  let saveTimeout = null;
  let hasPendingChanges = false;
  let isRestoring = false;

  function getCsrfToken() {
    const input = form.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : "";
  }

  function setStatus(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message ? " — " + message : "";
    statusEl.classList.toggle("has-text-grey", !isError);
    statusEl.classList.toggle("has-text-danger", isError);
  }

  function isExpired(savedAt) {
    return Date.now() - new Date(savedAt).getTime() > LOCAL_STORAGE_TTL_MS;
  }

  function cleanupExpiredEntries() {
    const now = Date.now();
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (key && key.startsWith(STORAGE_KEY_PREFIX + ":")) {
        try {
          const entry = JSON.parse(localStorage.getItem(key) || "null");
          if (!entry || !entry.savedAt || now - new Date(entry.savedAt).getTime() > LOCAL_STORAGE_TTL_MS) {
            localStorage.removeItem(key);
          }
        } catch {
          localStorage.removeItem(key);
        }
      }
    }
  }

  function readLocalDraft() {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return null;
      const entry = JSON.parse(raw);
      if (!entry || !entry.savedAt || isExpired(entry.savedAt)) {
        localStorage.removeItem(storageKey);
        return null;
      }
      return entry;
    } catch {
      localStorage.removeItem(storageKey);
      return null;
    }
  }

  function writeLocalDraft() {
    const data = serializeForm(form);
    const entry = {
      savedAt: new Date().toISOString(),
      fields: data.fields,
      enabledCategories: data.enabledCategories,
      points: data.points,
      stagedAttachments: data.stagedAttachments,
    };
    try {
      localStorage.setItem(storageKey, JSON.stringify(entry));
      cleanupExpiredEntries();
    } catch (e) {
      // localStorage can throw when quota is exceeded; keep working.
      if (console && console.warn) {
        console.warn("Could not write inspection draft to localStorage:", e);
      }
    }
  }

  function clearLocalDraft() {
    localStorage.removeItem(storageKey);
  }

  function serializeForm(formEl) {
    const formData = new FormData(formEl);
    const fields = {};
    const points = {};
    let enabledCategories = "";
    let stagedAttachments = "";

    formData.forEach((value, key) => {
      if (key === "csrfmiddlewaretoken" || key === "attachments") return;
      if (key === "enabled_categories") {
        enabledCategories = value;
        return;
      }
      if (key === "staged_attachments") {
        stagedAttachments = value;
        return;
      }
      if (key.startsWith("points-")) {
        points[key] = value;
        return;
      }
      fields[key] = value;
    });

    return { fields, enabledCategories, points, stagedAttachments };
  }

  function applyFieldValue(field, value) {
    if (!field) return;
    if (field.type === "checkbox") {
      field.checked = value === "on" || value === true || value === "true";
    } else if (field.type === "radio") {
      field.checked = field.value === value;
    } else {
      field.value = value;
    }
  }

  function restoreForm(entry) {
    isRestoring = true;

    Object.entries(entry.fields || {}).forEach(([name, value]) => {
      const field = form.querySelector('[name="' + CSS.escape(name) + '"]');
      applyFieldValue(field, value);
    });

    if (entry.enabledCategories) {
      const enabledInput = form.querySelector('input[name="enabled_categories"]');
      if (enabledInput) enabledInput.value = entry.enabledCategories;
    }

    // Update category toggles before restoring point values so disabled
    // categories reset their points to N/A as the UI expects.
    form.dispatchEvent(new CustomEvent("inspection:restored", { bubbles: true }));

    Object.entries(entry.points || {}).forEach(([name, value]) => {
      const field = form.querySelector('[name="' + CSS.escape(name) + '"]');
      applyFieldValue(field, value);
    });

    if (entry.stagedAttachments) {
      const stagedInput = form.querySelector('input[name="staged_attachments"]');
      if (stagedInput) stagedInput.value = entry.stagedAttachments;
    }

    // Notify the attachment uploader so it can rebuild the preview list.
    if (entry.stagedAttachments && window.AttachmentUploader && window.AttachmentUploader.restoreStaged) {
      window.AttachmentUploader.restoreStaged(entry.stagedAttachments, stagedListUrl);
    }

    // Give other scripts a tick to process the restored values, then re-backup.
    window.setTimeout(() => {
      isRestoring = false;
      writeLocalDraft();
      hasPendingChanges = false;
      setStatus("Restored from this device", false);
    }, 0);
  }

  function isFormDifferentFromEntry(entry) {
    const current = serializeForm(form);
    const currentJson = JSON.stringify(current);
    const entryJson = JSON.stringify({
      fields: entry.fields,
      enabledCategories: entry.enabledCategories,
      points: entry.points,
      stagedAttachments: entry.stagedAttachments,
    });
    return currentJson !== entryJson;
  }

  function showRestoreBanner(entry) {
    if (!restoreBanner) return;
    restoreBanner.classList.remove("is-hidden");

    if (restoreButton) {
      restoreButton.addEventListener("click", () => {
        restoreForm(entry);
        restoreBanner.classList.add("is-hidden");
      }, { once: true });
    }

    if (discardButton) {
      discardButton.addEventListener("click", () => {
        clearLocalDraft();
        restoreBanner.classList.add("is-hidden");
      }, { once: true });
    }
  }

  function maybeOfferRestore() {
    const entry = readLocalDraft();
    if (!entry) return;
    if (!isFormDifferentFromEntry(entry)) {
      // Already matches the server-rendered form; mark clean but keep the
      // backup in case the user refreshes later.
      hasPendingChanges = false;
      return;
    }
    showRestoreBanner(entry);
  }

  function performAutosave() {
    if (!form) return;
    hasPendingChanges = false;

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
          const errors = payload.errors || {};
          const messages = [];
          Object.keys(errors).forEach((field) => {
            const fieldErrors = Array.isArray(errors[field]) ? errors[field] : [errors[field]];
            fieldErrors.forEach((message) => {
              messages.push(field === "points" ? message : field + ": " + message);
              const control = form.querySelector('[name="' + CSS.escape(field) + '"]');
              if (control) {
                control.setAttribute("aria-invalid", "true");
                let help = control.parentElement && control.parentElement.querySelector(".help.is-danger.autosave-error");
                if (!help) {
                  help = document.createElement("p");
                  help.className = "help is-danger autosave-error";
                  if (control.parentElement) control.parentElement.appendChild(help);
                }
                help.textContent = Array.isArray(errors[field]) ? errors[field].join(" ") : String(errors[field]);
              }
            });
          });
          const summary = messages.length ? messages.join("; ") : (payload.error || "Autosave failed.");
          throw new Error(summary);
        }
        setStatus("Draft saved", false);
        clearLocalDraft();
        // Clear any stale autosave error markers on success.
        form.querySelectorAll(".autosave-error").forEach((el) => el.remove());
        form.querySelectorAll("[aria-invalid='true']").forEach((el) => el.removeAttribute("aria-invalid"));
      })
      .catch((error) => {
        setStatus(error.message || "Autosave failed", true);
        // Keep localStorage backup since server save failed.
      });
  }

  function scheduleAutosave() {
    if (isRestoring) return;
    hasPendingChanges = true;
    writeLocalDraft();

    if (saveTimeout) {
      window.clearTimeout(saveTimeout);
    }
    saveTimeout = window.setTimeout(performAutosave, AUTOSAVE_DELAY_MS);
  }

  function sendBeaconSave() {
    if (!form || !navigator.sendBeacon) return;
    const data = new FormData(form);
    data.append("action", "save_draft");
    const csrfToken = getCsrfToken();
    // sendBeacon does not support custom headers, so include CSRF in the body.
    if (csrfToken && !data.get("csrfmiddlewaretoken")) {
      data.append("csrfmiddlewaretoken", csrfToken);
    }
    navigator.sendBeacon(autosaveUrl, data);
  }

  // Listeners that back up to localStorage and schedule server saves.
  form.addEventListener("input", scheduleAutosave);
  form.addEventListener("change", (event) => {
    // Avoid reacting to programmatic changes during restore.
    if (isRestoring) return;
    scheduleAutosave();
    // For selects/checkboxes, save to server quickly.
    if (event.target && (event.target.tagName === "SELECT" || event.target.type === "checkbox" || event.target.type === "radio")) {
      if (saveTimeout) window.clearTimeout(saveTimeout);
      saveTimeout = window.setTimeout(performAutosave, 250);
    }
  });

  // Save on blur so mechanics don't lose work when switching apps/fields.
  form.addEventListener("focusout", (event) => {
    if (isRestoring) return;
    if (event.target && ["INPUT", "TEXTAREA", "SELECT"].includes(event.target.tagName)) {
      writeLocalDraft();
      if (saveTimeout) window.clearTimeout(saveTimeout);
      saveTimeout = window.setTimeout(performAutosave, 250);
    }
  });

  // Save immediately when the form is submitted normally.
  form.addEventListener("submit", () => {
    if (saveTimeout) {
      window.clearTimeout(saveTimeout);
      saveTimeout = null;
    }
    clearLocalDraft();
  });

  // Critical for iPad sleep / tab switch.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      writeLocalDraft();
      sendBeaconSave();
    } else if (document.visibilityState === "visible") {
      // Re-check for local backup in case another tab or a reload happened.
      maybeOfferRestore();
    }
  });

  window.addEventListener("pagehide", () => {
    writeLocalDraft();
    sendBeaconSave();
  });

  // Public API so attachments.js can tell us when staged attachments change.
  window.InspectionAutosave = {
    backup: writeLocalDraft,
    clear: clearLocalDraft,
  };

  // Initial blank draft save, plus restore banner check.
  writeLocalDraft();
  scheduleAutosave();
  maybeOfferRestore();
})();
