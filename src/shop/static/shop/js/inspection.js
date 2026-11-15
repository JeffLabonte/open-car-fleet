/**
 * Inspection checklist UI:
 * - Categories are accordion blocks that can be expanded/collapsed.
 * - Each category has an "Enable section" toggle. Disabling a category
 *   collapses it and resets its points to N/A so the mechanic can focus
 *   only on the sections relevant to the current inspection.
 * - The set of enabled categories is persisted in the hidden
 *   #id_enabled_categories field as JSON.
 */
(function () {
  "use strict";

  const NA_VALUE = "na";
  const DISABLED_CLASS = "is-disabled";
  const ENABLED_CATEGORIES_INPUT_ID = "id_enabled_categories";

  function getEnabledCategoriesInput() {
    return document.getElementById(ENABLED_CATEGORIES_INPUT_ID);
  }

  function getEnabledCategories() {
    const input = getEnabledCategoriesInput();
    if (!input || !input.value) {
      return [];
    }
    try {
      return JSON.parse(input.value);
    } catch {
      return [];
    }
  }

  function setEnabledCategories(categories) {
    const input = getEnabledCategoriesInput();
    if (input) {
      input.value = JSON.stringify(categories);
    }
  }

  function addEnabledCategory(category) {
    const enabled = new Set(getEnabledCategories());
    enabled.add(category);
    setEnabledCategories(Array.from(enabled));
  }

  function removeEnabledCategory(category) {
    const enabled = new Set(getEnabledCategories());
    enabled.delete(category);
    setEnabledCategories(Array.from(enabled));
  }

  function isEmptyPoint(point) {
    const status = point.querySelector('select[name$="-status"]');
    const measurement = point.querySelector('input[name$="-measurement"], select[name$="-measurement"]');
    const notes = point.querySelector('textarea[name$="-notes"]');

    const statusEmpty = !status || status.value === NA_VALUE;
    const measurementEmpty = !measurement || measurement.value.trim() === "";
    const notesEmpty = !notes || notes.value.trim() === "";

    return statusEmpty && measurementEmpty && notesEmpty;
  }

  function resetPoint(point) {
    const status = point.querySelector('select[name$="-status"]');
    const measurement = point.querySelector('input[name$="-measurement"], select[name$="-measurement"]');
    const notes = point.querySelector('textarea[name$="-notes"]');

    if (status) {
      status.value = NA_VALUE;
    }
    if (measurement) {
      measurement.value = "";
    }
    if (notes) {
      notes.value = "";
    }
    updatePointRequiredState(point);
  }

  function updatePointRequiredState(point) {
    const status = point.querySelector('select[name$="-status"]');
    const measurement = point.querySelector('input[name$="-measurement"], select[name$="-measurement"]');
    const labelCell = point.querySelector(".inspection-point__label");
    if (!status || !measurement) {
      return;
    }
    const required = status.value !== NA_VALUE;
    measurement.classList.toggle("is-required", required);
    if (labelCell) {
      labelCell.classList.toggle("is-required", required);
    }
  }

  function setCategoryEnabled(category, enabled) {
    const pointForms = category.querySelectorAll(".inspection-point");
    pointForms.forEach((point) => {
      if (!enabled) {
        resetPoint(point);
      }
    });

    category.classList.toggle(DISABLED_CLASS, !enabled);
  }

  function initCategory(category) {
    const toggle = category.querySelector(".category-enable-toggle");
    if (!toggle) return;

    const categoryCode = category.dataset.category;
    const enabledCategories = getEnabledCategories();
    const isEnabled = enabledCategories.includes(categoryCode);

    toggle.checked = isEnabled;
    const hasErrors = category.querySelector(".help.is-danger") !== null;
    category.open = hasErrors || isEnabled;
    setCategoryEnabled(category, isEnabled);

    category.querySelectorAll(".inspection-point").forEach((point) => {
      const status = point.querySelector('select[name$="-status"]');
      if (status) {
        status.addEventListener("change", () => updatePointRequiredState(point));
      }
      updatePointRequiredState(point);
    });

    toggle.addEventListener("change", () => {
      const enabled = toggle.checked;
      setCategoryEnabled(category, enabled);
      category.open = enabled;
      if (enabled) {
        addEnabledCategory(categoryCode);
      } else {
        removeEnabledCategory(categoryCode);
      }
    });

    // Prevent clicking the toggle from opening/closing the accordion;
    // the toggle has its own dedicated behaviour.
    const toggleLabel = category.querySelector(".inspection-category__toggle");
    if (toggleLabel) {
      toggleLabel.addEventListener("click", (event) => {
        event.stopPropagation();
      });
    }
  }

  function setAllCategoriesEnabled(enabled) {
    const categories = document.querySelectorAll(".inspection-category");
    const categoryCodes = [];
    categories.forEach((category) => {
      const toggle = category.querySelector(".category-enable-toggle");
      if (!toggle) return;
      toggle.checked = enabled;
      setCategoryEnabled(category, enabled);
      category.open = enabled;
      if (enabled) {
        categoryCodes.push(category.dataset.category);
      }
    });
    setEnabledCategories(categoryCodes);
  }

  function initGlobalToggles() {
    const selectAllButton = document.querySelector('[data-testid="select-all-sections"]');
    const deselectAllButton = document.querySelector('[data-testid="deselect-all-sections"]');

    if (selectAllButton) {
      selectAllButton.addEventListener("click", () => setAllCategoriesEnabled(true));
    }
    if (deselectAllButton) {
      deselectAllButton.addEventListener("click", () => setAllCategoriesEnabled(false));
    }
  }

  function refreshFromInput() {
    const categories = document.querySelectorAll(".inspection-category");
    const enabledCategories = getEnabledCategories();
    categories.forEach((category) => {
      const toggle = category.querySelector(".category-enable-toggle");
      if (!toggle) return;
      const enabled = enabledCategories.includes(category.dataset.category);
      toggle.checked = enabled;
      setCategoryEnabled(category, enabled);
      category.querySelectorAll(".inspection-point").forEach(updatePointRequiredState);
    });
  }

  function highlightValidationErrors() {
    const errorMessages = document.querySelectorAll(".help.is-danger");
    if (errorMessages.length === 0) {
      return;
    }
    errorMessages.forEach((message) => {
      const control = message.parentElement && message.parentElement.querySelector("input, select, textarea");
      if (control) {
        control.setAttribute("aria-invalid", "true");
      }
    });

    // Build a summary at the top of the form so the mechanic sees every
    // affected section even when the page is long.
    const form = document.querySelector("form[data-testid='inspection-form']") || document.querySelector("form");
    if (!form) {
      return;
    }
    const existing = form.querySelector("[data-testid='inspection-error-summary']");
    if (existing) {
      existing.remove();
    }
    const summary = document.createElement("div");
    summary.className = "notification is-danger mb-4";
    summary.setAttribute("data-testid", "inspection-error-summary");
    summary.setAttribute("role", "alert");
    summary.tabIndex = -1;
    const count = errorMessages.length;
    summary.textContent = count === 1
      ? "1 checklist item needs your attention before this inspection can be finalized."
      : count + " checklist items need your attention before this inspection can be finalized.";
    const firstError = errorMessages[0];
    const firstControl = firstError.parentElement && firstError.parentElement.querySelector("input, select, textarea");
    if (firstControl && firstControl.id) {
      const link = document.createElement("a");
      link.href = "#" + firstControl.id;
      link.textContent = " Jump to the first invalid item.";
      summary.appendChild(link);
    }
    form.insertBefore(summary, form.firstChild);
    if (typeof summary.focus === "function") {
      summary.focus();
    }
  }

  function init() {
    const categories = document.querySelectorAll(".inspection-category");
    const input = getEnabledCategoriesInput();
    // Only when the hidden input is completely absent or blank (e.g. an old
    // unstructured inspection) do we default to all categories. An explicit
    // empty JSON array ([]) means the mechanic disabled every section.
    if ((!input || input.value === "") && categories.length > 0) {
      setEnabledCategories(Array.from(categories).map((category) => category.dataset.category));
    }
    categories.forEach(initCategory);
    initGlobalToggles();
    highlightValidationErrors();

    document.addEventListener("inspection:restored", refreshFromInput);
    window.InspectionUI = { refreshFromInput };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
