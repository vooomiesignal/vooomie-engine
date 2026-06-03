"""
╔══════════════════════════════════════════════════════════════╗
║           VOOOMIE TRENDS — VIRAL ENGINE BACKEND              ║
║           vooomiegroup.com/trends                            ║
║           Lagos, Nigeria 🇳🇬                                 ║
╚══════════════════════════════════════════════════════════════╝

Full automated viral content engine:
  Layer 1: Trend Scouts    — RSS + API polling every 15 min
  Layer 2: AI Scoring      — Velocity + sentiment + cross-platform
  Layer 3: Content Factory — Claude AI rewrite + image + SEO
  Layer 4: Publish Engine  — WordPress REST + social platforms
  Layer 5: Monetization    — AdSense auto-insert + affiliate links

Run: python engine.py
"""

import os, sys, json, time, logging, hashlib, re, sqlite3
import feedparser
import requests
from datetime import datetime, timedelta
from anthropic import Anthropic

# ── CONFIG ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("vooomie.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("vooomie")

# Load from environment variables (set in .env or server env)
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")
WP_URL              = os.getenv("WP_URL", "https://vooomiegroup.com")
WP_TRENDS_SLUG      = os.getenv("WP_TRENDS_SLUG", "vooomietrends")
WP_USERNAME         = os.getenv("WP_USERNAME", "admin")
WP_APP_PASSWORD     = os.getenv("WP_APP_PASSWORD", "")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@vooomietrends")
VIRAL_THRESHOLD     = int(os.getenv("VIRAL_THRESHOLD", "35"))
SCAN_INTERVAL_MIN   = int(os.getenv("SCAN_INTERVAL_MIN", "15"))
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
GIST_ID             = os.getenv("GIST_ID", "8f3b89e534895a9253d233ba006a31a6")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN", "")

# ── TWITTER/X API v2 ──────────────────────────────────────────────────────────
TWITTER_API_KEY         = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET      = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN    = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET   = os.getenv("TWITTER_ACCESS_SECRET", "")
TWITTER_BEARER_TOKEN    = os.getenv("TWITTER_BEARER_TOKEN", "")

# ── FACEBOOK GRAPH API ────────────────────────────────────────────────────────
FACEBOOK_PAGE_ID        = os.getenv("FACEBOOK_PAGE_ID", "")
FACEBOOK_ACCESS_TOKEN   = os.getenv("FACEBOOK_ACCESS_TOKEN", "")
RESET_SEEN          = os.getenv("RESET_SEEN", "false").lower() == "true"

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ── IN-MEMORY STATE (synced to JSONBin) ───────────────────────────────────────
engine_state = {
    "scanCount": 0,
    "publishCount": 0,
    "totalViews": 0,
    "totalEarnings": 0.0,
    "recentStories": [],
    "recentPublished": [],
    "logs": [],
    "lastUpdated": "",
    "status": "running",
}

# ── SOURCES ───────────────────────────────────────────────────────────────────

RSS_SOURCES = [
    # Nigerian News
    {"name": "Pulse.ng",        "url": "https://www.pulse.ng/rss", "weight": 1.3},
    {"name": "Vanguard",        "url": "https://www.vanguardngr.com/feed/", "weight": 1.2},
    {"name": "Channels TV",     "url": "https://www.channelstv.com/feed/", "weight": 1.2},
    {"name": "Premium Times",   "url": "https://www.premiumtimesng.com/feed", "weight": 1.1},
    {"name": "Guardian NG",     "url": "https://guardian.ng/feed/", "weight": 1.1},
    {"name": "TheCable",        "url": "https://www.thecable.ng/feed", "weight": 1.0},
    # African / Global
    {"name": "BBC Africa",      "url": "http://feeds.bbci.co.uk/news/world/africa/rss.xml", "weight": 1.0},
    {"name": "Naija247news",    "url": "https://naija247news.com/feed/", "weight": 0.9},
    # Entertainment
    {"name": "BellaNaija",      "url": "https://www.bellanaija.com/feed/", "weight": 1.2},
    {"name": "Notjustok",       "url": "https://notjustok.com/feed/", "weight": 1.1},
    # Reddit (hot posts as proxy for viral)
    {"name": "Reddit/Nigeria",  "url": "https://www.reddit.com/r/Nigeria/hot/.rss", "weight": 1.3},
    {"name": "Reddit/Africa",   "url": "https://www.reddit.com/r/Africa/hot/.rss", "weight": 1.0},
    {"name": "Reddit/WorldNews","url": "https://www.reddit.com/r/worldnews/hot/.rss?limit=10", "weight": 0.8},
]

GOOGLE_TRENDS_REGIONS = ["NG", "GH", "ZA"]  # Nigeria, Ghana, South Africa

CATEGORIES = {
    "funny":      ["hilarious", "lol", "comedy", "joke", "funny", "prank", "meme", "skit",
                   "goes viral", "twitter reacts", "reactions", "social media laughs",
                   "landlord", "drama", "shocking moment", "caught on camera doing",
                   "you won't believe", "what he did", "what she did", "embarrassing"],
    "sports":     ["super eagles", "afcon", "premier league", "champions league", "nba", "nfl",
                   "transfer", "goal", "match", "chelsea", "arsenal", "psg", "fifa", "uefa",
                   "world cup", "la liga", "bundesliga", "football", "soccer", "basketball",
                   "tennis", "athletics", "olympic", "sports", "tournament", "league",
                   "cup final", "arteta", "rice", "mbappe", "ronaldo", "messi", "atletico",
                   "real madrid", "manchester", "liverpool", "tottenham"],
    "politics":   ["senate", "president", "governor", "minister", "election", "aso rock",
                   "nass", "tinubu", "atiku", "peter obi", "APC", "PDP", "labour party",
                   "parliament", "congress", "government", "policy", "vote", "democracy",
                   "inauguration", "impeach", "house of reps", "national assembly"],
    "celebrity":  ["wizkid", "burna boy", "davido", "tiwa savage", "olamide", "adekunle gold",
                   "tems", "rema", "ayra starr", "album", "tour", "grammy", "bet awards",
                   "afrobeats", "musician", "singer", "actor", "actress", "nollywood",
                   "billboard", "portable", "asake", "kizz daniel", "fireboy", "ruger"],
    "crime":      ["arrested", "efcc", "police", "court", "jail", "fraud", "robbery",
                   "kidnap", "IPOB", "bandits", "terrorism", "murder", "killed", "attack",
                   "shooting", "arson", "stolen", "suspect", "naira marley", "abducted",
                   "ransom", "detention", "convicted", "sentenced"],
    "business":   ["naira", "CBN", "economy", "investment", "profit", "stock", "oil",
                   "revenue", "company", "billion", "million", "market", "trade", "export",
                   "import", "gdp", "inflation", "interest rate", "bank", "forex",
                   "cryptocurrency", "startup funding", "ipo", "acquisition"],
    "tech":       ["artificial intelligence", "AI model", "app launch", "software",
                   "funding round", "fintech", "crypto", "blockchain", "silicon",
                   "developer", "programming", "cybersecurity", "data breach",
                   "spacex", "tesla", "google", "apple", "microsoft", "meta",
                   "openai", "chatgpt", "robot", "drone"],
    "lifestyle":  ["fashion", "style", "beauty", "food", "restaurant", "travel", "luxury",
                   "wedding", "health", "fitness", "relationship", "marriage", "family",
                   "recipe", "diet", "workout", "skincare", "hair", "house tour"],
}

