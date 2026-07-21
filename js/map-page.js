const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const regions=[
  ['North',205,112],
  ['Interior',230,270],
  ['Lower Mainland',210,425],
  ['Vancouver Island',83,411],
  ['Kootenays',286,370]
];
const map=document.querySelector('#bcMap'),list=document.querySelector('#mapList'),input=document.querySelector('#mapSearch');
let courts=[];

const bcMapSvg=`
<svg viewBox="0 0 360 500" role="img" aria-labelledby="bcMapTitle bcMapDesc">
  <title id="bcMapTitle">British Columbia courthouse regions</title>
  <desc id="bcMapDesc">Recognizable outline of British Columbia including Vancouver Island and Haida Gwaii, with broad regional courthouse markers.</desc>
  <rect class="bc-water" x="0" y="0" width="360" height="500" rx="22"></rect>
  <path class="bc-shape bc-mainland" d="M76 28 L309 28 L309 449 L154 449 L146 438 L137 432 L132 419 L120 412 L116 398 L104 389 L102 373 L91 361 L95 346 L84 332 L89 316 L78 301 L85 284 L74 268 L82 251 L70 234 L80 216 L69 198 L79 180 L68 162 L79 144 L69 126 L80 109 L71 91 L82 74 L75 55 L86 42 Z"></path>
  <path class="bc-coast-inlet" d="M154 449 L145 433 L135 426 L130 412 L119 405 L115 390 L104 380 L108 364 L97 350 L102 334 L91 319 L98 301 L88 285 L96 266 L86 249 L96 230 L86 212 L97 194 L87 176 L98 158 L88 140 L99 122 L89 104 L99 86"></path>
  <path class="bc-island" d="M54 337 C67 321 79 311 89 316 C97 323 94 342 87 360 C80 381 72 402 61 424 C52 443 42 456 34 451 C25 445 28 428 34 409 C40 389 43 367 54 337 Z"></path>
  <path class="bc-island" d="M39 142 C48 130 56 129 61 138 C66 149 61 163 54 177 C47 189 39 194 33 186 C27 178 30 157 39 142 Z"></path>
  <path class="bc-island bc-small-island" d="M31 200 C37 194 42 196 43 203 C43 210 38 215 33 213 C28 211 27 205 31 200 Z"></path>
  <path class="bc-island bc-small-island" d="M111 431 C116 425 121 426 122 433 C121 440 116 444 111 441 C107 439 107 434 111 431 Z"></path>
  <path class="bc-border-line" d="M309 28 L309 449 L154 449"></path>
  ${regions.map(r=>`<g class="map-region" transform="translate(${r[1]} ${r[2]})"><circle r="7"></circle><text y="-12">${esc(r[0])}</text></g>`).join('')}
</svg>`;
map.innerHTML=bcMapSvg;

function region(c){const s=[c.name,c.registry,c.city,c.address].filter(Boolean).join(' ').toLowerCase();if(/nanaimo|victoria|courtenay|campbell|port hardy|duncan|island/.test(s))return'Vancouver Island';if(/vancouver|surrey|richmond|new west|burnaby|abbotsford|chilliwack|langley|port coquitlam/.test(s))return'Lower Mainland';if(/cranbrook|nelson|rossland|castlegar|revelstoke|golden/.test(s))return'Kootenays';if(/prince george|fort st|dawson|smithers|terrace|quesnel|williams lake|100 mile/.test(s))return'North';return'Interior'}
function normalizeCourts(data){if(Array.isArray(data))return data;if(Array.isArray(data?.courthouses))return data.courthouses;if(Array.isArray(data?.records))return data.records;return []}
function draw(){const q=(input?.value||'').trim().toLowerCase();const rows=courts.filter(c=>!q||[c.name,c.registry,c.city,c.address,c.type,region(c)].filter(Boolean).join(' ').toLowerCase().includes(q));list.innerHTML=rows.slice(0,100).map(c=>{const slug=c.slug||c.courthouse_slug||'';const name=c.name||c.courthouse_name||c.city||'Unnamed courthouse';return `<a class="map-item" href="court/detail.html?court=${encodeURIComponent(slug)}"><strong>${esc(name)}</strong><span>${esc(region(c))} · ${esc(c.type||c.registry||'Court registry')}</span></a>`}).join('')||'<p class="empty">No matching courthouses or regions.</p>'}
async function init(){try{const response=await fetch('data/courthouses.json',{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);courts=normalizeCourts(await response.json());if(!courts.length)throw Error('No courthouse records');draw()}catch{list.innerHTML='<p class="empty">Courthouse results are unavailable. Run tools\\collect-new.cmd to rebuild courthouse data.</p>'}}
if(input)input.addEventListener('input',draw);
init();
