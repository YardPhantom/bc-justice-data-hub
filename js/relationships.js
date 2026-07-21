const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const input=document.querySelector('#relSearch');
const out=document.querySelector('#relResults');
const summary=document.querySelector('#relSummary');

const load=async url=>{
  try{
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)return null;
    return await response.json();
  }catch{return null;}
};
const records=(data,keys=[])=>{
  if(Array.isArray(data))return data;
  for(const key of keys)if(Array.isArray(data?.[key]))return data[key];
  return [];
};
async function loadPaged(url,keys){
  const data=await load(url);
  if(!data)return [];
  const first=records(data,keys);
  const pages=Math.max(1,Number(data.pageCount||1));
  if(pages<=1)return first;
  const extra=await Promise.all(Array.from({length:pages-1},(_,index)=>load(url.replace(/\.json$/i,`-page-${index+2}.json`))));
  return [...first,...extra.flatMap(page=>records(page,keys))];
}
const text=(row,...keys)=>{
  for(const key of keys){
    const value=row?.[key];
    if(value!==undefined&&value!==null&&String(value).trim())return String(value).trim();
  }
  return '';
};
const fileNumber=row=>text(row,'court_file_number','file_number','fileNumber','court_file');
const citation=row=>text(row,'citation','neutral_citation');
const caseId=row=>text(row,'case_id','caseId');
const normalize=value=>String(value||'').trim().toLowerCase().replace(/\s+/g,' ');
const matterKey=row=>{
  const file=normalize(fileNumber(row));
  if(file)return `file:${file}`;
  const cite=normalize(citation(row));
  if(cite)return `citation:${cite}`;
  const id=normalize(caseId(row));
  if(id)return `case:${id}`;
  return '';
};
const unique=values=>[...new Set(values.map(value=>String(value||'').trim()).filter(Boolean))];
const label=value=>String(value||'unknown').replaceAll('_',' ').replace(/\b\w/g,char=>char.toUpperCase());
const statusClass=value=>{
  const v=normalize(value);
  if(v.includes('convict'))return 'status-convicted';
  if(v.includes('acquit'))return 'status-acquitted';
  if(v.includes('stay')||v.includes('dismiss')||v.includes('withdraw'))return 'status-closed';
  if(v.includes('scheduled')||v.includes('appearance'))return 'status-scheduled';
  if(v.includes('charg')||v.includes('alleg')||v.includes('accus'))return 'status-charged';
  return 'status-review';
};

