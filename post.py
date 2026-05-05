import os
import re
import time
import random
import requests
import tempfile
from datetime import datetime, timezone

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BSKY_HANDLE       = os.environ.get("BSKY_HANDLE")
BSKY_APP_PASSWORD = os.environ.get("BSKY_APP_PASSWORD")
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY")
POST_COUNT        = int(os.environ.get("POST_COUNT", "1"))
POST_DELAY        = int(os.environ.get("POST_DELAY_SECONDS", "30"))

if not all([BSKY_HANDLE, BSKY_APP_PASSWORD, DEEPSEEK_API_KEY]):
    print("❌ Missing env vars!")
    exit(1)

# ─── POST ANGLES (প্রতিটি আলাদা) ─────────────────────────────────────────────
ANGLES = [
    {
        "angle": "personal_story",
        "prompt": """Write a Bluesky post (max 280 chars) in English.
Angle: Personal story — "I started with zero experience, now I run a remote team"
Topic: Hiring people for simple online tasks (data entry, content review, research)
Agency pays weekly via PayPal. US residents only.
CTA: DM "JOIN" to learn more.
Include 2-3 emojis and hashtags: #WorkFromHome #RemoteWork #SideHustle
Sound real, humble, genuine — NOT salesy or hype.
Return only the post text."""
    },
    {
        "angle": "social_proof",
        "prompt": """Write a Bluesky post (max 280 chars) in English.
Angle: Social proof — a team member just got their weekly payment
Topic: Remote agency hiring for simple online tasks, flexible hours, weekly PayPal payment
US residents only. No experience needed.
CTA: DM "JOIN" if interested.
Include 2-3 emojis and hashtags: #OnlineJobs #WorkFromHome #MakeMoneyOnline
Sound authentic, like a real person sharing good news — NOT an ad.
Return only the post text."""
    },
    {
        "angle": "scarcity",
        "prompt": """Write a Bluesky post (max 280 chars) in English.
Angle: Limited spots — only accepting a few people this month
Topic: Remote agency doing simple online tasks, earn $300-$800/month part-time
Flexible hours, weekly payments, US residents only.
CTA: Comment "WORK" or DM to apply.
Include 2-3 emojis and hashtags: #RemoteWork #SideHustle #OnlineJobs
Sound genuine and low-pressure — NOT fake urgency.
Return only the post text."""
    },
    {
        "angle": "beginner_friendly",
        "prompt": """Write a Bluesky post (max 280 chars) in English.
Angle: No experience needed — perfect for beginners
Topic: Remote team doing simple tasks online, flexible schedule, weekly PayPal pay
Open to US residents. Tasks include data entry, content review, research.
CTA: DM "START" to get details.
Include 2-3 emojis and hashtags: #WorkFromHome #BeginnerFriendly #SideHustle
Warm, encouraging tone — like a friend giving advice.
Return only the post text."""
    },
    {
        "angle": "income_proof",
        "prompt": """Write a Bluesky post (max 280 chars) in English.
Angle: Realistic income — showing actual weekly earnings range
Topic: Remote agency hiring, simple tasks, $300-$800/month part-time, weekly payments
US only, flexible hours, no experience required.
CTA: DM "INFO" for details.
Include 2-3 emojis and hashtags: #PassiveIncome #OnlineJobs #WorkFromHome
Be honest about earnings — NOT overpromising. Sound trustworthy.
Return only the post text."""
    },
    {
        "angle": "lifestyle",
        "prompt": """Write a Bluesky post (max 280 chars) in English.
Angle: Lifestyle — work from anywhere, be your own boss of your time
Topic: Remote agency, simple online tasks, flexible hours, weekly PayPal payments
US residents, no experience needed, $300-$800/month part-time.
CTA: DM "FLEX" to learn more.
Include 2-3 emojis and hashtags: #WorkFromAnywhere #RemoteLife #SideHustle
Aspirational but grounded tone — real, not dreamy hype.
Return only the post text."""
    },
]