# ── DATABASE ──────────────────────────────────────────────────────────────────

def reset_seen_stories():
    """Clear seen stories DB so engine re-processes everything fresh."""
    conn = sqlite3.connect("vooomie.db")
    c = conn.cursor()
    c.execute("DELETE FROM seen_stories")
    conn.commit()
    conn.close()
    log.info("✦ RESET: Cleared seen stories — engine will re-scan all sources fresh!")

def init_db():
    conn = sqlite3.connect("vooomie.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS seen_stories (
            hash TEXT PRIMARY KEY,
            title TEXT,
            source TEXT,
            score INTEGER,
            published INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS published_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wp_post_id INTEGER,
            title TEXT,
            url TEXT,
            category TEXT,
            score INTEGER,
            platforms TEXT,
            views INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized ✦")
    if RESET_SEEN:
        reset_seen_stories()

def story_hash(title):
    return hashlib.md5(title.lower().encode()).hexdigest()

def is_seen(title):
    conn = sqlite3.connect("vooomie.db")
    c = conn.cursor()
    c.execute("SELECT hash FROM seen_stories WHERE hash=?", (story_hash(title),))
    result = c.fetchone()
    conn.close()
    return result is not None

def mark_seen(title, source, score, published=False):
    conn = sqlite3.connect("vooomie.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO seen_stories (hash, title, source, score, published, created_at)
        VALUES (?,?,?,?,?,?)
    """, (story_hash(title), title[:500], source, score, int(published), datetime.now().isoformat()))
    conn.commit()
    conn.close()

def save_published(wp_id, title, url, category, score, platforms):
    conn = sqlite3.connect("vooomie.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO published_posts (wp_post_id, title, url, category, score, platforms, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (wp_id, title[:500], url, category, score, ",".join(platforms), datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ── LAYER 1: TREND SCOUTS ─────────────────────────────────────────────────────

def scrape_rss_sources():
    """Poll all RSS sources and return raw stories."""
    stories = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VooomieBot/1.0; +https://vooomiegroup.com)"
    }
    for source in RSS_SOURCES:
        try:
            feed = feedparser.parse(source["url"], request_headers=headers)
            for entry in feed.entries[:8]:  # top 8 per source
                title = entry.get("title", "").strip()
                link  = entry.get("link", "")
                summary = entry.get("summary", entry.get("description", ""))[:500]

                # ── Extract original image from RSS entry ──────────────────
                image_url = None
                # Method 1: media:content or media:thumbnail tags
                if hasattr(entry, "media_content") and entry.media_content:
                    image_url = entry.media_content[0].get("url")
                elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                    image_url = entry.media_thumbnail[0].get("url")
                # Method 2: enclosure tag (podcasts/images)
                elif hasattr(entry, "enclosures") and entry.enclosures:
                    for enc in entry.enclosures:
                        if enc.get("type", "").startswith("image"):
                            image_url = enc.get("href") or enc.get("url")
                            break
                # Method 3: og:image from summary HTML
                if not image_url and summary:
                    og_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
                    if og_match:
                        image_url = og_match.group(1)
                # Method 4: links in entry
                if not image_url:
                    for lnk in entry.get("links", []):
                        if lnk.get("type","").startswith("image"):
                            image_url = lnk.get("href","")
                            break

                if title and len(title) > 15:
                    stories.append({
                        "title":     title,
                        "summary":   re.sub(r"<[^>]+>", "", summary),
                        "link":      link,
                        "source":    source["name"],
                        "weight":    source["weight"],
                        "time":      datetime.now(),
                        "image_url": image_url,
                    })
            log.info(f"  ◈ {source['name']}: {len(feed.entries)} entries")
        except Exception as e:
            log.warning(f"  ✗ {source['name']}: {e}")
        time.sleep(0.3)  # polite crawling
    log.info(f"Scraped {len(stories)} raw stories from {len(RSS_SOURCES)} sources")
    return stories

def fetch_google_trends():
    """Fetch Google Trends RSS for Nigeria."""
    trends = []
    for region in GOOGLE_TRENDS_REGIONS:
        try:
            url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={region}"
            feed = feedparser.parse(url)
            for entry in feed.entries[:5]:
                title = entry.get("title", "").strip()
                if title:
                    trends.append({
                        "title":   f"TRENDING: {title}",
                        "summary": entry.get("ht_approx_traffic", ""),
                        "link":    f"https://www.google.com/search?q={requests.utils.quote(title)}",
                        "source":  f"Google Trends ({region})",
                        "weight":  1.4,
                        "time":    datetime.now(),
                        "is_trend_keyword": True,
                        "keyword": title,
                    })
        except Exception as e:
            log.warning(f"Google Trends ({region}): {e}")
    return trends

# ── LAYER 2: AI SCORING ENGINE ────────────────────────────────────────────────

def detect_category(title, summary=""):
    """Classify story into category based on keywords."""
    text = (title + " " + summary).lower()
    scores = {}
    for cat, keywords in CATEGORIES.items():
        scores[cat] = sum(1 for kw in keywords if kw.lower() in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"

def score_velocity(title, source_weight=1.0):
    """
    Velocity: how fast is this story rising?
    Generous scoring for real RSS headlines.
    """
    title_lower = title.lower()
    score = 50  # higher base for real news
    # Breaking / urgency signals
    if any(w in title_lower for w in ["breaking", "just in", "urgent", "alert", "update"]):
        score += 25
    if any(w in title_lower for w in ["exclusive", "leaked", "caught", "exposed"]):
        score += 20
    if any(w in title_lower for w in ["exclusive", "leaked", "caught", "exposed",
        "arrests", "arrested", "killed", "dead", "crisis", "attack", "scandal"]):
        score += 15
    # Nigerian specific signals
    if any(w in title_lower for w in ["nigeria", "lagos", "abuja", "naira", "tinubu",
        "senate", "efcc", "cbn", "inec", "aso rock", "naija"]):
        score += 12
    # Emotional triggers
    if any(w in title_lower for w in ["shocking", "unbelievable", "wow", "omg", "crazy",
        "massive", "huge", "major", "historic", "record", "first", "new"]):
        score += 10
    if any(c in title for c in ["!", "?", "…"]):
        score += 8
    # Numbers = specificity
    if re.search(r"\d+", title):
        score += 8
    # Long headlines = more content = more shareable
    if len(title) > 60:
        score += 5
    # Source authority weight
    score = int(score * source_weight)
    return min(score, 100)

def score_sentiment(title, summary=""):
    """
    High-emotion stories go viral.
    Generous base score for real news.
    """
    text = (title + " " + summary).lower()
    high_emotion = ["arrested", "dead", "killed", "shocking", "viral", "outrage",
                    "angry", "furious", "heartbreaking", "incredible", "amazing",
                    "disgusting", "scandal", "corruption", "exposed", "leaked",
                    "wow", "omg", "love", "hate", "winning", "champion", "record",
                    "ban", "crisis", "attack", "resign", "fire", "bomb", "crash",
                    "flood", "strike", "protest", "riot", "coup", "impeach",
                    "billion", "million", "trillion", "free", "win", "lose",
                    "increase", "decrease", "rise", "fall", "high", "low"]
    neutral = ["report", "says", "according", "statement", "meeting"]
    emotion_hits = sum(1 for w in high_emotion if w in text)
    neutral_hits  = sum(1 for w in neutral if w in text)
    score = 55 + (emotion_hits * 8) - (neutral_hits * 3)
    return max(30, min(score, 100))

def score_cross_platform(title, all_stories):
    """
    If same story/topic appears across multiple sources → high viral potential.
    """
    keywords = set(re.findall(r'\b\w{5,}\b', title.lower()))
    matches = 0
    for story in all_stories:
        if story["title"] == title:
            continue
        other_keywords = set(re.findall(r'\b\w{5,}\b', story["title"].lower()))
        overlap = len(keywords & other_keywords)
        if overlap >= 2:
            matches += 1
    return min(30 + (matches * 15), 100)

def compute_viral_score(story, all_stories):
    """Weighted composite score: velocity(45%) + sentiment(30%) + cross(25%)"""
    v = score_velocity(story["title"], story.get("weight", 1.0))
    s = score_sentiment(story["title"], story.get("summary", ""))
    c = score_cross_platform(story["title"], all_stories)
    score = int((v * 0.45) + (s * 0.30) + (c * 0.25))
    return {
        "score":        score,
        "velocity":     v,
        "sentiment":    s,
        "cross":        c,
        "category":     detect_category(story["title"], story.get("summary", "")),
        "hot":          score >= VIRAL_THRESHOLD,
    }

def filter_and_score_all(raw_stories):
    """Score ALL stories for dashboard display — no threshold filter."""
    unique = []
    seen_hashes = set()
    for s in raw_stories:
        h = story_hash(s["title"])
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique.append(s)
    scored = []
    for story in unique[:50]:  # top 50 for display
        metrics = compute_viral_score(story, unique)
        story.update(metrics)
        scored.append(story)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored

def filter_and_score(raw_stories):
    """Remove duplicates, score everything, return sorted hot stories."""
    unique = []
    seen_hashes = set()
    for s in raw_stories:
        h = story_hash(s["title"])
        if h not in seen_hashes and not is_seen(s["title"]):
            seen_hashes.add(h)
            unique.append(s)

    log.info(f"Unique new stories: {len(unique)}")
    scored = []
    for story in unique:
        metrics = compute_viral_score(story, unique)
        story.update(metrics)
        scored.append(story)
        mark_seen(story["title"], story["source"], story["score"])

    hot = [s for s in scored if s["hot"]]
    hot.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Hot stories (score ≥ {VIRAL_THRESHOLD}): {len(hot)}")
    return hot

# ── LAYER 3: CONTENT FACTORY ──────────────────────────────────────────────────

REWRITE_PROMPT = """You are the chief content writer for VOOOMIE Trends, Nigeria's fastest viral news site (vooomiegroup.com/trends).

Your job: transform breaking stories into content that Nigerians will SHARE IMMEDIATELY.

Story: {title}
Summary: {summary}
Category: {category}
Source: {source}

Return ONLY a valid JSON object — no markdown fences, no preamble, no explanation:
{{
  "headline": "punchy headline under 14 words, use Nigerian English tone where appropriate",
  "subheadline": "one sentence explainer under 20 words",
  "hook": "opening sentence that makes someone stop scrolling",
  "body_paragraph_1": "what happened — 2-3 sentences, conversational, factual",
  "body_paragraph_2": "why it matters / reactions — 2-3 sentences",
  "body_paragraph_3": "what happens next / VOOOMIE take — 1-2 sentences, end with a question for comments",
  "tiktok_caption": "under 150 chars, viral hook + 3 hashtags including #VooomieNG",
  "instagram_caption": "engaging caption 100-200 chars + 8 hashtags, include #VooomieNG #NaijaNews",
  "whatsapp_blast": "broadcast message max 200 chars, punchy, ends with 👉 [LINK]",
  "telegram_post": "short post with bold headline (use **bold**), 2 sentences, link placeholder [LINK]",
  "seo_title": "under 60 chars, keyword-rich",
  "meta_description": "under 155 chars, includes main keyword",
  "focus_keyword": "main SEO keyword for this post",
  "tags": ["tag1","tag2","tag3","tag4","tag5"],
  "image_search_query": "3-5 word Unsplash search query for a relevant thumbnail"
}}"""

def ai_rewrite(story):
    """Use Claude to rewrite story for maximum virality across all platforms."""
    if not client:
        log.warning("No Anthropic API key — using title as headline")
        return _fallback_content(story)

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": REWRITE_PROMPT.format(
                    title=story["title"],
                    summary=story.get("summary", "")[:300],
                    category=story["category"],
                    source=story["source"],
                )
            }]
        )
        text = message.content[0].text.strip()
        # Strip any accidental markdown fences
        text = re.sub(r"```json|```", "", text).strip()
        content = json.loads(text)
        log.info(f"  ✦ AI rewrote: {content['headline'][:60]}…")
        return content
    except json.JSONDecodeError as e:
        log.warning(f"  AI JSON parse error: {e} — using fallback")
        return _fallback_content(story)
    except Exception as e:
        log.warning(f"  AI rewrite failed: {e}")
        return _fallback_content(story)

def _fallback_content(story):
    """Fallback content when Claude API is unavailable."""
    title = story["title"]
    cat = story["category"].title()
    return {
        "headline": title[:70],
        "subheadline": f"Full story from {story['source']}",
        "hook": f"This is the story everyone in Nigeria is talking about right now.",
        "body_paragraph_1": story.get("summary", f"This developing story is gaining rapid attention across Nigerian social media platforms. Our team is tracking all updates in real time."),
        "body_paragraph_2": f"Reactions are pouring in from across the country as this story continues to develop. Multiple sources have confirmed the reports.",
        "body_paragraph_3": f"VOOOMIE Trends will keep you updated as more details emerge. What do you think about this? Drop your comment below! 👇",
        "tiktok_caption": f"{title[:80]} #VooomieNG #NaijaNews #Viral",
        "instagram_caption": f"🔥 {title[:100]}\n\nFollow @vooomietrends 🇳🇬\n\n#VooomieNG #NaijaNews #Nigeria #Trending #Naija #Viral #BreakingNews #Lagos",
        "whatsapp_blast": f"🚨 VOOOMIE: {title[:120]}...\n\n👉 [LINK]",
        "telegram_post": f"**{title[:100]}**\n\nRead full story on VOOOMIE Trends.\n\n[LINK]",
        "seo_title": title[:58],
        "meta_description": f"{title[:130]}. Full story and reactions on VOOOMIE Trends.",
        "focus_keyword": story["category"],
        "tags": [story["category"], "nigeria", "trending", "naija", "vooomie"],
        "image_search_query": f"{story['category']} nigeria news",
    }

def fetch_unsplash_image(query, access_key=None):
    """Fetch relevant image — tries multiple free sources."""
    clean_q = re.sub(r"[^a-zA-Z0-9 ]", "", query).strip()[:60]
    encoded = requests.utils.quote(clean_q)

    # Try Unsplash CDN (free, no auth needed, relevant images)
    sources = [
        f"https://source.unsplash.com/1200x630/?{encoded}",
        f"https://loremflickr.com/1200/630/{encoded}",
        f"https://picsum.photos/seed/{encoded.replace('+','')}/1200/630",
    ]
    # Validate first source works
    for src in sources:
        try:
            r = requests.head(src, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                return src
        except:
            pass
    return sources[0]  # return first as fallback


def fetch_image_from_article(url, summary=""):
    """
    Get the REAL original image from an article.
    Priority: og:image > twitter:image > first article image > RSS media
    """
    # First check summary/RSS content for image
    if summary:
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
        if img_match:
            img_url = img_match.group(1)
            if img_url.startswith("http") and any(ext in img_url.lower() for ext in [".jpg",".jpeg",".png",".webp",".gif"]):
                return img_url

    # Scrape article page
    if not url:
        return None
    try:
        res = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (compatible; VooomieBot/1.0; +https://vooomiegroup.com)",
            "Accept": "text/html,application/xhtml+xml",
        })
        html = res.text

        # 1. og:image (best quality, set by publisher)
        patterns = [
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
            r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"',
            r'<meta[^>]+content="([^"]+)"[^>]+name="twitter:image"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                img = match.group(1).strip()
                if img.startswith("http") and len(img) > 10:
                    log.info(f"    Real image found (og:image): {img[:70]}")
                    return img

        # 2. First large image in article body
        imgs = re.findall(r'<img[^>]+src="([^"]+)"', html)
        for img in imgs:
            if not img.startswith("http"): continue
            if any(s in img.lower() for s in ["logo","icon","avatar","pixel","1x1","spacer","ad","banner"]): continue
            if any(ext in img.lower() for ext in [".jpg",".jpeg",".png",".webp"]):
                log.info(f"    Real image found (img tag): {img[:70]}")
                return img

    except Exception as e:
        log.debug(f"Image scrape failed for {url}: {e}")
    return None

def build_wp_content(story, content):
    """Build full WordPress HTML post body."""
    tags_html = " ".join([f'<a href="/tag/{t.replace(" ","-")}" rel="tag">{t}</a>' for t in content.get("tags", [])])
    affiliate_block = ""
    if story["category"] in ["lifestyle", "tech", "business"]:
        affiliate_block = """
        <div class="vooomie-affiliate" style="background:#fff8e1;border-left:4px solid #ffd700;padding:16px;margin:24px 0;border-radius:4px;">
            <strong>🛍️ Trending Products:</strong> Shop the best deals on 
            <a href="https://jumia.com.ng/?ref=vooomietrends" rel="nofollow sponsored" target="_blank">Jumia Nigeria</a> | 
            <a href="https://konga.com/?ref=vooomietrends" rel="nofollow sponsored" target="_blank">Konga</a>
        </div>"""

    return f"""
<!-- wp:paragraph -->
<p class="vooomie-hook"><strong>{content['hook']}</strong></p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{content['body_paragraph_1']}</p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>{content['body_paragraph_2']}</p>
<!-- /wp:paragraph -->

{affiliate_block}

<!-- wp:paragraph -->
<p>{content['body_paragraph_3']}</p>
<!-- /wp:paragraph -->

<!-- wp:separator -->
<hr class="wp-block-separator"/>
<!-- /wp:separator -->

<!-- wp:paragraph -->
<p><em>Source: {story['source']} | Viral Score: {story['score']} | Category: {story['category'].title()}</em></p>
<!-- /wp:paragraph -->

<!-- wp:paragraph -->
<p>Tags: {tags_html}</p>
<!-- /wp:paragraph -->

<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "{content['seo_title']}",
  "description": "{content['meta_description']}",
  "publisher": {{
    "@type": "Organization",
    "name": "VOOOMIE Trends",
    "url": "https://vooomiegroup.com/vooomietrends"
  }},
  "datePublished": "{datetime.now().isoformat()}"
}}
</script>
"""

# ── LAYER 4: PUBLISH ENGINE ───────────────────────────────────────────────────

def scrape_og_image(url):
    """Scrape og:image or first image from article page."""
    try:
        res = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (compatible; VooomieBot/1.0)"
        })
        html = res.text
        # og:image (highest quality)
        og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
        if og: return og.group(1)
        og2 = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html)
        if og2: return og2.group(1)
        # twitter:image
        tw = re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', html)
        if tw: return tw.group(1)
        # first large img tag
        imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        for img in imgs:
            if any(ext in img.lower() for ext in [".jpg",".jpeg",".png",".webp"]):
                if img.startswith("http") and len(img) > 20:
                    return img
    except Exception as e:
        log.debug(f"og:image scrape failed for {url}: {e}")
    return None

def detect_video(url, summary="", title=""):
    """
    Detect video content from article URL, summary, or title.
    Returns dict with video_type and embed_code, or None.
    Supports: YouTube, TikTok, Twitter/X, Facebook, Instagram, direct MP4
    """
    text = (url + " " + summary + " " + title).lower()

    # ── YouTube ──────────────────────────────────────────────────────────────
    yt_patterns = [
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in yt_patterns:
        match = re.search(pattern, text)
        if match:
            vid_id = match.group(1)
            return {
                "type": "youtube",
                "id": vid_id,
                "url": f"https://www.youtube.com/watch?v={vid_id}",
                "thumbnail": f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg",
                "embed": f'''<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:12px;margin:16px 0">
<iframe src="https://www.youtube.com/embed/{vid_id}?rel=0&autoplay=0" 
  style="position:absolute;top:0;left:0;width:100%;height:100%;border:none"
  allow="accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture" 
  allowfullscreen loading="lazy"></iframe>
</div>'''
            }

    # ── TikTok ───────────────────────────────────────────────────────────────
    tt_match = re.search(r"tiktok\.com/@[^/]+/video/(\d+)", text)
    if tt_match:
        vid_id = tt_match.group(1)
        return {
            "type": "tiktok",
            "id": vid_id,
            "url": f"https://www.tiktok.com/embed/v2/{vid_id}",
            "embed": f'''<div style="position:relative;padding-bottom:120%;height:0;overflow:hidden;border-radius:12px;margin:16px 0;max-width:325px;margin-left:auto;margin-right:auto">
<iframe src="https://www.tiktok.com/embed/v2/{vid_id}" 
  style="position:absolute;top:0;left:0;width:100%;height:100%;border:none"
  allow="encrypted-media" allowfullscreen loading="lazy"></iframe>
</div>'''
        }

    # ── Twitter/X ─────────────────────────────────────────────────────────────
    tw_match = re.search(r"(?:twitter|x)\.com/\w+/status/(\d+)", text)
    if tw_match:
        tweet_id = tw_match.group(1)
        tweet_url = f"https://twitter.com/i/status/{tweet_id}"
        return {
            "type": "twitter",
            "id": tweet_id,
            "url": tweet_url,
            "embed": f'''<div style="margin:16px 0;border-radius:12px;overflow:hidden">
<blockquote class="twitter-tweet" data-dnt="true">
<a href="{tweet_url}">Loading tweet...</a>
</blockquote>
<script async src="https://platform.twitter.com/widgets.js" charset="utf-8"></script>
</div>'''
        }

    # ── Facebook Video ────────────────────────────────────────────────────────
    fb_match = re.search(r"facebook\.com/(?:watch|video).*?v=(\d+)", text)
    if not fb_match:
        fb_match = re.search(r"facebook\.com/.+/videos/(\d+)", text)
    if fb_match:
        fb_url = f"https://www.facebook.com/video/embed?video_id={fb_match.group(1)}"
        return {
            "type": "facebook",
            "id": fb_match.group(1),
            "url": fb_url,
            "embed": f'''<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;border-radius:12px;margin:16px 0">
<iframe src="{fb_url}"
  style="position:absolute;top:0;left:0;width:100%;height:100%;border:none"
  allowfullscreen loading="lazy"></iframe>
</div>'''
        }

    # ── Direct MP4/Video ──────────────────────────────────────────────────────
    mp4_match = re.search(r'(https?://[^\s<>]+\.(?:mp4|webm|ogg|mov))', text)
    if mp4_match:
        vid_url = mp4_match.group(1)
        return {
            "type": "direct",
            "url": vid_url,
            "embed": f'''<div style="margin:16px 0;border-radius:12px;overflow:hidden">
<video controls preload="none" style="width:100%;border-radius:12px;max-height:400px"
  poster="">
  <source src="{vid_url}" type="video/mp4">
  Your browser does not support video.
</video>
</div>'''
        }

    # ── Check if story is video-based by title keywords ───────────────────────
    video_keywords = ["watch:", "video:", "[video]", "(video)", "watch this", 
                      "viral video", "caught on camera", "cctv footage",
                      "exclusive video", "breaking video"]
    if any(kw in title.lower() for kw in video_keywords):
        return {"type": "keyword_detected", "embed": None}

    return None


def scrape_video_from_page(url):
    """Scrape article page for embedded video content."""
    try:
        res = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0 (compatible; VooomieBot/1.0)"
        })
        html = res.text

        # Check for YouTube embed
        yt = re.search(r"youtube\.com/embed/([a-zA-Z0-9_-]{11})", html)
        if not yt:
            yt = re.search(r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})", html)
        if not yt:
            yt = re.search(r"youtu\.be/([a-zA-Z0-9_-]{11})", html)
        if yt:
            vid_id = yt.group(1)
            return detect_video(f"https://youtu.be/{vid_id}")

        # Check for TikTok
        tt = re.search(r"tiktok\.com/@[^/]+/video/(\d+)", html)
        if tt:
            return detect_video(f"https://www.tiktok.com/@x/video/{tt.group(1)}")

        # Check for Twitter
        tw = re.search(r"twitter\.com/\w+/status/(\d+)", html)
        if not tw:
            tw = re.search(r"x\.com/\w+/status/(\d+)", html)
        if tw:
            return detect_video(f"https://twitter.com/x/status/{tw.group(1)}")

        # Check for direct MP4
        mp4 = re.search(r"src=[^>]+(https?://[^>]+\.mp4)", html)
        if mp4:
            return detect_video(mp4.group(1))

    except Exception as e:
        log.debug(f"Video scrape failed for {url}: {e}")
    return None


def upload_image_to_wp(image_url, title):
    """Download image and upload to WordPress media library."""
    if not WP_APP_PASSWORD or not image_url:
        return None
    try:
        img_res = requests.get(image_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; VooomieBot/1.0)"
        })
        if img_res.status_code != 200:
            return None
        content_type = img_res.headers.get("Content-Type", "image/jpeg")
        if not content_type.startswith("image"):
            return None
        ext = {"image/jpeg":".jpg","image/png":".png","image/webp":".webp","image/gif":".gif"}.get(content_type,".jpg")
        filename = re.sub(r"[^a-z0-9]+","-",title.lower())[:40] + ext
        import base64
        credentials = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
        media_res = requests.post(
            f"{WP_URL}/wp-json/wp/v2/media",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": content_type,
            },
            data=img_res.content,
            timeout=30
        )
        if media_res.status_code == 201:
            media_id = media_res.json()["id"]
            media_url = media_res.json()["source_url"]
            log.info(f"  ✦ Image uploaded to WordPress: {media_url}")
            return media_id, media_url
    except Exception as e:
        log.warning(f"  Image upload failed: {e}")
    return None, None

def publish_to_wordpress(story, content, image_url, video_data=None):
    """Publish to WordPress via XML-RPC — more compatible than REST API."""
    if not WP_APP_PASSWORD:
        log.warning("WordPress credentials not set — skipping")
        return None, None

    wp_category_map = {
        "politics":  174, "funny":     175, "lifestyle": 176,
        "sports":    177, "tech":      178, "celebrity": 179,
        "crime":     180, "business":  181, "general":   182,
    }
    category_id = wp_category_map.get(story.get("category", "general"), 182)

    headline = content.get("headline", story["title"])
    category = story.get("category", "general")
    img_query = content.get("image_search_query", f"{category} nigeria").replace(" ", "%20")
    img_url = f"https://source.unsplash.com/1200x630/?{img_query}"
    body = f"""<figure style="margin:0 0 20px 0">
