#!/usr/bin/env python3
"""
Multi-Account Bluesky Movie Poster Bot
- Fetches trending/hidden gem movies from TMDB
- Generates organic fan-style posts via NVIDIA NIM (DeepSeek)
- Posts with movie poster image to multiple Bluesky accounts
"""

import os
import sys
import random
import requests
import json
import time
from datetime import datetime, timezone
from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────
TMDB_API_KEY   = os.environ["TMDB_API_KEY"]
NVIDIA_API_KEY = os.environ["NVIDIA_API_KEY"]
TMDB_BASE      = "https://api.themoviedb.org/3"
TMDB_IMAGE     = "https://image.tmdb.org/t/p/w500"
BSKY_API       = "https://bsky.social/xrpc"

# Load all Bluesky accounts from env  (BSKY_HANDLE_1 / BSKY_PASSWORD_1 … up to 5)
def load_accounts() -> list[dict]:
    accounts = []
    for i in range(1, 6):
        handle   = os.environ.get(f"BSKY_HANDLE_{i}")
        password = os.environ.get(f"BSKY_PASSWORD_{i}")
        if handle and password:
            accounts.append({"handle": handle, "password": password})
    if not accounts:
        sys.exit("No Bluesky accounts configured. Set BSKY_HANDLE_1 / BSKY_PASSWORD_1 etc.")
    return accounts


# ── TMDB helpers ───────────────────────────────────────────────────────────────
TMDB_SOURCES = [
    ("trending/movie/week",          {"language": "en-US"}),
    ("movie/top_rated",              {"language": "en-US", "page": random.randint(1, 5)}),
    ("discover/movie",               {
        "language": "en-US",
        "sort_by": "vote_average.desc",
        "vote_count.gte": 500,
        "vote_average.gte": 7.5,
        "page": random.randint(1, 10),
    }),
    ("movie/now_playing",            {"language": "en-US"}),
    ("discover/movie",               {
        "language": "en-US",
        "sort_by": "popularity.desc",
        "with_genres": "27",          # Horror – often underrated gems
        "page": random.randint(1, 5),
    }),
]

