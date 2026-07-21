"""Verified HTTPS helpers using the Windows trust store, then certifi as a fallback."""
from __future__ import annotations
import ssl
from urllib.error import URLError
from urllib.request import urlopen


def windows_trust_context():
    """Return a truststore-backed SSL context when the optional package is installed."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return None


def certifi_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


def _is_cert_error(exc):
    reason = getattr(exc, 'reason', None)
    return isinstance(reason, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(exc)


def verified_urlopen(request, *, timeout=45):
    """Open HTTPS with verification, preferring the native Windows certificate store on retry."""
    errors = []
    try:
        return urlopen(request, timeout=timeout)
    except URLError as exc:
        if not _is_cert_error(exc):
            raise
        errors.append(exc)

    for context in (windows_trust_context(), certifi_context()):
        if context is None:
            continue
        try:
            return urlopen(request, timeout=timeout, context=context)
        except URLError as exc:
            if not _is_cert_error(exc):
                raise
            errors.append(exc)

    raise RuntimeError(
        'HTTPS certificate verification failed with the default, Windows, and certifi trust stores. '
        r'Run tools\setup-data.cmd to install/update truststore and certifi, then retry.'
    ) from errors[-1]
