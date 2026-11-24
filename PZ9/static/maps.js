/* Map picker and read-only route preview. */
const initialView = [54.7388, 55.9560];
const pointColors = { pickup: '#008e84', destination: '#185fc8' };

function readPoint(value) {
  if (!value) return null;
  const coordinates = value.split(',').map(Number);
  return coordinates.length === 2 && coordinates.every(Number.isFinite) ? coordinates : null;
}

function addPoint(map, coordinates, kind) {
  const label = kind === 'pickup' ? 'Место посадки' : 'Пункт назначения';
  return L.circleMarker(coordinates, {
    radius: 9,
    color: '#fff',
    weight: 3,
    fillColor: pointColors[kind],
    fillOpacity: 1,
  }).addTo(map).bindTooltip(label);
}

function fitPoints(map, points) {
  if (points.length === 1) {
    map.setView(points[0], 15);
  } else if (points.length > 1) {
    map.fitBounds(points, { padding: [25, 25], maxZoom: 16 });
  }
}

function enablePicker(map, form, status) {
  const controls = [...form.querySelectorAll('[data-pick-point]')];
  const submit = form.querySelector('button[type="submit"]');
  const useCenter = form.querySelector('[data-map-center]');
  const places = {
    pickup: { point: form.elements.pickup_point, address: form.elements.from },
    destination: { point: form.elements.dropoff_point, address: form.elements.to },
  };
  let active = places.pickup.point.value && !places.destination.point.value ? 'destination' : 'pickup';
  let submitting = false;

  function refresh() {
    controls.forEach(button => button.setAttribute('aria-pressed', button.dataset.pickPoint === active));
    const ready = Object.values(places).every(place => place.point.value || place.address.value.trim());
    submit.disabled = !ready || submitting;
    submit.textContent = submitting ? 'Строим маршрут…' : 'Рассчитать поездку';
    status.textContent = ready ? 'Можно рассчитать поездку.' : 'Отметьте точку на карте или введите адрес.';
    for (const [kind, place] of Object.entries(places)) {
      form.querySelector(`[data-point-value="${kind}"]`).textContent = place.hint || '';
    }
  }

  async function lookupAddress(place, point) {
    const lookup = new AbortController();
    place.lookup = lookup;
    place.hint = 'Уточняем адрес…';
    refresh();
    try {
      const response = await fetch('/api/map/address?' + new URLSearchParams({ point }), { signal: lookup.signal });
      if (!response.ok) return;
      const result = await response.json();
      if (place.lookup === lookup && result.label) place.address.value = result.label;
    } catch {
      // A selected point remains usable when the address lookup fails.
    } finally {
      if (place.lookup === lookup) {
        place.lookup = null;
        place.hint = place.address.value ? '' : 'Точка выбрана. Название улицы недоступно.';
        refresh();
      }
    }
  }

  function choosePoint(latLng) {
    const location = latLng.wrap();
    const coordinates = [location.lat, location.lng].map(value => Number(value.toFixed(6)));
    if (Math.abs(coordinates[0]) > 85) return;
    const kind = active;
    const place = places[kind];
    place.lookup?.abort();
    place.point.value = coordinates.join(',');
    place.address.value = '';
    if (place.marker) map.removeLayer(place.marker);
    place.marker = addPoint(map, coordinates, kind);
    if (kind === 'pickup' && !places.destination.point.value && !places.destination.address.value.trim()) {
      active = 'destination';
    }
    lookupAddress(place, place.point.value);
  }

  const points = [];
  for (const [kind, place] of Object.entries(places)) {
    const coordinates = readPoint(place.point.value);
    if (coordinates) {
      place.marker = addPoint(map, coordinates, kind);
      points.push(coordinates);
    }
    place.address.addEventListener('input', () => {
      place.lookup?.abort();
      place.lookup = null;
      place.hint = '';
      place.point.value = '';
      if (place.marker) map.removeLayer(place.marker);
      place.marker = null;
      refresh();
    });
  }
  controls.forEach(button => button.addEventListener('click', () => {
    active = button.dataset.pickPoint;
    refresh();
  }));
  map.on('click', event => choosePoint(event.latlng));
  useCenter.disabled = false;
  useCenter.addEventListener('click', () => choosePoint(map.getCenter()));
  form.addEventListener('submit', () => {
    submitting = true;
    refresh();
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    refresh();
  });
  fitPoints(map, points);
  refresh();
}

function showMap(element) {
  const tileStatus = document.createElement('p');
  tileStatus.className = 'map-connection';
  tileStatus.setAttribute('role', 'status');
  element.appendChild(tileStatus);
  if (!window.L) {
    tileStatus.textContent = 'Карта не загрузилась. Можно ввести адреса вручную.';
    return;
  }
  const options = JSON.parse(element.dataset.routeMap);
  const map = L.map(element, { zoomControl: false, scrollWheelZoom: false }).setView(initialView, 14);
  L.control.zoom({ zoomInTitle: 'Приблизить', zoomOutTitle: 'Отдалить' }).addTo(map);
  const tile = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  let tileLoaded = false;
  tile.on('tileload', () => { tileLoaded = true; tileStatus.textContent = ''; });
  tile.on('load', () => {
    if (!tileLoaded) tileStatus.textContent = 'Подложка карты недоступна. Проверьте подключение к интернету.';
  });
  if (options.geometry) {
    L.polyline(options.geometry, { color: '#186ce1', weight: 5 }).addTo(map);
    addPoint(map, options.pickup, 'pickup');
    addPoint(map, options.destination, 'destination');
    fitPoints(map, [...options.geometry, options.pickup, options.destination]);
    map.attributionControl.addAttribution('<a href="https://project-osrm.org/">OSRM</a>');
  }
  const form = element.closest('[data-map-picker]');
  if (form) enablePicker(map, form, form.querySelector('[data-map-status]'));
}

document.querySelectorAll('[data-route-map]').forEach(showMap);
