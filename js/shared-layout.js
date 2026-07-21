(() => {
  const init = () => {
    if (!document.body.id) document.body.id = 'top';
    const depth = location.pathname.split('/').filter(Boolean).slice(-2,-1)[0] === 'court' || location.pathname.includes('/stats/') ? '../' : '';
    const p = path => depth + path;
    const header = `<header class="site-head grouped-head">
      <a class="brand pill" href="${p('index.html')}"><img class="brand-icon" src="${p('favicon.svg')}" alt="" aria-hidden="true">Justice Data Hub</a>
      <nav class="grouped-nav" aria-label="Primary navigation">
        <a class="pill primary-nav-pill" href="${p('appearance-search.html')}">Search</a>
        <div class="nav-menu"><button class="pill nav-menu-toggle" type="button" aria-expanded="false" aria-haspopup="true">Daily Justice <span aria-hidden="true">⌄</span></button><div class="nav-menu-list"><a href="${p('index.html#dailyJustice')}">Daily Justice Overview</a><a href="${p('today-court.html')}">Today's Court Lists</a><a href="${p('court/index.html')}">Court Locations</a><a href="${p('judgments.html')}">Recent Judgments</a><a href="${p('collection-alerts.html')}">Collection Alerts</a></div></div>
        <div class="nav-menu"><button class="pill nav-menu-toggle" type="button" aria-expanded="false" aria-haspopup="true">Cases &amp; Review <span aria-hidden="true">⌄</span></button><div class="nav-menu-list"><a href="${p('index.html#caseJudgmentTools')}">Cases, Judgments &amp; Review</a><a href="${p('index.html#records')}">Case and Person Index</a><a href="${p('judgments.html')}">Published Judgments</a><a href="${p('case-timelines.html')}">Case Timelines</a><a href="${p('case-links.html')}">Linked Proceedings</a><a href="${p('cso-index.html')}">CSO Case Index</a><a href="${p('review-centre.html')}">Review Centre</a><a href="${p('identity-review.html')}">Identity Review</a></div></div>
        <div class="nav-menu"><button class="pill nav-menu-toggle" type="button" aria-expanded="false" aria-haspopup="true">Crime Statistics <span aria-hidden="true">⌄</span></button><div class="nav-menu-list"><a href="${p('index.html#crimeStats')}">Crime Statistics</a><a href="${p('stats/court-system.html')}">Court System</a><a href="${p('stats/crime-policing.html')}">Crime and Policing</a><a href="${p('police-data.html')}">Police Data</a><a href="${p('statcan-crime.html')}">Statistics Canada Crime</a><a href="${p('prosecution.html')}">Prosecution</a><a href="${p('stats/corrections-custody.html')}">Corrections and Custody</a><a href="${p('corrections-oversight.html')}">Corrections Oversight</a><a href="${p('stats/youth-justice.html')}">Youth Justice</a><a href="${p('stats/civil-forfeiture.html')}">Civil Forfeiture</a><a href="${p('comparisons.html')}">Regional Comparisons</a><a href="${p('map.html')}">Maps</a></div></div>
        <div class="nav-menu"><button class="pill nav-menu-toggle" type="button" aria-expanded="false" aria-haspopup="true">Admin System <span aria-hidden="true">⌄</span></button><div class="nav-menu-list"><a href="${p('index.html#adminSystem')}">Admin System</a><a href="${p('reports.html')}">Reports and Exports</a><a href="${p('watchlists.html')}">Watchlists</a><a href="${p('private-notes.html')}">Private Notes</a><a href="${p('index.html#sources')}">Official Sources</a><a href="${p('source-validation.html')}">Source Validation</a><a href="${p('data-dictionary.html')}">Data Dictionary</a><a href="${p('collection-policy.html')}">Collection Policy</a><a href="${p('privacy-review.html')}">Privacy Review</a><a href="${p('index.html#dataManager')}">Dataset Manager</a><a href="${p('system-health.html')}">System Health</a><a href="${p('scheduling.html')}">Scheduling</a><a href="${p('retry-centre.html')}">Retry Centre</a><a href="${p('index.html#commandsPanel')}">Commands</a><a href="${p('sitemap.html')}">Sitemap</a></div></div>
      </nav><button class="pill" id="themeBtn" type="button">Dark mode</button>
    </header>`;
    const footer = `<footer class="site-footer"><a class="footer-pill" href="${p('index.html')}">BC Justice Data Hub</a><span class="footer-pill">Private local-use build</span><span class="footer-pill">Data must be verified against the official source</span><span class="footer-pill">v0.20.7</span><a class="footer-pill repeat-footer-pill" href="${p('repeat-offenders.html')}">Repeat Offenders</a><a class="footer-pill sitemap-pill" href="${p('sitemap.html')}">Sitemap</a><a class="footer-pill back-top-pill" href="#top" aria-label="Back to top">Back to top ↑</a></footer>`;
    const oldHeader=document.querySelector('header.site-head'); if(oldHeader) oldHeader.outerHTML=header; else document.body.insertAdjacentHTML('afterbegin',header);
    const existingFooters=[...document.querySelectorAll('footer')];
    if(existingFooters.length){
      existingFooters[0].outerHTML=footer;
      existingFooters.slice(1).forEach(item=>item.remove());
    }else{
      document.body.insertAdjacentHTML('beforeend',footer);
    }
    const themeBtn=document.getElementById('themeBtn');
    const themeKey='bcjusTheme';
    let savedTheme='light';
    try { savedTheme=localStorage.getItem(themeKey)||'light'; } catch (_) {}
    document.body.classList.toggle('dark',savedTheme==='dark');
    const updateThemeButton=()=>{
      if(themeBtn) themeBtn.textContent=document.body.classList.contains('dark')?'Light mode':'Dark mode';
    };
    updateThemeButton();
    if(themeBtn){
      themeBtn.onclick=()=>{
        const dark=!document.body.classList.contains('dark');
        document.body.classList.toggle('dark',dark);
        try { localStorage.setItem(themeKey,dark?'dark':'light'); } catch (_) {}
        updateThemeButton();
      };
    }
    const closeMenus=except=>document.querySelectorAll('.nav-menu.open').forEach(m=>{if(m!==except){m.classList.remove('open');m.querySelector('.nav-menu-toggle')?.setAttribute('aria-expanded','false')}});
    document.querySelectorAll('.nav-menu-toggle').forEach(btn=>btn.addEventListener('click',e=>{e.stopPropagation();const menu=btn.closest('.nav-menu');const opening=!menu.classList.contains('open');closeMenus(menu);menu.classList.toggle('open',opening);btn.setAttribute('aria-expanded',String(opening))}));
    document.addEventListener('click',e=>{if(!e.target.closest('.nav-menu'))closeMenus()});

    const syncExpander = details => {
      const summary = details?.querySelector(':scope > summary.expander-toggle');
      if (!summary) return;
      summary.setAttribute('role','button');
      summary.setAttribute('aria-expanded',String(details.open));
      if (summary.dataset.bcjusExpanderReady === '1') return;
      summary.dataset.bcjusExpanderReady = '1';
      details.addEventListener('toggle',()=>summary.setAttribute('aria-expanded',String(details.open)));
    };
    const initExpanders = root => root.querySelectorAll?.('details.section-expander').forEach(syncExpander);
    initExpanders(document);
    document.addEventListener('click',e=>{
      const summary=e.target.closest('summary.expander-toggle');
      if(!summary || e.button!==0 || e.defaultPrevented) return;
      if(e.target.closest('a,button,input,select,textarea,label')) return;
      const details=summary.parentElement;
      if(!details || details.tagName!=='DETAILS') return;
      e.preventDefault();
      details.open=!details.open;
      summary.setAttribute('aria-expanded',String(details.open));
      try { window.getSelection?.().removeAllRanges(); } catch (_) {}
    },true);
    document.addEventListener('keydown',e=>{
      const summary=e.target.closest?.('summary.expander-toggle');
      if(!summary || (e.key!=='Enter' && e.key!==' ')) return;
      const details=summary.parentElement;
      if(!details || details.tagName!=='DETAILS') return;
      e.preventDefault();
      details.open=!details.open;
      summary.setAttribute('aria-expanded',String(details.open));
    });
    new MutationObserver(items=>items.forEach(item=>item.addedNodes.forEach(node=>{
      if(node.nodeType!==1) return;
      if(node.matches?.('details.section-expander')) syncExpander(node);
      initExpanders(node);
    }))).observe(document.body,{childList:true,subtree:true});
    window.BCJUS_STATUS_HELP={accused:'Named as accused; allegation not proven.',charged:'A charge is recorded; no conviction is implied.',scheduled_appearance:'A court appearance is scheduled; allegation not proven.',convicted:'A court outcome records a conviction. Verify the official judgment or disposition.',acquitted:'The person was found not guilty on the recorded matter.',stayed:'Proceedings were stayed; this is not a conviction.',withdrawn:'The charge was withdrawn or dismissed.',unknown:'The final outcome has not been verified.'};
    window.bcjusStatusTitle=s=>window.BCJUS_STATUS_HELP[String(s||'unknown').toLowerCase()]||window.BCJUS_STATUS_HELP.unknown;
    window.bcjusHideEmpty=(section, count)=>{const el=typeof section==='string'?document.querySelector(section):section;if(el)el.hidden=!count};
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
