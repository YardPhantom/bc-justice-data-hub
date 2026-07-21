const $=s=>document.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));
let data={}, rows=[], decisions=new Map(); const type=document.body.dataset.advanced;
const pageParams=new URLSearchParams(location.search),pageQuery=pageParams.get('q')||pageParams.get('resource')||'';if(pageQuery&&$('#q'))$('#q').value=pageQuery;
const specs={
 prosecution:{title:'Prosecution statistics',key:'prosecution',cols:['fiscal_year','region','metric','value','unit']},
 duplicates:{title:'Duplicate-person review',key:'duplicates',cols:['name_a','name_b','match_score','reasons','status']},
 links:{title:'Cross-source case links',key:'links',cols:['case_id','entity_type','entity_id','match_method','match_score']},
 privacy:{title:'Privacy and publication safeguards',key:'privacy',cols:['severity','entity_type','flag_type','details','status']},
 timelines:{title:'Case-status timelines',key:'timelines',cols:['case_id','event_date','status','source_type','verified']},
 comparisons:{title:'Regional and period comparisons',key:'comparisons',cols:['subject_area','geography','period','metric','current_value','change_percent']}
};
function trendChart(items){if(!['comparisons','prosecution'].includes(type)||!items.length)return '';const vals=items.slice(0,20).map(r=>Number(r.current_value??r.value??0));const max=Math.max(...vals.map(Math.abs),1);return `<div class="trend-chart">${items.slice(0,20).map((r,i)=>`<div class="trend-row"><span>${esc(r.geography||r.region||r.metric||'Record')}</span><i style="--bar:${Math.max(2,Math.abs(vals[i])/max*100)}%"></i><strong>${Number(vals[i]).toLocaleString()}</strong></div>`).join('')}</div>`}

function timelineLabel(value){return String(value||'unknown').replaceAll('_',' ').replace(/\b\w/g,m=>m.toUpperCase())}
function timelineClass(value){const v=String(value||'').toLowerCase();if(v.includes('convict'))return 'status-convicted';if(v.includes('acquit'))return 'status-acquitted';if(v.includes('stay')||v.includes('dismiss')||v.includes('withdraw'))return 'status-closed';if(v.includes('scheduled')||v.includes('appearance'))return 'status-scheduled';if(v.includes('charg')||v.includes('alleg'))return 'status-charged';return 'status-review'}
function renderTimelines(){
 const q=($('#q')?.value||'').trim().toLowerCase();
 const all=Array.isArray(data.timelines)?data.timelines:[];
 const filtered=all.filter(r=>!q||JSON.stringify(r).toLowerCase().includes(q));
 const grouped=new Map();
 filtered.forEach(r=>{const key=r.case_id||r.court_file_number||r.history_id;const item=grouped.get(key)||{meta:r,events:[]};item.events.push(r);grouped.set(key,item)});
 const cases=[...grouped.values()].sort((a,b)=>String(b.events[0]?.event_date||'').localeCompare(String(a.events[0]?.event_date||'')));
 $('#count').textContent=`${cases.length.toLocaleString()} matching cases · ${filtered.length.toLocaleString()} timeline events · generated ${data.generatedAt?new Date(data.generatedAt).toLocaleString():'not yet'}`;
 $('#head').innerHTML='';
 $('#rows').innerHTML=cases.slice(0,1000).map(({meta,events})=>{
  events.sort((a,b)=>String(b.event_date||'').localeCompare(String(a.event_date||'')));
  const title=meta.case_title||meta.people||meta.court_file_number||'Unnamed case';
  const identifiers=[meta.court_file_number&&`File ${esc(meta.court_file_number)}`,meta.citation&&esc(meta.citation),meta.courthouse_slug&&esc(meta.courthouse_slug.replaceAll('-',' '))].filter(Boolean).join(' · ');
  const eventHtml=events.map(e=>`<li><time>${esc(e.event_date||'Date unavailable')}</time><span class="timeline-status ${timelineClass(e.status)}">${esc(timelineLabel(e.status))}</span><small>${esc(timelineLabel(e.source_type))}${e.verified?' · verified':' · review/unverified'}</small></li>`).join('');
  return `<tr><td><article class="case-timeline-card"><div class="case-timeline-head"><div><h3>${esc(title)}</h3><p>${identifiers||'No file or citation available'}</p></div><a class="pill" href="search.html?q=${encodeURIComponent(meta.court_file_number||meta.case_title||meta.people||meta.case_id||'')}">Open records</a></div>${meta.people?`<p><strong>People:</strong> ${esc(meta.people)}</p>`:''}${meta.offences?`<p><strong>Recorded offences:</strong> ${esc(meta.offences)}</p>`:''}<ol class="case-timeline-list">${eventHtml}</ol><p class="legal-note">Scheduled appearances, allegations and charges are not convictions. Only verified outcomes are labelled verified.</p></article></td></tr>`;
 }).join('');
 $('#empty').hidden=cases.length>0;
}