<img src="{img_url}" alt="{headline[:100]}" style="width:100%;max-height:400px;object-fit:cover;border-radius:8px"/>
</figure>
<p><strong>{content.get('hook', '')}</strong></p>
<p>{content.get('body_paragraph_1', story.get('summary', ''))}</p>
<p>{content.get('body_paragraph_2', '')}</p>
<p>{content.get('body_paragraph_3', '')}</p>
<div style="background:#f8f9fa;padding:12px;border-radius:6px;margin-top:20px;font-size:14px">
📍 <strong>Source:</strong> {story.get('source', '')} &nbsp;|&nbsp; 🔥 <strong>Viral Score:</strong> {story.get('score', 0)} &nbsp;|&nbsp; 📂 <strong>Category:</strong> {story.get('category', '').title()}
</div>"""

    # Try REST API first with Basic Auth
    try:
        import base64
        credentials = base64.b64encode(f"{WP_USERNAME}:{WP_APP_PASSWORD}".encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {credentials}",
        }
        # ── Build media section (video takes priority over image) ──────────────
        media_id = 0
        media_section = ""

        if video_data and video_data.get("embed"):
            # Embed video at top of post
            vtype = video_data.get("type","video").upper()
            vurl  = video_data.get("url","")
            media_section = f'''<div style="background:#0a0a0a;border:1px solid #1a1a1a;border-radius:12px;padding:4px;margin-bottom:20px">
<div style="background:#ff000015;border-bottom:1px solid #ff000033;padding:8px 14px;border-radius:8px 8px 0 0;display:flex;align-items:center;gap:8px;margin-bottom:8px">
  <span style="background:#ff0000;color:#fff;font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px;letter-spacing:1px">{vtype}</span>
  <span style="font-size:12px;color:#888">Video content detected</span>
</div>
{video_data["embed"]}
</div>'''
            log.info(f"  ✦ {vtype} video embedded in post")

            # Also try to get thumbnail as featured image for social sharing
            if video_data.get("thumbnail") or image_url:
                thumb = video_data.get("thumbnail") or image_url
                result = upload_image_to_wp(thumb, headline)
                if result and result[0]:
                    media_id = result[0]

        elif image_url:
            # No video — use image
            result = upload_image_to_wp(image_url, headline)
            if result and result[0]:
                media_id = result[0]
                wp_img_url = result[1]
                media_section = f"<figure style=\'margin:0 0 20px 0;border-radius:10px;overflow:hidden\'><img src=\'{wp_img_url}\' alt=\'{headline[:80]}\' style=\'width:100%;max-height:450px;object-fit:cover;display:block\'/></figure>"

        body = media_section + body

        post_data = {
            "title":          headline,
            "content":        body,
            "status":         "publish",
            "categories":     [category_id],
            "featured_media": media_id,
        }
        log.info(f"  Posting to WordPress: {headline[:60]}...")
        res = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts",
            headers=headers,
            json=post_data,
            timeout=30
        )
        log.info(f"  WordPress response: {res.status_code}")
        if res.status_code == 201:
            post = res.json()
            wp_id  = post["id"]
            wp_url = post["link"]
            log.info(f"  ✦ WordPress post live: {wp_url}")
            return wp_id, wp_url
        else:
            log.error(f"  REST API error {res.status_code}: {res.text[:200]}")
    except Exception as e:
        log.error(f"  REST API failed: {e}")

    # Fallback: Try XML-RPC
    try:
        import xmlrpc.client
        log.info("  Trying XML-RPC fallback...")
        wp = xmlrpc.client.ServerProxy(f"{WP_URL}/xmlrpc.php")
        post = {
            "post_title":   headline,
            "post_content": body,
            "post_status":  "publish",
            "post_type":    "post",
            "terms": {"category": [str(category_id)]},
        }
        post_id = wp.wp.newPost(1, WP_USERNAME, WP_APP_PASSWORD, post)
        wp_url = f"{WP_URL}/?p={post_id}"
        log.info(f"  ✦ WordPress XML-RPC post live: ID {post_id}")
        return int(post_id), wp_url
    except Exception as e:
        log.error(f"  XML-RPC failed: {e}")

    return None, None


def post_to_telegram(content, post_url):
    """Blast to Telegram channel."""
    if not TELEGRAM_BOT_TOKEN:
        log.info("  Telegram token not set — skipping")
        return
    try:
        caption = content["telegram_post"].replace("[LINK]", post_url)
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id":    TELEGRAM_CHANNEL_ID,
                "text":       caption,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10
        )
        log.info(f"  ✦ Telegram blasted")
    except Exception as e:
        log.warning(f"  Telegram failed: {e}")

def post_to_twitter(content, post_url, image_url=None):
    """Post to Twitter/X using API v2 with OAuth 1.0a — clean implementation."""
    if not all([TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET]):
        log.info("  Twitter/X: credentials missing — skipping")
        return False
    try:
        import hmac as _hmac
        import hashlib as _hashlib
        import base64 as _base64
        import urllib.parse as _urlparse
        import time as _time

        # Build tweet text — max 280 chars
        headline = content.get("headline", "")
        tweet_body = content.get("tiktok_caption", headline)
        # Trim to fit URL
        max_len = 250 - len(post_url)
        if len(tweet_body) > max_len:
            tweet_body = tweet_body[:max_len-3] + "..."
        tweet_text = tweet_body + "\n\n" + post_url

        # OAuth 1.0a parameters
        nonce = _base64.b64encode(os.urandom(16)).decode().replace("=","").replace("+","").replace("/","")[:32]
        timestamp = str(int(_time.time()))

        oauth = {
            "oauth_consumer_key":     TWITTER_API_KEY,
            "oauth_nonce":            nonce,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp":        timestamp,
            "oauth_token":            TWITTER_ACCESS_TOKEN,
            "oauth_version":          "1.0",
        }

        # Build signature base string
        api_url = "https://api.twitter.com/2/tweets"
        all_params = {**oauth, "text": tweet_text}
        param_str = "&".join(
            f"{_urlparse.quote(str(k), safe='')}"
            f"={_urlparse.quote(str(v), safe='')}"
            for k, v in sorted(all_params.items())
        )
        base_str = (
            "POST"
            + "&" + _urlparse.quote(api_url, safe="")
            + "&" + _urlparse.quote(param_str, safe="")
        )
        signing_key = (
            _urlparse.quote(TWITTER_API_SECRET, safe="")
            + "&"
            + _urlparse.quote(TWITTER_ACCESS_SECRET, safe="")
        )
        signature = _base64.b64encode(
            _hmac.new(signing_key.encode("utf-8"), base_str.encode("utf-8"), _hashlib.sha1).digest()
        ).decode()
        oauth["oauth_signature"] = signature

        # Build Authorization header
        auth_header = "OAuth " + ", ".join(
            f'{_urlparse.quote(k, safe="")}="{_urlparse.quote(v, safe="")}"'
            for k, v in sorted(oauth.items())
        )

        # Post the tweet
        res = requests.post(
            api_url,
            headers={
                "Authorization": auth_header,
                "Content-Type":  "application/json",
            },
            json={"text": tweet_text},
            timeout=20
        )

        log.info(f"  [TW] Response {res.status_code}: {res.text[:200]}")

        if res.status_code in [200, 201]:
            tweet_id = res.json().get("data", {}).get("id", "")
            log.info(f"  ✦ Twitter/X posted: https://twitter.com/VOOOMIETrends/status/{tweet_id}")
            return True
        else:
            log.error(f"  Twitter error {res.status_code}: {res.text[:300]}")
            return False

    except Exception as e:
        log.error(f"  Twitter post failed: {e}")
        return False


def post_to_facebook(content, post_url, image_url=None):
    """Post to Facebook Page using Graph API v19."""
    log.info(f"  [FB] PAGE_ID={'SET(' + FACEBOOK_PAGE_ID[:8] + '...)' if FACEBOOK_PAGE_ID else 'MISSING'} TOKEN={'SET' if FACEBOOK_ACCESS_TOKEN else 'MISSING'}")
    if not FACEBOOK_PAGE_ID or not FACEBOOK_ACCESS_TOKEN:
        log.info("  Facebook: credentials not set — skipping")
        return False
    try:
        headline = content.get("headline", "")
        caption  = content.get("instagram_caption", content.get("tiktok_caption", headline))
        # Clean caption — remove hashtags for Facebook (they look spammy)
        import re as _re
        clean_caption = _re.sub(r"#\w+", "", caption).strip()
        message = clean_caption + "\n\n🔗 " + post_url + "\n\n📱 Follow VOOOMIE Trends for more!"

        # Always post as link post for better reach on Facebook
        post_data = {
            "message":      message,
            "link":         post_url,
            "access_token": FACEBOOK_ACCESS_TOKEN,
        }

        log.info(f"  [FB] Posting to page {FACEBOOK_PAGE_ID[:8]}...")
        res = requests.post(
            f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed",
            data=post_data,
            timeout=25
        )

        log.info(f"  [FB] Response {res.status_code}: {res.text[:300]}")

        if res.status_code == 200:
            result = res.json()
            post_id = result.get("id", "")
            log.info(f"  ✦ Facebook posted! Post ID: {post_id}")
            return True
        else:
            # Parse error details
            try:
                err = res.json().get("error", {})
                log.error(f"  Facebook error {res.status_code}: {err.get('message','unknown')} (code {err.get('code','?')})")
                if err.get("code") in [190, 102]:
                    log.error("  ⚠️ Facebook token expired! Generate a new long-lived token.")
                elif err.get("code") == 200:
                    log.error("  ⚠️ Facebook permissions missing! Need pages_manage_posts permission.")
            except:
                log.error(f"  Facebook error {res.status_code}: {res.text[:200]}")
            return False

    except Exception as e:
        log.error(f"  Facebook post failed: {e}")
        return False


def post_to_whatsapp_log(content, post_url):
    """Log WhatsApp broadcast message (manual send via WhatsApp Business API)."""
    msg = content["whatsapp_blast"].replace("[LINK]", post_url)
    # WhatsApp Business API requires approval for broadcast templates.
    # Log to file so it can be sent via manual broadcast or approved template.
    with open("whatsapp_queue.txt", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]\n{msg}\n\n---\n\n")
    log.info(f"  ✦ WhatsApp message queued in whatsapp_queue.txt")

def post_to_social_queue(content, post_url, story):
    """Write all social captions to a queue file for Buffer/Later scheduling."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "story":     story["title"],
        "score":     story["score"],
        "url":       post_url,
        "platforms": {
            "tiktok":    content["tiktok_caption"],
            "instagram": content["instagram_caption"].replace("[LINK]", post_url),
            "whatsapp":  content["whatsapp_blast"].replace("[LINK]", post_url),
            "telegram":  content["telegram_post"].replace("[LINK]", post_url),
        }
    }
    with open("social_queue.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"  ✦ Social captions written to social_queue.jsonl")

def publish_story(story):
    """Full publish pipeline for one hot story."""
    log.info(f"\n{'═'*60}")
    log.info(f"PUBLISHING: {story['title'][:70]}…")
    log.info(f"Score: {story['score']} | Category: {story['category']} | Source: {story['source']}")

    # Step 1: AI rewrite
    content = ai_rewrite(story)

    # Step 2: Detect VIDEO content first (higher priority than images)
    video_data = None
    story_link = story.get("link", "")
    story_summary = story.get("summary", "")
    story_title = story.get("title", "")

    # Check RSS feed data for video links
    video_data = detect_video(story_link, story_summary, story_title)

    # If no video in RSS, scrape the article page
    if not video_data and story_link:
        log.info(f"  Checking page for video: {story_link[:60]}...")
        video_data = scrape_video_from_page(story_link)

    if video_data:
        log.info(f"  ✦ VIDEO detected: {video_data.get('type','unknown')} — {video_data.get('url','')[:60]}")
    else:
        log.info(f"  No video found — using image")

    # Step 2b: Get REAL image from article source
    image_url = story.get("image_url")  # from RSS media tags

    # YouTube thumbnail takes priority if YouTube video
    if video_data and video_data.get("type") == "youtube" and video_data.get("thumbnail"):
        image_url = video_data["thumbnail"]
        log.info(f"  Using YouTube thumbnail")

    # Scrape real og:image from article page
    if not image_url:
        log.info(f"  Fetching real image from article...")
        image_url = fetch_image_from_article(
            story_link,
            story.get("summary","")
        )

    # Last resort — Unsplash with relevant query
    if not image_url:
        query = content.get("image_search_query", f"{story.get('category','news')} nigeria")
        image_url = fetch_unsplash_image(query)
        log.info(f"  Using Unsplash fallback: {query}")
    else:
        log.info(f"  Real image: {image_url[:70]}")

    # Step 3: Publish to WordPress
    wp_id, wp_url = publish_to_wordpress(story, content, image_url, video_data)
    post_url = wp_url or f"{WP_URL}/vooomietrends/{story_hash(story['title'])[:8]}"

    # Step 4: Social distribution — all platforms
    platforms = []
    if wp_id:
        platforms.append("WordPress")

    # Telegram
    post_to_telegram(content, post_url)
    platforms.append("Telegram")

    # Twitter/X
    log.info(f"  [TW] API_KEY={'SET' if TWITTER_API_KEY else 'MISSING'} ACCESS_TOKEN={'SET' if TWITTER_ACCESS_TOKEN else 'MISSING'}")
    if TWITTER_API_KEY and TWITTER_ACCESS_TOKEN:
        ok = post_to_twitter(content, post_url, image_url)
        if ok: platforms.append("Twitter/X")
    else:
        log.info("  Twitter/X: credentials missing — skipping")

    # Facebook — always attempt, function handles missing credentials
    ok = post_to_facebook(content, post_url, image_url)
    if ok: platforms.append("Facebook")

    # WhatsApp queue + social captions
    post_to_whatsapp_log(content, post_url)
    platforms.append("WhatsApp Queue")
    post_to_social_queue(content, post_url, story)
    platforms.append("Social Queue")

    # Step 5: Save to DB
    if wp_id:
        save_published(wp_id, story["title"], post_url, story["category"], story["score"], platforms)
        mark_seen(story["title"], story["source"], story["score"], published=True)

    log.info(f"✦ COMPLETE: Published to {', '.join(platforms)}")
    log.info(f"{'═'*60}\n")
    return post_url

# ── LAYER 5: MONETIZATION HELPERS ────────────────────────────────────────────

def inject_adsense_snippet():
    """
    Returns AdSense auto-ads script to add to WordPress header.
    Add via Appearance > Theme Editor > header.php or use 'Insert Headers and Footers' plugin.
    """
    return """
<!-- VOOOMIE AdSense Auto Ads -->
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-XXXXXXXXXXXXXXXXX" crossorigin="anonymous"></script>
<!-- Replace ca-pub-XXXXXXXXXXXXXXXXX with your actual AdSense publisher ID -->
"""

def print_monetization_report():
    """Print a monetization status report."""
    conn = sqlite3.connect("vooomie.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM published_posts")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM published_posts WHERE created_at >= ?",
              ((datetime.now() - timedelta(hours=24)).isoformat(),))
    today = c.fetchone()[0]
    conn.close()

    log.info("\n" + "═"*60)
    log.info("VOOOMIE MONETIZATION REPORT")
    log.info("═"*60)
    log.info(f"Total posts published: {total}")
    log.info(f"Posts in last 24h:     {today}")
    log.info(f"Est. daily views:      {today * 350:,}  (avg 350/post)")
    log.info(f"Est. daily AdSense:    ${today * 350 * 0.003:.2f}  (RPM $3)")
    log.info(f"Est. monthly revenue:  ${today * 350 * 0.003 * 30:.2f}")
    log.info("\nUNLOCK CHECKLIST:")
    log.info(f"  {'✦' if total >= 30 else '○'} AdSense: need 30 posts ({total}/30)")
    log.info(f"  {'✦' if today >= 5 else '○'} TikTok Creator Fund: need daily posts")
    log.info(f"  {'✦' if total >= 10 else '○'} Jumia Affiliate: need 10 posts ({total}/10)")
    log.info("═"*60 + "\n")

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────

