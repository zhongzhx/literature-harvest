"""Shared access-barrier detection — paywall, login, captcha markers.

Used by DownloadSession, InstitutionalResolver, and BrowserDownloader
to avoid duplicated marker strings drifting out of sync.
"""

from __future__ import annotations

import re

# ── Text markers (substring match, case-insensitive) ──────────────

LOGIN_MARKERS = [
    "login",
    "sign in",
    "sign-in",
    "log in",
    "log-in",
    "institutional login",
    "access through your institution",
    "access via your institution",
    "shibboleth",
    "saml",
    "openathens",
    "wayfinder",
]

CAPTCHA_MARKERS = [
    "captcha",
    "recaptcha",
    "are you a robot",
    "verify you are human",
    "unusual traffic",
]

PAYWALL_MARKERS = [
    "subscription required",
    "purchase this article",
    "buy this article",
    "access through your institution",
    "institutional access",
    "paywall",
    "pay per view",
    "pay-per-view",
    "subscribe to journal",
    "subscribe to this journal",
    "purchase pdf",
    "rent this article",
    "add to cart",
    "requires a subscription",
]

# ── Regex variants (for BrowserDownloader's compiled-pattern path) ─

_LOGIN_MARKERS_RE = re.compile(
    r"login|sign[-\s]in|log[-\s]in|institutional.login|shibboleth|"
    r"openathens|wayfinder|access.through.your.institution"
    r"|access.via.your.institution",
    re.IGNORECASE,
)

_CAPTCHA_MARKERS_RE = re.compile(
    r"captcha|recaptcha|are.you.a.robot|verify.you.are.human|unusual.traffic",
    re.IGNORECASE,
)

_PAYWALL_MARKERS_RE = re.compile(
    r"subscription.required|purchase.this.article|pay.per.view|add.to.cart|"
    r"subscribe.to.journal|buy.this.article|requires.a.subscription",
    re.IGNORECASE,
)


# ── Detection helpers ─────────────────────────────────────────────


def looks_paywalled(text: str) -> bool:
    """Check if *text* contains paywall markers (substring match)."""
    lowered = text.lower()
    return any(marker in lowered for marker in PAYWALL_MARKERS)


def detect_access_barriers(
    html: str,
    url: str = "",
    use_regex: bool = False,
) -> list[str]:
    """Scan a page for login walls, captchas, and paywalls.

    Returns a list of unique marker strings found.
    """
    markers: list[str] = []
    if use_regex:
        text = html
    else:
        text = html.lower()

    # Login
    candidates = _LOGIN_MARKERS_RE if use_regex else LOGIN_MARKERS
    for marker in candidates:
        if (re.search(marker, text) if use_regex else marker in text):
            markers.append(marker if isinstance(marker, str) else marker.pattern)
            break

    # Captcha
    candidates = _CAPTCHA_MARKERS_RE if use_regex else CAPTCHA_MARKERS
    for marker in candidates:
        if (re.search(marker, text) if use_regex else marker in text):
            markers.append(marker if isinstance(marker, str) else marker.pattern)
            break

    # Paywall
    candidates = _PAYWALL_MARKERS_RE if use_regex else PAYWALL_MARKERS
    for marker in candidates:
        if (re.search(marker, text) if use_regex else marker in text):
            markers.append(marker if isinstance(marker, str) else marker.pattern)
            break

    return markers
