"""
main.py  (v2 — loads from Jikan-scraped CSVs)
─────────────────────────────────────────────
FastAPI backend for the anime recommender.

Start server
------------
    py -3.11 -m uvicorn main:app --reload --port 8000

Make sure you've run jikan_scraper.py first to generate:
    anime.csv
    ratings.csv
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from recommender import AnimeRecommender, MODEL_PATH

ANIME_FILE   = Path("anime.csv")
RATINGS_FILE = Path("ratings.csv")


# ── App state ─────────────────────────────────────────────────────────────────

class AppState:
    recommender: AnimeRecommender = None
    anime_df:    pd.DataFrame     = None
    is_training: bool             = False

state = AppState()


# ── Startup ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up …")

    if not ANIME_FILE.exists():
        raise RuntimeError(
            "anime.csv not found!\n"
            "Run `py -3.11 jikan_scraper.py` first to generate the data."
        )

    if MODEL_PATH.exists():
        state.recommender = AnimeRecommender.load()
        state.anime_df    = state.recommender.anime_df
        print("Pre-trained model loaded.")
    else:
        print("No saved model found — training now …")
        await _train_model()

    yield
    print("Shutting down.")


app = FastAPI(title="Anime Recommender API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────

class RecommendRequest(BaseModel):
    liked_anime_ids: list[int]     = []
    genres:          list[str]     = []
    mood:            Optional[str] = None
    exclude_ids:     list[int]     = []
    top_n:           int           = 20

class TrainRequest(BaseModel):
    pass


# ── Training helper ───────────────────────────────────────────────────────────

async def _train_model():
    state.is_training = True
    try:
        loop = asyncio.get_event_loop()

        def _load_and_train():
            print("Loading anime.csv …")
            anime_df = pd.read_csv(ANIME_FILE)
            print(f"  {len(anime_df)} anime loaded.")

            ratings_df = None
            if RATINGS_FILE.exists():
                print("Loading ratings.csv …")
                ratings_df = pd.read_csv(RATINGS_FILE)
                print(f"  {len(ratings_df)} ratings loaded.")
            else:
                print("No ratings.csv found — content-based only.")

            rec = AnimeRecommender()
            rec.fit(anime_df, ratings_df)
            rec.save()
            return rec, anime_df

        state.recommender, state.anime_df = await loop.run_in_executor(None, _load_and_train)
    finally:
        state.is_training = False


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {
        "status":      "ok",
        "model_ready": state.recommender is not None,
        "catalogue":   len(state.anime_df) if state.anime_df is not None else 0,
        "is_training": state.is_training,
    }


@app.post("/recommend")
def recommend(body: RecommendRequest):
    """Get personalised anime recommendations."""
    if state.recommender is None:
        raise HTTPException(503, "Model not ready — training in progress")

    results = state.recommender.recommend(
        liked_anime_ids = body.liked_anime_ids,
        genres          = body.genres,
        mood            = body.mood,
        exclude_ids     = body.exclude_ids,
        top_n           = body.top_n,
    )
    return {"results": results, "count": len(results)}


@app.get("/anime/{anime_id}/similar")
def get_similar(anime_id: int, top_n: int = Query(10, ge=1, le=50)):
    """Return content-similar anime."""
    if state.recommender is None:
        raise HTTPException(503, "Model not ready")
    results = state.recommender.get_similar(anime_id, top_n=top_n)
    if not results:
        raise HTTPException(404, f"Anime {anime_id} not in catalogue")
    return {"results": results}


@app.get("/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(20, ge=1, le=100)):
    """Search anime by title in the local catalogue."""
    if state.anime_df is None:
        raise HTTPException(503, "Data not loaded")
    q_lower = q.lower()
    matches = state.anime_df[
        state.anime_df["title"].str.lower().str.contains(q_lower, na=False)
    ].head(limit)
    results = [
        {
            "id":       int(row["id"]),
            "title":    row["title"],
            "score":    round(float(row["score"]), 1),
            "genres":   (row["genres"] or "").split("|"),
            "episodes": int(row.get("episodes") or 0),
            "year":     row.get("year"),
        }
        for _, row in matches.iterrows()
    ]
    return {"results": results, "count": len(results)}


@app.get("/trending")
def trending(limit: int = Query(50, ge=1, le=200)):
    """Return top anime by score from local catalogue."""
    if state.anime_df is None:
        raise HTTPException(503, "Data not loaded")
    top = state.anime_df.nlargest(limit, "score")
    results = [
        {
            "id":       int(row["id"]),
            "title":    row["title"],
            "score":    round(float(row["score"]), 1),
            "genres":   (row["genres"] or "").split("|"),
            "episodes": int(row.get("episodes") or 0),
            "year":     row.get("year"),
        }
        for _, row in top.iterrows()
    ]
    return {"results": results, "count": len(results)}


@app.post("/train")
async def retrain(background_tasks: BackgroundTasks):
    """Re-train the model from the CSV files."""
    if state.is_training:
        return {"message": "Already training"}
    background_tasks.add_task(_train_model)
    return {"message": "Training started in background"}
