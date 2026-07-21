(() => {
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  let payload = {cases:[], judgments:[], reviews:[]};
  let currentRows = [];
  let currentType = 'cases';
  let filterTimer = 0;

  const labels = {
    review_id:'Review ID', entity_type:'Record type', entity_id:'Record ID', reason:'Review needed', severity:'Priority', source_document_id:'Source document', status:'Status', created_at:'Created', resolved_at:'Resolved', resolution_notes:'Resolution notes',
    case_title:'Case', court_file_number:'Court file', courthouse:'Courthouse', courthouse_slug:'Courthouse', city:'City', location:'Location', legal_status:'Legal status', final_outcome:'Final outcome', verification_state:'Verification', participant_name:'Person', person_name:'Person', display_name:'Person', full_name:'Person', exact_name:'Person', aliases:'Aliases',
    title:'Judgment', citation:'Citation', decision_date:'Decision date', source_url:'Official source', outcome:'Outcome', sentence:'Sentence', publication_restrictions:'Publication restrictions'
  };

  const asRows = (value, preferredKeys = []) => {
    if (Array.isArray(value)) return value.filter(item => item && typeof item === 'object');
    if (!value || typeof value !== 'object') return [];
    for (const key of preferredKeys) {
      if (Array.isArray(value[key])) return value[key].filter(item => item && typeof item === 'object');
    }
    for (const nested of Object.values(value)) {
      if (Array.isArray(nested)) return nested.filter(item => item && typeof item === 'object');
    }
    return [];
  };

  const usefulEntries = row => Object.entries(row || {}).filter(([key,value]) => value !== null && value !== '' && value !== undefined && !['raw_json','search_text','search_normalized'].includes(key));
  const prettyValue = (key, value) => {
    if (Array.isArray(value)) return value.map(item => typeof item === 'object' ? JSON.stringify(item) : item).join(', ') || '—';
    if (typeof value === 'object' && value) return JSON.stringify(value, null, 2);
    if (/_at$|_date$/.test(key) && value) {
      const date = new Date(value);
      if (!Number.isNaN(date.valueOf())) return date.toLocaleString();
    }
    return String(value ?? '—');
  };
  const titleFor = (row, type) => {
    if (type === 'reviews') return row.reason || `${row.entity_type || 'Record'} review`;
    if (type === 'judgments') return row.case_title || row.title || row.citation || 'Published judgment';
    return row.case_title || row.court_file_number || row.title || row.display_name || row.full_name || row.person_name || row.participant_name || 'Case record';
  };
  const sourceLink = row => {
    const url = row.source_url || row.url || row.official_url;
    return url ? `<a class="pill report-source-pill" href="${esc(url)}" target="_blank" rel="noopener">Open source ↗</a>` : '';
  };
  const card = (row, type) => {
    const entries = usefulEntries(row);
    return `<article class="report-item report-card"><div class="report-card-head"><div><span class="eyebrow">${esc(type === 'reviews' ? (row.severity || 'review') : type)}</span><h3>${esc(titleFor(row,type))}</h3></div>${sourceLink(row)}</div><dl class="report-fields">${entries.map(([key,value]) => `<div><dt>${esc(labels[key] || key.replaceAll('_',' '))}</dt><dd>${esc(prettyValue(key,value))}</dd></div>`).join('')}</dl></article>`;
  };

  const searchableText = row => {
    const values = [];
    const walk = value => {
      if (value === null || value === undefined) return;
      if (Array.isArray(value)) { value.forEach(walk); return; }
      if (typeof value === 'object') { Object.values(value).forEach(walk); return; }
      values.push(String(value));
    };
    walk(row);
    return values.join(' ').toLowerCase();
  };

  function build() {
    const input = $('#q');
    const report = $('#report');
    const status = $('#reportStatus');
    if (!input || !report || !status) return;

    const query = input.value.trim().toLowerCase();
    currentType = $('#reportType')?.value || 'cases';
    const rows = Array.isArray(payload[currentType]) ? payload[currentType] : [];
    currentRows = query ? rows.filter(row => searchableText(row).includes(query)) : rows.slice();

    const heading = currentType === 'reviews' ? 'Reviews report' : `${currentType[0].toUpperCase()}${currentType.slice(1)} report`;
    const visibleRows = currentRows.slice(0,1000);
    const emptyText = query
      ? `No ${currentType} records match “${esc(input.value.trim())}”. Try a full or partial person name, city, courthouse, court file, citation, status, or outcome.`
      : `No ${currentType} data is available. Run tools\\collect-new.cmd to rebuild generated report indexes.`;

    report.innerHTML = `<div class="section-head"><div><p class="eyebrow">Printable local report</p><h2>${esc(heading)}</h2><p>Generated ${new Date().toLocaleString()} · ${currentRows.length.toLocaleString()} matching of ${rows.length.toLocaleString()} records</p></div></div>${visibleRows.map(row => card(row,currentType)).join('') || `<p class="empty">${emptyText}</p>`}`;
    status.textContent = currentRows.length > 1000
      ? `Found ${currentRows.length.toLocaleString()} matches; showing the first 1,000.`
      : query
        ? `Found ${currentRows.length.toLocaleString()} matching ${currentType} record${currentRows.length === 1 ? '' : 's'}.`
        : `${rows.length.toLocaleString()} ${currentType} record${rows.length === 1 ? '' : 's'} loaded.`;
  }

  const fetchJson = async (url, fallback = {}) => {
    try {
      const response = await fetch(url,{cache:'no-store'});
      if (!response.ok) return fallback;
      return await response.json();
    } catch (_) {
      return fallback;
    }
  };

  const dedupe = rows => {
    const seen = new Set();
    return rows.filter(row => {
      const key = String(row.case_id || row.judgment_id || row.review_id || row.person_id || row.id || row.court_file_number || row.file_number || row.citation || JSON.stringify(row));
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  };

  Promise.all([
    fetchJson('data/cso-cases.json'),
    fetchJson('data/case-person-records.json'),
    fetchJson('data/search-cases.json'),
    fetchJson('data/search-people.json'),
    fetchJson('data/person-mentions.json'),
    fetchJson('data/published-judgments.json'),
    fetchJson('data/search-judgments.json'),
    fetchJson('data/review-queue.json')
  ]).then(([cso,indexed,searchCases,searchPeople,mentions,published,searchJudgments,reviews]) => {
    const caseRows = [
      ...asRows(cso,['cases','records','items']),
      ...asRows(indexed,['records','cases','items']),
      ...asRows(searchCases,['records','cases','items','results']),
      ...asRows(searchPeople,['people','records','items','results']),
      ...asRows(mentions,['mentions','records','items','results'])
    ];
    const judgmentRows = [
      ...asRows(published,['judgments','records','items','results']),
      ...asRows(searchJudgments,['judgments','records','items','results'])
    ];
    payload = {
      cases: dedupe(caseRows),
      judgments: dedupe(judgmentRows),
      reviews: dedupe(asRows(reviews,['items','reviews','records','results']))
    };
    build();
  }).catch(() => build());

  function exportExcel() {
    const keys = [...new Set(currentRows.flatMap(row => Object.keys(row || {})))];
    const cell = value => `<td>${esc(typeof value === 'object' && value !== null ? JSON.stringify(value) : value ?? '')}</td>`;
    const html = `<!doctype html><html><head><meta charset="utf-8"><style>table{border-collapse:collapse;font-family:Segoe UI,Arial}th{background:#1261a6;color:white}th,td{border:1px solid #9bc9f5;padding:8px;vertical-align:top}tr:nth-child(even){background:#eef6ff}</style></head><body><table><thead><tr>${keys.map(key=>`<th>${esc(labels[key]||key.replaceAll('_',' '))}</th>`).join('')}</tr></thead><tbody>${currentRows.map(row=>`<tr>${keys.map(key=>cell(row[key])).join('')}</tr>`).join('')}</tbody></table></body></html>`;
    const blob = new Blob([html],{type:'application/vnd.ms-excel'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `bc-justice-${currentType}-report.xls`;
    link.click();
    setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  }
  function exportPdf() {
    $('#reportStatus').textContent = 'The print dialog is opening. Choose “Save as PDF” as the printer destination.';
    document.body.classList.add('pdf-export');
    window.print();
    setTimeout(()=>document.body.classList.remove('pdf-export'),500);
  }

  $('#reportType')?.addEventListener('change',build);
  $('#q')?.addEventListener('input',() => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(build,80);
  });
  $('#q')?.addEventListener('search',build);
  $('#printBtn')?.addEventListener('click',()=>window.print());
  $('#excelBtn')?.addEventListener('click',exportExcel);
  $('#pdfBtn')?.addEventListener('click',exportPdf);
})();
