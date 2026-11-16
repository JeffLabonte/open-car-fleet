export function isSafeCarPk(value) {
  return typeof value === 'string'
    && (/^[0-9a-fA-F-]{36}$/.test(value) || /^\d+$/.test(value));
}

export function buildFleetCarsUrl(carsUrl, fleetPk) {
  const separator = carsUrl.includes('?') ? '&' : '?';
  return `${carsUrl}${separator}fleet=${encodeURIComponent(fleetPk)}`;
}
