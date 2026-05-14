"""requests.Session download wrapper with PDF validation and error classification.

Replaces the legacy ``urllib``-based download in ``download_fulltexts.py``
with a ``requests.Session`` that supports cookies, referer, and redirect
history for institutional access scenarios.

Compliance:
  1. Only uses locally available legitimate access rights.
  2. No paywall bypass, captcha bypass, account restriction bypass.
  3. No Sci-Hub, pirate sources, or unauthorized mirrors.
  4. No credentials, cookies, or tokens in logs or output files.
  5. Low concurrency, respect publisher access rules.
  6. Non-OA papers that cannot be auto-downloaded -> manual_download_required.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import requests

from literature_harvest.access_markers import looks_paywalled
from literature_harvest.status import (
    BROKEN_LINK,
    DOWNLOADED_BUT_NOT_PARSEABLE,
    DOWNLOAD_FAILED,
    HTML_SAVED,
    OA_PDF_DOWNLOADED,
    PAYWALL_DETECTED_NO_ENTITLEMENT,
    PUBLISHER_BLOCKED,
    RATE_LIMITED,
    XML_SAVED,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class DownloadSession:
    """HTTP download wrapper built on ``requests.Session``.

    Provides download, content classification, PDF validation, and
    paywall detection — all in a single class that preserves cookies
    and headers across requests.
    """

    def __init__(
        self,
        timeout: int = 45,
        delay: float = 0.25,
        user_agent: str = USER_AGENT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def attempt_download(self, url: str) -> dict[str, Any]:
        """Download a URL and return structured result.

        Returns:
            A dict with keys:
            - ``status_code`` (int)
            - ``content_type`` (str)
            - ``final_url`` (str)
            - ``payload`` (bytes)
            - ``redirect_history`` (list[str])
            - ``error`` (str or None)
        """
        result: dict[str, Any] = {
            "status_code": 0,
            "content_type": "",
            "final_url": url,
            "payload": b"",
            "redirect_history": [],
            "error": None,
        }
        try:
            resp = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                headers={
                    "Accept": "application/pdf, application/xml, "
                              "text/xml, text/html;q=0.9, */*;q=0.1",
                },
            )
            result["status_code"] = resp.status_code
            result["content_type"] = (resp.headers.get("Content-Type") or "").lower()
            result["final_url"] = resp.url
            result["payload"] = resp.content
            result["redirect_history"] = [r.url for r in resp.history]

            if resp.status_code == 429:
                result["error"] = "rate_limited"
            elif resp.status_code in (401, 402, 403):
                result["error"] = f"http_{resp.status_code}"
            elif resp.status_code in (404, 410):
                result["error"] = f"http_{resp.status_code}_broken"
            elif resp.status_code >= 400:
                result["error"] = f"http_{resp.status_code}"

            return result

        except requests.exceptions.Timeout:
            result["error"] = "timeout"
            return result
        except requests.exceptions.ConnectionError:
            result["error"] = "connection_error"
            return result
        except requests.exceptions.RequestException as exc:
            result["error"] = str(exc)
            return result

    def classify_payload(self, payload: bytes, content_type: str) -> str:
        """Classify payload as ``pdf``, ``xml``, ``html``, or ``other``."""
        sample = payload[:3000].decode("utf-8", errors="ignore").lower()
        if payload.startswith(b"%PDF") or "pdf" in content_type:
            return "pdf"
        if "xml" in content_type or sample.lstrip().startswith("<?xml"):
            return "xml"
        if "html" in content_type or "<html" in sample:
            return "html"
        return "other"

    def looks_paywalled(self, text: str) -> bool:
        """Check if *text* contains paywall markers."""
        return looks_paywalled(text)

    def check_pdf_magic(self, path: str | Path) -> bool:
        """Verify that a file starts with ``%PDF``."""
        path = Path(path)
        if not path.is_file() or path.stat().st_size < 8:
            return False
        header = path.read_bytes()[:8]
        return header.startswith(b"%PDF")

    def save_payload(self, payload: bytes, path: str | Path) -> str:
        """Write *payload* to *path* and return the absolute path string."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return str(path.resolve())

    # ------------------------------------------------------------------
    # High-level download → save
    # ------------------------------------------------------------------

    def download_to_file(
        self, url: str, output_path: str | Path,
    ) -> dict[str, Any]:
        """Download *url* and save to *output_path*.

        Returns a dict with keys: status, reason, content_format, path, url.
        This is the primary method used by the pipeline.
        """
        response = self.attempt_download(url)
        payload = response["payload"]
        error = response["error"]
        content_type = response["content_type"]
        final_url = response["final_url"]

        # Handle errors
        if error == "rate_limited":
            return {"status": RATE_LIMITED.value, "reason": error,
                    "content_format": "", "path": "", "url": final_url}
        if error and "broken" in error:
            return {"status": BROKEN_LINK.value, "reason": error,
                    "content_format": "", "path": "", "url": final_url}
        if error and "http_" in error:
            return {"status": PUBLISHER_BLOCKED.value, "reason": error,
                    "content_format": "", "path": "", "url": final_url}
        if error:
            return {"status": DOWNLOAD_FAILED.value, "reason": error,
                    "content_format": "", "path": "", "url": final_url}

        # Classify
        kind = self.classify_payload(payload, content_type)

        # Paywall check for HTML
        if kind == "html":
            html_text = payload[:50000].decode("utf-8", errors="ignore")
            if self.looks_paywalled(html_text):
                return {"status": PAYWALL_DETECTED_NO_ENTITLEMENT.value,
                        "reason": "paywall_in_html",
                        "content_format": "html", "path": "", "url": final_url}

        # Determine extension
        if kind == "pdf":
            ext = ".pdf"
        elif kind == "xml":
            ext = ".xml"
        elif kind == "html":
            ext = ".html"
        else:
            ext = ".bin"

        # Save
        output_path = Path(output_path)
        save_path = output_path.with_suffix(ext)
        saved = self.save_payload(payload, save_path)

        # Status
        if kind == "pdf":
            if not self.check_pdf_magic(save_path):
                return {"status": DOWNLOADED_BUT_NOT_PARSEABLE.value,
                        "reason": "invalid_pdf_magic_bytes",
                        "content_format": "pdf", "path": saved, "url": final_url}
            status = OA_PDF_DOWNLOADED.value
        elif kind == "html":
            status = HTML_SAVED.value
        elif kind == "xml":
            status = XML_SAVED.value
        else:
            status = DOWNLOADED_BUT_NOT_PARSEABLE.value

        return {"status": status, "reason": "",
                "content_format": kind, "path": saved, "url": final_url}

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "DownloadSession":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
