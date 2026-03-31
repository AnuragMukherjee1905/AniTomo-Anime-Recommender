"""
mal_client.py
─────────────────────────────────────────────
Handles MAL OAuth2 authentication and all API
data-fetching needed by the recommender.

Usage
-----
First-time auth (run once from terminal):
    python mal_client.py --auth

Normal use (import in other modules):
    from mal_client import MALClient
    client = MALClient()
    anime  = client.get_anime_details(21)
    my_list = client.get_user_anime_list()
"""

import os
import sys
import json
import time
import secrets
import hashlib
import base64
import argparse
from pathlib import Path
from urllib.parse import urlencode
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Constants ─────────────────────────────────────────────────────────────────

MAL_API_BASE   = "https://api.myanimelist.net/v2"
MAL_AUTH_URL   = "https://myanimelist.net/v1/oauth2/authorize"
MAL_TOKEN_URL  = "https://myanimelist.net/v1/oauth2/token"
TOKEN_FILE     = Path(".mal_tokens.json")

# Fields to request for each anime record
ANIME_FIELDS = ",".join([
    "id", "title", "synopsis", "mean", "rank", "popularity",
    "num_episodes", "start_season", "genres", "studios",
    "media_type", "status", "num_scoring_users",
])

# Fields to request when fetching a user's list
LIST_FIELDS = "list_status{score,status,num_episodes_watched}"


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _generate_code_verifier() -> str:
    """Generate a 128-char PKCE code verifier."""
    return secrets.token_urlsafe(96)  # 96 bytes → 128 base64url chars


