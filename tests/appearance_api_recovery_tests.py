from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_appearance_api_waits_for_ready_and_uses_longer_cold_start_window():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert "API_STATUS='http://127.0.0.1:8764/status'" in js
    assert 'API_REQUEST_TIMEOUT=9000' in js
    assert 'API_COLD_START_TIMEOUT=15000' in js
    assert 'async function wakeAndWaitForApi' in js
    assert 'const wake=await supervisorJson(API_WAKE' in js
    assert 'const state=await supervisorJson(API_STATUS' in js
    assert 'if(state?.apiReady)return {ready:true,state}' in js


def test_database_busy_uses_retry_after_before_fallback():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert "response.headers.get('Retry-After')" in js
    assert "error?.status===503&&error?.code==='database_busy'" in js
    assert 'attempt<busyRetries' in js
    assert "await sleep(Math.max(1,error.retryAfterSeconds||2)*1000)" in js


def test_static_fallback_is_request_scoped_and_api_recovers_automatically():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert 'provider=await getFallback()' not in js
    assert 'const fallback=await requestFallback()' in js
    assert "fallback.search(filters)" in js
    assert "fallback.history(current)" in js
    assert "fallback.all(filters)" in js
    assert "controllers.forEach(controller=>controller.setProvider(createApiProvider(facets)))" in js
    assert "Local Search API is ready. Refreshing current results" in js


def test_api_failure_reason_is_shown_in_status():
    js=(ROOT/'js'/'appearance-search.js').read_text(encoding='utf-8')
    assert 'const apiFailureReason=error=>' in js
    assert 'connection refused or the local API is not listening' in js
    assert 'Local Search API unavailable: ${reason}' in js
    assert 'Static JSON will be used only for requests that fail.' in js
