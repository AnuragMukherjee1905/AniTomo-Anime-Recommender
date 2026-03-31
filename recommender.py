"""
recommender.py  (v2 — no scikit-surprise, uses implicit ALS instead)
─────────────────────────────────────────────
Hybrid anime recommendation engine.

Pipeline
--------
1. Content-based  → TF-IDF on synopsis + multi-hot genre vectors → cosine similarity
2. Collaborative  → ALS (Alternating Least Squares) via the `implicit` library
3. Hybrid blend   → weighted average: α × content + (1-α) × collaborative
4. Re-ranking     → boost by mood filter

Install
-------
    py -3.11 -m pip install implicit
"""

import numpy as np
import pandas as pd
import scipy.sparse as sp
import pickle
from pathlib import Path
from typing import Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MultiLabelBinarizer, MinMaxScaler
import implicit

MODEL_PATH = Path("model.pkl")

# ── Mood → Genre mapping ──────────────────────────────────────────────────────

MOOD_GENRE_MAP = {
    "Epic":      ["Action", "Adventure", "Fantasy", "Mecha"],
    "Cozy":      ["Slice of Life", "Comedy", "School"],
    "Dark":      ["Psychological", "Horror", "Thriller", "Drama"],
    "Heartfelt": ["Romance", "Drama", "Slice of Life"],
    "Hyped":     ["Action", "Sports", "Shounen"],
    "Chill":     ["Slice of Life", "Music", "Comedy"],
}


# ── AnimeRecommender ──────────────────────────────────────────────────────────

