from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_appearance_results_keep_only_name_and_record_details_columns():
    text = (ROOT / "js" / "appearance-search.js").read_text(encoding="utf-8")
    start = text.index("const markup=()")
    end = text.index("const STATIC_JSON_CACHE", start)
    markup = text[start:end]
    assert '<th>Name</th><th data-record-heading>Record details</th>' in markup
    assert "<th>Date</th><th>Time</th><th>Courthouse</th><th>File</th>" not in markup
    assert 'class="appearance-name-cell"' in text
    assert 'class="appearance-record-cell"' in text

def test_record_details_follow_requested_order_and_keep_history_badge_last():
    text = (ROOT / "js" / "appearance-search.js").read_text(encoding="utf-8")
    start = text.index("const recordDetailsMarkup=")
    end = text.index("const confidenceRank=", start)
    block = text[start:end]
    labels = [
        "detailLine('Appearance',",
        "detailLine('Appearance code',",
        "detailLine('Status code',",
        "detailLine('Statute',",
        "detailLine('Section',",
        "detailLine('Date and time',",
        "detailLine('Courthouse',",
        "detailLine('Courtroom',",
        "detailLine('Court file',",
        "detailLine('Court level',",
        "detailLine('Linked alleged charge',",
        "detailLine('Charge confidence',",
        "detailLine('Evidence',",
    ]
    positions = [block.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "const details=view==='compact'?compactRecordMarkup(r,courts):recordDetailsMarkup(r,courts);" in text
    assert '${details}${courtFileGroupMarkup(r,courts)}${historyControl}' in text
    assert 'summary class="appearance-count"' in text
    assert "catalogued appearance${historyCount===1?'':'s'}" in text

def test_raw_record_name_is_removed_globally_before_code_parsing():
    text = (ROOT / "js" / "appearance-search.js").read_text(encoding="utf-8")
    assert "new RegExp(pattern,'ig')" in text
    assert "nameVariants.add(`${rest.join(' ')} ${last}`)" in text

def test_requested_code_fields_link_to_exact_dictionary_definitions():
    text = (ROOT / "js" / "appearance-search.js").read_text(encoding="utf-8")
    block = text[text.index("const recordDetailsMarkup="):text.index("const confidenceRank=")]
    assert "dictionaryValueLink('appearance-code',appearanceCode" in block
    assert "dictionaryValueLink('status-code',statusCode" in block
    assert "dictionaryValueLink('statute',statute" in block
    assert "dictionaryValueLink('section',section,{statute" in block
    assert "data-dictionary.html?${params.toString()}#${anchor}" in text


def test_dictionary_builds_code_specific_target_cards_without_guessing():
    text = (ROOT / "js" / "data-dictionary.js").read_text(encoding="utf-8")
    assert "type==='appearance-code'" in text
    assert "type==='status-code'" in text
    assert "type==='statute'" in text
    assert "type==='section'" in text
    assert "Its exact local meaning has not been assumed" in text
    assert "Open official JUSTIN code table" in text
    assert "document.getElementById(decodeURIComponent(location.hash.slice(1)))" in text


def test_charge_details_use_right_hand_record_column():
    js = (ROOT / "js" / "appearance-search.js").read_text(encoding="utf-8")
    css = (ROOT / "style.css").read_text(encoding="utf-8")
    block = js[js.index("const recordDetailsMarkup="):js.index("const confidenceRank=")]
    assert 'class="record-detail-main"' in block
    assert 'class="record-detail-charge"' in block
    assert block.index('class="record-detail-charge"') < block.index("detailLine('Linked alleged charge',")
    assert '.record-detail-list{display:grid' in css
    assert 'grid-template-columns:minmax(0,1.45fr) minmax(16rem,.9fr)' in css
    assert '.record-detail-charge{padding-left:1rem;border-left:1px solid var(--line)}' in css
    assert '@media(max-width:900px)' in css
