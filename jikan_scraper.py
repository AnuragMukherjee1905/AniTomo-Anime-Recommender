"""
jikan_scraper.py
─────────────────────────────────────────────
Scrapes anime data and user ratings from the
Jikan API (unofficial MAL, no auth needed).

Usage
-----
    python jikan_scraper.py

This will create two CSV files:
    anime.csv    — anime catalogue with features
    ratings.csv  — user ratings for collaborative filtering

Jikan API docs: https://docs.api.jikan.moe/
Rate limit: 3 requests/second, 60/minute (handled automatically)
"""

import time
import csv
import json
import httpx
from pathlib import Path

JIKAN_BASE   = "https://api.jikan.moe/v4"
ANIME_FILE   = Path("anime.csv")
RATINGS_FILE = Path("ratings.csv")

# How many pages of top anime to fetch (each page = 25 anime)
# 40 pages = 1000 anime — good starting point
ANIME_PAGES  = 40

# How many reviews to scrape per anime (each review = one user rating)
REVIEWS_PER_ANIME = 20


# ── Request helper ────────────────────────────────────────────────────────────

def get(url: str, params: dict = None, retries: int = 5) -> dict:
    """
    GET request with automatic rate limit handling.
    Jikan allows 3 req/sec — we wait 0.4s between calls to stay safe.
    """
    for attempt in range(retries):
        try:
            resp = httpx.get(url, params=params or {}, timeout=15)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  Rate limited — waiting {wait}s …")
                time.sleep(wait)
                continue
            if resp.status_code == 503:
                print(f"  Jikan unavailable — waiting 10s (attempt {attempt+1}) …")
                time.sleep(10)
                continue
            resp.raise_for_status()
            time.sleep(0.4)   # polite delay between requests
            return resp.json()
        except httpx.RequestError as e:
            print(f"  Network error: {e} — retrying in 5s …")
            time.sleep(5)
    raise RuntimeError(f"Failed after {retries} retries: {url}")


# ── Parse helpers ─────────────────────────────────────────────────────────────

def parse_anime(item: dict) -> dict:
    images = item.get("images", {}).get("jpg", {})
    return {
        "id":         item.get("mal_id"),
        "title":      item.get("title", ""),
        "synopsis":   (item.get("synopsis") or "").replace("\n", " "),
        "score":      item.get("score") or 0.0,
        "rank":       item.get("rank"),
        "popularity": item.get("popularity"),
        "episodes":   item.get("episodes") or 0,
        "year":       (item.get("aired") or {}).get("prop", {}).get("from", {}).get("year"),
        "season":     item.get("season") or "",
        "genres":     "|".join(g["name"] for g in (item.get("genres") or [])),
        "studios":    "|".join(s["name"] for s in (item.get("studios") or [])),
        "media_type": item.get("type") or "",
        "status":     item.get("status") or "",
        "num_votes":  item.get("scored_by") or 0,
        "image_url":  images.get("large_image_url") or images.get("image_url") or "",  # ← add this
    }


# ── Scrape anime catalogue ────────────────────────────────────────────────────

def scrape_anime(pages: int = ANIME_PAGES) -> list[dict]:
    """
    Fetch top anime ordered by popularity.
    Returns a list of parsed anime dicts.
    """
    all_anime = []
    print(f"\nScraping anime catalogue ({pages} pages × 25 = ~{pages*25} anime) …")

    for page in range(1, pages + 1):
        print(f"  Page {page}/{pages} …", end="\r")
        data = get(f"{JIKAN_BASE}/top/anime", {"page": page, "filter": "bypopularity"})
        items = data.get("data", [])
        if not items:
            break
        all_anime.extend(parse_anime(item) for item in items)

    print(f"\n  Fetched {len(all_anime)} anime.")
    return all_anime


# ── Scrape reviews (ratings) ──────────────────────────────────────────────────

def scrape_ratings(anime_ids: list[int], reviews_per_anime: int = REVIEWS_PER_ANIME) -> list[dict]:
    """
    For each anime, fetch user reviews and extract the reviewer's score.
    Each review gives us one (user_id, anime_id, score) triplet.

    This builds a synthetic multi-user ratings matrix from public MAL reviews.
    """
    all_ratings = []
    total = len(anime_ids)
    print(f"\nScraping reviews for {total} anime (~{reviews_per_anime} reviews each) …")
    print("This will take a while — Jikan rate limits to 60 req/min.\n")

    for i, anime_id in enumerate(anime_ids):
        print(f"  [{i+1}/{total}] anime_id={anime_id} …", end="\r")
        try:
            data = get(
                f"{JIKAN_BASE}/anime/{anime_id}/reviews",
                {"page": 1, "preliminary": "false"}
            )
            reviews = data.get("data", [])[:reviews_per_anime]
            for review in reviews:
                user    = review.get("user", {})
                user_id = user.get("username")
                score   = review.get("score")
                if user_id and score and score > 0:
                    all_ratings.append({
                        "user_id":  user_id,
                        "anime_id": anime_id,
                        "score":    score,
                    })
        except Exception as e:
            print(f"\n  Skipping anime {anime_id}: {e}")
            continue

    print(f"\n  Collected {len(all_ratings)} ratings from {total} anime.")
    return all_ratings


# ── Save to CSV ───────────────────────────────────────────────────────────────

def save_csv(data: list[dict], path: Path):
    if not data:
        print(f"  No data to save to {path}")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print(f"  Saved {len(data)} rows → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print(" Jikan MAL Scraper")
    print("=" * 50)

    # Step 1 — Scrape anime catalogue
    if ANIME_FILE.exists():
        print(f"\nanime.csv already exists — skipping anime scrape.")
        print("Delete anime.csv to re-scrape.")
        import csv as _csv
        with open(ANIME_FILE, encoding="utf-8") as f:
            anime_list = list(_csv.DictReader(f))
    else:
        anime_list = scrape_anime(ANIME_PAGES)
        save_csv(anime_list, ANIME_FILE)

    # Step 2 — Scrape ratings from reviews
    if RATINGS_FILE.exists():
        print(f"\nratings.csv already exists — skipping ratings scrape.")
        print("Delete ratings.csv to re-scrape.")
    else:
        anime_ids = [int(a["id"]) for a in anime_list if a.get("id")]
        ratings   = scrape_ratings(anime_ids, REVIEWS_PER_ANIME)
        save_csv(ratings, RATINGS_FILE)

    print("\nDone! You now have:")
    print(f"  {ANIME_FILE}   — anime features")
    print(f"  {RATINGS_FILE} — user ratings")
    print("\nRun the backend next: py -3.11 -m uvicorn main:app --reload --port 8000")
