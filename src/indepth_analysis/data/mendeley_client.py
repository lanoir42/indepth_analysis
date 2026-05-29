"""Mendeley API client — OAuth2 auth, list folders/documents, download PDFs.

Adapted from /Users/lanoir42/projects/earnings/src/tools/mendeley.py for use
inside the indepth_analysis package. Credentials are loaded from .env files
in either the earnings or indepth_analysis project (silently skipped if
neither contains them).
"""

from __future__ import annotations

import json
import logging
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from dotenv import dotenv_values, load_dotenv

import requests

logger = logging.getLogger(__name__)

# Default in-process .env load (for run-time invocations from indepth_analysis).
load_dotenv()

AUTH_URL = "https://api.mendeley.com/oauth/authorize"
TOKEN_URL = "https://api.mendeley.com/oauth/token"
API_BASE = "https://api.mendeley.com"
REDIRECT_URI = "http://localhost:5000/callback"
TOKEN_FILE = Path(
    os.environ.get("MENDELEY_TOKEN_FILE", Path.home() / ".mendeley_token.json")
)

_ENV_CANDIDATES = (
    Path.home() / "projects" / "earnings" / ".env",
    Path.home() / "projects" / "indepth_analysis" / ".env",
)


def _get_credentials() -> tuple[str, str]:
    """Resolve Mendeley credentials from env or .env candidate files."""
    cid = os.environ.get("MENDELEY_CLIENT_ID", "")
    secret = (
        os.environ.get("MENDELEY_CLIENT_SECRET", "")
        or os.environ.get("MENDELEY_SECRET", "")
    )

    if not cid or not secret:
        for env_path in _ENV_CANDIDATES:
            if not env_path.exists():
                continue
            values = dotenv_values(env_path)
            cid = cid or (values.get("MENDELEY_CLIENT_ID") or "")
            secret = secret or (
                values.get("MENDELEY_CLIENT_SECRET")
                or values.get("MENDELEY_SECRET")
                or ""
            )
            if cid and secret:
                break

    if not cid or not secret:
        raise RuntimeError(
            "Mendeley credentials not found. Set MENDELEY_CLIENT_ID and "
            "MENDELEY_CLIENT_SECRET in ~/projects/earnings/.env or "
            "~/projects/indepth_analysis/.env"
        )
    return cid, secret


def _save_token(token_data: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))


def _load_token() -> dict | None:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def _refresh_access_token(refresh_token: str) -> dict:
    cid, secret = _get_credentials()
    resp = requests.post(
        TOKEN_URL,
        auth=(cid, secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": REDIRECT_URI,
        },
    )
    resp.raise_for_status()
    token_data = resp.json()
    _save_token(token_data)
    return token_data


def get_access_token() -> str:
    """Return a valid access token, refreshing if needed."""
    token_data = _load_token()
    if token_data:
        test = requests.get(
            f"{API_BASE}/documents",
            headers={"Authorization": f"Bearer {token_data['access_token']}"},
            params={"limit": 1},
        )
        if test.status_code == 200:
            return token_data["access_token"]
        if "refresh_token" in token_data:
            token_data = _refresh_access_token(token_data["refresh_token"])
            return token_data["access_token"]
    raise RuntimeError(
        "No valid Mendeley token. Run the earnings project's mendeley-login "
        "command to generate one (token file shared at ~/.mendeley_token.json)."
    )


