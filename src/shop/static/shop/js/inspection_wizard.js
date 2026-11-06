(() => {
  const form = document.getElementById('inspection-wizard-form');
  if (!form) return;

  const fleetSelect = form.querySelector('select[name="fleet"]');
  const carSelect = form.querySelector('select[name="car"]');
  const submitButton = document.getElementById('wizard-submit');
  const carsUrl = form.dataset.carsUrl;
  const createUrlTemplate = form.dataset.createUrlTemplate;
  const noCarsLabel = form.dataset.noCarsLabel || 'No vehicles available in this fleet';
  const selectFleetLabel = form.dataset.selectFleetLabel || 'Select a fleet first';
  const placeholderUuid = '00000000-0000-0000-0000-000000000000';

  const setCarOptions = (cars) => {
    carSelect.innerHTML = '';
    if (!cars || cars.length === 0) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = noCarsLabel;
      carSelect.appendChild(option);
      carSelect.disabled = true;
      submitButton.disabled = true;
      return;
    }

    carSelect.disabled = false;
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = selectFleetLabel;
    carSelect.appendChild(placeholder);

    cars.forEach((car) => {
      const option = document.createElement('option');
      option.value = car.pk;
      option.textContent = car.name;
      carSelect.appendChild(option);
    });
  };

  const resetCarSelect = () => {
    carSelect.innerHTML = '';
    const option = document.createElement('option');
    option.value = '';
    option.textContent = selectFleetLabel;
    carSelect.appendChild(option);
    carSelect.disabled = true;
    submitButton.disabled = true;
  };

  const updateFormAction = () => {
    const carPk = carSelect.value;
    if (carPk && createUrlTemplate) {
      form.action = createUrlTemplate.replace(placeholderUuid, carPk);
      submitButton.disabled = false;
    } else {
      submitButton.disabled = true;
    }
  };

  const loadCarsForFleet = async (fleetPk) => {
    if (!fleetPk) {
      resetCarSelect();
      return;
    }

    try {
      const response = await fetch(`${carsUrl}?fleet=${encodeURIComponent(fleetPk)}`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('Failed to load vehicles');
      const data = await response.json();
      setCarOptions(data.cars);
      updateFormAction();
    } catch (error) {
      carSelect.innerHTML = '';
      const option = document.createElement('option');
      option.value = '';
      option.textContent = noCarsLabel;
      carSelect.appendChild(option);
      carSelect.disabled = true;
      submitButton.disabled = true;
    }
  };

  if (fleetSelect) {
    fleetSelect.addEventListener('change', () => {
      loadCarsForFleet(fleetSelect.value);
    });

    // Pre-populate when the page is rendered with an initial fleet.
    if (fleetSelect.value) {
      loadCarsForFleet(fleetSelect.value);
    }
  }

  if (carSelect) {
    carSelect.addEventListener('change', updateFormAction);
  }
})();
