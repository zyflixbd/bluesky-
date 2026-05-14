#!/usr/bin/env python3
"""
Multi-Account Bluesky Movie Poster Bot
- TMDB থেকে movie info fetch করে
- Python দিয়েই post লেখে (কোনো AI API নেই)
- Multiple Bluesky account-এ movie poster সহ post করে
"""

import os
import re
import sys
import random
import requests
import time
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────────────────────────
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
if not TMDB_API_KEY:
    print("TMDB_API_KEY missing!"); exit(1)

TMDB_BASE  = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w500"
BSKY_API   = "https://bsky.social/xrpc"

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
    ("discover/movie",        {
        "language": "en-US",
        "sort_by": "popularity.desc",
        "vote_average.lte": 7.0,
        "vote_count.gte": 200,
        "page": random.randint(1, 5),
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

# ── Post Templates ─────────────────────────────────────────────────────────────
# প্রতিটা template-এ {title}, {year}, {rating}, {genre}, {overview_hook} use হবে

TEMPLATES = [
    # Hidden gem angle
    "Not enough people are talking about {title} ({year}). "
    "{overview_hook} "
    "Sitting at {rating}/10 and it deserves way more attention. "
    "{hashtags}\nmycinebd.com",

    # Plot twist angle
    "If you haven't seen {title} yet, stop what you're doing. "
    "{overview_hook} "
    "The kind of film that stays with you for days. "
    "{hashtags}\nmycinebd.com",

    # Curious angle
    "{title} ({year}) is one of those films that sneaks up on you. "
    "{overview_hook} "
    "Rated {rating}/10 — and honestly, that feels low. "
    "{hashtags}\nmycinebd.com",

    # Recommendation angle
    "Genuine recommendation: watch {title}. "
    "{overview_hook} "
    "A {genre} film that actually delivers on its premise. {rating}/10. "
    "{hashtags}\nmycinebd.com",

    # Underrated angle
    "Slept on {title} ({year}) for too long. Finally watched it. "
    "{overview_hook} "
    "Do yourself a favor and check it out. "
    "{hashtags}\nmycinebd.com",

    # Shocking ending angle
    "Just finished {title} and I'm still processing. "
    "{overview_hook} "
    "A {rating}/10 {genre} that earns every bit of that score. "
    "{hashtags}\nmycinebd.com",

    # Trending angle
    "Everyone's watching {title} right now and for good reason. "
    "{overview_hook} "
    "One of the better {genre} films in recent memory. "
    "{hashtags}\nmycinebd.com",

    # Question hook angle
    "What happens when {overview_hook} "
    "{title} ({year}) answers that question better than most. "
    "Solid {rating}/10. "
    "{hashtags}\nmycinebd.com",
]

GENRE_HASHTAGS = {
    "Action":    ["#Action", "#ActionMovies"],
    "Adventure": ["#Adventure", "#MustWatch"],
    "Animation": ["#Animation", "#AnimatedFilm"],
    "Comedy":    ["#Comedy", "#ComedyMovies"],
    "Crime":     ["#Crime", "#CrimeThriller"],
    "Drama":     ["#Drama", "#FilmDrama"],
    "Fantasy":   ["#Fantasy", "#FantasyFilm"],
    "Horror":    ["#Horror", "#HorrorMovies"],
    "Mystery":   ["#Mystery", "#MysteryFilm"],
    "Romance":   ["#Romance", "#RomanceFilm"],
    "Sci-Fi":    ["#SciFi", "#ScienceFiction"],
    "Thriller":  ["#Thriller", "#ThrillerMovies"],
    "War":       ["#WarFilm", "#War"],
    "Western":   ["#Western", "#WesternFilm"],
}

GENERAL_HASHTAGS = ["#Movies", "#Film", "#Cinema", "#FilmTwitter", "#MovieRecommendation",
                    "#MustWatch", "#Filmlovers", "#NowWatching", "#FilmBuff"]

def pick_hashtags(genres: list) -> str:
    tags = []
    for g in genres[:2]:
        if g in GENRE_HASHTAGS:
            tags.extend(GENRE_HASHTAGS[g])
    # Add 1-2 general tags
    tags += random.sample(GENERAL_HASHTAGS, 2)
    # Dedupe, limit to 4
    seen = []
    for t in tags:
        if t not in seen:
            seen.append(t)
    return " ".join(seen[:4])

def make_overview_hook(overview: str) -> str:
    """Turn TMDB overview into a punchy short hook."""
    if not overview:
        return "This one is hard to describe without spoiling it."
    # Take first sentence or first 120 chars
    sentences = overview.split(". ")
    hook = sentences[0].strip()
    if not hook.endswith("."):
        hook += "."
    if len(hook) > 130:
        hook = hook[:127] + "..."
    return hook

def generate_post(movie: dict, variation: int = 0) -> str:
    title    = movie.get("title", "Unknown")
    year     = (movie.get("release_date") or "")[:4]
    rating   = round(movie.get("vote_average", 0), 1)
    genres   = [g["name"] for g in movie.get("genres", [])[:3]]
    genre    = genres[0] if genres else "Film"
    overview = movie.get("overview") or ""

    overview_hook = make_overview_hook(overview)
    hashtags      = pick_hashtags(genres)

    # Pick template based on variation so each account gets different style
    template = TEMPLATES[variation % len(TEMPLATES)]

    post = template.format(
        title=title,
        year=year,
        rating=rating,
        genre=genre,
        overview_hook=overview_hook,
        hashtags=hashtags,
    )

    # Truncate if over 300 chars (keep CTA)
    if len(post) > 300:
        # Trim overview_hook to fit
        excess = len(post) - 297
        short_hook = overview_hook[:max(20, len(overview_hook) - excess - 3)] + "..."
        post = template.format(
            title=title,
            year=year,
            rating=rating,
            genre=genre,
            overview_hook=short_hook,
            hashtags=hashtags,
        )
        if len(post) > 300:
            post = post[:297] + "..."

    return post

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
    # mycinebd.com as clickable link
    link_text = "mycinebd.com"
    link_uri  = "https://mycinebd.com"
    idx = text.find(link_text)
    if idx != -1:
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
        print(f"\n{'━'*45}")
        print(f"Account {account['id']}: {account['handle']}")

        try:
            details = fetch_movie_details(movie_stub["id"])
            title   = details.get("title", "Unknown")
            print(f"Movie   : {title}")

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
            print(f"Posted : {uri}")
            results.append({"account": account["handle"], "status": "success"})

        except Exception as e:
            print(f"Failed : {e}")
            results.append({"account": account["handle"], "status": "failed", "error": str(e)})

        if i < len(accounts) - 1:
            delay = random.randint(10, 20)
            print(f"Waiting {delay}s...")
            time.sleep(delay)

    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\n{'━'*45}")
    print(f"Done: {success} success | {failed} failed")
    if success == 0:
        exit(1)

if __name__ == "__main__":
    main()
