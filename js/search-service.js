(function(){
'use strict';
const CACHE=new Map();
const INDEXES={
 case:'data/search-cases.json',
 person:'data/search-people.json',
 judgment:'data/search-judgments.json',
 statistics:'data/search-statistics.json'
};
const ALL_INDEXES=Object.values(INDEXES);
const SYNONYMS={
 'dui':['impaired driving','driving while impaired','over 80'],
 'impaired driving':['dui','driving while impaired','over 80'],
 'assault':['common assault','aggravated assault','assault causing bodily harm'],
 'theft':['stealing','shoplifting'],
 'firearm':['gun','weapon'],
 'gun':['firearm','weapon'],
 'conviction':['convicted','guilty'],
 'convicted':['conviction','guilty'],
 'dismissed':['withdrawn','stayed','acquitted'],
 'withdrawn':['dismissed','stayed'],
 'nanaimo':['nanaimo provincial court','nanaimo courthouse'],
 'victoria':['victoria law courts','victoria courthouse'],
 'vancouver':['vancouver law courts','vancouver provincial court']
};
const normalize=v=>String(v??'').toLocaleLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim().replace(/\s+/g,' ');
const compact=v=>normalize(v).replace(/\s+/g,'');
const soundex=value=>{const text=normalize(value).replace(/[^a-z]/g,'');if(!text)return '';const map={b:1,f:1,p:1,v:1,c:2,g:2,j:2,k:2,q:2,s:2,x:2,z:2,d:3,t:3,l:4,m:5,n:5,r:6};let out=text[0].toUpperCase(),prev=map[text[0]]||'';for(const ch of text.slice(1)){const code=map[ch]||'';if(code&&code!==prev)out+=code;prev=code}return (out+'000').slice(0,4)};
const editDistance=(a,b,cap=3)=>{a=normalize(a);b=normalize(b);if(Math.abs(a.length-b.length)>cap)return cap+1;let prev=Array.from({length:b.length+1},(_,i)=>i);for(let i=1;i<=a.length;i++){const cur=[i];for(let j=1;j<=b.length;j++)cur[j]=Math.min(cur[j-1]+1,prev[j]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1));if(Math.min(...cur)>cap)return cap+1;prev=cur}return prev[b.length]};
const nameParts=value=>normalize(value).split(' ').filter(Boolean);
const verificationWeight={verified:500,reviewed:350,official:300,review:100,unverified:0,unknown:0};
function expandTerms(query){const q=normalize(query),out=new Set(q.split(' ').filter(Boolean));for(const [key,vals] of Object.entries(SYNONYMS)){if(q.includes(key)){out.add(key);vals.forEach(v=>out.add(normalize(v)))}}return [...out]}
function interpret(query){const raw=String(query||'').trim(),q=normalize(raw),hints={};
 if(/^\d{2,}[\s-]?\d*$/.test(raw)||/^[a-z]{0,3}\d{3,}[a-z0-9\s-]*$/i.test(raw))hints.courtFile=compact(raw);
 const citation=raw.match(/\b(19|20)\d{2}\s+(BCPC|BCSC|BCCA|BCCRT)\s+\d+\b/i);if(citation)hints.citation=normalize(citation[0]);
 const outcomes=['convicted','guilty','acquitted','stayed','withdrawn','dismissed'];for(const x of outcomes)if(q.includes(x)){hints.outcome=x;break}
 const offenceAliases=['assault','theft','impaired driving','dui','firearm','fraud','robbery','mischief','traffic'];for(const x of offenceAliases)if(q.includes(x)){hints.offence=x;break}
 const locations=['nanaimo','victoria','vancouver','surrey','kelowna','kamloops','prince george','abbotsford'];for(const x of locations)if(q.includes(x)){hints.location=x;break}
 const words=q.split(' ').filter(Boolean);if(!hints.courtFile&&!hints.citation&&words.length>=2&&!hints.offence&&!hints.outcome&&!hints.location)hints.personName=q;
 return hints;
}
function key(r){return r.court_file_normalized?`file:${r.court_file_normalized}:${normalize(r.location)}:${r.type}`:r.citation?`citation:${normalize(r.citation)}:${r.type}`:`${r.type}:${normalize(r.title)}:${r.date||''}`}
function scoreVerification(r){return verificationWeight[String(r.verification||'unknown').toLowerCase()]||0}
function dedupe(rows){const out=new Map();for(const row of rows){const k=key(row),old=out.get(k);if(!old||scoreVerification(row)>scoreVerification(old))out.set(k,row)}return [...out.values()]}
function matchEvidence(r,query){const q=normalize(query),parts=nameParts(q),names=(r.name_variants||r.names||[]).map(normalize),evidence=[],conflicts=[];if(!q)return {evidence,conflicts};
 if(names.some(x=>x===q))evidence.push('Exact published or reviewed name');
 else if(names.some(x=>x.startsWith(q)||q.startsWith(x)))evidence.push('Name prefix or shortened form');
 if(r.type==='person'&&parts.length>=2){const qFirst=parts[0],qLast=parts.at(-1),recordParts=nameParts(r.title),rFirst=recordParts[0]||'',rLast=recordParts.at(-1)||'';if(rLast&&soundex(qLast)===soundex(rLast)&&qLast!==rLast)evidence.push('Phonetic surname match');if(rFirst&&soundex(qFirst)===soundex(rFirst)&&qFirst!==rFirst)evidence.push('Phonetic given-name match');const d=editDistance(q,r.title,3);if(d>0&&d<=3)evidence.push(`Possible spelling match (${d} edit${d===1?'':'s'})`);if(Number(r.common_name_frequency||0)>=5)conflicts.push(`Common surname across ${r.common_name_frequency} person records`);}
 const birth=String(r.birth_year||'');if(birth&&q.includes(birth))evidence.push(`Matching birth year ${birth}`);
 for(const signal of r.identity_signals||[]){if(/^conflict/i.test(signal.signal_type||''))conflicts.push(signal.signal_value);}
 return {evidence:[...new Set(evidence)],conflicts:[...new Set(conflicts)]};}
function score(r,query){const q=normalize(query),qc=compact(query);if(!q)return scoreVerification(r);let n=0;const title=normalize(r.title),file=compact(r.court_file),citation=normalize(r.citation),names=(r.name_variants||r.names||[]).map(normalize),offences=(r.offences||[]).map(normalize),location=normalize(r.location),outcome=normalize(r.outcome),body=r.search_normalized||normalize(JSON.stringify(r)),h=interpret(query),terms=expandTerms(query),birth=String(r.birth_year||''),middle=normalize(r.middle_names||r.middle_name||''),identity=Number(r.identity_confidence||0),e=matchEvidence(r,query);
 if(file&&file===qc)n+=10000;if(h.courtFile&&file===h.courtFile)n+=12000;if(citation&&citation===q)n+=9500;if(h.citation&&citation===h.citation)n+=11500;
 if(names.some(x=>x===q))n+=9000;if(h.personName&&names.some(x=>x===h.personName))n+=10500;
 if(r.type==='person'){const qp=nameParts(q),rp=nameParts(r.title),qFirst=qp[0]||'',qLast=qp.at(-1)||'',rFirst=rp[0]||'',rLast=rp.at(-1)||'';if(names.some(x=>x===q))n+=2500;if(qLast&&rLast===qLast)n+=1800;else if(qLast&&rLast&&soundex(qLast)===soundex(rLast))n+=850;if(qFirst&&rFirst===qFirst)n+=1300;else if(qFirst&&rFirst&&soundex(qFirst)===soundex(rFirst))n+=600;if(birth&&q.includes(birth))n+=1800;if(middle&&qp.slice(1,-1).some(x=>x&&middle.includes(x)))n+=1000;if(identity)n+=Math.round(identity*700);const history=normalize([r.location,(r.location_history||[]).join(' '),(r.courthouse_history||[]).join(' ')].join(' '));if(h.location&&history.includes(h.location))n+=950;for(const item of e.evidence){if(item.startsWith('Phonetic'))n+=650;if(item.startsWith('Possible spelling'))n+=350}n-=Math.min(900,Number(r.common_name_frequency||0)*70);n-=e.conflicts.length*750;}
 if(title===q)n+=8500;if(names.some(x=>x.startsWith(q)))n+=7000;if(title.startsWith(q))n+=6500;if(offences.some(x=>x===q)||location===q)n+=5500;if(h.location&&location.includes(h.location))n+=2200;if(h.offence&&offences.some(x=>x.includes(normalize(h.offence))))n+=2200;if(h.outcome&&outcome.includes(h.outcome))n+=2200;for(const t of terms){if(t&&body.includes(t))n+=t.includes(' ')?650:300}if(body.includes(q))n+=1000;return n+scoreVerification(r)}
function matchesFilters(r,f={}){const offence=normalize(f.offence),court=normalize(f.court),outcome=normalize(f.outcome),verification=normalize(f.verification),recordStatus=normalize(f.recordStatus||'current'),metric=normalize(f.metric),dataset=normalize(f.dataset),geography=normalize(f.geography),period=normalize(f.period),unit=normalize(f.unit),dateFrom=f.dateFrom||'',dateTo=f.dateTo||'',date=String(r.date||'').slice(0,10);
 if(offence&&!normalize((r.offences||[]).join(' ')).includes(offence))return false;
 if(court&&!normalize([r.court,r.location].join(' ')).includes(court))return false;
 if(outcome&&!normalize(r.outcome).includes(outcome))return false;
 if(verification&&normalize(r.verification)!==verification)return false;
 if(recordStatus&&recordStatus!=='all'&&normalize(r.record_status||'current')!==recordStatus)return false;
 if(metric&&!normalize(r.metric).includes(metric))return false;
 if(dataset&&!normalize([r.dataset_id,r.domain].join(' ')).includes(dataset))return false;
 if(geography&&!normalize(r.location).includes(geography))return false;
 if(period&&!normalize(r.date).includes(period))return false;
 if(unit&&!normalize(r.unit).includes(unit))return false;
 if(dateFrom&&date&&date<dateFrom)return false;if(dateTo&&date&&date>dateTo)return false;
 return true;
}
async function loadOne(url){if(!CACHE.has(url))CACHE.set(url,fetch(url,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error(`Search index unavailable (${r.status})`);return r.json()}).then(x=>x.records||[]));return CACHE.get(url)}
async function load(urls=ALL_INDEXES){const list=Array.isArray(urls)?urls:[urls];const settled=await Promise.allSettled(list.map(loadOne)),groups=settled.filter(x=>x.status==='fulfilled').map(x=>x.value);if(!groups.length)throw Error('Search indexes unavailable');return dedupe(groups.flat())}
async function search(query,{type='',types='',limit=100,offset=0,offence='',court='',outcome='',verification='',recordStatus='current',dateFrom='',dateTo='',metric='',dataset='',geography='',period='',unit=''}={}){const allowed=String(types||type||'').split(',').map(x=>x.trim()).filter(x=>INDEXES[x]),urls=allowed.length?allowed.map(x=>INDEXES[x]):ALL_INDEXES,rows=await load(urls),opts={offence,court,outcome,verification,recordStatus,dateFrom,dateTo,metric,dataset,geography,period,unit};return rows.filter(r=>(!allowed.length||allowed.includes(r.type))&&matchesFilters(r,opts)&&(!query||score(r,query)>scoreVerification(r))).map(r=>({record:r,score:score(r,query)})).sort((a,b)=>b.score-a.score||String(b.record.date||'').localeCompare(String(a.record.date||''))).slice(offset,offset+limit).map(x=>x.record)}
const API_BASE='http://127.0.0.1:8765';
const API_HELPER='http://127.0.0.1:8764/wake';
const apiPreference=()=>{try{const params=new URLSearchParams(location.search),requested=params.get('api');if(requested==='1'){localStorage.setItem('bcjusSearchApi','1');return true}if(requested==='0'){localStorage.setItem('bcjusSearchApi','0');return false}return localStorage.getItem('bcjusSearchApi')!=='0'}catch{return true}};
let API_ENABLED=apiPreference();
function setApiEnabled(enabled){API_ENABLED=Boolean(enabled);try{localStorage.setItem('bcjusSearchApi',API_ENABLED?'1':'0')}catch{}return API_ENABLED}
async function wakeApi(){if(!API_ENABLED)return false;try{const r=await fetch(API_HELPER,{cache:'no-store'});return r.ok}catch{return false}}
async function apiJson(path,timeout=1200){if(!API_ENABLED)throw Error('Local search API disabled');await wakeApi();const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),timeout);try{const r=await fetch(API_BASE+path,{cache:'no-store',signal:ctrl.signal});if(!r.ok)throw Error(`API ${r.status}`);return await r.json()}finally{clearTimeout(timer)}}
function matterKey(r){const file=compact(r.court_file_normalized||r.court_file),citation=normalize(r.citation),location=normalize(r.location||r.court);if(file)return `file:${file}:${location}`;if(citation)return `citation:${citation}`;if(r.case_id)return `case:${r.case_id}`;return `record:${r.type}:${r.id}`}
function groupRecords(records){const groups=new Map();for(const r of records){const k=matterKey(r);if(!groups.has(k))groups.set(k,{grouped:true,matter_key:k,title:r.court_file||r.citation||r.title||'Linked matter',records:[],types:new Set(),latest_date:'',verification:'unknown'});const g=groups.get(k);g.records.push(r);g.types.add(r.type||'record');g.latest_date=String(g.latest_date)>String(r.date||'')?g.latest_date:String(r.date||'');if(['verified','official','reviewed'].includes(r.verification))g.verification=r.verification}return [...groups.values()].map(g=>{if(g.records.length===1)return g.records[0];g.types=[...g.types].sort();g.counts=Object.fromEntries(g.types.map(t=>[t,g.records.filter(r=>r.type===t).length]));g.records.sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));return g}).sort((a,b)=>String(b.latest_date||b.date||'').localeCompare(String(a.latest_date||a.date||'')))}
async function searchDetailed(query,opts={}){const params=new URLSearchParams({q:query||'',limit:String(opts.limit||25),offset:String(opts.offset||0)});for(const k of ['type','types','offence','court','outcome','verification','dateFrom','dateTo','recordStatus','metric','dataset','geography','period','unit','group'])if(opts[k])params.set(k,opts[k]);if(API_ENABLED){try{const live=await apiJson('/api/search?'+params.toString(),1800);if(!query||Number(live.total||0)>0)return live}catch{ } }const all=await search(query,{...opts,limit:Number.MAX_SAFE_INTEGER,offset:0});const grouped=opts.group!=='false'&&opts.type!=='statistics'&&!String(opts.types||'').split(',').includes('statistics'),rows=grouped?groupRecords(all):all,offset=Number(opts.offset||0),limit=Number(opts.limit||25);return {records:rows.slice(offset,offset+limit),total:rows.length,limit,offset,source:'json-fallback',grouped}}
async function searchStatus(){if(API_ENABLED){try{return await apiJson('/api/search/status',1000)}catch{ } }try{const r=await fetch('data/search-status.json',{cache:'no-store'});if(r.ok){const x=await r.json();return {mode:'JSON fallback',databaseUpdatedAt:'',indexUpdatedAt:x.generatedAt||'',recordsIndexed:x.recordsIndexed||0,indexStatus:'fallback',incrementalChanged:x.changed||0,incrementalRemoved:x.removed||0}}}catch{}return {mode:'JSON fallback',indexStatus:'unavailable',recordsIndexed:0}}
async function apiLocations(){if(!API_ENABLED)return [];try{return (await apiJson('/api/courts',1000)).aliases||[]}catch{return []}}
async function apiFacets(){if(!API_ENABLED)return {metrics:[],datasets:[],domains:[],geographies:[],periods:[],units:[]};try{return await apiJson('/api/search/facets',1200)}catch{return {metrics:[],datasets:[],domains:[],geographies:[],periods:[],units:[]}}}
window.bcjusSearch={load,search,searchDetailed,searchStatus,apiLocations,apiFacets,setApiEnabled,isApiEnabled:()=>API_ENABLED,normalize,compact,score,dedupe,interpret,expandTerms,matchEvidence,soundex,editDistance,synonyms:SYNONYMS,indexes:INDEXES,clear:()=>CACHE.clear()};
})();
