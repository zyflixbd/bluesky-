#!/usr/bin/env python3
"""
Multi-Account Bluesky Movie Poster Bot
- TMDB থেকে movie info fetch করে
- Python দিয়েই post লেখে (কোনো AI API নেই)
- Duplicate avoid করে (GitHub Gist-এ posted IDs track করে)
- Multiple Bluesky account-এ movie poster সহ post করে
"""

import os
import re
import sys
import json
import random
import requests
import time
from datetime import datetime, timezone, timedelta

# ── Config ─────────────────────────────────────────────────────────────────────
TMDB_API_KEY  = os.environ.get("TMDB_API_KEY")
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN")   # built-in Actions token
GIST_ID       = os.environ.get("GIST_ID", "")    # optional: set once after first run

if not TMDB_API_KEY:
    print("TMDB_API_KEY missing!"); exit(1)

TMDB_BASE  = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/w500"
BSKY_API   = "https://bsky.social/xrpc"
GIST_FILE  = "posted_movies.json"

# Keep last 30 days worth of IDs (max 20/day × 30 = 600)
MAX_HISTORY = 600

# ── Gist: load & save posted IDs ──────────────────────────────────────────────
def gist_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def load_posted_ids() -> set:
    if not GITHUB_TOKEN or not GIST_ID:
        print("No GIST_ID set — duplicate tracking disabled for this run.")
        return set()
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}",
                         headers=gist_headers(), timeout=10)
        r.raise_for_status()
        content = r.json()["files"][GIST_FILE]["content"]
        data    = json.loads(content)
        return set(data.get("posted_ids", []))
    except Exception as e:
        print(f"Could not load posted IDs: {e}")
        return set()

def save_posted_ids(posted_ids: set):
    if not GITHUB_TOKEN or not GIST_ID:
        return
    # Trim to max history
    id_list = list(posted_ids)[-MAX_HISTORY:]
    payload = {"posted_ids": id_list}
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=gist_headers(),
            json={"files": {GIST_FILE: {"content": json.dumps(payload, indent=2)}}},
            timeout=10,
        )
        r.raise_for_status()
        print(f"Saved {len(id_list)} posted IDs to Gist.")
    except Exception as e:
        print(f"Could not save posted IDs: {e}")

def create_gist_if_needed():
    """Call once manually or on first run to create the tracking Gist."""
    if not GITHUB_TOKEN:
        return None
    r = requests.post(
        "https://api.github.com/gists",
        headers=gist_headers(),
        json={
            "description": "Bluesky Bot — Posted Movie IDs",
            "public": False,
            "files": {GIST_FILE: {"content": json.dumps({"posted_ids": []}, indent=2)}},
        },
        timeout=10,
    )
    r.raise_for_status()
    gist_id = r.json()["id"]
    print(f"Created Gist! Add this to your GitHub Secrets as GIST_ID: {gist_id}")
    return gist_id

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
    ("trending/movie/day",    {"language": "en-US"}),
    ("movie/top_rated",       {"language": "en-US", "page": random.randint(1, 8)}),
    ("movie/now_playing",     {"language": "en-US"}),
    ("movie/popular",         {"language": "en-US", "page": random.randint(1, 5)}),
    ("discover/movie",        {
        "language": "en-US",
        "sort_by": "vote_average.desc",
        "vote_count.gte": 500,
        "vote_average.gte": 7.5,
        "page": random.randint(1, 10),
    }),
    ("discover/movie",        {
        "language": "en-US",
        "sort_by": "popularity.desc",
        "vote_average.lte": 7.0,
        "vote_count.gte": 200,
        "page": random.randint(1, 5),
    }),
]

def fetch_movies(posted_ids: set, needed: int) -> list:
    """Fetch enough unseen movies for all accounts."""
    candidates = []
    sources = TMDB_SOURCES.copy()
    random.shuffle(sources)

    for endpoint, params in sources:
        if len(candidates) >= needed * 3:
            break
        p = dict(params)
        p["api_key"] = TMDB_API_KEY
        try:
            r = requests.get(f"{TMDB_BASE}/{endpoint}", params=p, timeout=15)
            r.raise_for_status()
            results = r.json().get("results", [])
            for m in results:
                if m.get("poster_path") and m["id"] not in posted_ids:
                    if not any(c["id"] == m["id"] for c in candidates):
                        candidates.append(m)
        except Exception as e:
            print(f"TMDB source error: {e}")

    random.shuffle(candidates)
    return candidates[:needed]

