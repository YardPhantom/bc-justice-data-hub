const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));

const normalizeCourt = value => String(value || '')
  .toLowerCase()
  .replace(/&/g, ' and ')
  .replace(/\b(law courts?|provincial court|supreme court|courthouse|court house|registry)\b/g, ' ')
  .replace(/[^a-z0-9]+/g, ' ')
  .trim();

const slugify = value => normalizeCourt(value).replace(/\s+/g, '-');

async function loadJson(url, fallback = {}) {
  try {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch {
    return fallback;
  }
}

function listFrom(data, keys = []) {
  if (Array.isArray(data)) return data;
  for (const key of keys) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

async function loadPaged(url, keys) {
  const data = await loadJson(url, {});
  const key = keys.find(candidate => Array.isArray(data?.[candidate]));
  if (!key || Number(data.pageCount || 1) <= 1) return data;
  const extra = await Promise.all(
    Array.from({ length: Number(data.pageCount) - 1 }, (_, index) =>
      loadJson(url.replace(/\.json$/i, `-page-${index + 2}.json`), {})
    )
  );
  data[key] = [
    ...(data[key] || []),
    ...extra.flatMap(page => page[key] || [])
  ];
  return data;
}

const requestedSlug = new URLSearchParams(location.search).get('court') || '';

function buildCourtMatcher(court, aliases) {
  const canonical = [court.slug, court.name, court.city, court.registry, court.responsible_registry]
    .filter(Boolean);
  const normalized = new Set(canonical.flatMap(value => [normalizeCourt(value), slugify(value)]).filter(Boolean));

  for (const alias of aliases) {
    const aliasCanonical = normalizeCourt(alias.canonical || alias.canonical_name);
    const aliasCanonicalSlug = slugify(alias.canonical || alias.canonical_name);
    if (normalized.has(aliasCanonical) || normalized.has(aliasCanonicalSlug)) {
      normalized.add(normalizeCourt(alias.alias || alias.alias_name));
      normalized.add(slugify(alias.alias || alias.alias_name));
      normalized.add(normalizeCourt(alias.alias_normalized));
    }
  }

  return record => {
    const values = [
      record.courthouse_slug,
      record.courthouse_name,
      record.courthouse,
      record.location,
      record.court,
      record.registry
    ].filter(Boolean);
    return values.some(value => {
      const name = normalizeCourt(value);
      const slug = slugify(value);
      if (!name && !slug) return false;
      if (normalized.has(name) || normalized.has(slug)) return true;
      return [...normalized].some(candidate =>
        candidate.length >= 4 && (name.includes(candidate) || candidate.includes(name))
      );
    });
  };
}

function setRows(bodySelector, emptySelector, rows, html) {
  $(bodySelector).innerHTML = rows.map(html).join('');
  $(emptySelector).hidden = rows.length > 0;
}

const normalizedState = row => String(
  row?.verification || row?.verification_state || row?.verified || ''
).trim().toLowerCase().replace(/_/g, '-');

const isVerified = row => {
  const state = normalizedState(row);
  return state === 'verified' || state === 'source-verified' || state === '1' || state === 'true';
};

const finalOutcomes = new Set([
  'convicted', 'guilty', 'guilty plea', 'sentenced', 'acquitted',
  'stayed', 'withdrawn', 'dismissed'
]);

const hasVerifiedOutcome = row => {
  const outcome = String(
    row?.final_outcome || row?.outcome || row?.outcome_type || row?.legal_status || row?.status || ''
  ).trim().toLowerCase().replace(/_/g, ' ');
  return isVerified(row) && finalOutcomes.has(outcome);
};

function recordKey(row, prefix = 'record') {
  return [
    prefix,
    row?.case_id,
    row?.judgment_id,
    row?.appearance_id,
    row?.person_id,
    row?.court_file_number,
    row?.file_number,
    row?.fileNumber,
    row?.citation,
    row?.participant_name,
    row?.person_name,
    row?.name,
    row?.decision_date,
    row?.list_date,
    row?.date
  ].filter(Boolean).join('|') || `${prefix}|${JSON.stringify(row)}`;
}

function uniqueRows(rows, prefix) {
  return [...new Map(rows.map(row => [recordKey(row, prefix), row])).values()];
}

function summaryCount(summary, ...keys) {
  return keys.reduce((highest, key) => Math.max(highest, Number(summary?.[key] || 0)), 0);
}

function updateArticleCounts({ localRecords, verifiedOutcomes, needsReview }) {
  $('#localCount').textContent = Number(localRecords || 0).toLocaleString();
  $('#localVerified').textContent = Number(verifiedOutcomes || 0).toLocaleString();
  $('#localReview').textContent = Number(needsReview || 0).toLocaleString();
}

async function init() {
  const [courtData, aliasData, courtSummary] = await Promise.all([
    loadJson('../data/courthouses.json', []),
    loadJson('../data/courthouse-aliases.json', { aliases: [] }),
    loadJson('../data/courthouse-data.json', { courthouses: [] })
  ]);
  const courts = listFrom(courtData, ['courthouses', 'records', 'items']);
  const aliases = listFrom(aliasData, ['aliases', 'records', 'items']);
  const court = courts.find(item =>
    String(item.slug || '') === requestedSlug || slugify(item.name) === requestedSlug
  );

  if (!court) {
    $('#courtName').textContent = requestedSlug ? 'Courthouse not found' : 'No courthouse selected';
    $('#courtAddress').textContent = 'Return to the courthouse directory and choose a location.';
    $('#coverageState').textContent = 'Unavailable';
    $('#coverageWarning').textContent = courts.length
      ? 'The selected courthouse slug does not match the courthouse directory.'
      : 'courthouses.json is missing or empty. Run tools\\collect-new.cmd.';
    $('#localCount').textContent = '—';
    $('#localVerified').textContent = '—';
    $('#localReview').textContent = '—';
    return;
  }

  const matchesCourt = buildCourtMatcher(court, aliases);
  const summaryRows = listFrom(courtSummary, ['courthouses', 'records', 'items']);
  const summary = summaryRows.find(matchesCourt);
  if (summary) {
    updateArticleCounts({
      localRecords: summaryCount(summary, 'linked_records', 'local_records', 'imported_rows'),
      verifiedOutcomes: summaryCount(summary, 'verified_outcomes'),
      needsReview: summaryCount(summary, 'needs_review')
    });
  }
  document.title = `${court.name} | BC Justice Data Hub`;
  $('#courtTypeLabel').textContent = court.type || 'Courthouse';
  $('#courtName').textContent = court.name;
  $('#courtAddress').textContent = court.address || court.city || '';
  $('#locationType').textContent = court.type || '—';
  $('#contactCard').innerHTML = `<strong>Registry contact</strong>
    <span><b>Phone:</b> ${court.phone ? `<a href="tel:${esc(String(court.phone).replace(/\D/g, ''))}">${esc(court.phone)}</a>` : 'Not listed'}</span>
    <span><b>Directory:</b> <a href="https://www2.gov.bc.ca/gov/content/justice/courthouse-services/courthouse-locations" target="_blank" rel="noopener">Official registry directory ↗</a></span>
    <span><b>Responsible registry:</b> ${esc(court.registry || court.responsible_registry || court.name)}</span>`;

  const [recordData, explorerData, listData, judgmentData, csoData] = await Promise.all([
    loadJson('../data/case-person-records.json', { records: [] }),
    loadJson('../data/data-explorer.json', { records: [] }),
    loadPaged('../data/daily-court-lists.json', ['appearances', 'records']),
    loadJson('../data/published-judgments.json', { judgments: [] }),
    loadJson('../data/cso-cases.json', { cases: [] })
  ]);

  const records = listFrom(recordData, ['records', 'cases', 'items']);
  const csoCases = listFrom(csoData, ['cases', 'records', 'items']);
  const local = [...records, ...csoCases].filter(matchesCourt);
  const uniqueLocal = [...new Map(local.map(row => [
    [row.case_id, row.person_id, row.fileNumber, row.file_number, row.court_file_number, row.citation, row.name, row.person_name].filter(Boolean).join('|') || JSON.stringify(row),
    row
  ])).values()];

  setRows('#courtRecordsBody', '#courtEmpty', uniqueLocal, row => `<tr>
    <td><strong>${esc(row.name || row.person_name || row.participant_name || row.case_title || 'Unnamed')}</strong><br><small>${esc(row.offence || row.offence_text || '')}</small></td>
    <td><span class="badge status-${esc(row.status || row.legal_status || row.final_outcome || 'unknown')}" title="${esc(window.bcjusStatusTitle ? window.bcjusStatusTitle(row.status || row.legal_status || row.final_outcome) : 'Verify against official source')}">${esc(row.status || row.legal_status || row.final_outcome || 'unknown')}</span></td>
    <td>${esc(row.fileNumber || row.file_number || row.court_file_number || row.citation || '—')}</td>
    <td>${esc(row.date || row.event_date || row.outcome_date || row.opened_date || '—')}</td>
    <td><span class="verify ${esc(row.verification || row.verification_state || 'review')}">${isVerified(row) ? 'Verified' : 'Needs review'}</span></td>
    <td>${row.sourceUrl || row.source_url ? `<a href="${esc(row.sourceUrl || row.source_url)}" target="_blank" rel="noopener">Open ↗</a>` : '—'}</td>
  </tr>`);

  const statistics = listFrom(explorerData, ['records', 'items']).filter(row =>
    row.type === 'court_statistics' && matchesCourt(row)
  );
  setRows('#courtStatsBody', '#courtStatsEmpty', statistics, row => `<tr>
    <td>${esc(row.fiscal_year || row.year || row.period || '—')}</td>
    <td><strong>${esc(row.metric || row.measure || 'Imported metric')}</strong></td>
    <td>${esc(row.value ?? '—')} ${esc(row.unit || '')}</td>
    <td>${esc(row.category || '—')}</td>
  </tr>`);

  const allAppearances = listFrom(listData, ['appearances', 'records', 'items']).filter(matchesCourt);
  const appearancePageSize = 50;
  let appearancePage = 1;
  const renderAppearances = () => {
    const pageCount = Math.max(1, Math.ceil(allAppearances.length / appearancePageSize));
    appearancePage = Math.min(Math.max(appearancePage, 1), pageCount);
    const startIndex = (appearancePage - 1) * appearancePageSize;
    const appearances = allAppearances.slice(startIndex, startIndex + appearancePageSize);
    setRows('#appearanceBody', '#appearanceEmpty', appearances, row => `<tr>
      <td>${esc(row.list_date || row.date || row.event_date || '—')}</td>
      <td><strong>${esc(row.participant_name || row.name || row.person_name || row.case_name || 'Case')}</strong><br><small title="Scheduled appearance — allegation not proven">Scheduled appearance — allegation not proven</small></td>
      <td>${esc(row.court_file_number || row.file_number || row.fileNumber || '—')}</td>
      <td>${esc(row.appearance_type || row.hearing_type || '—')}</td>
      <td>${row.source_url ? `<a href="${esc(row.source_url)}" target="_blank" rel="noopener">Open ↗</a>` : '—'}</td>
    </tr>`);

    const pagination = $('#appearancePagination');
    const prev = $('#appearancePrev');
    const next = $('#appearanceNext');
    const label = $('#appearancePageLabel');
    pagination.hidden = allAppearances.length === 0;
    if (allAppearances.length) {
      const first = startIndex + 1;
      const last = Math.min(startIndex + appearancePageSize, allAppearances.length);
      label.textContent = `Showing ${first.toLocaleString()}–${last.toLocaleString()} of ${allAppearances.length.toLocaleString()} · Page ${appearancePage} of ${pageCount}`;
    }
    else {
      label.textContent = 'Showing 0 results';
    }
    prev.disabled = appearancePage <= 1;
    next.disabled = appearancePage >= pageCount;
  };

  $('#appearancePrev').addEventListener('click', () => {
    if (appearancePage <= 1) return;
    appearancePage -= 1;
    renderAppearances();
    $('#todayAppearances').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  $('#appearanceNext').addEventListener('click', () => {
    const pageCount = Math.max(1, Math.ceil(allAppearances.length / appearancePageSize));
    if (appearancePage >= pageCount) return;
    appearancePage += 1;
    renderAppearances();
    $('#todayAppearances').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  renderAppearances();

  const allJudgments = listFrom(judgmentData, ['judgments', 'records', 'items']).filter(matchesCourt);
  const judgments = allJudgments.slice(0, 30);
  setRows('#judgmentBody', '#judgmentEmpty', judgments, row => `<tr>
    <td>${esc(row.decision_date || row.date || '—')}</td>
    <td><strong>${esc(row.citation || row.case_name || row.title || 'Decision')}</strong></td>
    <td><span class="badge status-${esc(row.outcome || row.outcome_type || row.final_outcome || 'unknown')}" title="${esc(window.bcjusStatusTitle ? window.bcjusStatusTitle(row.outcome || row.outcome_type || row.final_outcome) : 'Verify outcome')}">${esc(row.outcome || row.outcome_type || row.final_outcome || 'Outcome unverified')}</span></td>
    <td>${row.url || row.source_url ? `<a href="${esc(row.url || row.source_url)}" target="_blank" rel="noopener">Open ↗</a>` : '—'}</td>
  </tr>`);

  if (window.bcjusHideEmpty) {
    window.bcjusHideEmpty('#importedData', statistics.length);
    window.bcjusHideEmpty('#todayAppearances', allAppearances.length);
    window.bcjusHideEmpty('#recentJudgments', judgments.length);
  }

  const linkedLocalRows = uniqueRows([
    ...uniqueLocal,
    ...allAppearances,
    ...allJudgments
  ], 'linked');
  const verifiedOutcomeRows = uniqueRows([
    ...uniqueLocal.filter(hasVerifiedOutcome),
    ...allJudgments.filter(hasVerifiedOutcome)
  ], 'verified-outcome');
  const reviewRows = uniqueRows([
    ...uniqueLocal.filter(row => !isVerified(row)),
    ...allJudgments.filter(row => !isVerified(row))
  ], 'review');
  const importedRows = Number(summary?.imported_rows || 0);
  const localRecordCount = Math.max(
    linkedLocalRows.length + statistics.length,
    importedRows,
    summaryCount(summary, 'linked_records', 'local_records')
  );
  const verifiedOutcomeCount = Math.max(
    verifiedOutcomeRows.length,
    summaryCount(summary, 'verified_outcomes')
  );
  const needsReviewCount = Math.max(
    reviewRows.length,
    summaryCount(summary, 'needs_review')
  );
  updateArticleCounts({
    localRecords: localRecordCount,
    verifiedOutcomes: verifiedOutcomeCount,
    needsReview: needsReviewCount
  });

  const dates = [
    recordData.generatedAt,
    explorerData.generatedAt,
    listData.generatedAt,
    judgmentData.generatedAt,
    csoData.generatedAt,
    courtSummary.generatedAt
  ].filter(Boolean).map(value => new Date(value)).filter(value => !Number.isNaN(value.getTime()));
  $('#lastRefresh').textContent = dates.length
    ? new Date(Math.max(...dates.map(value => value.getTime()))).toLocaleString()
    : 'Unknown';

  const coverage = localRecordCount;
  $('#coverageState').textContent = coverage ? 'Data available' : 'No linked data';
  $('#coverageWarning').textContent = coverage
    ? `Linked using courthouse slug, official name, and aliases.${importedRows ? ` ${importedRows} imported row${importedRows === 1 ? '' : 's'} are associated with this courthouse.` : ''} Article counts include the full matched datasets, not only the rows shown in each preview table. Verify important results against official sources.`
    : 'No local records currently match this courthouse. Run collect-new.cmd, then review courthouse-aliases.json for unmatched naming variants.';
}

init().catch(error => {
  console.error('Courthouse detail failed:', error);
  $('#courtName').textContent = 'Courthouse data unavailable';
  $('#coverageState').textContent = 'Load error';
  $('#coverageWarning').textContent = 'One or more local data files could not be read. Run tools\\collect-new.cmd and refresh the page.';
  $('#localCount').textContent = '—';
  $('#localVerified').textContent = '—';
  $('#localReview').textContent = '—';
});
