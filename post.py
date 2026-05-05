import os
import re
import time
import json
import random
import requests
import tempfile
from datetime import datetime, timezone
from image_gen import generate_image

# ─── ACCOUNTS CONFIG ──────────────────────────────────────────────────────────
# GitHub Secrets থেকে পড়া হবে
# Format: BSKY_HANDLE_1, BSKY_PASSWORD_1 ... BSKY_HANDLE_5, BSKY_PASSWORD_5
def load_accounts() -> list[dict]:
    accounts = []
    for i in range(1, 6):  # max 5 accounts
        handle   = os.environ.get(f"BSKY_HANDLE_{i}")
        password = os.environ.get(f"BSKY_PASSWORD_{i}")
        if handle and password:
            accounts.append({
                "id": i,
                "handle": handle,
                "password": password,
            })
    if not accounts:
        print("❌ কোনো account পাওয়া যায়নি! BSKY_HANDLE_1 এবং BSKY_PASSWORD_1 set করুন।")
        exit(1)
    return accounts

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("❌ DEEPSEEK_API_KEY missing!")
    exit(1)

# ─── POST ANGLES ──────────────────────────────────────────────────────────────
ANGLES = [
    {
        "angle": "personal_story",
        "image_main": "I Started With Zero Experience",
        "image_sub":  "Now I Run a Remote Team 💼",
        "prompt": """Write a Bluesky post (max 270 chars) in English.
Angle: Personal story — started with no experience, now running a remote team doing simple online tasks.
We hire people for: data entry, content review, research tasks.
Flexible hours, weekly PayPal payments, $300-$800/month part-time, US residents.
CTA: DM "JOIN" to get started.
Hashtags: #WorkFromHome #RemoteWork #SideHustle
Tone: Real, humble, genuine — NOT salesy. Like a friend sharing their experience.
Return ONLY the post text."""
    },
    {
        "angle": "social_proof",
        "image_main": "Our Team Member Just Got Paid 💸",
        "image_sub":  "Weekly PayPal Payment — On Time",
        "prompt": """Write a Bluesky post (max 270 chars) in English.
Angle: Social proof — celebrating a team member's weekly payment.
Remote agency, simple online tasks, flexible hours, weekly PayPal payments.
US residents only. No experience needed. $300-$800/month part-time.
CTA: DM "PAID" if you want in.
Hashtags: #OnlineJobs #WorkFromHome #MakeMoneyOnline
Tone: Authentic celebration — NOT an ad. Like sharing good news.
Return ONLY the post text."""
    },
    {
        "angle": "scarcity",
        "image_main": "Only 3 Spots Left This Month",
        "image_sub":  "Remote Work — Weekly Pay — US Only",
        "prompt": """Write a Bluesky post (max 270 chars) in English.
Angle: Limited spots open this month for remote workers.
Simple online tasks, flexible hours, $300-$800/month, weekly PayPal payments.
US residents only. No experience required.
CTA: Comment "WORK" or DM to apply before spots fill.
Hashtags: #RemoteWork #SideHustle #OnlineJobs
Tone: Low-pressure urgency — NOT fake hype. Genuine and direct.
Return ONLY the post text."""
    },
    {
        "angle": "beginner_friendly",
        "image_main": "No Experience? No Problem.",
        "image_sub":  "We Train You — You Earn Weekly 🎯",
        "prompt": """Write a Bluesky post (max 270 chars) in English.
Angle: Perfect for beginners — no experience needed, full training provided.
Remote agency doing simple tasks: data entry, content review, research.
Flexible schedule, weekly PayPal, $300-$800/month, US residents only.
CTA: DM "START" to get all details.
Hashtags: #WorkFromHome #BeginnerFriendly #SideHustle
Tone: Warm, encouraging — like a friend giving honest advice.
Return ONLY the post text."""
    },
    {
        "angle": "lifestyle",
        "image_main": "Work From Anywhere. Earn Weekly.",
        "image_sub":  "Flexible Hours — Simple Tasks 🌍",
        "prompt": """Write a Bluesky post (max 270 chars) in English.
Angle: Lifestyle freedom — work from anywhere on your own schedule.
Remote agency, simple online tasks, flexible hours, weekly PayPal payments.
$300-$800/month part-time. US residents only. No experience needed.
CTA: DM "FLEX" to learn more.
Hashtags: #WorkFromAnywhere #RemoteLife #SideHustle
Tone: Aspirational but grounded — real, not dreamy hype.
Return ONLY the post text."""
    },
]

# ─── DEEPSEEK: TEXT GENERATE ──────────────────────────────────────────────────
def generate_post_text(angle_data: dict) -> str:
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": angle_data["prompt"]}],
            "max_tokens": 300,
            "temperature": 0.9,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


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
def bsky_post(session: dict, text: str, image_path: str | None = None) -> str:
    # Hashtag facets
    facets = []
    for match in re.finditer(r"#(\w+)", text):
        tag   = match.group(1)
        start = len(text[:match.start()].encode("utf-8"))
        end   = len(text[:match.end()].encode("utf-8"))
        facets.append({
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}],
        })

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if facets:
        record["facets"] = facets

    # Image attach
    if image_path:
        blob = bsky_upload_image(session, image_path)
        if blob:
            record["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [{"image": blob, "alt": "Remote work opportunity"}],
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
    print(f"🚀 Multi-Account Poster শুরু!")
    print(f"👥 Accounts: {len(accounts)}টি")
    print(f"📝 প্রতিটি account-এ ১টি পোস্ট\n")

    # সব account-এর জন্য আলাদা angle select
    angles = random.sample(ANGLES, min(len(accounts), len(ANGLES)))
    # যদি accounts > angles হয়, repeat করো
    while len(angles) < len(accounts):
        angles.append(random.choice(ANGLES))

    results = []

    for i, (account, angle_data) in enumerate(zip(accounts, angles)):
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"👤 Account {account['id']}: {account['handle']}")
        print(f"📌 Angle: {angle_data['angle']}")

        try:
            # 1. Login
            print(f"  🔑 Login করছি...")
            session = bsky_login(account["handle"], account["password"])
            print(f"  ✅ Login সফল!")

            # 2. Generate text
            print(f"  🤖 Text লিখছি...")
            post_text = generate_post_text(angle_data)
            print(f"  ✍️  {post_text[:80]}...")
            print(f"  📏 {len(post_text)} chars")

            # 3. Generate image (Pillow)
            print(f"  🖼️  Image বানাচ্ছি...")
            image_path = generate_image(
                main_text=angle_data["image_main"],
                sub_text=angle_data["image_sub"],
            )
            print(f"  ✅ Image তৈরি!")

            # 4. Post
            print(f"  📤 Post করছি...")
            uri = bsky_post(session, post_text, image_path)
            print(f"  ✅ পোস্ট সফল! {uri}")
            results.append({"account": account["handle"], "status": "success", "uri": uri})

        except Exception as e:
            print(f"  ❌ ব্যর্থ: {e}")
            results.append({"account": account["handle"], "status": "failed", "error": str(e)})

        # Accounts-এর মাঝে ছোট delay
        if i < len(accounts) - 1:
            print(f"  ⏳ 10 সেকেন্ড অপেক্ষা...")
            time.sleep(10)

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    failed  = sum(1 for r in results if r["status"] == "failed")
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 সারসংক্ষেপ: ✅ {success} সফল | ❌ {failed} ব্যর্থ")
    print("🎉 সম্পন্ন!")

    if success == 0:
        exit(1)


if __name__ == "__main__":
    main()
