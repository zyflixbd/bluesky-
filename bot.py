#!/usr/bin/env python3
"""
Multi-Account Bluesky Movie Poster Bot
- Fetches trending/hidden gem movies from TMDB
- Generates organic fan-style posts via NVIDIA NIM (DeepSeek)
- Posts with movie poster image to multiple Bluesky accounts
"""

import os
import re
import sys
import random
import requests
import time
from datetime import datetime, timezone
from openai import OpenAI

# ── Config ─────────────────────────────────────────────────────────────────────
TMDB_API_KEY   = os.environ.get("TMDB_API_KEY")
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")

if not TMDB_API_KEY:
    print("TMDB_API_KEY missing!"); exit(1)
if not NVIDIA_API_KEY:
    print("NVIDIA_API_KEY missing!"); exit(1)

TMDB_BASE  = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w500"
BSKY_API   = "https://bsky.social/xrpc"

# ── NVIDIA NIM client (same as working file) ───────────────────────────────────
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)

# ── Load Bluesky accounts ──────────────────────────────────────────────────────
def load_accounts():
    accounts = []
    for i in range(1, 6):
        handle   = os.environ.get(f"BSKY_HANDLE_{i}")
        password = os.environ.get(f"BSKY_PASSWORD_{i}")
        if handle and password:
            accounts.append({"id": i, "handle": handle, "password": password})
    if not accounts:
        print("No Bluesky accounts configured!"); exit(1)
    return accounts

# ── TMDB ───────────────────────────────────────────────────────────────────────
TMDB_SOURCES = [
    ("trending/movie/week",   {"language": "en-US"}),
    ("movie/top_rated",       {"language": "en-US", "page": random.randint(1, 5)}),
    ("movie/now_playing",     {"language": "en-US"}),
    ("discover/movie",        {
        "language": "en-US",
        "sort_by": "vote_average.desc",
        "vote_count.gte": 500,
        "vote_average.gte": 7.5,
        "page": random.randint(1, 8),
    }),
]

def fetch_movies():
    endpoint, params = random.choice(TMDB_SOURCES)
    params["api_key"] = TMDB_API_KEY
    r = requests.get(f"{TMDB_BASE}/{endpoint}", params=params, timeout=15)
    r.raise_for_status()
    results = r.json().get("results", [])
    return [m for m in results if m.get("poster_path")]

