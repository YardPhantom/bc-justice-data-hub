# BC Justice Data Hub — Site Summary

**Current version:** v0.20.7  
**Deployment path:** `C:\inetpub\wwwroot\sites\bcjus`  
**Purpose:** Private, local-use IIS site for collecting, reviewing, searching and reporting on official British Columbia justice data.

## v0.20.7 latest changes

Appearance Search no longer duplicates the Show 50 / 100 page-size selector in the bottom pagination row. Page size remains in the sticky results toolbar; bottom pagination now contains only Previous, page number, and Next controls.

## v0.20.1 previous changes

Appearance Search added date shortcut pills, removable active-filter pills, URL-persisted filters, Compact and Detailed views, optional court-file grouping, visible charge-confidence badges, a sticky result-control bar, API-supplied person-profile metadata, and mobile result cards.

## v0.19.9 previous changes

Appearance Search Record details now use the available horizontal space more efficiently. Core appearance and court information remains in the left column, while Linked alleged charge, Charge confidence and Evidence appear in a dedicated right column. The layout returns to one column on smaller screens, and the existing catalogued-appearances badge remains below the details.


## v0.19.3 latest changes

Header dropdown arrows now rotate clockwise to point upward when opened, with a centered transform origin for consistent animation. Appearance Search also retains the v0.19.2 prompt wording: “Begin typing a name or select a date for results to populate.”

## v0.19.1 homepage regrouping

The homepage keeps Search & People unchanged and uses four additional categories: Daily Justice Overview; Cases, Judgments & Review; Crime Statistics; and Admin System. Reports, monitoring and governance are nested inside Admin System. The shared header mirrors those categories while preserving the Justice Data Hub brand, Search pill, and theme toggle.


## Core principles

- Official and traceable source data is preserved with provenance.
- Accused, charged, convicted, acquitted, stayed, withdrawn and dismissed outcomes remain distinct.
- Same-name records are never assumed to be the same person.
- Confirmed repeat offending requires at least two distinct verified conviction events.
- Runtime databases, imports, reports, backups and generated data are not replaced by deployment ZIPs.

## Main site areas

- Daily control centre and collection status
- Full local search and case/person search
- Charts and comparison tables
- Courthouse directory, map and daily court appearances
- Published judgments and judgment verification
- Review centre and manual review editor
- Repeat Offenders and person profiles
- Police, corrections, prosecution, crime and Statistics Canada dashboards
- Printable local reports with Excel and PDF export
- Advanced tools, source registry, system health, storage and scheduling
- Numbered command launcher and on-site Commands list

## Appearance Search

Appearance Search uses the loopback Search API and a normalized SQLite cache for name, courthouse, date, and charge-confidence filtering. Results are paged at 50 or 100 rows and can be ordered by newest appearance, oldest appearance, name, courthouse, charge-confidence strength, or catalogue-history count. Results use two columns: the highlighted name with profile/review controls, and ordered Record details containing appearance codes, statute/section, date/time, courthouse, courtroom, file, court level, linked alleged charge, confidence, and evidence. The existing catalogued-appearances history badge remains at the bottom of each record. Centered CSV, JSON, and printable-report pills appear below the results table only when the current search has matching records; exports retrieve the complete filtered result set. Static paged JSON remains the automatic fallback and uses conditional browser caching, so IIS can return unchanged files through ETag or Last-Modified validation while regenerated exports refresh normally.

## Homepage defaults

Search & People and Appearance Search open by default. Full Index Search remains closed until selected, while direct hash links can still open it automatically.

## Search system

Search uses SQLite FTS5 plus generated browser indexes:

- `data/search-cases.json`
- `data/search-people.json`
- `data/search-judgments.json`
- `data/search-statistics.json`

The shared cached search service provides:

- Exact-match weighted ranking
- Name and court-file normalization
- Verification priority
- Cross-source deduplication
- Synonyms and aliases
- Query interpretation
- Advanced filters
- Match highlighting
- Initial 25-result rendering with Load more

## Person identity and repeat offending

The identity layer includes:

- Stable `person_id` records
- Published and generated name variants
- Middle-name and initial matching
- Available birth, age, location, courthouse, counsel and co-accused signals
- Identity-confidence scoring
- Manual merge, split, alias and different-person decisions
- Offence normalization across all applicable legislation
- Distinct verified conviction-event counting
- Historical judgment and prior-record references

Repeat-offender profiles show:

- Verified conviction events and years
- First and most recent verified conviction
- Active years and calendar span
- Same-category and cross-category repetition
- Breach or probation-related events
- Transparent offence-pattern trend
- Source links and unverified identity warnings

## Judgment workflow

Both the Judgments and Manual Review pages support:

- Verify judgment
- Needs correction
- Dismiss review

Verified judgment actions can write reviewed names, charges, outcomes and sentences into searchable case/person tables after the exported review CSV is applied with:

```bat
tools\apply-reviews.cmd review-actions.csv
```

## Collection and imports

Normal update:

```bat
tools\collect-new.cmd
```

Full forced refresh:

```bat
tools\collect-all.cmd
```

Historical judgment backfill:

```bat
tools\collect-historical-judgments.cmd
```

Person identity rebuild:

```bat
tools\person-identity.cmd
```

Manual collection commands ask `Y/N` before backing up. Scheduled tasks back up automatically. Only the newest database backup is retained.

## Command launcher

Run from the site root:

```bat
command.cmd
```

The launcher presents a numbered list and executes the selected command from the main site folder. `commands.txt`, `command.cmd`, and the on-site Commands expander should always be kept synchronized.

## Data storage