def fetch_movie_details(movie_id):
    r = requests.get(
        f"{TMDB_BASE}/movie/{movie_id}",
        params={"api_key": TMDB_API_KEY, "append_to_response": "keywords"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

# ── Post Templates ─────────────────────────────────────────────────────────────
TEMPLATES = [
    "Not enough people are talking about {title} ({year}). "
    "{overview_hook} "
    "Sitting at {rating}/10 and it deserves way more attention. "
    "{hashtags}\nmycinebd.com",

    "If you haven't seen {title} yet, stop what you're doing. "
    "{overview_hook} "
    "The kind of film that stays with you for days. "
    "{hashtags}\nmycinebd.com",

    "{title} ({year}) is one of those films that sneaks up on you. "
    "{overview_hook} "
    "Rated {rating}/10 — and honestly, that feels low. "
    "{hashtags}\nmycinebd.com",

    "Genuine recommendation: watch {title}. "
    "{overview_hook} "
    "A {genre} film that actually delivers on its premise. {rating}/10. "
    "{hashtags}\nmycinebd.com",

    "Slept on {title} ({year}) for too long. Finally watched it. "
    "{overview_hook} "
    "Do yourself a favor and check it out. "
    "{hashtags}\nmycinebd.com",

    "Just finished {title} and I'm still processing. "
    "{overview_hook} "
    "A {rating}/10 {genre} that earns every bit of that score. "
    "{hashtags}\nmycinebd.com",

    "Everyone's watching {title} right now and for good reason. "
    "{overview_hook} "
    "One of the better {genre} films in recent memory. "
    "{hashtags}\nmycinebd.com",

    "Can't stop thinking about {title} ({year}). "
    "{overview_hook} "
    "This {genre} film hit differently. {rating}/10. "
    "{hashtags}\nmycinebd.com",

    "{title} is exactly the kind of {genre} film that gets overlooked. "
    "{overview_hook} "
    "Give it a shot — {rating}/10 and worth every minute. "
    "{hashtags}\nmycinebd.com",

    "The ending of {title} alone is worth the watch. "
    "{overview_hook} "
    "Solid {rating}/10 {genre} that flies under the radar. "
    "{hashtags}\nmycinebd.com",

    "Been recommending {title} to everyone lately. "
    "{overview_hook} "
    "A {rating}/10 that more people need to see. "
    "{hashtags}\nmycinebd.com",

    "If {genre} is your thing, {title} ({year}) should be on your list. "
    "{overview_hook} "
    "Seriously underrated at {rating}/10. "
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
    "Science Fiction": ["#SciFi", "#ScienceFiction"],
    "Thriller":  ["#Thriller", "#ThrillerMovies"],
    "War":       ["#WarFilm", "#War"],
    "Western":   ["#Western", "#WesternFilm"],
}

GENERAL_HASHTAGS = ["#Movies", "#Film", "#Cinema", "#MustWatch",
                    "#Filmlovers", "#NowWatching", "#FilmBuff", "#MovieNight"]

def pick_hashtags(genres: list) -> str:
    tags = []
    for g in genres[:2]:
        if g in GENRE_HASHTAGS:
            tags.extend(GENRE_HASHTAGS[g])
    tags += random.sample(GENERAL_HASHTAGS, 2)
    seen = []
    for t in tags:
        if t not in seen:
            seen.append(t)
    return " ".join(seen[:4])

def make_overview_hook(overview: str) -> str:
    if not overview:
        return "This one is hard to describe without spoiling it."
    sentences = overview.split(". ")
    hook = sentences[0].strip()
    if not hook.endswith("."):
        hook += "."
    if len(hook) > 120:
        hook = hook[:117] + "..."
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

    # Rotate templates — each account + each time slot gets different style
    template = TEMPLATES[variation % len(TEMPLATES)]

    post = template.format(
        title=title, year=year, rating=rating,
        genre=genre, overview_hook=overview_hook, hashtags=hashtags,
    )

    if len(post) > 300:
        excess     = len(post) - 297
        short_hook = overview_hook[:max(20, len(overview_hook) - excess - 3)] + "..."
        post = template.format(
            title=title, year=year, rating=rating,
            genre=genre, overview_hook=short_hook, hashtags=hashtags,
        )
        if len(post) > 300:
            post = post[:297] + "..."

    return post

# ── Bluesky helpers ────────────────────────────────────────────────────────────
def build_facets(text):
    facets = []
    for match in re.finditer(r"#(\w+)", text):
        start = len(text[:match.start()].encode("utf-8"))
        end   = len(text[:match.end()].encode("utf-8"))
        facets.append({
            "index":    {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": match.group(1)}],
        })
    link_text = "mycinebd.com"
    idx = text.find(link_text)
    if idx != -1:
        start = len(text[:idx].encode("utf-8"))
        end   = len(text[:idx + len(link_text)].encode("utf-8"))
        facets.append({
            "index":    {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://mycinebd.com"}],
        })
    return facets

def bsky_login(handle, password):
    r = requests.post(f"{BSKY_API}/com.atproto.server.createSession",
                      json={"identifier": handle, "password": password}, timeout=15)
    r.raise_for_status()
    return r.json()

def bsky_upload_blob(session, image_bytes):
    r = requests.post(
        f"{BSKY_API}/com.atproto.repo.uploadBlob",
        headers={"Authorization": f"Bearer {session['accessJwt']}", "Content-Type": "image/jpeg"},
        data=image_bytes, timeout=30,
    )
    r.raise_for_status()
    return r.json()["blob"]

def bsky_post(session, text, blob=None, alt_text=""):
    facets = build_facets(text)
    record = {"$type": "app.bsky.feed.post", "text": text,
               "createdAt": datetime.now(timezone.utc).isoformat()}
    if facets:
        record["facets"] = facets
    if blob:
        record["embed"] = {"$type": "app.bsky.embed.images",
                           "images": [{"image": blob, "alt": alt_text}]}
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

    # Auto-create Gist on very first run if no GIST_ID set
    if GITHUB_TOKEN and not GIST_ID:
        create_gist_if_needed()
        print("Re-run after adding GIST_ID to secrets.")
        # Continue without duplicate tracking this first time
    
    posted_ids = load_posted_ids()
    print(f"Already posted: {len(posted_ids)} movies (tracking history)")

    movies = fetch_movies(posted_ids, needed=len(accounts))

    if not movies:
        print("No new unseen movies found from TMDB!"); exit(1)

    print(f"Found {len(movies)} new movies for {len(accounts)} accounts\n")

    # Time slot: use hour to vary template rotation across the 4 daily runs
    hour_slot = datetime.now(timezone.utc).hour // 6  # 0,1,2,3

    new_posted_ids = set()
    results = []

    for i, (account, movie_stub) in enumerate(zip(accounts, movies)):
        print(f"\n{'━'*45}")
        print(f"Account {account['id']}: {account['handle']}")

        try:
            details = fetch_movie_details(movie_stub["id"])
            title   = details.get("title", "Unknown")
            print(f"Movie   : {title} (ID: {movie_stub['id']})")

            # variation uses both account index + time slot to maximize template diversity
            variation = (i + hour_slot * len(accounts)) % len(TEMPLATES)
            post_text = generate_post(details, variation=variation)
            print(f"Post ({len(post_text)} chars):\n{post_text}\n")

            session = bsky_login(account["handle"], account["password"])
            print("Login OK")

            poster_blob = None
            if details.get("poster_path"):
                img_r = requests.get(f"{TMDB_IMAGE}{details['poster_path']}", timeout=20)
                if img_r.ok:
                    poster_blob = bsky_upload_blob(session, img_r.content)
                    print("Poster uploaded.")

            uri = bsky_post(session, post_text, blob=poster_blob,
                            alt_text=f"Movie poster for {title}")
            print(f"Posted : {uri}")

            new_posted_ids.add(movie_stub["id"])
            results.append({"account": account["handle"], "status": "success"})

        except Exception as e:
            print(f"Failed : {e}")
            results.append({"account": account["handle"], "status": "failed"})

        if i < len(accounts) - 1:
            delay = random.randint(10, 20)
            print(f"Waiting {delay}s...")
            time.sleep(delay)

    # Save updated IDs
    save_posted_ids(posted_ids | new_posted_ids)

    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\n{'━'*45}")
    print(f"Done: {success} success | {failed} failed")
    if success == 0:
        exit(1)

if __name__ == "__main__":
    main()
