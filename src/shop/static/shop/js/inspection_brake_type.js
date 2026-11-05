/**
 * Show/hide rear brake items based on the selected rear brake type.
 *
 * When the rear axle uses disc brakes, only rear disc/pad fields are shown.
 * When it uses drum brakes, only rear drum/shoe fields are shown.
 * Hidden fields are reset to N/A so only the relevant type is saved.
 */
(function () {
  "use strict";

  const NA_VALUE = "na";
  const HIDDEN_CLASS = "is-hidden";

  const REAR_BRAKE_TYPE_CODE = "rear_brake_type";
  const DISC_CODES = [
    "pad_rear_right",
    "disc_rear_right",
    "pad_rear_left",
    "disc_rear_left",
  ];
  const DRUM_CODES = [
    "shoe_rear_right",
    "drum_rear_right",
    "shoe_rear_left",
    "drum_rear_left",
  ];

  function getPointByCode(code) {
    return document.querySelector(
      `[data-testid="inspection-point-${code}"]`
    );
  }

  function getRearBrakeTypeSelect() {
    const point = getPointByCode(REAR_BRAKE_TYPE_CODE);
    if (!point) return null;
    return point.querySelector("[data-rear-brake-type-select]");
  }

  function resetPoint(point) {
    if (!point) return;
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
  }

  function updateVisibility() {
    const select = getRearBrakeTypeSelect();
    if (!select) return;

    const selectedType = select.value.toLowerCase();
    const showDisc = selectedType === "disc" || selectedType === "disque";
    const showDrum = selectedType === "drum" || selectedType === "tambour";

    DISC_CODES.forEach((code) => {
      const point = getPointByCode(code);
      if (!point) return;
      if (showDisc) {
        point.classList.remove(HIDDEN_CLASS);
      } else {
        point.classList.add(HIDDEN_CLASS);
        resetPoint(point);
      }
    });

    DRUM_CODES.forEach((code) => {
      const point = getPointByCode(code);
      if (!point) return;
      if (showDrum) {
        point.classList.remove(HIDDEN_CLASS);
      } else {
        point.classList.add(HIDDEN_CLASS);
        resetPoint(point);
      }
    });
  }

  function init() {
    const select = getRearBrakeTypeSelect();
    if (!select) return;

    updateVisibility();
    select.addEventListener("change", updateVisibility);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