Primary database:

```text
database\bc_justice.db
```

Runtime areas include:

- `database\`
- `backups\database\`
- `imports\`
- `reports\`
- generated `data\*.json`

Deployment ZIPs exclude runtime data. Extract updates over the existing IIS site folder rather than deleting the folder first.

## Scheduled operations

Available scheduled tasks include:

- Daily court-list collection
- Weekly BC Data Catalogue synchronization
- Monthly statistics refresh

Scheduler commands are listed in `commands.txt` and the on-site Commands expander.

## Current quality safeguards

- Shared header and footer on all pages
- One footer per page
- Blue themed scrollbars and navigation pills
- Header bounce feedback
- Search boxes use generated project data, not browser-local records
- Clear empty and error states
- Local-link, duplicate-ID, JavaScript and Python validation
- Integrity-checked database backups
- Review-required status for uncertain extraction and historical records


## Person-focused search quality

Person searches prioritize exact reviewed names and aliases, then carefully consider phonetic equivalents and small spelling errors. Birth-year, age and middle-name conflicts lower confidence. Common surnames require stronger secondary evidence. Identity Review displays supporting and conflicting evidence together, and applied decisions are stored permanently. Run `tools\test-person-search.cmd` after search or identity changes.

## v0.8.4 person-result refinements
Person matching now uses separate surname/given-name weights, stronger middle-name conflict rules, date-specific age plausibility, and cautious location/courthouse-history scoring.


## Person-focused search and profile controls (v0.8.4)

- Permanent pair-level identity decisions survive index rebuilds and retain evidence notes, reviewer and source metadata.
- Full Search includes a dedicated People-only mode that loads the person index and links directly to permanent profiles.
- Person profiles support search-within-person filters for free text, year, legislation, court/location and outcome, including sentence text.

## Repeat-offender event integrity

Linked appeals, sentencing decisions, retrials, and related files are excluded from repeat-event inflation. Event separation prefers occurrence identifiers and offence dates. The dashboard provides confidence modes, historical coverage, missing-history alerts, and conviction sequence gaps.


## Homepage layout

The homepage is organized into seven purpose-based expandable groups. Daily Justice Overview and Search & People open by default; cases, statistics, reporting, governance, and maintenance remain collapsed until needed. Each linked page appears in only one homepage group.


## Name recurrence analysis

Repeat-offender exports include a separate `repeat_appearances_only` tier derived from recurring normalized names across distinct court-list dates or file numbers. These records are review-only and are never counted as convictions or confirmed identities.

## v0.8.4 safeguard hardening
- Preserves prior daily-court file versions and historical appearance rows.
- Tracks superseded appearances and replacement links.
- Uses paged daily-court JSON exports to avoid silent truncation.
- Uses transactional replace logic for Statistics Canada and police refreshes.
- Keeps atomic JSON outputs with last-known-good backups.
- Audits replaced person links, charges and outcomes into `case_record_history`.
- Adds a regression test for corrected-file retention behavior.

## v0.8.4 corrections
Historical collection has SQLite busy retries and WAL support. Nested homepage arrows use direct-child state. Charts include distinct current criminal court-list records without calling them convictions. Custody extraction recognizes catalogue metadata and the dashboard no longer presents missing custody data as a real zero.

## Live search architecture (v0.8.4, no version change)
- `tools\start-search-server.cmd` starts a loopback-only SQLite/FTS5 API.
- `search.html` prefers live database search and automatically falls back to generated JSON.
- Search records are incrementally upserted by content hash; unchanged rows are not re-indexed.
- Current, superseded, and all-version court-list filters are available.
- Search status shows source mode, indexed count, freshness, changed rows, and removed rows.
- Results are paginated at the search source in groups of 25.


## Completed search architecture
- Loopback SQLite/FTS5 API with 25-result source pagination and JSON fallback.
- Cross-source grouping by court file, citation, case identity and location.
- Expandable provenance showing source table, document/version identifiers, index time, verification and record status.
- Statistics-specific dataset, metric, geography, period and unit filters.
- Persistent courthouse alias registry generated from official and indexed courthouse/location names.
- Automated search-quality tests for grouping, provenance, aliases, superseded filtering and statistics facets.


## v0.8.4 cleanup baseline

Version 0.8.2 begins from a verified cleanup pass: no broken local references, no orphaned JavaScript, synchronized command documentation, clean release packaging, and passing retention, person-search, repeat-offender, search-control and search-quality tests.


## v0.8.4 network reliability

BC Courts judgment collection now retries certificate validation through the native Windows trust store and certifi without disabling TLS verification. Police report discovery retries temporary gateway failures and falls back to its last verified discovery list while preserving previously imported records.


## v0.20.7 Collect New identity-aware post-processing

- Collect New snapshots identity inputs before collection and rebuilds person identities only when people, aliases, appearances, cases, judgments, outcomes, charges, or identity decisions changed.
- Collection publishes initial exports first, reports “Collection is complete,” then launches required post-processing automatically in a separate process by default.
- `tools\collect-new.cmd --wait` keeps the command open until person identities, advanced features, and final exports finish.
- Statistics-only changes skip `person_identity.py` and run only non-identity advanced stages.
- `data/post-processing-status.json` and `reports/identity-postprocess-latest.log` record background progress and failures.

## v0.20.7 charge-confidence definitions

Appearance Search charge-confidence badges and values link directly to anchored Data Dictionary definitions for Confirmed, Likely, Possible, Non Verified, and Charge Not Available. The Name column now uses the same Charge Not Available badge; the separate Charge unavailable warning and definition were removed.