def fetch_movie_details(movie_id):
    r = requests.get(
        f"{TMDB_BASE}/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "append_to_response": "keywords"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

# ── AI Post Generator (exact same pattern as working file) ─────────────────────
SYSTEM_PROMPT = """You are a passionate American movie fan writing short Bluesky posts.

STRICT RULES:
1. Natural conversational American tone — like a real film fan, NOT a critic
2. Pick ONE angle: trending movie, hidden gem, plot twist, shocking ending, or underrated film
3. Make readers curious enough to visit mycinebd.com
4. Add 2-4 relevant hashtags at the end
5. Very last line must be exactly: mycinebd.com
6. Zero emojis anywhere
7. Never use: FREE DOWNLOAD, WATCH FREE, HD DOWNLOAD
8. Total post: 220 to 280 characters
9. Output ONLY the post text, nothing else"""

def generate_post(movie, variation=0):
    title    = movie.get("title", "Unknown")
    overview = (movie.get("overview") or "")[:300]
    year     = (movie.get("release_date") or "")[:4]
    rating   = movie.get("vote_average", 0)
    genres   = ", ".join(g["name"] for g in movie.get("genres", [])[:3])
    kw_raw   = movie.get("keywords", {}).get("keywords", [])
    keywords = ", ".join(k["name"] for k in kw_raw[:4])

    user_msg = (
        f"Movie: {title} ({year})\n"
        f"Genres: {genres}\n"
        f"Rating: {rating}/10\n"
        f"Keywords: {keywords}\n"
        f"Plot: {overview}\n\n"
        f"Variation #{variation + 1}: Write a completely unique Bluesky post."
    )

    # ── Exact same call pattern as the working post.py ──
    completion = nvidia_client.chat.completions.create(
        model="deepseek-ai/deepseek-v4-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.92,
        top_p=0.95,
        max_tokens=200,
    )
    text = completion.choices[0].message.content.strip()

    # Strip surrounding quotes if model wraps them
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    # Safety truncate
    if len(text) > 300:
        text = text[:297] + "..."

    return text

# ── Bluesky helpers ────────────────────────────────────────────────────────────
def build_facets(text):
    facets = []
    # Hashtags
    for match in re.finditer(r"#(\w+)", text):
        start = len(text[:match.start()].encode("utf-8"))
        end   = len(text[:match.end()].encode("utf-8"))
        facets.append({
            "index":    {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": match.group(1)}],
        })
    # URLs
    for match in re.finditer(r"https?://[^\s\)\]\}\"\']+", text):
        url   = match.group(0)
        start = len(text[:match.start()].encode("utf-8"))
        end   = len(text[:match.end()].encode("utf-8"))
        facets.append({
            "index":    {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        })
    # mycinebd.com plain text link
    link_text = "mycinebd.com"
    link_uri  = "https://mycinebd.com"
    idx = text.find(link_text)
    if idx != -1 and not any("mycinebd" in str(f) for f in facets):
        start = len(text[:idx].encode("utf-8"))
        end   = len(text[:idx + len(link_text)].encode("utf-8"))
        facets.append({
            "index":    {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link_uri}],
        })
    return facets

def bsky_login(handle, password):
    r = requests.post(
        f"{BSKY_API}/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def bsky_upload_blob(session, image_bytes, mime="image/jpeg"):
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

def bsky_post(session, text, blob=None, alt_text=""):
    facets = build_facets(text)
    record = {
        "$type":     "app.bsky.feed.post",
        "text":      text,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if facets:
        record["facets"] = facets
    if blob:
        record["embed"] = {
            "$type":  "app.bsky.embed.images",
            "images": [{"image": blob, "alt": alt_text}],
        }
    r = requests.post(
        f"{BSKY_API}/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["uri"]

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    accounts = load_accounts()
    movies   = fetch_movies()

    if not movies:
        print("No movies returned from TMDB."); exit(1)

    random.shuffle(movies)
    selected = movies[:len(accounts)]

    results = []

    for i, (account, movie_stub) in enumerate(zip(accounts, selected)):
        print(f"\n{'━'*40}")
        print(f"Account {account['id']}: {account['handle']}")

        try:
            details = fetch_movie_details(movie_stub["id"])
            title   = details.get("title", "Unknown")
            print(f"Movie   : {title}")

            print(f"Generating post (variation {i+1})...")
            post_text = generate_post(details, variation=i)
            print(f"Post ({len(post_text)} chars):\n{post_text}\n")

            print("Logging in...")
            session = bsky_login(account["handle"], account["password"])
            print("Login OK")

            poster_blob = None
            poster_path = details.get("poster_path")
            alt_text    = f"Movie poster for {title}"
            if poster_path:
                img_r = requests.get(f"{TMDB_IMAGE}{poster_path}", timeout=20)
                if img_r.ok:
                    poster_blob = bsky_upload_blob(session, img_r.content)
                    print("Poster uploaded.")

            uri = bsky_post(session, post_text, blob=poster_blob, alt_text=alt_text)
            print(f"Posted: {uri}")
            results.append({"account": account["handle"], "status": "success"})

        except Exception as e:
            print(f"Failed: {e}")
            results.append({"account": account["handle"], "status": "failed", "error": str(e)})

        if i < len(accounts) - 1:
            delay = random.randint(10, 20)
            print(f"Waiting {delay}s...")
            time.sleep(delay)

    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\n{'━'*40}")
    print(f"Done: {success} success | {failed} failed")

    if success == 0:
        exit(1)

if __name__ == "__main__":
    main()