let matters=[];
function build({cases,appearances,judgments,people,mentions}){
  const map=new Map();
  const ensure=(row,type)=>{
    const key=matterKey(row);
    if(!key)return null;
    if(!map.has(key))map.set(key,{key,cases:[],appearances:[],judgments:[],people:[],mentions:[]});
    const matter=map.get(key);
    matter[type].push(row);
    return matter;
  };
  cases.forEach(row=>ensure(row,'cases'));
  appearances.forEach(row=>ensure(row,'appearances'));
  judgments.forEach(row=>ensure(row,'judgments'));
  mentions.forEach(row=>ensure(row,'mentions'));

  const peopleById=new Map(people.map(row=>[text(row,'person_id','id'),row]));
  for(const matter of map.values()){
    const ids=unique([
      ...matter.cases.map(row=>text(row,'person_id')),
      ...matter.appearances.map(row=>text(row,'person_id')),
      ...matter.mentions.map(row=>text(row,'person_id'))
    ]);
    matter.people=ids.map(id=>peopleById.get(id)).filter(Boolean);
  }
  return [...map.values()];
}
function matterNames(matter){
  return unique([
    ...matter.people.map(row=>text(row,'display_name','canonical_name','full_name','name')),
    ...matter.mentions.map(row=>text(row,'exact_name','display_name','person_name','participant_name','name')),
    ...matter.cases.map(row=>text(row,'person_name','participant_name','people','case_title','title')),
    ...matter.appearances.map(row=>text(row,'person_name','participant_name','name')),
    ...matter.judgments.map(row=>text(row,'case_title','title','style_of_cause'))
  ]);
}
function matterLocations(matter){
  return unique([...matter.cases,...matter.appearances,...matter.judgments,...matter.mentions].map(row=>text(row,'courthouse_name','courthouse','court','location','city','registry')));
}
function matterOffences(matter){
  return unique([...matter.cases,...matter.appearances,...matter.judgments,...matter.mentions].flatMap(row=>{
    const raw=row.offences??row.offence??row.offence_text??row.charge??row.charges??'';
    return Array.isArray(raw)?raw:[raw];
  }));
}
function matterStatuses(matter){
  return unique([...matter.cases,...matter.appearances,...matter.judgments,...matter.mentions].map(row=>text(row,'legal_status','status','final_outcome','outcome')));
}
function matterSources(matter){
  return unique([
    ...matter.cases.map(()=> 'Case index'),
    ...matter.appearances.map(()=> 'Court list'),
    ...matter.judgments.map(()=> 'Judgment'),
    ...matter.mentions.map(row=>label(text(row,'source_entity_type','source_type')||'Person mention'))
  ]);
}
function searchText(matter){
  return normalize(JSON.stringify({
    file:matterKey(matter.cases[0]||matter.appearances[0]||matter.judgments[0]||matter.mentions[0]),
    names:matterNames(matter),locations:matterLocations(matter),offences:matterOffences(matter),statuses:matterStatuses(matter),sources:matterSources(matter),matter
  }));
}
function renderCard(matter){
  const anchor=matter.cases[0]||matter.appearances[0]||matter.judgments[0]||matter.mentions[0]||{};
  const names=matterNames(matter);
  const locations=matterLocations(matter);
  const offences=matterOffences(matter);
  const statuses=matterStatuses(matter);
  const sources=matterSources(matter);
  const file=fileNumber(anchor);
  const cite=citation(anchor)||citation(matter.judgments[0]||{});
  const query=file||cite||names[0]||'';
  return `<article class="relationship-card relationship-detail-card">
    <header class="relationship-card-head">
      <div><p class="eyebrow">Linked court matter</p><h2>${esc(names[0]||cite||file||'Unnamed linked matter')}</h2><p>${[file&&`File ${file}`,cite,locations[0]].filter(Boolean).map(esc).join(' · ')||'No file, citation, or courthouse recorded'}</p></div>
      <a class="pill" href="search.html?q=${encodeURIComponent(query)}">Open records</a>
    </header>
    <div class="relationship-detail-grid">
      <section><small>People / names</small><strong>${names.length}</strong><p>${names.map(esc).join(' · ')||'No linked person name'}</p></section>
      <section><small>Appearances</small><strong>${matter.appearances.length}</strong><p>${locations.map(esc).join(' · ')||'No courthouse recorded'}</p></section>
      <section><small>Judgments</small><strong>${matter.judgments.length}</strong><p>${matter.judgments.map(row=>esc(citation(row)||text(row,'case_title','title')||'Judgment record')).join(' · ')||'No linked judgment'}</p></section>
      <section><small>Sources</small><strong>${sources.length}</strong><p>${sources.map(esc).join(' · ')}</p></section>
    </div>
    ${statuses.length?`<div class="relationship-tags"><strong>Status:</strong> ${statuses.map(status=>`<span class="timeline-status ${statusClass(status)}">${esc(label(status))}</span>`).join(' ')}</div>`:''}
    ${offences.length?`<p><strong>Recorded offences:</strong> ${offences.map(esc).join(' · ')}</p>`:''}
    <p class="legal-note">A linked appearance, allegation, charge, or name mention is not a conviction. Only verified judgment outcomes may support a conviction label.</p>
  </article>`;
}
function draw(){
  const q=normalize(input?.value);
  const filtered=matters.filter(matter=>!q||searchText(matter).includes(q));
  if(summary)summary.textContent=`${filtered.length.toLocaleString()} matching linked matters · ${matters.length.toLocaleString()} total`;
  out.innerHTML=filtered.length?filtered.slice(0,500).map(renderCard).join(''):'<p class="empty">No linked relationships match this search. Try a person, city, courthouse, court file, citation, status, or offence.</p>';
}
async function init(){
  if(summary)summary.textContent='Loading linked records…';
  const [cso,searchCases,appearances,published,searchPeople,personMentions]=await Promise.all([
    load('data/cso-cases.json'),
    load('data/search-cases.json'),
    loadPaged('data/daily-court-lists.json',['records','appearances']),
    load('data/published-judgments.json'),
    load('data/search-people.json'),
    load('data/person-mentions.json')
  ]);
  const cases=[...records(cso,['records','cases']),...records(searchCases,['records','cases'])];
  const judgments=records(published,['records','judgments']);
  const people=records(searchPeople,['records','people']);
  const mentions=records(personMentions,['records','mentions']);
  matters=build({cases,appearances,judgments,people,mentions});
  if(!matters.length){
    if(summary)summary.textContent='0 linked matters';
    out.innerHTML='<p class="empty">No relationship data is available. Run tools\\collect-new.cmd to rebuild case, person, court-list, and judgment indexes.</p>';
    return;
  }
  draw();
}
input?.addEventListener('input',draw);
init();