class AnimeRecommender:
    """
    Hybrid recommender using TF-IDF content model + ALS collaborative model.

    Parameters
    ----------
    content_weight : float
        α in the blend. 1.0 = pure content, 0.0 = pure collaborative.
    min_votes : int
        Minimum MAL votes to appear in results (filters obscure entries).
    """

    def __init__(self, content_weight: float = 0.5, min_votes: int = 500):
        self.content_weight = content_weight
        self.min_votes      = min_votes

        self.anime_df       = None
        self.cosine_sim     = None
        self.als_model      = None
        self.user_factors   = None
        self.item_factors   = None
        self.anime_index    = {}    # anime_id → row index
        self.user_index     = {}    # username → row index

        self._tfidf  = TfidfVectorizer(max_features=5000, stop_words="english")
        self._mlb    = MultiLabelBinarizer()
        self._scaler = MinMaxScaler()

    # ── Fit ───────────────────────────────────────────────────────────────────

    def fit(self, anime_df: pd.DataFrame, ratings_df: Optional[pd.DataFrame] = None):
        """
        Train both models.

        Parameters
        ----------
        anime_df   : columns — id, title, synopsis, genres (pipe-separated), score, num_votes
        ratings_df : columns — user_id, anime_id, score  (optional)
        """
        print("Fitting recommender …")
        self.anime_df  = anime_df.copy().reset_index(drop=True)
        self.anime_index = {int(row["id"]): idx for idx, row in self.anime_df.iterrows()}

        self._fit_content_model()

        if ratings_df is not None and not ratings_df.empty:
            self._fit_collaborative_model(ratings_df)
            n = len(ratings_df)
            self.content_weight = 0.3 if n > 5000 else 0.4 if n > 1000 else 0.6
            print(f"  Content weight → {self.content_weight} (based on {n} ratings)")
        else:
            self.content_weight = 1.0
            print("  No ratings — pure content-based mode")

        print("  Recommender ready.")
        return self

    def _fit_content_model(self):
        print("  Building content model …")
        df = self.anime_df

        synopses = df["synopsis"].fillna("").astype(str)
        tfidf_mat = self._tfidf.fit_transform(synopses)

        # Parse genres — stored as pipe-separated string in CSV
        genres = df["genres"].fillna("").apply(
            lambda g: g.split("|") if isinstance(g, str) and g else []
        )
        genre_mat = self._mlb.fit_transform(genres)

        scores = self._scaler.fit_transform(
            df["score"].fillna(0).values.reshape(-1, 1)
        )

        self.content_matrix = sp.hstack([
            tfidf_mat,
            sp.csr_matrix(genre_mat),
            sp.csr_matrix(scores),
        ])
        self.cosine_sim = cosine_similarity(self.content_matrix, self.content_matrix)
        print(f"  Content matrix shape: {self.content_matrix.shape}")

    def _fit_collaborative_model(self, ratings_df: pd.DataFrame):
        """Train ALS on the user–anime interaction matrix."""
        print("  Training ALS collaborative model …")

        # Build user and item index maps
        users  = ratings_df["user_id"].unique().tolist()
        items  = ratings_df["anime_id"].unique().tolist()
        self.user_index = {u: i for i, u in enumerate(users)}
        item_index      = {a: i for i, a in enumerate(items)}

        # Build sparse user–item matrix (users × anime)
        rows = ratings_df["user_id"].map(self.user_index)
        cols = ratings_df["anime_id"].map(item_index)
        vals = ratings_df["score"].astype(float)

        n_users = len(users)
        n_items = len(items)
        user_item = sp.csr_matrix((vals, (rows, cols)), shape=(n_users, n_items))

        # ALS model — easy to install, no C++ compiler needed
        self.als_model = implicit.als.AlternatingLeastSquares(
            factors=64, iterations=20, regularization=0.1, use_gpu=False
        )
        self.als_model.fit(user_item.T)   # ALS expects item–user matrix

        # Store item factors aligned to our anime_df order
        # Map each anime in our catalogue to its ALS factor (or zeros if unseen)
        n_catalogue = len(self.anime_df)
        factor_dim  = self.als_model.item_factors.shape[1]
        self.item_factors = np.zeros((n_catalogue, factor_dim))

        for anime_id, als_idx in item_index.items():
            cat_idx = self.anime_index.get(int(anime_id))
            if cat_idx is not None:
                self.item_factors[cat_idx] = self.als_model.item_factors[als_idx]

        print(f"  ALS trained on {n_users} users × {n_items} anime.")

    # ── Recommend ─────────────────────────────────────────────────────────────

    def recommend(
        self,
        liked_anime_ids: list[int] = None,
        genres:          list[str] = None,
        mood:            str       = None,
        exclude_ids:     list[int] = None,
        top_n:           int       = 20,
    ) -> list[dict]:
        """
        Generate recommendations.

        Parameters
        ----------
        liked_anime_ids : anime IDs the user rated highly
        genres          : genre filters from the frontend
        mood            : mood key (Epic, Cozy, Dark, etc.)
        exclude_ids     : anime IDs to hide (already watched)
        top_n           : number of results
        """
        df          = self.anime_df.copy()
        exclude_ids = set(exclude_ids or [])

        # Content scores
        content_scores = self._get_content_scores(liked_anime_ids or [])

        # Collaborative scores
        if self.item_factors is not None and self.content_weight < 1.0:
            collab_scores = self._get_collab_scores(liked_anime_ids or [])
        else:
            collab_scores = np.zeros(len(df))

        # Blend
        α = self.content_weight
        df["_match"] = α * content_scores + (1 - α) * collab_scores

        # Filter minimum votes
        df = df[df["num_votes"].astype(float) >= self.min_votes]

        # Filter by genre pills
        if genres:
            df = df[df["genres"].apply(
                lambda g: any(genre in (g or "") for genre in genres)
            )]

        # Mood boost
        if mood and mood in MOOD_GENRE_MAP:
            mood_genres = set(MOOD_GENRE_MAP[mood])
            boost = df["genres"].apply(
                lambda g: bool(set((g or "").split("|")) & mood_genres)
            )
            df.loc[boost, "_match"] *= 1.25

        # Exclude seen
        if exclude_ids:
            df = df[~df["id"].astype(int).isin(exclude_ids)]

        top = df.nlargest(top_n, "_match")

        return [
            {
                "id":          int(row["id"]),
                "title":       row["title"],
                "score":       round(float(row["score"]), 1),
                "genres":      (row["genres"] or "").split("|"),
                "synopsis":    (row["synopsis"] or "")[:200] + "…",
                "episodes":    int(row.get("episodes") or 0),
                "year":        row.get("year"),
                "match_score": round(float(row["_match"]), 4),
            }
            for _, row in top.iterrows()
        ]

    def _get_content_scores(self, liked_ids: list[int]) -> np.ndarray:
        n = len(self.anime_df)
        if not liked_ids:
            scores = self.anime_df["score"].fillna(0).astype(float).values
            mn, mx = scores.min(), scores.max()
            return (scores - mn) / (mx - mn + 1e-9)

        rows = [self.cosine_sim[self.anime_index[aid]]
                for aid in liked_ids if aid in self.anime_index]
        if not rows:
            return np.zeros(n)
        avg = np.mean(rows, axis=0)
        mn, mx = avg.min(), avg.max()
        return (avg - mn) / (mx - mn + 1e-9)

    def _get_collab_scores(self, liked_ids: list[int]) -> np.ndarray:
        """
        Average item factors of liked anime as a pseudo user-vector,
        then score all catalogue items by dot product similarity.
        """
        rows = [self.item_factors[self.anime_index[aid]]
                for aid in liked_ids if aid in self.anime_index]
        if not rows:
            return np.zeros(len(self.anime_df))
        user_vec = np.mean(rows, axis=0)
        scores   = self.item_factors @ user_vec
        mn, mx   = scores.min(), scores.max()
        return (scores - mn) / (mx - mn + 1e-9)

    # ── Similar anime ─────────────────────────────────────────────────────────

    def get_similar(self, anime_id: int, top_n: int = 10) -> list[dict]:
        idx = self.anime_index.get(anime_id)
        if idx is None:
            return []
        sim = sorted(enumerate(self.cosine_sim[idx]), key=lambda x: x[1], reverse=True)
        results = []
        for i, score in sim[1:top_n+1]:
            row = self.anime_df.iloc[i]
            results.append({
                "id":         int(row["id"]),
                "title":      row["title"],
                "score":      round(float(row["score"]), 1),
                "genres":     (row["genres"] or "").split("|"),
                "similarity": round(float(score), 4),
            })
        return results

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: Path = MODEL_PATH):
        with open(path, "wb") as f:
            pickle.dump(self, f)
        print(f"Model saved → {path}")

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> "AnimeRecommender":
        with open(path, "rb") as f:
            return pickle.load(f)
