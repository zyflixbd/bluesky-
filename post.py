import os
import re
import time
import json
import random
import requests
import tempfile
from datetime import datetime, timezone
from openai import OpenAI
from image_gen import generate_image_from_poster, generate_fallback_image

# ─── ACCOUNTS CONFIG ──────────────────────────────────────────────────────────
def load_accounts() -> list[dict]:
    accounts = []
    for i in range(1, 6):  # max 5 accounts
        handle   = os.environ.get(f"BSKY_HANDLE_{i}")
        password = os.environ.get(f"BSKY_PASSWORD_{i}")
        if handle and password:
            accounts.append({"id": i, "handle": handle, "password": password})
    if not accounts:
        print("❌ No accounts found! Set BSKY_HANDLE_1 and BSKY_PASSWORD_1.")
        exit(1)
    return accounts

# ─── API KEYS ─────────────────────────────────────────────────────────────────
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY")
if not NVIDIA_API_KEY:
    print("❌ NVIDIA_API_KEY missing!")
    exit(1)

TMDB_API_KEY = os.environ.get("TMDB_API_KEY")
if not TMDB_API_KEY:
    print("❌ TMDB_API_KEY missing!")
    exit(1)

# ─── NVIDIA NIM CLIENT ────────────────────────────────────────────────────────
nim_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY,
)

# ─── POST ANGLES ──────────────────────────────────────────────────────────────
ANGLES = [
    {
        "angle": "plot_twist",
        "prompt_template": """Write a Bluesky post (STRICTLY max 300 chars — count carefully) in English.
Movie: "{title}" ({year})
Brief: {overview}
Angle: Tease a shocking plot twist or unexpected turn WITHOUT spoiling it. Make fans desperately want to watch.
CTA must be exactly: mycinebd.com
Hashtags: 2-4 relevant movie hashtags at the end.
Tone: Authentic American movie fan — natural, excited, conversational. NOT an ad.
Rules: No emojis. No "FREE DOWNLOAD" or "HD DOWNLOAD". Sound organic.
Return ONLY the post text, nothing else."""
    },
    {
        "angle": "hidden_gem",
        "prompt_template": """Write a Bluesky post (STRICTLY max 300 chars — count carefully) in English.
Movie: "{title}" ({year})
Brief: {overview}
Angle: Position this as an underrated hidden gem most people slept on. Create FOMO.
CTA must be exactly: mycinebd.com
Hashtags: 2-4 relevant movie hashtags at the end.
Tone: Real movie enthusiast sharing a discovery — passionate but natural. NOT an ad.
Rules: No emojis. No "FREE DOWNLOAD" or "HD DOWNLOAD". Sound organic.
Return ONLY the post text, nothing else."""
    },
    {
        "angle": "shocking_ending",
        "prompt_template": """Write a Bluesky post (STRICTLY max 300 chars — count carefully) in English.
Movie: "{title}" ({year})
Brief: {overview}
Angle: The ending changes everything — tease that without spoiling it. Make readers feel like they MUST see it.
CTA must be exactly: mycinebd.com
Hashtags: 2-4 relevant movie hashtags at the end.
Tone: Like a friend texting after watching — raw, genuine, a little obsessed. NOT an ad.
Rules: No emojis. No "FREE DOWNLOAD" or "HD DOWNLOAD". Sound organic.
Return ONLY the post text, nothing else."""
    },
    {
        "angle": "hot_take",
        "prompt_template": """Write a Bluesky post (STRICTLY max 300 chars — count carefully) in English.
Movie: "{title}" ({year})
Brief: {overview}
Angle: A bold, slightly controversial hot take about this film — provocative but not mean-spirited. Sparks debate.
CTA must be exactly: mycinebd.com
Hashtags: 2-4 relevant movie hashtags at the end.
Tone: Opinionated American movie fan — confident, direct, real. NOT an ad.
Rules: No emojis. No "FREE DOWNLOAD" or "HD DOWNLOAD". Sound organic.
Return ONLY the post text, nothing else."""
    },
    {
        "angle": "must_watch",
        "prompt_template": """Write a Bluesky post (STRICTLY max 300 chars — count carefully) in English.
Movie: "{title}" ({year})
Brief: {overview}
Angle: Build massive curiosity and FOMO — this movie is doing something most films never dare to do. Readers must find out what.
CTA must be exactly: mycinebd.com
Hashtags: 2-4 relevant movie hashtags at the end.
Tone: Excited but grounded — sounds like a real person recommending to friends. NOT an ad.
Rules: No emojis. No "FREE DOWNLOAD" or "HD DOWNLOAD". Sound organic.
Return ONLY the post text, nothing else."""
    },
]

# ─── TMDB: FETCH TRENDING MOVIES ─────────────────────────────────────────────
def fetch_tmdb_movies() -> list[dict]:
    """Fetch trending movies from TMDB this week."""
    url = "https://api.themoviedb.org/3/trending/movie/week"
    r = requests.get(
        url,
        params={"api_key": TMDB_API_KEY, "language": "en-US"},
        timeout=15,
    )
    r.raise_for_status()
    results = r.json().get("results", [])

    movies = []
    for m in results:
        if not m.get("title") or not m.get("overview"):
            continue
        release_year = (m.get("release_date") or "")[:4] or "N/A"
        poster_path  = m.get("poster_path")
        poster_url   = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        movies.append({
            "title":      m["title"],
            "year":       release_year,
            "overview":   m["overview"][:300],
            "rating":     m.get("vote_average", 0),
            "poster_url": poster_url,
        })
    return movies