def _generate_code_challenge(verifier: str) -> str:
    """SHA-256 code challenge derived from verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ── Token persistence ─────────────────────────────────────────────────────────

def _save_tokens(tokens: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    print(f"  Tokens saved to {TOKEN_FILE}")


def _load_tokens() -> Optional[dict]:
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


# ── First-time OAuth2 flow ────────────────────────────────────────────────────

def run_auth_flow() -> dict:
    """
    Interactive PKCE OAuth2 flow.
    Prints an auth URL, waits for the user to paste the redirect URL,
    then exchanges the code for access + refresh tokens.
    """
    client_id     = os.getenv("MAL_CLIENT_ID")
    client_secret = os.getenv("MAL_CLIENT_SECRET")

    if not client_id or not client_secret:
        sys.exit(
            "ERROR: MAL_CLIENT_ID and MAL_CLIENT_SECRET must be set in your .env file.\n"
            "  1. Go to https://myanimelist.net/apiconfig\n"
            "  2. Create an app (type: web, redirect URL: http://localhost)\n"
            "  3. Copy the credentials into .env"
        )

    verifier  = _generate_code_verifier()
    challenge = _generate_code_challenge(verifier)
    state     = secrets.token_urlsafe(16)

    params = urlencode({
        "response_type":         "code",
        "client_id":             client_id,
        "redirect_uri":          "http://localhost",
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    })
    auth_url = f"{MAL_AUTH_URL}?{params}"

    print("\n─── MAL OAuth2 Setup ───────────────────────────────────────")
    print("Step 1 → Open this URL in your browser and approve access:\n")
    print(f"  {auth_url}\n")
    print("Step 2 → After approving, your browser will redirect to")
    print("  something like:  http://localhost/?code=XXXX&state=XXXX")
    print("  Paste that FULL URL (or just the 'code' value) below.\n")

    raw = input("Paste URL or code: ").strip()

    # Accept either the full URL or just the code value
    if "code=" in raw:
        code = raw.split("code=")[1].split("&")[0]
    else:
        code = raw

    # Exchange code for tokens
    print("\nExchanging code for tokens …")
    with httpx.Client() as http:
        resp = http.post(
            MAL_TOKEN_URL,
            data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  "http://localhost",
                "code_verifier": verifier,
            },
        )
        resp.raise_for_status()
        tokens = resp.json()

    tokens["obtained_at"] = time.time()
    _save_tokens(tokens)
    print("  Auth successful!")
    return tokens


# ── MALClient ─────────────────────────────────────────────────────────────────

class MALClient:
    """
    Thin wrapper around MAL API v2.
    Auto-refreshes the access token when it is close to expiry.
    """

    def __init__(self):
        self.client_id     = os.getenv("MAL_CLIENT_ID")
        self.client_secret = os.getenv("MAL_CLIENT_SECRET")
        self._tokens       = _load_tokens()

        if not self._tokens:
            sys.exit(
                "No MAL tokens found. Run `python mal_client.py --auth` first."
            )

        self._http = httpx.Client(timeout=15)
        self._maybe_refresh()

    # ── Token management ──────────────────────────────────────────────────────

    def _maybe_refresh(self) -> None:
        """Refresh the access token if it has fewer than 5 minutes left."""
        obtained_at = self._tokens.get("obtained_at", 0)
        expires_in  = self._tokens.get("expires_in", 3600)
        age         = time.time() - obtained_at
        if age >= (expires_in - 300):           # refresh 5 min before expiry
            self._refresh_token()

    def _refresh_token(self) -> None:
        print("Refreshing MAL access token …")
        resp = self._http.post(
            MAL_TOKEN_URL,
            data={
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
                "grant_type":    "refresh_token",
                "refresh_token": self._tokens["refresh_token"],
            },
        )
        resp.raise_for_status()
        self._tokens = {**resp.json(), "obtained_at": time.time()}
        _save_tokens(self._tokens)

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._tokens['access_token']}"}

    # ── Internal request helper ───────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> dict:
        """Make a GET request to MAL API v2, handling rate limits gracefully."""
        url  = f"{MAL_API_BASE}{path}"
        for attempt in range(3):
            resp = self._http.get(url, headers=self._headers, params=params or {})
            if resp.status_code == 429:             # rate-limited
                wait = int(resp.headers.get("Retry-After", 5))
                print(f"  Rate limited — waiting {wait}s …")
                time.sleep(wait)
                continue
            if resp.status_code == 401:             # token expired mid-session
                self._refresh_token()
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("MAL API request failed after 3 retries")

    # ── Public methods ────────────────────────────────────────────────────────

    def get_anime_details(self, anime_id: int) -> dict:
        """
        Fetch full details for a single anime by its MAL ID.

        Returns a flat dict with: id, title, synopsis, score, rank,
        popularity, episodes, season, genres, studios, media_type.
        """
        raw = self._get(f"/anime/{anime_id}", {"fields": ANIME_FIELDS})
        return self._parse_anime(raw)

    def search_anime(self, query: str, limit: int = 20) -> list[dict]:
        """
        Search anime by keyword.
        Returns a list of parsed anime dicts (without full synopsis).
        """
        raw = self._get("/anime", {"q": query, "limit": limit, "fields": ANIME_FIELDS})
        return [self._parse_anime(item["node"]) for item in raw.get("data", [])]

    def get_anime_ranking(
        self,
        ranking_type: str = "all",
        limit: int = 200,
    ) -> list[dict]:
        """
        Fetch a ranked list of anime.

        ranking_type options:
            all, airing, upcoming, tv, ova, movie, special,
            bypopularity, favorite
        """
        results, offset = [], 0
        while len(results) < limit:
            batch_size = min(100, limit - len(results))   # MAL max = 100 per page
            raw = self._get("/anime/ranking", {
                "ranking_type": ranking_type,
                "limit":        batch_size,
                "offset":       offset,
                "fields":       ANIME_FIELDS,
            })
            items = raw.get("data", [])
            if not items:
                break
            results.extend(self._parse_anime(item["node"]) for item in items)
            offset += batch_size
            if not raw.get("paging", {}).get("next"):
                break
        return results

    def get_user_anime_list(
        self,
        username: str = "@me",
        status: str = "completed",
        limit: int = 1000,
    ) -> list[dict]:
        """
        Fetch a user's anime list.

        status options: watching, completed, on_hold, dropped, plan_to_watch
        Use "@me" for the authenticated user.

        Returns a list of dicts:
            { anime_id, title, score, status, episodes_watched }
        """
        results, offset = [], 0
        while len(results) < limit:
            batch_size = min(100, limit - len(results))
            raw = self._get(f"/users/{username}/animelist", {
                "status": status,
                "sort":   "list_score",
                "limit":  batch_size,
                "offset": offset,
                "fields": LIST_FIELDS,
            })
            items = raw.get("data", [])
            if not items:
                break
            for item in items:
                node   = item["node"]
                status_info = item.get("list_status", {})
                results.append({
                    "anime_id":         node["id"],
                    "title":            node["title"],
                    "score":            status_info.get("score", 0),
                    "status":           status_info.get("status", ""),
                    "episodes_watched": status_info.get("num_episodes_watched", 0),
                })
            offset += batch_size
            if not raw.get("paging", {}).get("next"):
                break
        return results

    def get_seasonal_anime(self, year: int, season: str, limit: int = 50) -> list[dict]:
        """
        Fetch anime for a specific season.

        season: winter | spring | summer | fall
        """
        raw = self._get(f"/anime/season/{year}/{season}", {
            "limit":  min(limit, 100),
            "fields": ANIME_FIELDS,
            "sort":   "anime_score",
        })
        return [self._parse_anime(item["node"]) for item in raw.get("data", [])]

    # ── Parsing helper ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_anime(node: dict) -> dict:
        """Normalise a raw MAL anime node into a clean flat dict."""
        season = node.get("start_season") or {}
        return {
            "id":          node.get("id"),
            "title":       node.get("title", ""),
            "synopsis":    node.get("synopsis", ""),
            "score":       node.get("mean", 0.0) or 0.0,
            "rank":        node.get("rank"),
            "popularity":  node.get("popularity"),
            "episodes":    node.get("num_episodes", 0),
            "season":      season.get("season", ""),
            "year":        season.get("year"),
            "genres":      [g["name"] for g in node.get("genres", [])],
            "studios":     [s["name"] for s in node.get("studios", [])],
            "media_type":  node.get("media_type", ""),
            "status":      node.get("status", ""),
            "num_votes":   node.get("num_scoring_users", 0),
        }

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MAL API client utility")
    parser.add_argument("--auth",   action="store_true", help="Run OAuth2 setup")
    parser.add_argument("--test",   action="store_true", help="Test the client")
    args = parser.parse_args()

    if args.auth:
        run_auth_flow()

    if args.test:
        with MALClient() as client:
            print("\nFetching top 5 anime …")
            top = client.get_anime_ranking(limit=5)
            for a in top:
                print(f"  [{a['score']}] {a['title']}  ({', '.join(a['genres'])})")

            print("\nFetching your completed list (first 5) …")
            my_list = client.get_user_anime_list(limit=5)
            for a in my_list:
                print(f"  [{a['score']}/10] {a['title']}")