# ─── IMAGE PROMPTS (Pollinations.ai) ──────────────────────────────────────────
IMAGE_PROMPTS = [
    "minimalist poster, dark background, white text: 'Work From Home. Weekly Pay. No Experience Needed.', clean modern design, professional",
    "simple graphic, navy blue background, bold white text: 'Hiring Remote Workers. Flexible Hours. US Only.', modern flat design",
    "clean poster, gradient purple background, white text: 'Earn $300-800/month. Simple Online Tasks. Apply Now.', minimal professional",
    "modern banner, black background, gold accent text: 'Remote Work Opportunity. Weekly PayPal Payment. DM to Join.', sleek design",
    "flat design poster, teal background, white bold text: 'Work Anywhere. Earn Weekly. No Experience Required.', minimal clean",
    "professional graphic, dark charcoal background, white text: 'Join Our Remote Team. Simple Tasks. Flexible Schedule.', modern design",
]

# ─── DEEPSEEK: পোস্ট লেখা ────────────────────────────────────────────────────
def generate_post(angle_data: dict) -> str:
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "user", "content": angle_data["prompt"]}
            ],
            "max_tokens": 300,
            "temperature": 0.9,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# ─── POLLINATIONS.AI: Image Generate ─────────────────────────────────────────
def generate_image(image_prompt: str) -> str | None:
    try:
        # Pollinations.ai — no API key needed
        encoded = requests.utils.quote(image_prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=512&nologo=true&seed={random.randint(1,9999)}"
        
        print(f"🖼️  Image generate করছি...")
        response = requests.get(url, timeout=60)
        
        if response.status_code == 200 and len(response.content) > 10000:
            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.write(response.content)
            tmp.close()
            print(f"✅ Image তৈরি হয়েছে: {len(response.content)//1024}KB")
            return tmp.name
        else:
            print(f"⚠️  Image generate হয়নি, text-only পোস্ট করব")
            return None
    except Exception as e:
        print(f"⚠️  Image error: {e} — text-only পোস্ট করব")
        return None


# ─── BLUESKY LOGIN ────────────────────────────────────────────────────────────
def bsky_login() -> dict:
    r = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": BSKY_HANDLE, "password": BSKY_APP_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ─── BLUESKY IMAGE UPLOAD ─────────────────────────────────────────────────────
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
        print(f"⚠️  Image upload error: {e}")
        return None
    finally:
        # Temp file delete
        try:
            os.unlink(image_path)
        except:
            pass


# ─── BLUESKY POST ─────────────────────────────────────────────────────────────
def bsky_post(session: dict, text: str, image_path: str | None = None) -> str:
    # Hashtag facets
    facets = []
    for match in re.finditer(r"#(\w+)", text):
        tag = match.group(1)
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

    # Image attach করা
    if image_path:
        blob = bsky_upload_image(session, image_path)
        if blob:
            record["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [{
                    "image": blob,
                    "alt": "Remote work opportunity - Work from home"
                }]
            }
            print("🖼️  Image পোস্টে যুক্ত হয়েছে")

    r = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {session['accessJwt']}"},
        json={
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": record,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["uri"]


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print(f"🚀 Bluesky Agency Recruiter শুরু হচ্ছে...")
    print(f"📝 আজকে {POST_COUNT}টি পোস্ট করা হবে\n")

    print("🔑 Bluesky-তে লগইন করছি...")
    session = bsky_login()
    print(f"✅ লগইন সফল!\n")

    # Random angles & image prompts select
    selected_angles = random.sample(ANGLES, min(POST_COUNT, len(ANGLES)))
    selected_images = random.sample(IMAGE_PROMPTS, min(POST_COUNT, len(IMAGE_PROMPTS)))
    results = []

    for i, (angle_data, img_prompt) in enumerate(zip(selected_angles, selected_images)):
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"📌 পোস্ট {i+1}/{len(selected_angles)} [{angle_data['angle']}]")

        try:
            # AI দিয়ে পোস্ট লেখা
            print("🤖 DeepSeek দিয়ে পোস্ট লিখছি...")
            post_text = generate_post(angle_data)
            print(f"✍️  Post:\n{post_text}")
            print(f"📏 {len(post_text)} chars")

            # Image generate
            image_path = generate_image(img_prompt)

            # Bluesky-তে পোস্ট
            print("📤 Bluesky-তে পোস্ট করছি...")
            uri = bsky_post(session, post_text, image_path)
            print(f"✅ সফল! URI: {uri}")
            results.append({"status": "success", "angle": angle_data["angle"], "uri": uri})

        except Exception as e:
            print(f"❌ ব্যর্থ: {e}")
            results.append({"status": "failed", "error": str(e)})

        if i < len(selected_angles) - 1:
            print(f"⏳ {POST_DELAY} সেকেন্ড অপেক্ষা...")
            time.sleep(POST_DELAY)

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