function actionCell(r){if(type==='duplicates')return `<div class="review-actions"><button data-decision="not_match" data-id="${esc(r.candidate_id)}">Not a match</button><button data-decision="verified_match" data-id="${esc(r.candidate_id)}">Same person</button><button data-decision="merge" data-id="${esc(r.candidate_id)}" data-keep="${esc(r.person_a)}" data-remove="${esc(r.person_b)}">Merge B into A</button></div>`;if(type==='links')return `<div class="review-actions"><button data-decision="approve" data-id="${esc(r.link_id)}">Approve</button><button data-decision="reject" data-id="${esc(r.link_id)}">Reject</button></div>`;return ''}
function render(){if(type==='timelines'){renderTimelines();return}const s=specs[type],q=($('#q')?.value||'').toLowerCase(); rows=(data[s.key]||[]).filter(r=>!q||JSON.stringify(r).toLowerCase().includes(q));
 $('#count').innerHTML=`${rows.length.toLocaleString()} matching records · ${decisions.size} decisions prepared · generated ${data.generatedAt?new Date(data.generatedAt).toLocaleString():'not yet'}${trendChart(rows)}`;
 const action=['duplicates','links'].includes(type); $('#head').innerHTML=s.cols.map(c=>`<th>${esc(c.replaceAll('_',' '))}</th>`).join('')+(action?'<th>Decision</th>':'');
 $('#rows').innerHTML=rows.slice(0,5000).map(r=>`<tr>${s.cols.map(c=>`<td>${c==='change_percent'&&r[c]!=null?Number(r[c]).toFixed(1)+'%':esc(r[c]??'—')}</td>`).join('')}${action?`<td>${actionCell(r)}</td>`:''}</tr>`).join('');
 document.querySelectorAll('[data-decision]').forEach(b=>b.onclick=()=>{decisions.set(b.dataset.id,{action_type:type==='duplicates'?'duplicate':'case_link',entity_id:b.dataset.id,decision:b.dataset.decision,keep_person_id:b.dataset.keep||'',remove_person_id:b.dataset.remove||'',notes:''});render()}); $('#empty').hidden=rows.length>0;
}
function csv(){const cols=['action_type','entity_id','decision','keep_person_id','remove_person_id','notes'],q=v=>'"'+String(v??'').replaceAll('"','""')+'"';return [cols.join(','),...Array.from(decisions.values()).map(a=>cols.map(c=>q(a[c])).join(','))].join('\r\n')}
$('#downloadActions')?.addEventListener('click',()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv()],{type:'text/csv'}));a.download='review-actions.csv';a.click();URL.revokeObjectURL(a.href)});
fetch('data/advanced-data.json',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(Error('Run tools\\collect-new.cmd first.'))).then(x=>{data=x;render()}).catch(e=>$('#count').textContent=e.message);
$('#q')?.addEventListener('input',render); ;