def sync_to_gist():
    """Push real engine state to GitHub Gist so dashboard can read it publicly."""
    if not GITHUB_TOKEN:
        log.warning("GITHUB_TOKEN not set — skipping gist sync")
        return
    try:
        engine_state["lastUpdated"] = datetime.now().isoformat()
        res = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            json={"files": {"vooomie-data.json": {"content": json.dumps(engine_state, indent=2)}}},
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=15
        )
        if res.status_code == 200:
            log.info("✦ Synced real data to GitHub Gist → dashboard updated")
        else:
            log.warning(f"Gist sync returned {res.status_code}: {res.text[:100]}")
    except Exception as e:
        log.warning(f"Gist sync failed: {e}")

def add_engine_log(msg, type="info"):
    """Add to in-memory log and keep last 50."""
    engine_state["logs"].insert(0, {
        "msg": msg, "type": type,
        "time": datetime.now().strftime("%H:%M:%S")
    })
    engine_state["logs"] = engine_state["logs"][:50]

def run_scan_cycle():
    """One full scan cycle: scrape → score → publish → sync to dashboard."""
    log.info(f"\n{'▶'*20} SCAN CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {'◀'*20}")
    engine_state["status"] = "scanning"

    # Layer 1: Scrape
    raw = scrape_rss_sources()
    raw += fetch_google_trends()
    engine_state["scanCount"] += len(raw)

    # Layer 2: Score & filter
    hot = filter_and_score(raw)

    # Score ALL stories for dashboard display (not just hot ones)
    all_scored = filter_and_score_all(raw)
    engine_state["recentStories"] = [{
        "title":    s["title"],
        "category": s.get("category", "general"),
        "source":   s.get("source", ""),
        "score":    s.get("score", 0),
        "velocity": s.get("velocity", 0),
        "sentiment":s.get("sentiment", 0),
        "cross":    s.get("crossPlatform", s.get("cross", 0)),
        "hot":      s.get("score", 0) >= VIRAL_THRESHOLD,
        "time":     datetime.now().isoformat(),
    } for s in all_scored[:30]]

    # Use top scored stories even if none meet threshold
    publish_list = hot if hot else sorted(all_scored, key=lambda x: x["score"], reverse=True)[:5]
    add_engine_log(f"Scraped {len(raw)} stories — {len(publish_list)} to publish", "info")

    if not publish_list:
        log.info("No stories found this cycle.")
        engine_state["status"] = "idle"
        sync_to_gist()
        return

    # Layer 3+4: Publish top stories
    published_count = 0
    for story in publish_list[:5]:
        try:
            post_url = publish_story(story)

            # Update state with real published post
            views = 0
            rev   = 0.0
            engine_state["publishCount"] += 1
            engine_state["totalViews"]   += views
            engine_state["totalEarnings"] = round(engine_state["totalEarnings"] + rev, 2)
            engine_state["recentPublished"].insert(0, {
                "title":       story["title"],
                "category":    story["category"],
                "source":      story["source"],
                "score":       story["score"],
                "url":         post_url,
                "platforms":   ["WordPress", "Telegram", "WhatsApp"],
                "publishedAt": datetime.now().isoformat(),
                "pageViews":   views,
                "revenue":     rev,
            })
            engine_state["recentPublished"] = engine_state["recentPublished"][:30]
            add_engine_log(f"✦ PUBLISHED: {story['title'][:60]}… (score {story['score']})", "success")
            published_count += 1
            time.sleep(8)
        except Exception as e:
            log.error(f"Failed to publish '{story['title'][:50]}': {e}")
            add_engine_log(f"✗ Publish failed: {str(e)[:60]}", "error")

    engine_state["status"] = "idle"
    log.info(f"Cycle complete: {published_count}/{len(hot)} hot stories published")

    # Sync everything to JSONBin → dashboard picks it up
    sync_to_gist()
    print_monetization_report()

