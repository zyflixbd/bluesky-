import os
import re
import io
import time
import random
import requests
import tempfile
from datetime import datetime, timezone
from openai import OpenAI

# ─── ACCOUNTS CONFIG ──────────────────────────────────────────────────────────
def load_accounts() -> list[dict]:
    accounts = []
    for i in range(1, 6):
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

# ─── TMDB: FETCH & SORT MOVIES ────────────────────────────────────────────────
def fetch_tmdb_movies() -> list[dict]:
    """
    Fetch trending movies (this week) from TMDB.
    Priority:
      1. 2026 releases with vote_average >= 5  (sorted by vote desc)
      2. Other years with vote_average >= 5     (sorted by vote desc)
      3. Rest                                   (sorted by vote desc)
    """
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
        poster_url   = f"https://image.tmdb.org/t/p/w780{poster_path}" if poster_path else None
        vote         = float(m.get("vote_average") or 0)
        movies.append({
            "title":      m["title"],
            "year":       release_year,
            "overview":   m["overview"][:300],
            "rating":     vote,
            "poster_url": poster_url,
        })

    def sort_key(mv):
        is_2026   = mv["year"] == "2026"
        good_vote = mv["rating"] >= 5
        return (is_2026 and good_vote, good_vote, mv["rating"])

    movies.sort(key=sort_key, reverse=True)
    return movies

# ─── DOWNLOAD TMDB POSTER → TEMP FILE ────────────────────────────────────────
def download_poster_to_file(poster_url: str) -> str | None:
    try:
        resp = requests.get(poster_url, timeout=20)
        resp.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp.write(resp.content)
        tmp.close()
        print(f"  ✅ Poster downloaded ({len(resp.content)//1024} KB)")
        return tmp.name
    except Exception as e:
        print(f"  ⚠️  Poster download failed: {e}")
        return None

# ─── NVIDIA NIM: GENERATE POST TEXT ──────────────────────────────────────────
def generate_post_text(angle_data: dict, movie: dict) -> str:
    prompt = angle_data["prompt_template"].format(
        title    = movie["title"],
        year     = movie["year"],
        overview = movie["overview"],
    )

    full_text = ""
    completion = nim_client.chat.completions.create(
        model="deepseek-ai/deepseek-v4-flash",
        messages=[{"role": "user", "content": prompt}],
        temperature=1,
        top_p=0.95,
        max_tokens=16384,
        extra_body={"chat_template_kwargs": {"thinking": True, "reasoning_effort": "high"}},
        stream=True,
    )

    for chunk in completion:
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        
        # Handle reasoning content if present
        reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
        if reasoning:
            full_text += reasoning
        
        # Handle regular content
        content = getattr(delta, "content", None)
        if content:
            full_text += content

    text = full_text.strip()
    text = re.sub(r'^[""]|[""]$', '', text).strip()

    if len(text) > 300:
        cutoff = text[:297].rsplit(" ", 1)[0]
        text   = cutoff + "..."

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
                "Content-Type":  "image/jpeg",
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
    print(f"🚀 Bluesky Movie Bot — Started!")
    print(f"👥 Accounts: {len(accounts)}")
    print()

    print("🎬 Fetching trending movies from TMDB...")
    try:
        movies = fetch_tmdb_movies()
        if not movies:
            print("❌ No movies fetched from TMDB!")
            exit(1)
        print(f"✅ Fetched {len(movies)} movies")
        print(f"🏆 Top pick: {movies[0]['title']} ({movies[0]['year']}) ⭐ {movies[0]['rating']:.1f}")
    except Exception as e:
        print(f"❌ TMDB fetch failed: {e}")
        exit(1)

    angles = random.sample(ANGLES, min(len(accounts), len(ANGLES)))
    while len(angles) < len(accounts):
        angles.append(random.choice(ANGLES))

    selected_movies = random.sample(movies, min(len(accounts), len(movies)))
    while len(selected_movies) < len(accounts):
        selected_movies.append(random.choice(movies))

    results = []

    for i, (account, angle_data, movie) in enumerate(zip(accounts, angles, selected_movies)):
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"👤 Account {account['id']}: {account['handle']}")
        print(f"🎬 Movie: {movie['title']} ({movie['year']}) ⭐ {movie['rating']:.1f}")
        print(f"📌 Angle: {angle_data['angle']}")

        try:
            print(f"  🔑 Logging in...")
            session = bsky_login(account["handle"], account["password"])
            print(f"  ✅ Login OK")

            print(f"  🤖 Generating post via NVIDIA NIM...")
            post_text = generate_post_text(angle_data, movie)
            print(f"  ✍️  {post_text[:120]}...")
            print(f"  📏 {len(post_text)} chars")

            image_path = None
            if movie["poster_url"]:
                print(f"  🖼️  Downloading TMDB poster...")
                image_path = download_poster_to_file(movie["poster_url"])
            else:
                print(f"  ⚠️  No poster URL — posting without image")

            print(f"  📤 Posting to Bluesky...")
            uri = bsky_post(session, post_text, image_path, movie_title=movie["title"])
            print(f"  ✅ Posted! {uri}")
            results.append({"account": account["handle"], "status": "success", "uri": uri, "movie": movie["title"]})

        except Exception as e:
            print(f"  ❌ Failed: {e}")
            results.append({"account": account["handle"], "status": "failed", "error": str(e)})

        if i < len(accounts) - 1:
            print(f"  ⏳ Waiting 10 seconds...")
            time.sleep(10)

    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 Summary: ✅ {success} success | ❌ {failed} failed")
    print("🎉 Done!")

    if success == 0:
        exit(1)


if __name__ == "__main__":
    main()

