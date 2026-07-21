const $ = selector => document.querySelector(selector);
const listFrom = data => Array.isArray(data) ? data : (data?.courthouses || data?.records || data?.items || []);
let courts = [];

async function init() {
  try {
    const response = await fetch('../data/courthouses.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    courts = listFrom(await response.json());
    if (!courts.length) throw new Error('Empty courthouse directory');
    render();
  } catch {
    $('#courtGrid').innerHTML = '<p class="empty">Run tools/collect-new.cmd to generate courthouse data.</p>';
  }
  $('#courtSearch').oninput = render;
  $('#courtType').onchange = render;
}

function render() {
  const query = $('#courtSearch').value.toLowerCase();
  const type = $('#courtType').value;
  const rows = courts.filter(court =>
    (!type || court.type === type) &&
    (!query || [court.name, court.address, court.city, court.registry, court.type]
      .filter(Boolean).join(' ').toLowerCase().includes(query))
  );
  $('#courtGrid').innerHTML = rows.map(court => `<article class="court-card">
    <span class="mini">${court.type || 'Courthouse'}</span>
    <h3>${court.name}</h3>
    <p>${court.address || court.city || ''}</p>
    <p><strong>Phone:</strong> ${court.phone || 'Not listed'}</p>
    <a class="primary link-btn" href="detail.html?court=${encodeURIComponent(court.slug)}">View courthouse data</a>
  </article>`).join('') || '<p class="empty">No matching courthouses.</p>';
}

init();