def main():
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║   VOOOMIE TRENDS VIRAL ENGINE — STARTING    ║")
    log.info("║   vooomiegroup.com/trends  🇳🇬              ║")
    log.info("╚══════════════════════════════════════════════╝")
    
    init_db()
    
    if not ANTHROPIC_API_KEY:
        log.warning("⚠ ANTHROPIC_API_KEY not set — AI rewrites disabled (using fallback)")
    if not WP_APP_PASSWORD:
        log.warning("⚠ WP_APP_PASSWORD not set — WordPress publishing disabled")
    if not TELEGRAM_BOT_TOKEN:
        log.warning("⚠ TELEGRAM_BOT_TOKEN not set — Telegram blasts disabled")
    
    log.info(f"Viral threshold: {VIRAL_THRESHOLD} | Scan interval: {SCAN_INTERVAL_MIN}min")
    log.info("Starting first scan in 5 seconds...\n")
    time.sleep(5)
    
    while True:
        try:
            run_scan_cycle()
        except KeyboardInterrupt:
            log.info("\n✦ Engine stopped by user. Goodbye! 🇳🇬")
            break
        except Exception as e:
            log.error(f"Scan cycle error: {e}")
        
        log.info(f"⏸ Sleeping {SCAN_INTERVAL_MIN} minutes until next scan…")
        time.sleep(SCAN_INTERVAL_MIN * 60)

if __name__ == "__main__":
    main()
