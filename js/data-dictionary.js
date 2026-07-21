const OFFICIAL_JUSTIN_CODES='https://www2.gov.bc.ca/assets/gov/law-crime-and-justice/courthouse-services/daily-court-lists/abbreviations.xls?forcedownload=true';
const statuteDefinitions={
  BCPC:'Provincial Court of British Columbia.',
  BCSC:'Supreme Court of British Columbia.',
  BCCA:'Court of Appeal for British Columbia.',
  BCTC:'Tax Court designation used in some imported citation data.',
  CCC:'Criminal Code of Canada.',
  CDSA:'Controlled Drugs and Substances Act.',
  MVA:'Motor Vehicle Act of British Columbia.'
};
const terms=[
  {key:'accused',category:'Legal status',definition:'A person named in an allegation or proceeding. No guilt is implied.'},
  {key:'charged',category:'Legal status',definition:'A charge is recorded. This is not a conviction.'},
  {key:'scheduled_appearance',category:'Case event',definition:'A court appearance is scheduled; allegation not proven.'},
  {key:'convicted',category:'Outcome',definition:'A court disposition records a conviction. Verify the official source.'},
  {key:'acquitted',category:'Outcome',definition:'The person was found not guilty on the recorded matter.'},
  {key:'stayed',category:'Outcome',definition:'Proceedings were stayed; this is not a conviction.'},
  {key:'withdrawn',category:'Outcome',definition:'A charge was withdrawn or dismissed.'},
  {key:'verification',category:'Quality',definition:'Whether a record is verified, pending review, or unresolved.'},
  {key:'source_url',category:'Provenance',definition:'Official page or document from which the record was collected.'},
  {key:'retrieved_at',category:'Provenance',definition:'Timestamp when the source was collected locally.'},
  {key:'file_number',category:'Case identity',definition:'Official court file identifier when available.'},
  {key:'citation',category:'Judgment identity',definition:'Neutral citation for a published decision.'},
  {key:'dataset_id',category:'Catalogue',definition:'BC Data Catalogue dataset identifier.'},
  {key:'resource_id',category:'Catalogue',definition:'Identifier for a downloadable dataset resource.'},
  {key:'source_modified_at',category:'Freshness',definition:'Modification date reported by the source.'},
  {key:'file_hash',category:'Integrity',definition:'Hash used to detect changed downloads.'},
  {key:'federal_source',category:'Source label',definition:'Marks data supplied by Statistics Canada or another federal source.'},
  {key:'review_required',category:'Quality',definition:'Indicates that a person must check the record before relying on it.'},
  {key:'appearance_code',category:'Court-list field',definition:'A source code identifying the stated purpose or reason for an appearance. Use the code-specific link or official JUSTIN table for the exact meaning.'},
  {key:'status_code',category:'Court-list field',definition:'A source status or result code carried in the court-list row. Use the code-specific link or official JUSTIN table for the exact meaning.'},
  {key:'statute',category:'Charge field',definition:'The legislation abbreviation associated with the listed alleged charge.'},
  {key:'section',category:'Charge field',definition:'The numbered provision within the listed statute. A section reference identifies an alleged statutory provision and is not proof of guilt or disposition.'},
  {id:'charge-confidence',key:'Charge confidence',category:'Charge linking',definition:'A data-linking assessment showing how strongly an appearance has been connected to alleged charge information. It is not a legal finding, proof of guilt, or a measure of whether an allegation is true.'},
  {id:'charge-confidence-confirmed',key:'Confirmed',category:'Charge confidence',definition:'The appearance and charge record share the exact court file and accused name, with supporting courthouse, date, or court-level evidence. Confirmed describes the strength of the data link, not guilt.'},
  {id:'charge-confidence-likely',key:'Likely',category:'Charge confidence',definition:'The appearance and charge record share the exact court file and accused name, but supporting courthouse, date, or court-level details are incomplete. Likely describes the data link, not guilt.'},
  {id:'charge-confidence-possible',key:'Possible',category:'Charge confidence',definition:'The court file matches and partial supporting evidence exists, such as a partial name, courthouse, date, or court level. Manual verification is required.'},
  {id:'charge-confidence-non-verified',key:'Non Verified',category:'Charge confidence',definition:'The court file matches, but the accused name and supporting details have not been sufficiently verified. Treat the linked alleged charge as unconfirmed.'},
  {id:'charge-confidence-not-available',key:'Charge Not Available',category:'Charge confidence',definition:'No charge record is currently linked to this appearance in the local index. This does not mean there was no charge, that a charge was withdrawn, or that the person was acquitted.'},
  ...Object.entries(statuteDefinitions).map(([key,definition])=>({key,category:key.startsWith('BC')?'Court code':'Statute code',definition}))
];
const box=document.querySelector('#dictionary'),q=document.querySelector('#dictSearch');
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const slug=value=>String(value||'').toLocaleLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'')||'unknown';
const legacyAnchor=value=>`court-code-${slug(value)}`;
const requestedDefinition=()=>{
  const params=new URLSearchParams(location.search),type=params.get('type')||'',value=(params.get('value')||'').trim(),statute=(params.get('statute')||'').trim();
  if(!type||!value)return null;
  const id=`definition-${slug(type)}-${slug(statute?`${statute}-${value}`:value)}`;
  if(type==='appearance-code')return {id,key:value,category:'Appearance code',definition:`${value} is the appearance-purpose code recorded in this source row. Its exact local meaning has not been assumed; verify it against the official JUSTIN code table.`,official:true};
  if(type==='status-code')return {id,key:value,category:'Status code',definition:`${value} is the status or result code recorded in this source row. Its exact local meaning has not been assumed; verify it against the official JUSTIN code table.`,official:true};
  if(type==='statute')return {id,key:value,category:'Statute code',definition:statuteDefinitions[value.toUpperCase()]||`${value} is the legislation abbreviation recorded with this appearance. Confirm the full legislation title against the source record.`,official:!statuteDefinitions[value.toUpperCase()]};
  if(type==='section'){
    const statuteCode=statute.toUpperCase(),statuteName=statuteDefinitions[statuteCode]||statute||'the listed statute';
    return {id,key:`${statute?`${statute} `:''}s. ${value}`,category:'Statute section',definition:`Section ${value} is the numbered provision recorded under ${statuteName}. It identifies the alleged statutory provision and is not proof of guilt, attendance, or disposition.`};
  }
  return null;
};
const cardMarkup=term=>`<article class="dictionary-card" id="${esc(term.id||legacyAnchor(term.key))}"><span>${esc(term.category)}</span><h3><code>${esc(term.key)}</code></h3><p>${esc(term.definition)}</p>${term.official?`<p><a class="dictionary-source-link" href="${OFFICIAL_JUSTIN_CODES}" target="_blank" rel="noopener">Open official JUSTIN code table ↗</a></p>`:''}</article>`;
function draw(){
  const search=q.value.toLocaleLowerCase(),requested=requestedDefinition();
  const rows=terms.filter(term=>!search||`${term.key} ${term.category} ${term.definition}`.toLocaleLowerCase().includes(search));
  box.innerHTML=(requested?cardMarkup(requested):'')+rows.map(cardMarkup).join('');
  const target=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));
  if(target)setTimeout(()=>target.scrollIntoView({block:'center'}),0);
}
q.oninput=draw;draw();
