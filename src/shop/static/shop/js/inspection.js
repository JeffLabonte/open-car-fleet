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
    const measurement = point.querySelector('input[name$="-measurement"]');
    const notes = point.querySelector('textarea[name$="-notes"]');

    const statusEmpty = !status || status.value === NA_VALUE;
    const measurementEmpty = !measurement || measurement.value.trim() === "";
    const notesEmpty = !notes || notes.value.trim() === "";

    return statusEmpty && measurementEmpty && notesEmpty;
  }

  function resetPoint(point) {
    const status = point.querySelector('select[name$="-status"]');
    const measurement = point.querySelector('input[name$="-measurement"]');
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
    // Sections are enabled by default so mechanics can see the whole checklist.
    const isEnabled = enabledCategories.length === 0 || enabledCategories.includes(categoryCode);

    toggle.checked = isEnabled;
    category.open = isEnabled;
    setCategoryEnabled(category, isEnabled);

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

  function init() {
    const categories = document.querySelectorAll(".inspection-category");
    // If no enabled-categories state exists yet, default to all categories enabled.
    if (getEnabledCategories().length === 0 && categories.length > 0) {
      setEnabledCategories(Array.from(categories).map((category) => category.dataset.category));
    }
    categories.forEach(initCategory);
    initGlobalToggles();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