# ─── NVIDIA NIM: GENERATE POST TEXT ──────────────────────────────────────────
def generate_post_text(angle_data: dict, movie: dict) -> str:
    prompt = angle_data["prompt_template"].format(
        title    = movie["title"],
        year     = movie["year"],
        overview = movie["overview"],
    )

    full_text = ""
    completion = nim_client.chat.completions.create(
        model="deepseek-ai/deepseek-r1-distill-llama-70b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        top_p=0.95,
        max_tokens=400,
        stream=True,
    )

    for chunk in completion:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        # Skip reasoning/thinking tokens — only keep final content
        content = getattr(delta, "content", None)
        if content:
            full_text += content

    text = full_text.strip()

    # Strip markdown quotes if model wraps in them
    text = re.sub(r'^[""]|[""]$', '', text).strip()

    # Hard cap at 300 chars
    if len(text) > 300:
        # Try to cut at a word boundary
        cutoff = text[:297].rsplit(" ", 1)[0]
        text = cutoff + "..."

    return text


# ─── BLUESKY: LOGIN ───────────────────────────────────────────────────────────
def bsky_login(handle: str, password: str) -> dict:
    r = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": handle, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ─── BLUESKY: IMAGE UPLOAD ────────────────────────────────────────────────────
def bsky_upload_image(session: dict, image_path: str) -> dict | None:
    try:
        with open(image_path, "rb") as f:
            img_data = f.read()
        r = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
            headers={
                "Authorization": f"Bearer {session['accessJwt']}",
                "Content-Type": "image/jpeg",
            },
            data=img_data,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["blob"]
    except Exception as e:
        print(f"  ⚠️  Image upload error: {e}")
        return None
    finally:
        try:
            os.unlink(image_path)
        except:
            pass


# ─── BLUESKY: POST ────────────────────────────────────────────────────────────
def bsky_post(session: dict, text: str, image_path: str | None = None, movie_title: str = "") -> str:
    # Build hashtag facets
    facets = []
    for match in re.finditer(r"#(\w+)", text):
        tag   = match.group(1)
        start = len(text[:match.start()].encode("utf-8"))
        end   = len(text[:match.end()].encode("utf-8"))
        facets.append({
            "index":    {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}],
        })

    record = {
        "$type":     "app.bsky.feed.post",
        "text":      text,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if facets:
        record["facets"] = facets

    if image_path:
        blob = bsky_upload_image(session, image_path)
        if blob:
            alt_text = f"Movie poster — {movie_title}" if movie_title else "Movie poster"
            record["embed"] = {
                "$type":  "app.bsky.embed.images",
                "images": [{"image": blob, "alt": alt_text}],
            }

    r = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["uri"]


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    accounts = load_accounts()
    print(f"🚀 Bluesky Movie Poster — Started!")
    print(f"👥 Accounts: {len(accounts)}")
    print()

    # Fetch trending movies from TMDB
    print("🎬 Fetching trending movies from TMDB...")
    try:
        movies = fetch_tmdb_movies()
        if not movies:
            print("❌ No movies fetched from TMDB!")
            exit(1)
        print(f"✅ Fetched {len(movies)} trending movies")
    except Exception as e:
        print(f"❌ TMDB fetch failed: {e}")
        exit(1)

    # Assign unique angle + movie to each account
    angles     = random.sample(ANGLES, min(len(accounts), len(ANGLES)))
    while len(angles) < len(accounts):
        angles.append(random.choice(ANGLES))

    selected_movies = random.sample(movies, min(len(accounts), len(movies)))
    while len(selected_movies) < len(accounts):
        selected_movies.append(random.choice(movies))

    results = []

    for i, (account, angle_data, movie) in enumerate(zip(accounts, angles, selected_movies)):
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"👤 Account {account['id']}: {account['handle']}")
        print(f"🎬 Movie: {movie['title']} ({movie['year']})")
        print(f"📌 Angle: {angle_data['angle']}")

        try:
            # 1. Login
            print(f"  🔑 Logging in...")
            session = bsky_login(account["handle"], account["password"])
            print(f"  ✅ Login successful!")

            # 2. Generate post text via NVIDIA NIM
            print(f"  🤖 Generating post text via NVIDIA NIM...")
            post_text = generate_post_text(angle_data, movie)
            print(f"  ✍️  {post_text[:100]}...")
            print(f"  📏 {len(post_text)} chars")

            # 3. Get movie poster image from TMDB
            print(f"  🖼️  Preparing movie poster image...")
            if movie["poster_url"]:
                image_path = generate_image_from_poster(
                    poster_url  = movie["poster_url"],
                    movie_title = movie["title"],
                    year        = movie["year"],
                    site_label  = "mycinebd.com",
                )
            else:
                image_path = generate_fallback_image(
                    movie_title = movie["title"],
                    year        = movie["year"],
                    site_label  = "mycinebd.com",
                )
            print(f"  ✅ Image ready!")

            # 4. Post to Bluesky
            print(f"  📤 Posting...")
            uri = bsky_post(session, post_text, image_path, movie_title=movie["title"])
            print(f"  ✅ Posted! {uri}")
            results.append({"account": account["handle"], "status": "success", "uri": uri, "movie": movie["title"]})

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            results.append({"account": account["handle"], "status": "failed", "error": str(e)})

        if i < len(accounts) - 1:
            print(f"  ⏳ Waiting 10 seconds...")
            time.sleep(10)

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 Summary: ✅ {success} success | ❌ {failed} failed")
    print("🎉 Done!")

    if success == 0:
        exit(1)


if __name__ == "__main__":
    main()