def fetch_movies() -> list[dict]:
    endpoint, params = random.choice(TMDB_SOURCES)
    params["api_key"] = TMDB_API_KEY
    r = requests.get(f"{TMDB_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    results = r.json().get("results", [])
    # Keep only movies that have a poster
    results = [m for m in results if m.get("poster_path")]
    return results


def fetch_movie_details(movie_id: int) -> dict:
    r = requests.get(
        f"{TMDB_BASE}/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "append_to_response": "credits,keywords"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ── NVIDIA NIM / DeepSeek post generator ──────────────────────────────────────
NIM_CLIENT = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)

SYSTEM_PROMPT = """You are a passionate American movie fan who writes short, organic Bluesky posts about films.
Rules you MUST follow every single time:
- Tone: natural, conversational American — like a real film enthusiast, NOT a critic
- Focus angle (pick one per post, vary it): trending movies, hidden gems, plot twists, shocking endings, underrated series
- Make readers curious enough to visit mycinebd.com
- Add 2-4 relevant hashtags at the end (no emojis anywhere in the post)
- Final line must always be exactly: mycinebd.com
- No emojis at all
- Never say FREE DOWNLOAD, WATCH FREE, HD DOWNLOAD, or anything spammy
- Every post must feel unique — different opening, different angle, different phrasing
- Keep the post between 200 and 290 characters (Bluesky limit is 300)
- Do NOT add any explanation — output ONLY the post text"""

def generate_post(movie: dict) -> str:
    title       = movie.get("title", "Unknown")
    overview    = (movie.get("overview") or "")[:400]
    year        = (movie.get("release_date") or "")[:4]
    rating      = movie.get("vote_average", 0)
    genres      = ", ".join(g["name"] for g in movie.get("genres", [])[:3])
    keywords_raw = movie.get("keywords", {}).get("keywords", [])
    keywords    = ", ".join(k["name"] for k in keywords_raw[:5])

    user_prompt = (
        f"Movie: {title} ({year})\n"
        f"Genres: {genres}\n"
        f"Rating: {rating}/10\n"
        f"Keywords: {keywords}\n"
        f"Overview: {overview}\n\n"
        "Write a Bluesky post following all rules."
    )

    full_text = ""
    completion = NIM_CLIENT.chat.completions.create(
        model="deepseek-ai/deepseek-v4-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=1,
        top_p=0.95,
        max_tokens=512,
        extra_body={
            "chat_template_kwargs": {"thinking": True, "reasoning_effort": "high"}
        },
        stream=True,
    )

    for chunk in completion:
        if not getattr(chunk, "choices", None):
            continue
        delta   = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            full_text += content

    post = full_text.strip()
    # Safety: truncate if somehow over 300 chars (keep hashtags + CTA)
    if len(post) > 300:
        post = post[:297] + "..."
    return post


# ── Bluesky helpers ────────────────────────────────────────────────────────────
def bsky_login(handle: str, password: str) -> dict:
    r = requests.post(
        f"{BSKY_API}/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()   # contains accessJwt, did, etc.


def bsky_upload_blob(session: dict, image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    r = requests.post(
        f"{BSKY_API}/com.atproto.repo.uploadBlob",
        headers={
            "Authorization": f"Bearer {session['accessJwt']}",
            "Content-Type":  mime,
        },
        data=image_bytes,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["blob"]


def bsky_post(session: dict, text: str, blob: dict | None = None, alt_text: str = "") -> dict:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Build facets for the mycinebd.com link
    link_url  = "https://mycinebd.com"
    link_text = "mycinebd.com"
    byte_text = text.encode("utf-8")
    idx = byte_text.find(link_text.encode("utf-8"))

    facets = []
    if idx != -1:
        facets.append({
            "index": {"byteStart": idx, "byteEnd": idx + len(link_text.encode("utf-8"))},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link_url}],
        })

    record: dict = {
        "$type":     "app.bsky.feed.post",
        "text":      text,
        "createdAt": now,
    }
    if facets:
        record["facets"] = facets
    if blob:
        record["embed"] = {
            "$type": "app.bsky.embed.images",
            "images": [{"image": blob, "alt": alt_text}],
        }

    r = requests.post(
        f"{BSKY_API}/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo":       session["did"],
            "collection": "app.bsky.feed.post",
            "record":     record,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    accounts = load_accounts()
    movies   = fetch_movies()

    if not movies:
        sys.exit("No movies found from TMDB.")

    # Pick one random movie per account (no repeats within a run)
    random.shuffle(movies)
    selected = movies[: len(accounts)]

    for account, movie_stub in zip(accounts, selected):
        handle = account["handle"]
        print(f"\n{'─'*60}")
        print(f"Account : {handle}")

        # Fetch full details (genres, keywords, etc.)
        details = fetch_movie_details(movie_stub["id"])
        title   = details.get("title", "Unknown")
        print(f"Movie   : {title}")

        # Generate AI post
        print("Generating post via NVIDIA NIM…")
        post_text = generate_post(details)
        print(f"Post    :\n{post_text}\n")

        # Download poster
        poster_blob = None
        poster_path = details.get("poster_path")
        alt_text    = f"Movie poster for {title}"
        if poster_path:
            img_url = f"{TMDB_IMAGE}{poster_path}"
            print(f"Fetching poster: {img_url}")
            img_r = requests.get(img_url, timeout=20)
            if img_r.ok:
                # Login & upload
                session     = bsky_login(handle, account["password"])
                poster_blob = bsky_upload_blob(session, img_r.content, "image/jpeg")
                print("Poster uploaded.")
            else:
                print("Poster fetch failed — posting without image.")
                session = bsky_login(handle, account["password"])
        else:
            session = bsky_login(handle, account["password"])

        # Post!
        result = bsky_post(session, post_text, blob=poster_blob, alt_text=alt_text)
        print(f"Posted  : {result.get('uri', 'ok')}")

        # Be polite to the APIs
        time.sleep(3)

    print(f"\n{'─'*60}")
    print(f"Done. Posted to {len(accounts)} account(s).")


if __name__ == "__main__":
    main()