def login() -> str:
    """Run OAuth2 authorization code flow via browser. Returns access token."""
    cid, secret = _get_credentials()

    auth_code_holder: dict[str, str | None] = {"code": None}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            qs = parse_qs(urlparse(self.path).query)
            auth_code_holder["code"] = qs.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Success! You can close this tab.</h2>")

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", 5000), CallbackHandler)

    params = urlencode(
        {
            "client_id": cid,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "all",
        }
    )
    url = f"{AUTH_URL}?{params}"
    print(f"Opening browser for Mendeley login...\n{url}")
    webbrowser.open(url)

    server.handle_request()
    server.server_close()

    code = auth_code_holder["code"]
    if not code:
        raise RuntimeError("Did not receive authorization code from Mendeley.")

    resp = requests.post(
        TOKEN_URL,
        auth=(cid, secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
    )
    resp.raise_for_status()
    token_data = resp.json()
    _save_token(token_data)
    print(f"Token saved to {TOKEN_FILE}")
    return token_data["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {get_access_token()}"}


def list_folders() -> list[dict]:
    """List all folders in the library."""
    resp = requests.get(
        f"{API_BASE}/folders",
        headers={**_headers(), "Accept": "application/vnd.mendeley-folder.1+json"},
    )
    resp.raise_for_status()
    return resp.json()


def find_folder_by_name(name: str) -> str | None:
    """Search list_folders() by case-insensitive name match. Returns folder_id or None."""
    target = name.strip().lower()
    try:
        folders = list_folders()
    except Exception as exc:
        logger.warning("Mendeley list_folders failed: %s", exc)
        return None
    for folder in folders:
        fname = (folder.get("name") or "").strip().lower()
        if fname == target:
            return folder.get("id")
    return None


def list_documents(
    folder_id: str | None = None,
    limit: int = 50,
    view: str = "all",
) -> list[dict]:
    """List documents, optionally filtered by folder."""
    if folder_id:
        url = f"{API_BASE}/folders/{folder_id}/documents"
        resp = requests.get(url, headers=_headers(), params={"limit": limit})
        resp.raise_for_status()
        doc_ids = [d["id"] for d in resp.json()]
        docs = []
        for did in doc_ids:
            r = requests.get(
                f"{API_BASE}/documents/{did}",
                headers={
                    **_headers(),
                    "Accept": "application/vnd.mendeley-document.1+json",
                },
                params={"view": view},
            )
            r.raise_for_status()
            docs.append(r.json())
        return docs
    else:
        resp = requests.get(
            f"{API_BASE}/documents",
            headers={
                **_headers(),
                "Accept": "application/vnd.mendeley-document.1+json",
            },
            params={
                "limit": limit,
                "view": view,
                "sort": "created",
                "order": "desc",
            },
        )
        resp.raise_for_status()
        return resp.json()


def list_files(document_id: str) -> list[dict]:
    """List files attached to a document."""
    resp = requests.get(
        f"{API_BASE}/files",
        headers={**_headers(), "Accept": "application/vnd.mendeley-file.1+json"},
        params={"document_id": document_id},
    )
    resp.raise_for_status()
    return resp.json()


def download_file(
    file_id: str, dest_dir: str | Path, filename: str | None = None
) -> Path:
    """Download a file by ID. Returns the saved path."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    resp = requests.get(
        f"{API_BASE}/files/{file_id}",
        headers=_headers(),
        allow_redirects=True,
    )
    resp.raise_for_status()

    if not filename:
        cd = resp.headers.get("Content-Disposition", "")
        if "filename=" in cd:
            filename = cd.split("filename=")[-1].strip('" ')
        else:
            filename = f"{file_id}.pdf"

    dest = dest_dir / filename
    dest.write_bytes(resp.content)
    return dest


def download_documents(
    dest_dir: str | Path,
    folder_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Download PDFs for documents. Returns list of {title, filename, path}."""
    docs = list_documents(folder_id=folder_id, limit=limit)
    dest_dir = Path(dest_dir)
    results = []

    for doc in docs:
        title = doc.get("title", "untitled")
        doc_id = doc["id"]
        files = list_files(doc_id)

        for f in files:
            fname = f.get("file_name", f"{doc_id}.pdf")
            path = download_file(f["id"], dest_dir, filename=fname)
            results.append({"title": title, "filename": fname, "path": str(path)})

    return results


def download_latest_weekly_pdf(
    dest_dir: Path, folder_name: str = "WEEKLY"
) -> Path | None:
    """Find a folder by name, list its docs sorted by title desc, download first PDF.

    Returns the saved path, or None if any step fails (folder missing, no docs,
    no files, or credentials/token unavailable). All errors are logged at WARNING
    level — Mendeley reference download is treated as optional.
    """
    try:
        folder_id = find_folder_by_name(folder_name)
    except Exception as exc:
        logger.warning("Mendeley folder lookup failed: %s", exc)
        return None

    if not folder_id:
        logger.warning("Mendeley folder %r not found", folder_name)
        return None

    try:
        docs = list_documents(folder_id=folder_id, limit=50)
    except Exception as exc:
        logger.warning("Mendeley list_documents failed: %s", exc)
        return None

    if not docs:
        logger.warning("Mendeley folder %r is empty", folder_name)
        return None

    docs_sorted = sorted(
        docs, key=lambda d: (d.get("title") or "").lower(), reverse=True
    )

    for doc in docs_sorted:
        try:
            files = list_files(doc["id"])
        except Exception as exc:
            logger.warning(
                "Mendeley list_files failed for doc %s: %s", doc.get("id"), exc
            )
            continue
        if not files:
            continue

        f = files[0]
        fname = f.get("file_name") or f"{doc['id']}.pdf"
        try:
            path = download_file(f["id"], dest_dir, filename=fname)
            logger.info("Mendeley downloaded %s → %s", fname, path)
            return path
        except Exception as exc:
            logger.warning("Mendeley download failed for %s: %s", fname, exc)
            continue

    logger.warning("Mendeley folder %r yielded no downloadable PDF", folder_name)
    return None
