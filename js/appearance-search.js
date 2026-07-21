(()=>{
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rxEsc=v=>String(v||'').replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const normalize=v=>String(v||'').toLocaleLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
  const highlightResultName=(value,fullName,enabled=true)=>{
    const text=String(value||''),name=String(fullName||'').trim();
    if(!enabled||!name)return esc(text);
    const pattern=rxEsc(name).replace(/\\ /g,'\\s+').replace(/,\\s\+/g,',\\s*');
    const re=new RegExp(`(${pattern})`,'gi');
    return text.split(re).map((part,i)=>i%2?`<mark class="appearance-hit">${esc(part)}</mark>`:esc(part)).join('');
  };
  const safeHref=value=>{
    const href=String(value||'').trim();
    if(!href)return '';
    if(/^https?:\/\//i.test(href))return href;
    if(/^(?:archive|imports|data)\//i.test(href)&&!href.includes('..'))return href;
    return '';
  };
  const fileLinks=r=>{
    const local=safeHref(r.local_path),official=safeHref(r.source_url),links=[];
    if(local)links.push(`<a href="${esc(local)}" target="_blank" rel="noopener">Stored file ↗</a>`);
    if(official){
      const note='Courts re-use this same file name every day. If appearance was before today, use local link archive instead.';
      links.push(`<a href="${esc(official)}" target="_blank" rel="noopener" title="${esc(note)}" aria-label="Official file. ${esc(note)}">Official file ↗</a>`);
    }
    return links.length?links.join('<br>'):esc(r.court_file_number||'');
  };

  const downloadFile=(name,type,content)=>{
    const blob=new Blob([content],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const csvCell=value=>`"${String(value??'').replace(/"/g,'""')}"`;
  const exportRows=records=>records.map(r=>({
    name:r.participant_name||'',date:r.list_date||'',time:r.appearance_time||'',courthouse:r.courthouse_name||'',court_file:r.court_file_number||'',appearance:r.appearance_type||'',court_level:r.court_level||'',courtroom:r.courtroom||'',record_details:r.raw_line||'',charge_confidence:confidenceLabel(r),alleged_charges:r.alleged_charges||'',charge_notice:cleanChargeNotice(r.charge_notice,confidenceLabel(r)),stored_file:r.local_path||'',official_file:r.source_url||''
  }));
  const printReport=(records,filters)=>{
    const rows=exportRows(records),w=window.open('','_blank','noopener,noreferrer');
    if(!w)return;
    const filterText=Object.entries(filters).filter(([,v])=>v).map(([k,v])=>`${k}: ${v}`).join(' · ')||'All active filters';
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Appearance Search Report</title><style>body{font-family:Arial,sans-serif;margin:24px;color:#111}h1{margin-bottom:6px}.meta{margin:0 0 18px;color:#444}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #bbb;padding:6px;vertical-align:top;text-align:left}th{background:#eee}@media print{body{margin:10mm}.no-print{display:none}}</style></head><body><button class="no-print" onclick="window.print()">Print</button><h1>Appearance Search Report</h1><p class="meta">${esc(filterText)} · ${rows.length.toLocaleString()} results</p><table><thead><tr><th>Name</th><th>Date</th><th>Time</th><th>Courthouse</th><th>File</th><th>Appearance</th><th>Charge</th><th>Record details</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}</td><td>${esc(r.date)}</td><td>${esc(r.time)}</td><td>${esc(r.courthouse)}</td><td>${esc(r.court_file)}</td><td>${esc(r.appearance)}</td><td>${esc(r.alleged_charges||r.charge_confidence)}</td><td>${esc(r.record_details)}</td></tr>`).join('')}</tbody></table></body></html>`);
    w.document.close();
  };
  const dictionaryCodes=new Set(['BCPC','BCSC','BCCA','BCTC','CCC','CDSA','MVA']);
  const dictionarySlug=value=>String(value||'').toLocaleLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'')||'unknown';
  const dictionaryHref=(type,value,statute='')=>{
    const code=String(value||'').trim();
    if(!code)return '';
    const params=new URLSearchParams({type,value:code});
    if(statute)params.set('statute',String(statute).trim());
    const anchor=`definition-${dictionarySlug(type)}-${dictionarySlug(statute?`${statute}-${code}`:code)}`;
    return `data-dictionary.html?${params.toString()}#${anchor}`;
  };
  const dictionaryValueLink=(type,value,{statute='',label=''}={})=>{
    const text=String(value||'').trim();
    if(!text)return '';
    const href=dictionaryHref(type,text,statute);
    const title=label||`Open ${text} definition`;
    return `<a class="dictionary-code-link" href="${esc(href)}" title="${esc(title)}"><code>${esc(text)}</code></a>`;
  };
  const chargeConfidenceAnchors={
    'Confirmed':'charge-confidence-confirmed',
    'Likely':'charge-confidence-likely',
    'Possible':'charge-confidence-possible',
    'Non Verified':'charge-confidence-non-verified',
    'Charge Not Available':'charge-confidence-not-available'
  };
  const chargeConfidenceHref=tier=>`data-dictionary.html#${chargeConfidenceAnchors[tier]||'charge-confidence'}`;
  const chargeConfidenceLink=tier=>{
    const text=String(tier||'Charge Not Available').trim()||'Charge Not Available';
    return `<a class="dictionary-code-link charge-confidence-link" href="${esc(chargeConfidenceHref(text))}" title="Open ${esc(text)} charge-confidence definition">${esc(text)}</a>`;
  };
  const linkCourtCodes=value=>{
    const text=String(value||'');
    if(!text)return '';
    return text.split(/(\b[A-Z]{2,5}\b)/g).map(part=>dictionaryCodes.has(part)
      ?dictionaryValueLink('statute',part,{label:`Open ${part} definition`})
      :esc(part)).join('');
  };
  const rawRecordFields=record=>{
    const rawText=String(record.raw_line||'').replace(/\s+/g,' ').trim();
    if(!rawText)return {};
    const name=String(record.participant_name||'').trim(),file=String(record.court_file_number||'').trim();
    let text=rawText;
    const nameVariants=new Set([name]);
    if(name.includes(',')){
      const [last,...rest]=name.split(',').map(part=>part.trim()).filter(Boolean);
      if(last&&rest.length)nameVariants.add(`${rest.join(' ')} ${last}`);
    }
    [...nameVariants].filter(Boolean).sort((a,b)=>b.length-a.length).forEach(value=>{
      const pattern=rxEsc(value).replace(/\s+/g,'\\s+').replace(/,\\s\+/g,',\\s*');
      text=text.replace(new RegExp(pattern,'ig'),' ');
    });
    if(file)text=text.replace(new RegExp(rxEsc(file),'ig'),' ');
    text=text.replace(/\s{2,}/g,' ').replace(/^\s*[-–—|,:;]+\s*|\s*[-–—|,:;]+\s*$/g,'').trim();
    const fields={};
    let rest=text;
    const take=(key,re)=>{
      const m=rest.match(re);
      if(!m)return '';
      const value=m[1];
      rest=(rest.slice(0,m.index)+rest.slice(m.index+m[0].length)).replace(/\s{2,}/g,' ').trim();
      fields[key]=value;
      return value;
    };
    take('listNumber',/^\s*(\d{1,3})\b/);
    take('appearanceCode',/^\s*([A-Z]{2,6})\b/);
    take('statusCode',/^\s*([A-Z])\b/);
    take('rawCourtroom',/^\s*([A-Z]?\d{1,3}[A-Z]?)\b/);
    take('courtLocationCode',/^\s*([A-Z]{2,6})\b/);
    take('count',/^\s*(\d{3})\b/);
    take('statute',/^\s*(CCC|CDSA|MVA|YCJA|FDA|CA|IA|POA)\b/i);
    take('section',/^\s*([0-9]+(?:\.[0-9]+)?(?:\([^)]+\))?)\b/);
    fields.remainder=rest.replace(/^\s*[-–—|,:;]+\s*|\s*[-–—|,:;]+\s*$/g,'').trim();
    return fields;
  };
  const firstValue=(record,keys,fallback='')=>{
    for(const key of keys){
      const value=record?.[key];
      if(value!==undefined&&value!==null&&String(value).trim())return String(value).trim();
    }
    return fallback;
  };
  const detailLine=(label,value,{html=false,className=''}={})=>`<span class="record-detail-item${className?` ${className}`:''}"><strong>${esc(label)}:</strong> ${value?(html?value:esc(value)):'—'}</span>`;
  const recordDetailsMarkup=(record,courts)=>{
    const raw=rawRecordFields(record),tier=confidenceLabel(record),notice=cleanChargeNotice(record.charge_notice,tier);
    const appearanceCode=firstValue(record,['appearance_code','appearanceCode'],raw.appearanceCode);
    const statusCode=firstValue(record,['status_code','statusCode'],raw.statusCode);
    const statute=firstValue(record,['statute','statute_code','statuteCode'],raw.statute);
    const section=firstValue(record,['section','statute_section','statuteSection'],raw.section);
    const courtroom=firstValue(record,['courtroom'],raw.rawCourtroom);
    const dateTime=[record.list_date,record.appearance_time].filter(Boolean).map(esc).join(' · ');
    const courthouse=record.courthouse_name?courthouseLink(record.courthouse_name,courts):'';
    const file=String(record.court_file_number||'').trim();
    const linkedFiles=(record.local_path||record.source_url)?` <small class="record-file-links">${fileLinks(record)}</small>`:'';
    const fileValue=file?`<span class="record-file-number">${esc(file)}</span>${linkedFiles}`:'';
    const alleged=String(record.alleged_charges||'').trim()||'Not available';
    return `<span class="record-detail-list">
      <span class="record-detail-main">
        ${detailLine('Appearance',record.appearance_type)}
        ${detailLine('Appearance code',appearanceCode?dictionaryValueLink('appearance-code',appearanceCode,{label:`Open appearance code ${appearanceCode} definition`}):'',{html:true})}
        ${detailLine('Status code',statusCode?dictionaryValueLink('status-code',statusCode,{label:`Open status code ${statusCode} definition`}):'',{html:true})}
        ${detailLine('Statute',statute?dictionaryValueLink('statute',statute,{label:`Open statute ${statute} definition`}):'',{html:true})}
        ${detailLine('Section',section?dictionaryValueLink('section',section,{statute,label:`Open section ${section}${statute?` of ${statute}`:''} definition`}):'',{html:true})}
        ${detailLine('Date and time',dateTime,{html:true})}
        ${detailLine('Courthouse',courthouse,{html:true})}
        ${detailLine('Courtroom',courtroom)}
        ${detailLine('Court file',fileValue,{html:true})}
        ${detailLine('Court level',record.court_level?linkCourtCodes(record.court_level):'',{html:true})}
      </span>
      <span class="record-detail-charge">
        ${detailLine('Linked alleged charge',alleged)}
        ${detailLine('Charge confidence',chargeConfidenceLink(tier),{html:true})}
        ${detailLine('Evidence',notice)}
      </span>
    </span>`;
  };
  const confidenceRank={'Confirmed':1,'Likely':2,'Possible':3,'Non Verified':4,'Charge Not Available':5};
  const confidenceLabel=r=>r.charge_confidence||'Charge Not Available';
  const compareText=(a,b)=>String(a||'').localeCompare(String(b||''),undefined,{sensitivity:'base'});
  const compareDate=(a,b,direction='desc')=>{
    const left=String(a.list_date||''),right=String(b.list_date||'');
    if(!left&&!right)return 0;if(!left)return 1;if(!right)return -1;
    return direction==='asc'?left.localeCompare(right):right.localeCompare(left);
  };
  const compareNewest=(a,b)=>compareDate(a,b,'desc')||String(b.appearance_time||'').localeCompare(String(a.appearance_time||''))||compareText(a.participant_name,b.participant_name)||compareText(a.court_file_number,b.court_file_number);
  const sortRecords=(records,sort='newest')=>records.sort((a,b)=>{
    if(sort==='oldest')return compareDate(a,b,'asc')||String(a.appearance_time||'').localeCompare(String(b.appearance_time||''))||compareText(a.participant_name,b.participant_name);
    if(sort==='name')return compareText(a.participant_name,b.participant_name)||compareNewest(a,b);
    if(sort==='courthouse')return compareText(a.courthouse_name||'ZZZZ',b.courthouse_name||'ZZZZ')||compareNewest(a,b);
    if(sort==='confidence')return (confidenceRank[confidenceLabel(a)]||9)-(confidenceRank[confidenceLabel(b)]||9)||compareNewest(a,b);
    if(sort==='history')return Math.max(1,Number(b.history_count||1))-Math.max(1,Number(a.history_count||1))||compareNewest(a,b);
    return compareNewest(a,b);
  });
  const isoDate=date=>{
    const year=date.getFullYear(),month=String(date.getMonth()+1).padStart(2,'0'),day=String(date.getDate()).padStart(2,'0');
    return `${year}-${month}-${day}`;
  };
  const relativeDate=days=>{const date=new Date();date.setHours(12,0,0,0);date.setDate(date.getDate()+days);return isoDate(date)};
  const chargeClass=tier=>`charge-${String(tier||'').toLocaleLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')}`;
  const chargeBadgeMarkup=record=>{
    const tier=confidenceLabel(record);
    return `<a class="appearance-charge-badge ${chargeClass(tier)}" href="${esc(chargeConfidenceHref(tier))}" title="Open ${esc(tier)} charge-confidence definition">${esc(tier)}</a>`;
  };
  const compactRecordMarkup=(record,courts)=>{
    const parts=[];
    const dateTime=[record.list_date,record.appearance_time].filter(Boolean).join(' · ');
    if(dateTime)parts.push(`<span><strong>Date:</strong> ${esc(dateTime)}</span>`);
    if(record.courthouse_name)parts.push(`<span><strong>Courthouse:</strong> ${courthouseLink(record.courthouse_name,courts)}</span>`);
    if(record.court_file_number)parts.push(`<span><strong>File:</strong> ${fileLinks(record)}</span>`);
    if(record.appearance_type)parts.push(`<span><strong>Appearance:</strong> ${esc(record.appearance_type)}</span>`);
    return `<div class="appearance-compact-summary">${parts.join('<span class="appearance-separator" aria-hidden="true"> · </span>')}</div>`;
  };
  const courtFileGroupMarkup=(record,courts)=>{
    const grouped=Array.isArray(record.grouped_appearances)?record.grouped_appearances:[];
    if(grouped.length<2)return '';
    const file=String(record.court_file_number||'').trim();
    const items=grouped.map(item=>{
      const bits=[
        item.participant_name?`<span><strong>Name:</strong> ${esc(item.participant_name)}</span>`:'',
        item.list_date?`<span><strong>Date:</strong> ${esc(item.list_date)}</span>`:'',
        item.appearance_time?`<span><strong>Time:</strong> ${esc(item.appearance_time)}</span>`:'',
        item.courthouse_name?`<span><strong>Courthouse:</strong> ${courthouseLink(item.courthouse_name,courts)}</span>`:'',
        item.appearance_type?`<span><strong>Appearance:</strong> ${esc(item.appearance_type)}</span>`:''
      ].filter(Boolean).join('<span class="appearance-separator" aria-hidden="true"> · </span>');
      return `<li>${bits}</li>`;
    }).join('');
    return `<details class="appearance-file-group"><summary>${grouped.length.toLocaleString()} appearances${file?` for file ${esc(file)}`:' grouped by court file'}</summary><ul>${items}</ul></details>`;
  };
  const markup=()=>`<div class="appearance-name-row">
      <label>Name<input data-appearance-name type="search" autocomplete="off" placeholder="Begin typing a name or select a date for results to populate."></label>
      <button class="theme-pill" data-appearance-clear type="button">Clear</button>
    </div>
    <div class="appearance-date-shortcuts" aria-label="Appearance date shortcuts">
      <span>Date shortcuts:</span>
      <button class="theme-pill" data-date-shortcut="today" type="button" aria-pressed="false">Today</button>
      <button class="theme-pill" data-date-shortcut="next7" type="button" aria-pressed="false">Next 7 days</button>
      <button class="theme-pill" data-date-shortcut="past30" type="button" aria-pressed="false">Past 30 days</button>
      <button class="theme-pill" data-date-shortcut="all" type="button" aria-pressed="false">All dates</button>
    </div>
    <div class="appearance-filters appearance-filters-extended">
      <label>Name matching<select data-appearance-match><option value="partial">Partial name</option><option value="exact">Exact full name</option></select></label>
      <label>Courthouse<select data-appearance-court><option value="">All courthouses</option></select></label>
      <label>From<input data-appearance-from type="date"></label>
      <label>To<input data-appearance-to type="date"></label>
      <label>Charge confidence<select data-appearance-confidence><option value="">All confidence tiers</option><option>Confirmed</option><option>Likely</option><option>Possible</option><option>Non Verified</option><option>Charge Not Available</option></select></label>
    </div>
    <div class="appearance-active-filters" data-active-filters aria-label="Active Appearance Search filters" hidden></div>
    <div class="appearance-results-toolbar" data-results-toolbar>
      <p data-appearance-status>Enter a name, select a courthouse, choose a date range, or select a confidence tier.</p>
      <div class="appearance-toolbar-controls">
        <label>Sort <select data-appearance-sort><option value="newest">Newest appearance</option><option value="oldest">Oldest appearance</option><option value="name">Name A–Z</option><option value="courthouse">Courthouse A–Z</option><option value="confidence">Charge confidence — strongest first</option><option value="history">Most catalogued appearances</option></select></label>
        <label>Show <select data-page-size-top><option value="50">50</option><option value="100">100</option></select></label>
        <div class="appearance-view-switch" aria-label="Result detail level">
          <button class="theme-pill" data-view="compact" type="button" aria-pressed="false">Compact</button>
          <button class="theme-pill" data-view="detailed" type="button" aria-pressed="true">Detailed</button>
        </div>
        <button class="theme-pill" data-group-file type="button" aria-pressed="false">Group by court file</button>
      </div>
    </div>
    <div class="table-wrap appearance-table-wrap"><table class="appearance-results-table"><thead><tr><th>Name</th><th data-record-heading>Record details</th></tr></thead><tbody data-appearance-rows></tbody></table></div>
    <div class="appearance-pagination" data-appearance-pagination hidden>
      <button class="theme-pill" data-page-prev type="button">Previous</button>
      <span data-page-number>Page 1 of 1</span>
      <button class="theme-pill" data-page-next type="button">Next</button>
    </div>
    <div class="appearance-export-row" data-appearance-export aria-label="Appearance Search export options" hidden>
      <button class="theme-pill" data-export-csv type="button">Export CSV</button>
      <button class="theme-pill" data-export-json type="button">Export JSON</button>
      <button class="theme-pill" data-export-print type="button">Printable report</button>
    </div>
    <p class="empty" data-appearance-empty>No search is active.</p>`;
  // `no-cache` keeps static JSON in the browser cache but revalidates it with
  // IIS using ETag/Last-Modified. Regenerated exports therefore refresh without
  // forcing the full appearance catalogue to download again on every visit.
  const STATIC_JSON_CACHE='no-cache';
  async function getJson(url,options={}){const r=await fetch(url,{cache:options.cache??STATIC_JSON_CACHE,signal:options.signal});if(!r.ok)throw Error(`Could not load ${url}`);return r.json()}
  const normalizeCourt=value=>String(value||'').toLocaleLowerCase().replace(/&/g,' and ').replace(/\b(law courts?|provincial court|supreme court|courthouse|court house|registry)\b/g,' ').replace(/[^a-z0-9]+/g,' ').trim();
  const slugify=value=>normalizeCourt(value).replace(/\s+/g,'-');
  const API_BASE='http://127.0.0.1:8765',API_WAKE='http://127.0.0.1:8764/wake',API_STATUS='http://127.0.0.1:8764/status';
  const API_REQUEST_TIMEOUT=9000,API_COLD_START_TIMEOUT=15000,API_READY_POLL_MS=500;
  const FACETS_CACHE_KEY='bcjus.appearance.facets.v1';
  const emptyFacets=()=>({catalogueTotal:0,courthouses:[]});
  const readCachedFacets=()=>{
    try{
      const cached=JSON.parse(localStorage.getItem(FACETS_CACHE_KEY)||'null');
      return cached&&Array.isArray(cached.courthouses)?cached:emptyFacets();
    }catch{return emptyFacets()}
  };
  const writeCachedFacets=facets=>{
    try{localStorage.setItem(FACETS_CACHE_KEY,JSON.stringify({catalogueTotal:Number(facets.catalogueTotal||0),courthouses:Array.isArray(facets.courthouses)?facets.courthouses:[],cachedAt:new Date().toISOString()}))}catch{}
  };
  const scheduleBackground=callback=>{
    if('requestIdleCallback' in window)window.requestIdleCallback(callback,{timeout:800});
    else setTimeout(callback,0);
  };
  const queryString=filters=>{
    const p=new URLSearchParams();
    if(filters.name)p.set('name',filters.name);
    if(filters.match)p.set('match',filters.match);
    if(filters.court)p.set('court',filters.court);
    if(filters.from)p.set('from',filters.from);
    if(filters.to)p.set('to',filters.to);
    if(filters.confidence)p.set('confidence',filters.confidence);
    if(filters.sort)p.set('sort',filters.sort);
    if(filters.group)p.set('group',filters.group);
    p.set('limit',String(filters.limit||50));p.set('offset',String(filters.offset||0));
    return p.toString();
  };
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  class ApiRequestError extends Error{
    constructor(message,{status=0,code='',retryable=false,retryAfterSeconds=0,cause=null}={}){
      super(message);this.name='ApiRequestError';this.status=status;this.code=code;this.retryable=retryable;this.retryAfterSeconds=retryAfterSeconds;this.cause=cause;
    }
  }
  const apiFailureReason=error=>{
    if(error?.code==='database_busy')return error.message||'database is temporarily busy';
    if(error?.name==='AbortError'||error?.cause?.name==='AbortError')return 'request timed out while the local API was starting';
    if(Number(error?.status)===503)return error.message||'service temporarily unavailable';
    if(Number(error?.status)>0)return error.message||`HTTP ${error.status}`;
    const text=String(error?.message||'').trim();
    if(/failed to fetch|networkerror|load failed/i.test(text))return 'connection refused or the local API is not listening';
    return text||'local API unavailable';
  };
  const retryAfterSeconds=(response,payload)=>{
    const header=Number(response.headers.get('Retry-After')||0),body=Number(payload?.retryAfterSeconds||0);
    return Math.max(0,Number.isFinite(header)?header:0,Number.isFinite(body)?body:0);
  };
  async function fetchJsonWithTimeout(url,timeout){
    const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),timeout);
    try{
      const response=await fetch(url,{cache:'no-store',signal:ctrl.signal});
      let payload=null;
      try{payload=await response.json()}catch{}
      if(response.ok)return payload;
      throw new ApiRequestError(payload?.error||`HTTP ${response.status}`,{status:response.status,code:payload?.code||'',retryable:Boolean(payload?.retryable),retryAfterSeconds:retryAfterSeconds(response,payload)});
    }catch(error){
      if(error instanceof ApiRequestError)throw error;
      throw new ApiRequestError(error?.name==='AbortError'?'Local Search API request timed out.':(error?.message||'Local Search API request failed.'),{cause:error});
    }finally{clearTimeout(timer)}
  }
  async function apiJson(path,timeout=API_REQUEST_TIMEOUT,{busyRetries=2}={}){
    let attempt=0;
    while(true){
      try{return await fetchJsonWithTimeout(API_BASE+path,timeout)}
      catch(error){
        if(error?.status===503&&error?.code==='database_busy'&&attempt<busyRetries){
          attempt+=1;await sleep(Math.max(1,error.retryAfterSeconds||2)*1000);continue;
        }
        throw error;
      }
    }
  }
  async function supervisorJson(path,timeout=4000){return fetchJsonWithTimeout(path,timeout)}
  async function wakeAndWaitForApi(timeout=API_COLD_START_TIMEOUT){
    const started=Date.now();let lastReason='Search API is starting.';
    try{
      const wake=await supervisorJson(API_WAKE,6000);
      if(wake?.apiReady)return {ready:true,state:wake};
      if(wake?.apiRunning===false)lastReason='supervisor could not start the Search API';
    }catch(error){lastReason=apiFailureReason(error)}
    while(Date.now()-started<timeout){
      await sleep(API_READY_POLL_MS);
      try{
        const state=await supervisorJson(API_STATUS,3000);
        if(state?.apiReady)return {ready:true,state};
        lastReason=state?.apiRunning?'Search API is running but its database is not ready':'Search API process is not running';
      }catch(error){lastReason=apiFailureReason(error)}
    }
    return {ready:false,reason:lastReason};
  }
  async function loadCourtData(){
    const courtData=await getJson('data/courthouses.json').catch(()=>[]);
    return Array.isArray(courtData)?courtData:(courtData.courthouses||courtData.records||courtData.items||[]);
  }
  async function loadPeopleData(){
    const peopleData=await getJson('data/search-people.json').catch(()=>({records:[]}));
    return Array.isArray(peopleData)?peopleData:(peopleData.records||peopleData.people||[]);
  }
  async function loadStaticRecords(){
    const first=await getJson('data/daily-court-lists.json'),count=Number(first.pageCount||1);
    const later=await Promise.all(Array.from({length:Math.max(0,count-1)},(_,i)=>getJson(`data/daily-court-lists-page-${i+2}.json`)));
    return [first,...later].flatMap(x=>x.appearances||[]).filter(x=>x.participant_name);
  }
  function createApiProvider(facets=emptyFacets()){
    return {
      kind:'api',mode:'Local Search API',catalogueTotal:Number(facets.catalogueTotal||0),courthouses:Array.isArray(facets.courthouses)?facets.courthouses:[],
      async search(filters){return apiJson('/api/appearances?'+queryString(filters),API_REQUEST_TIMEOUT)},
      async history(record){return (await apiJson('/api/appearances/history?appearanceId='+encodeURIComponent(record.appearance_id||''),API_REQUEST_TIMEOUT)).records||[]},
      async all(filters){
        const records=[];let offset=0,total=0;
        const exportFilters={...filters,group:''};
        do{const page=await apiJson('/api/appearances?'+queryString({...exportFilters,limit:1000,offset}),12000);total=Number(page.total||0);records.push(...(page.records||[]));offset=records.length}while(offset<total);
        return records;
      }
    };
  }
  function courthouseMatch(name,courts){
    const target=normalizeCourt(name);
    if(!target)return null;
    const exact=courts.find(c=>[c.name,c.city,c.registry,c.responsible_registry,c.slug].filter(Boolean).some(v=>normalizeCourt(v)===target||slugify(v)===slugify(name)));
    return exact||courts.find(c=>[c.name,c.city,c.registry,c.responsible_registry].filter(Boolean).some(v=>{const n=normalizeCourt(v);return n.length>=4&&(target.includes(n)||n.includes(target))}))||null;
  }
  function courthouseLink(name,courts){
    const match=courthouseMatch(name,courts);
    if(!match)return esc(name||'');
    const slug=match.slug||match.courthouse_slug||slugify(match.name||name);
    return `<a href="court/detail.html?court=${encodeURIComponent(slug)}">${esc(name||match.name||'Courthouse')}</a>`;
  }
  const personRecordNames=record=>[record.title,...(record.names||[]),...(record.name_variants||[]),record.display_name,record.name].filter(Boolean);
  function buildPersonIndex(people){
    const map=new Map();
    people.filter(r=>!r.type||r.type==='person').forEach(r=>personRecordNames(r).forEach(name=>{
      const key=normalize(name);if(!key)return;if(!map.has(key))map.set(key,[]);map.get(key).push(r);
    }));
    return map;
  }
  const personIdOf=r=>r?.id||r?.person_id||r?.entity_id||'';
  const staticIdentityFields=(record,personIndex)=>{
    const matches=personIndex.get(normalize(record.participant_name))||[],unique=[...new Map(matches.map(r=>[personIdOf(r)||JSON.stringify(r),r])).values()];
    return {identity_match_count:unique.length,person_profile_id:unique.length===1?personIdOf(unique[0]):'',identity_review_required:unique.length!==1};
  };
  function createStaticProvider(records,people=[]){
    const personIndex=buildPersonIndex(people);
    const prepared=records.map((r,__index)=>({...r,...staticIdentityFields(r,personIndex),__index,__searchName:normalize(r.participant_name),__searchDate:String(r.list_date||'')}));
    const historyIndexes=buildHistoryIndexes(prepared);
    prepared.forEach(record=>{record.history_count=historyIdsFor(record,historyIndexes).length});
    const matching=filters=>sortRecords(prepared.filter(r=>{
      const name=normalize(filters.name),recordName=r.__searchName,nameMatch=!name||(filters.match==='exact'?recordName===name:recordName.includes(name)),date=r.__searchDate;
      return nameMatch&&(!filters.court||r.courthouse_name===filters.court)&&(!filters.from||date>=filters.from)&&(!filters.to||date<=filters.to)&&(!filters.confidence||confidenceLabel(r)===filters.confidence);
    }),filters.sort);
    const groupByFile=records=>{
      const groups=new Map();
      records.forEach(record=>{
        const file=normalize(record.court_file_number),key=file?`file:${file}`:`appearance:${record.appearance_id||record.__index}`;
        if(!groups.has(key))groups.set(key,[]);groups.get(key).push(record);
      });
      return [...groups.values()].map(items=>({...items[0],group_count:items.length,grouped_appearances:items,history_count:Math.max(...items.map(x=>Number(x.history_count||1)))}));
    };
    return {
      kind:'static',mode:'Static JSON fallback',catalogueTotal:prepared.length,courthouses:[...new Set(prepared.map(x=>x.courthouse_name).filter(Boolean))].sort((a,b)=>a.localeCompare(b)),people,
      async search(filters){const matches=matching(filters),results=filters.group==='file'?groupByFile(matches):matches;return {records:results.slice(filters.offset,filters.offset+filters.limit),total:results.length,limit:filters.limit,offset:filters.offset,source:'static-json',grouped:filters.group==='file'}},
      async history(record){return historyIdsFor(record,historyIndexes).map(i=>prepared[i]).sort((a,b)=>String(b.list_date).localeCompare(String(a.list_date))||String(b.appearance_time).localeCompare(String(a.appearance_time)))},
      async all(filters){return matching({...filters,group:''})}
    };
  }
  function personActionsMarkup(record,personIndex){
    const name=String(record.participant_name||'').trim();
    let count=Number.isFinite(Number(record.identity_match_count))?Number(record.identity_match_count):null;
    let profileId=String(record.person_profile_id||'').trim();
    if(count===null){
      const matches=personIndex.get(normalize(name))||[],unique=[...new Map(matches.map(r=>[personIdOf(r)||JSON.stringify(r),r])).values()];
      count=unique.length;if(count===1)profileId=personIdOf(unique[0]);
    }
    const links=[];
    if(count===1&&profileId)links.push(`<a class="mini-link" href="person-profile.html?id=${encodeURIComponent(profileId)}">Open person profile</a>`);
    links.push(`<a class="mini-link" href="identity-review.html?q=${encodeURIComponent(name)}">Review identity</a>`);
    if(count===0)links.push(`<a class="mini-link" href="identity-review.html?action=create&amp;q=${encodeURIComponent(name)}">Create person profile</a>`);
    return `<span class="appearance-person-actions">${links.join('')}</span>`;
  }
  function nameQuality(name){
    const raw=String(name||'').trim(),tokens=raw.replace(/,/g,' ').split(/\s+/).filter(Boolean),letterTokens=tokens.filter(t=>/[A-Za-z]/.test(t));
    const initialsOnly=letterTokens.length>0&&letterTokens.every(t=>/^[A-Za-z]\.?$/.test(t));
    const incomplete=!raw||letterTokens.length<2||letterTokens.some(t=>/^[A-Za-z]\.?$/.test(t));
    return {initialsOnly,incomplete};
  }
  function dataQualityMarkup(record,courts){
    const flags=[],quality=nameQuality(record.participant_name),tier=confidenceLabel(record);
    const addFlag=(label,href='')=>flags.push({label,href});
    if(quality.initialsOnly)addFlag('Initials-only name');
    if(quality.incomplete&&!quality.initialsOnly)addFlag('Incomplete name');
    if(!String(record.court_file_number||'').trim())addFlag('Missing court file');
    if(!String(record.list_date||'').trim())addFlag('Missing date');
    if(record.courthouse_name&&!courthouseMatch(record.courthouse_name,courts))addFlag('Unmatched courthouse');
    if(['Possible','Non Verified'].includes(tier))addFlag('Weak charge link','data-dictionary.html#charge-confidence');
    if(!flags.length)return '';
    return `<span class="appearance-quality-flags" aria-label="Data-quality indicators">${flags.map(flag=>flag.href?`<a class="appearance-quality-flag" href="${esc(flag.href)}" title="Open ${esc(flag.label)} definition">${esc(flag.label)}</a>`:`<span class="appearance-quality-flag">${esc(flag.label)}</span>`).join('')}</span>`;
  }
  const cleanChargeNotice=(notice,tier)=>{
    const text=String(notice||'').trim();
    if(!text)return tier==='Charge Not Available'
      ?'No charge information  linked to this appearance.'
      :'Verify against the official case source.';
    const prefix=new RegExp(`^${rxEsc(tier)}\\s*[—–-]\\s*`,'i');
    return text.replace(prefix,'').trim();
  };
  const historyKey=r=>({name:normalize(r.participant_name),file:normalize(r.court_file_number)});
  function buildHistoryIndexes(records){
    const byName=new Map(),byFile=new Map();
    records.forEach((r,index)=>{
      const key=historyKey(r);
      if(key.name){if(!byName.has(key.name))byName.set(key.name,[]);byName.get(key.name).push(index)}
      if(key.file){if(!byFile.has(key.file))byFile.set(key.file,[]);byFile.get(key.file).push(index)}
    });
    return {byName,byFile};
  }
  function historyIdsFor(record,indexes){
    const key=historyKey(record),ids=new Set([record.__index]);
    (indexes.byName.get(key.name)||[]).forEach(i=>ids.add(i));
    (indexes.byFile.get(key.file)||[]).forEach(i=>ids.add(i));
    return [...ids];
  }
  const sameAppearance=(a,b)=>Boolean(a&&b&&(
    (a.appearance_id&&b.appearance_id&&a.appearance_id===b.appearance_id)||
    (!a.appearance_id&&!b.appearance_id&&[a.participant_name,a.court_file_number,a.list_date,a.appearance_time].join('|')===[b.participant_name,b.court_file_number,b.list_date,b.appearance_time].join('|'))
  ));
  const historyMarkup=(history,current,courts)=>{
    const items=history.map(h=>{
      const isCurrent=sameAppearance(h,current),fields=[
        `<span><strong>Date:</strong> ${esc(h.list_date||'Unknown date')}</span>`,
        h.appearance_time?`<span><strong>Time:</strong> ${esc(h.appearance_time)}</span>`:'',
        `<span><strong>Courthouse:</strong> ${courthouseLink(h.courthouse_name,courts)}</span>`,
        h.court_file_number?`<span><strong>File:</strong> ${esc(h.court_file_number)}</span>`:'',
        h.appearance_type?`<span><strong>Appearance:</strong> ${esc(h.appearance_type)}</span>`:''
      ].filter(Boolean).join('<span class="appearance-separator" aria-hidden="true"> · </span>');
      return `<li${isCurrent?' class="appearance-current"':''}>${fields}${isCurrent?' <span class="appearance-current-tag">Current result</span>':''}</li>`;
    }).join('');
    return `<ul aria-label="Appearance history">${items}</ul>`;
  };
  const URL_FILTER_KEYS=['name','match','court','from','to','confidence','sort','pageSize','page','view','groupByFile'];
  function mountSearch(host,initialProvider,initialCourts=[],people=[],getFallback=null,onApiFailure=null){
    host.innerHTML=markup();
    const $=s=>host.querySelector(s),$$=s=>[...host.querySelectorAll(s)],nameInput=$('[data-appearance-name]'),matchInput=$('[data-appearance-match]'),courtInput=$('[data-appearance-court]'),fromInput=$('[data-appearance-from]'),toInput=$('[data-appearance-to]'),confidenceInput=$('[data-appearance-confidence]'),sortInput=$('[data-appearance-sort]'),rows=$('[data-appearance-rows]'),status=$('[data-appearance-status]'),empty=$('[data-appearance-empty]'),exportRow=$('[data-appearance-export]'),pagination=$('[data-appearance-pagination]'),pageNumber=$('[data-page-number]'),pageSizeInputs=$$('[data-page-size-top]'),prevButton=$('[data-page-prev]'),nextButton=$('[data-page-next]'),activeFilters=$('[data-active-filters]'),recordHeading=$('[data-record-heading]'),groupButton=$('[data-group-file]'),viewButtons=$$('[data-view]'),shortcutButtons=$$('[data-date-shortcut]');
    let courts=initialCourts,personIndex=buildPersonIndex(people),provider=initialProvider,fallbackCourthouses=[],pageRecords=[],total=0,offset=0,pageSize=50,searchSerial=0,lastStatus='',view='detailed',groupByFile=false,restoringUrl=false;
    const setExportAvailable=available=>{exportRow.hidden=!available;exportRow.querySelectorAll('button').forEach(button=>{button.disabled=!available})};
    const supportCourtNames=()=>[...new Set(courts.map(c=>c.name||c.courthouse_name||c.city||c.registry).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
    const setCourtOptions=()=>{
      const selected=courtInput.value||courtInput.dataset.pendingValue||'',available=(provider.courthouses&&provider.courthouses.length?provider.courthouses:(fallbackCourthouses.length?fallbackCourthouses:supportCourtNames())),choices=selected&&!available.includes(selected)?[selected,...available]:available;
      courtInput.innerHTML='<option value="">All courthouses</option>'+choices.map(x=>`<option>${esc(x)}</option>`).join('');
      if(selected){courtInput.value=selected;if(courtInput.value===selected)delete courtInput.dataset.pendingValue;}
    };
    const requestFallback=async error=>{
      if(!getFallback)return null;
      const fallback=await getFallback();
      if(Array.isArray(fallback.people))personIndex=buildPersonIndex(fallback.people);
      fallbackCourthouses=Array.isArray(fallback.courthouses)?fallback.courthouses:[];
      setCourtOptions();
      if(error&&typeof onApiFailure==='function')onApiFailure(error);
      return fallback;
    };
    const apiFailureStatus=(reason,action='using static JSON for this request')=>`Local Search API unavailable: ${reason}. ${action}.`;
    setCourtOptions();
    const currentFilters=()=>({name:nameInput.value.trim(),match:matchInput.value,court:courtInput.value||courtInput.dataset.pendingValue||'',from:fromInput.value,to:toInput.value,confidence:confidenceInput.value,sort:sortInput.value,group:groupByFile?'file':'',limit:pageSize,offset});
    const isActive=filters=>Boolean(normalize(filters.name)||filters.court||filters.from||filters.to||filters.confidence);
    const updateShortcutState=()=>{
      const today=relativeDate(0),next=relativeDate(6),past=relativeDate(-29);
      shortcutButtons.forEach(button=>{
        const key=button.dataset.dateShortcut;
        const active=(key==='today'&&fromInput.value===today&&toInput.value===today)||(key==='next7'&&fromInput.value===today&&toInput.value===next)||(key==='past30'&&fromInput.value===past&&toInput.value===today)||(key==='all'&&!fromInput.value&&!toInput.value);
        button.setAttribute('aria-pressed',String(active));
      });
    };
    const renderActiveFilters=()=>{
      const filters=currentFilters(),items=[];
      if(filters.name)items.push(['name',`Name: ${filters.name}`]);
      if(filters.match==='exact')items.push(['match','Exact full name']);
      if(filters.court)items.push(['court',filters.court]);
      if(filters.from||filters.to)items.push(['dates',`Date: ${filters.from||'Any'} to ${filters.to||'Any'}`]);
      if(filters.confidence)items.push(['confidence',filters.confidence]);
      activeFilters.innerHTML=items.map(([key,label])=>`<button class="theme-pill" type="button" data-clear-filter="${key}" title="Remove ${esc(label)}">${esc(label)} <span aria-hidden="true">×</span></button>`).join('');
      activeFilters.hidden=!items.length;updateShortcutState();
    };
    const setView=next=>{
      view=next==='compact'?'compact':'detailed';host.classList.toggle('appearance-view-compact',view==='compact');recordHeading.textContent=view==='compact'?'Summary':'Record details';
      viewButtons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.view===view)));
    };
    const setGroup=enabled=>{groupByFile=Boolean(enabled);groupButton.setAttribute('aria-pressed',String(groupByFile));};
    const applyUrlState=()=>{
      const p=new URLSearchParams(location.search);
      nameInput.value=p.get('name')||'';matchInput.value=p.get('match')==='exact'?'exact':'partial';courtInput.dataset.pendingValue=p.get('court')||'';courtInput.value=courtInput.dataset.pendingValue;fromInput.value=p.get('from')||'';toInput.value=p.get('to')||'';confidenceInput.value=p.get('confidence')||'';
      const allowedSort=new Set(['newest','oldest','name','courthouse','confidence','history']);sortInput.value=allowedSort.has(p.get('sort'))?p.get('sort'):'newest';
      pageSize=p.get('pageSize')==='100'?100:50;pageSizeInputs.forEach(input=>{input.value=String(pageSize)});offset=Math.max(0,(Math.max(1,Number(p.get('page')||1))-1)*pageSize);
      setView(p.get('view')==='compact'?'compact':'detailed');setGroup(p.get('groupByFile')==='1');renderActiveFilters();
    };
    const syncUrl=mode=>{
      if(restoringUrl)return;
      const url=new URL(location.href),filters=currentFilters();URL_FILTER_KEYS.forEach(key=>url.searchParams.delete(key));
      if(filters.name)url.searchParams.set('name',filters.name);if(filters.match==='exact')url.searchParams.set('match','exact');if(filters.court)url.searchParams.set('court',filters.court);if(filters.from)url.searchParams.set('from',filters.from);if(filters.to)url.searchParams.set('to',filters.to);if(filters.confidence)url.searchParams.set('confidence',filters.confidence);if(filters.sort!=='newest')url.searchParams.set('sort',filters.sort);if(pageSize!==50)url.searchParams.set('pageSize',String(pageSize));if(offset>0)url.searchParams.set('page',String(Math.floor(offset/pageSize)+1));if(view==='compact')url.searchParams.set('view','compact');if(groupByFile)url.searchParams.set('groupByFile','1');
      window.history[mode==='push'?'pushState':'replaceState']({appearanceSearch:true},'',url);
    };
    const updatePagination=()=>{
      if(!total){pagination.hidden=true;return}
      const pages=Math.max(1,Math.ceil(total/pageSize)),page=Math.floor(offset/pageSize)+1;
      pagination.hidden=false;pageNumber.textContent=`Page ${page.toLocaleString()} of ${pages.toLocaleString()}`;
      prevButton.disabled=offset<=0;nextButton.disabled=offset+pageSize>=total;
    };
    const renderRows=(records,highlightNames)=>{
      rows.innerHTML=records.map((r,index)=>{
        const historyCount=Math.max(1,Number(r.history_count||1)),nameMarkup=highlightResultName(r.participant_name,r.participant_name,highlightNames),label=`${historyCount} catalogued appearance${historyCount===1?'':'s'}`;
        const historyControl=`<details class="appearance-history" data-history-index="${index}"><summary class="appearance-count">${label}</summary><div class="appearance-history-body"><p class="empty">Open to load appearance history.</p></div></details>`;
        const details=view==='compact'?compactRecordMarkup(r,courts):recordDetailsMarkup(r,courts);
        const groupNotice=Array.isArray(r.grouped_appearances)&&r.grouped_appearances.length>1?`<span class="appearance-group-count">${r.grouped_appearances.length.toLocaleString()} grouped records</span>`:'';
        return `<tr><td class="appearance-name-cell"><span class="appearance-name-heading"><strong class="record-person-name">${nameMarkup}</strong>${chargeBadgeMarkup(r)}</span>${groupNotice}${personActionsMarkup(r,personIndex)}${dataQualityMarkup(r,courts)}</td><td class="appearance-record-cell">${details}${courtFileGroupMarkup(r,courts)}${historyControl}</td></tr>`;
      }).join('');
    };
    const showIdle=()=>{
      pageRecords=[];total=0;offset=0;rows.innerHTML='';setExportAvailable(false);pagination.hidden=true;empty.hidden=false;empty.textContent='No search is active.';renderActiveFilters();
      lastStatus=Number(provider.catalogueTotal||0)>0
        ?`${Number(provider.catalogueTotal).toLocaleString()} catalogued scheduled appearances available · ${provider.mode}. Enter at least one filter.`
        :`Search fields ready · ${provider.mode} is starting in the background. Enter at least one filter.`;
      status.textContent=lastStatus;
    };
    const runSearch=async({allowFallback=true,sync='replace'}={})=>{
      renderActiveFilters();if(sync)syncUrl(sync);
      let filters=currentFilters();const name=normalize(filters.name),typedLength=name.replace(/\s+/g,'').length,active=isActive(filters),serial=++searchSerial;
      if(!active){showIdle();return}
      if(name&&typedLength<2){pageRecords=[];total=0;rows.innerHTML='';setExportAvailable(false);pagination.hidden=true;status.textContent='Type at least 2 letters to search by name.';empty.hidden=false;empty.textContent='Keep typing to begin the name search.';return}
      status.textContent=`Searching ${provider.mode}…`;empty.hidden=true;
      const displayResult=async(result,mode,apiReason='')=>{
        if(serial!==searchSerial)return;
        pageRecords=result.records||[];total=Number(result.total||0);
        if(total&&offset>=total){
          offset=Math.max(0,(Math.ceil(total/pageSize)-1)*pageSize);syncUrl('replace');filters=currentFilters();return false;
        }
        renderRows(pageRecords,typedLength>=4);setExportAvailable(total>0);empty.hidden=total>0;empty.textContent='No matching catalogued appearances.';
        const start=total?offset+1:0,end=Math.min(offset+pageRecords.length,total),noun=groupByFile?'court-file groups':'catalogued appearances';
        const apiNote=apiReason?` · API unavailable: ${apiReason}.`:'';
        lastStatus=total?`Showing ${start.toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()} matching ${noun} · ${mode}${apiNote}`:`0 matching ${noun} · ${mode}${apiNote}`;
        status.textContent=lastStatus;updatePagination();return true;
      };
      try{
        let result=await provider.search(filters);
        if(await displayResult(result,provider.mode)===false){result=await provider.search(currentFilters());await displayResult(result,provider.mode)}
      }catch(error){
        if(serial!==searchSerial)return;
        const reason=apiFailureReason(error);
        if(provider.kind==='api'&&typeof onApiFailure==='function')onApiFailure(error);
        if(allowFallback&&provider.kind==='api'&&getFallback){
          status.textContent=apiFailureStatus(reason,'loading static JSON for this request');
          try{
            const fallback=await requestFallback();
            let result=await fallback.search(filters);
            if(await displayResult(result,fallback.mode,reason)===false){result=await fallback.search(currentFilters());await displayResult(result,fallback.mode,reason)}
            return;
          }catch(fallbackError){
            pageRecords=[];total=0;rows.innerHTML='';setExportAvailable(false);pagination.hidden=true;empty.hidden=false;empty.textContent='Search could not be completed.';status.textContent=`${apiFailureStatus(reason,'static JSON fallback also failed')} ${fallbackError.message||''}`.trim();return;
          }
        }
        pageRecords=[];total=0;rows.innerHTML='';setExportAvailable(false);pagination.hidden=true;empty.hidden=false;empty.textContent='Search could not be completed.';status.textContent=provider.kind==='api'?apiFailureStatus(reason,'search could not be completed'):error.message||'Appearance search unavailable.';
      }
    };
    rows.addEventListener('toggle',async event=>{
      const details=event.target.closest?.('details[data-history-index]');
      if(!details||!details.open||details.dataset.loaded==='1')return;
      const current=pageRecords[Number(details.dataset.historyIndex)],body=details.querySelector('.appearance-history-body');
      if(!current||!body)return;
      body.innerHTML='<p class="empty">Loading appearance history…</p>';
      try{const history=await provider.history(current);body.innerHTML=historyMarkup(history,current,courts);details.dataset.loaded='1'}
      catch(error){
        const reason=apiFailureReason(error);
        if(provider.kind==='api'&&typeof onApiFailure==='function')onApiFailure(error);
        try{
          if(provider.kind==='api'&&getFallback){const fallback=await requestFallback();const history=await fallback.history(current);body.innerHTML=historyMarkup(history,current,courts);details.dataset.loaded='1';status.textContent=`${lastStatus} API history unavailable: ${reason}. Static JSON was used for this history request.`;return}
        }catch{}
        body.innerHTML=`<p class="empty">${esc(provider.kind==='api'?`API history unavailable: ${reason}`:(error.message||'Appearance history unavailable.'))}</p>`
      }
    },true);
    const withAllResults=async action=>{
      const filters=currentFilters(),buttons=[...exportRow.querySelectorAll('button')];buttons.forEach(button=>button.disabled=true);status.textContent=`Preparing all matching records…`;
      try{const records=await provider.all(filters);action(records);status.textContent=lastStatus}
      catch(error){
        const reason=apiFailureReason(error);
        if(provider.kind==='api'&&typeof onApiFailure==='function')onApiFailure(error);
        try{
          if(provider.kind==='api'&&getFallback){const fallback=await requestFallback();const records=await fallback.all(filters);action(records);status.textContent=`${lastStatus} API export unavailable: ${reason}. Static JSON was used for this export request.`;return}
        }catch{}
        status.textContent=provider.kind==='api'?`Could not prepare the full export. API unavailable: ${reason}.`:(error.message||'Could not prepare the full export.')
      }
      finally{buttons.forEach(button=>button.disabled=false)}
    };
    const changeAndSearch=(mode='push')=>{offset=0;runSearch({sync:mode})};
    let timer;
    nameInput.addEventListener('input',()=>{clearTimeout(timer);offset=0;timer=setTimeout(()=>runSearch({sync:'replace'}),240)});
    [matchInput,fromInput,toInput,confidenceInput,sortInput].forEach(el=>el.addEventListener('change',()=>changeAndSearch('push')));courtInput.addEventListener('change',()=>{delete courtInput.dataset.pendingValue;changeAndSearch('push')});
    pageSizeInputs.forEach(input=>input.addEventListener('change',()=>{pageSize=Number(input.value)||50;pageSizeInputs.forEach(other=>{other.value=String(pageSize)});changeAndSearch('push')}));
    prevButton.addEventListener('click',()=>{offset=Math.max(0,offset-pageSize);runSearch({sync:'push'})});
    nextButton.addEventListener('click',()=>{if(offset+pageSize<total){offset+=pageSize;runSearch({sync:'push'})}});
    shortcutButtons.forEach(button=>button.addEventListener('click',()=>{
      const key=button.dataset.dateShortcut,today=relativeDate(0);
      if(key==='today'){fromInput.value=today;toInput.value=today}
      else if(key==='next7'){fromInput.value=today;toInput.value=relativeDate(6)}
      else if(key==='past30'){fromInput.value=relativeDate(-29);toInput.value=today}
      else{fromInput.value='';toInput.value=''}
      changeAndSearch('push');
    }));
    activeFilters.addEventListener('click',event=>{
      const button=event.target.closest('[data-clear-filter]');if(!button)return;
      const key=button.dataset.clearFilter;
      if(key==='name')nameInput.value='';else if(key==='match')matchInput.value='partial';else if(key==='court'){courtInput.value='';delete courtInput.dataset.pendingValue;}else if(key==='dates'){fromInput.value='';toInput.value=''}else if(key==='confidence')confidenceInput.value='';
      changeAndSearch('push');
    });
    viewButtons.forEach(button=>button.addEventListener('click',()=>{setView(button.dataset.view);if(pageRecords.length)renderRows(pageRecords,normalize(nameInput.value).replace(/\s+/g,'').length>=4);syncUrl('push')}));
    groupButton.addEventListener('click',()=>{setGroup(!groupByFile);changeAndSearch('push')});
    $('[data-export-csv]').addEventListener('click',()=>withAllResults(records=>{const data=exportRows(records),headers=Object.keys(data[0]||{});if(!headers.length)return;downloadFile('appearance-search-results.csv','text/csv;charset=utf-8',headers.join(',')+'\r\n'+data.map(r=>headers.map(h=>csvCell(r[h])).join(',')).join('\r\n'))}));
    $('[data-export-json]').addEventListener('click',()=>withAllResults(records=>downloadFile('appearance-search-results.json','application/json;charset=utf-8',JSON.stringify({exported_at:new Date().toISOString(),count:records.length,records:exportRows(records)},null,2))));
    $('[data-export-print]').addEventListener('click',()=>withAllResults(records=>printReport(records,{Name:nameInput.value.trim(),Matching:matchInput.value,Courthouse:courtInput.value,From:fromInput.value,To:toInput.value,'Charge confidence':confidenceInput.value,'Sort results':sortInput.options[sortInput.selectedIndex]?.textContent||sortInput.value})));
    $('[data-appearance-clear]').addEventListener('click',()=>{clearTimeout(timer);searchSerial++;nameInput.value='';matchInput.value='partial';courtInput.value='';delete courtInput.dataset.pendingValue;fromInput.value='';toInput.value='';confidenceInput.value='';sortInput.value='newest';pageSize=50;pageSizeInputs.forEach(input=>{input.value='50'});setView('detailed');setGroup(false);showIdle();syncUrl('push')});
    window.addEventListener('popstate',()=>{restoringUrl=true;applyUrlState();restoringUrl=false;runSearch({sync:null})});
    applyUrlState();
    if(isActive(currentFilters()))runSearch({sync:null});else showIdle();
    return {
      setProvider(nextProvider){
        const idle=!isActive(currentFilters());
        provider=nextProvider;setCourtOptions();
        if(idle)showIdle();
        else{status.textContent='Local Search API is ready. Refreshing current results…';runSearch({sync:'replace'})}
      },
      setApiFailure(reason){
        if(!isActive(currentFilters()))status.textContent=`Search fields ready · Local Search API unavailable: ${reason}. Static JSON will be used only for requests that fail.`;
      },
      setSupportData(support={}){
        if(Array.isArray(support.courts))courts=support.courts;
        if(Array.isArray(support.people))personIndex=buildPersonIndex(support.people);
        setCourtOptions();
        if(pageRecords.length)renderRows(pageRecords,normalize(nameInput.value).replace(/\s+/g,'').length>=4);
      }
    };
  }
  function init(){
    const hosts=[...document.querySelectorAll('[data-appearance-search-renderer]')];
    if(!hosts.length)return;
    let fallbackPromise,recoveryRunning=false,recoveryTimer=null,controllers=[];
    const getFallback=()=>fallbackPromise||(fallbackPromise=Promise.all([loadStaticRecords(),loadPeopleData()]).then(([records,people])=>createStaticProvider(records,people)));
    const cachedFacets=readCachedFacets();
    const scheduleRecovery=error=>{
      const immediateReason=error?apiFailureReason(error):'Search API is starting';
      controllers.forEach(controller=>controller.setApiFailure(immediateReason));
      if(recoveryRunning||recoveryTimer)return;
      recoveryTimer=setTimeout(async()=>{
        recoveryTimer=null;recoveryRunning=true;
        try{
          while(hosts.some(host=>host.isConnected)){
            const readiness=await wakeAndWaitForApi();
            if(readiness.ready){
              try{
                const facets=await apiJson('/api/appearances/facets',API_REQUEST_TIMEOUT);
                writeCachedFacets(facets);
                controllers.forEach(controller=>controller.setProvider(createApiProvider(facets)));
                return;
              }catch(facetError){controllers.forEach(controller=>controller.setApiFailure(apiFailureReason(facetError)))}
            }else controllers.forEach(controller=>controller.setApiFailure(readiness.reason||'Search API is not ready'));
            await sleep(5000);
          }
        }finally{recoveryRunning=false}
      },error?500:0);
    };
    controllers=hosts.map(host=>mountSearch(host,createApiProvider(cachedFacets),[],[],getFallback,scheduleRecovery));

    loadCourtData()
      .then(courts=>controllers.forEach(controller=>controller.setSupportData({courts})))
      .catch(()=>{});

    scheduleBackground(()=>scheduleRecovery());
  }
  const mount=(host,records,courts=[],people=[])=>mountSearch(host,createStaticProvider(records,people),courts,people,null);
  window.AppearanceSearchRenderer={init,mount};
  init();
})();
