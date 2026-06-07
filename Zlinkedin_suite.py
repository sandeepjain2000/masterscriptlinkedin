#!/usr/bin/env python3
"""
LinkedIn Suite — Combined Bot  (Z-edition)
Runs all LinkedIn tasks in one browser window, each in its own tab:
  Task 1:  AI Comment on advocate posts
  Task 1B: AI Comment on TPO posts
  Task 1C: AI Comment on startup funding posts (funding required; SaaS optional)
  Task 2:  Congratulate achievement posts
  Task 3:  Like advocate posts
  Task 4:  Post today's content from SQLite (Selenium version)
  Task 7:  Instagram Like & Comment

Startup:
  1. Scan open Firefox windows for one whose title contains "LinkedIn".
     If none found, use a Firefox window whose title contains "Instagram".
     If neither found -> quit with instructions.
  2. Bring that window to front (ctypes ALT trick, same as Z.py).
  3. Attach Selenium to the EXISTING Firefox via --connect-existing.
     Firefox must have been launched with --marionette  (or
     about:config -> marionette.enabled = true).
     If attach fails -> quit with setup instructions.
  4. Verify the session is logged in, then run all tasks in new tabs.
  5. At the end, close Firefox (Selenium quit + OS window close; connect-existing
     alone does not shut down the browser).
"""

import os
import sys
import time
import random
import logging
import sqlite3
import hashlib
import subprocess
import ctypes
import winsound
import urllib.parse
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except ImportError:
    PYGETWINDOW_AVAILABLE = False

try:
    import cv2
    import numpy as np
    from PIL import ImageGrab
    import pyautogui
    import pyperclip
    VISUAL_POST_AVAILABLE = True
except ImportError:
    VISUAL_POST_AVAILABLE = False

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

_claudes = next((p for p in Path(__file__).resolve().parents if p.name == "Claudes"), None)
if _claudes is None:
    raise ImportError("Claudes root not found (expected ...\\Claudes\\nvidia_keys)")
sys.path.insert(0, str(_claudes))
from nvidia_llm import (
    NVIDIA_KEYS_DIR,
    NVIDIA_MODEL,
    discover_nvidia_key_files,
    nvidia_chat,
)

_ai_keys_used: set[str] = set()

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.service import Service

# Clear terminal at startup
os.system("cls" if os.name == "nt" else "clear")

# ==================== PATHS & CONFIG ====================
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR      = os.path.join(SCRIPT_DIR, "logs_and_reports")
os.makedirs(LOG_DIR, exist_ok=True)
SUITE_LOG    = os.path.join(LOG_DIR, f"linkedin_suite_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Port Firefox must be listening on for Marionette (default 2828)
MARIONETTE_PORT = 2828

# Child scripts and data live under SmallNotFrequent (moved from Claudes root)
SMALL_NOT_FREQUENT   = os.path.join(str(_claudes), "SmallNotFrequent")

# Absolute paths to the existing SQLite databases (unchanged from originals)
COMMENTS_DB  = os.path.join(SMALL_NOT_FREQUENT, "LinkedIn_Like", "Working", "linkedin_ai_comments.db")
CONGRATS_DB  = os.path.join(SMALL_NOT_FREQUENT, "LinkedIn_Like", "working", "congratulations.db")
LIKES_DB     = os.path.join(SMALL_NOT_FREQUENT, "LinkedIn_Like", "working", "linkedin_likes.db")
POSTS_DB     = os.path.join(SMALL_NOT_FREQUENT, "LinkedIn_post", "Working", "linkedin_posts.db")

# ==================== INSTAGRAM CONFIG ====================
IG_SCRIPT_DIR        = os.path.join(SMALL_NOT_FREQUENT, "Instagram", "Working")
IG_HEART_EMPTY_PNG   = os.path.join(IG_SCRIPT_DIR, "heart_empty.png")
IG_HEART_FILLED_PNG  = os.path.join(IG_SCRIPT_DIR, "heart_filled.png")
IG_MY_USERNAME       = "jain35"
IG_COMMENT_TEXT      = "✨"
IG_PROFILES_PER_RUN  = 10   # max profiles to process per run

IG_TARGET_PROFILES = [
    "https://www.instagram.com/sandhya_moses_/",
    "https://www.instagram.com/drsonalitholia/",
    "https://www.instagram.com/ajaysenjain8/",
    "https://www.instagram.com/serena.moses6/",
    "https://www.instagram.com/charu.bansal311/",
    "https://www.instagram.com/fabricjourneywithakshaytholia/",
    "https://www.instagram.com/saanyajain/",
    "https://www.instagram.com/ysimages_by_yuvraj/",
    "https://www.instagram.com/akshay.tholia/",
    "https://www.instagram.com/sparklebysalika/",
    "https://www.instagram.com/stories/coolarchiek/",
    "https://www.instagram.com/bakingbros.co/",
    "https://www.instagram.com/zedekventures/",
]

PROFILE_NAME = "DvUA0K9i.Profile 2"   # Used only as a DB key label

# -- Task 1: Comment ----------------------------------------------------------
# Task 1 keyword pools — 30 keywords cycling by day-of-month
_COMMENT_KEYWORDS_GRP1 = [
    "advocate criminal mumbai",
    "advocate family delhi",
    "lawyer corporate bangalore",
    "legal professional compliance hyderabad",
    "corporate lawyer mumbai india",
    "advocate criminal mumbai",
    "advocate civil delhi",
    "litigation lawyer civil chennai",
    "legal updates corporate pune india",
    "advocate practice general kolkata",
    "indian lawyer tax gurgaon india",
    "advocate property ahmedabad",
]
_COMMENT_KEYWORDS_GRP2 = [
    "advocate criminal delhi",
    "lawyer startup bangalore india",
    "corporate lawyer compliance pune",
    "advocate family mumbai",
    "lawyer intellectual property chennai",
    "advocate arbitration delhi india",
    "legal professional contracts hyderabad",
    "lawyer tax mumbai india",
    "advocate real estate bangalore",
    "litigation lawyer commercial delhi",
    "lawyer employment pune",
    "advocate civil ahmedabad",
    "lawyer mergers acquisitions mumbai",
    "advocate criminal kolkata",
    "lawyer banking finance delhi",
    "advocate consumer court chennai",
    "lawyer data privacy bangalore india",
    "advocate environmental law hyderabad",
]
_ALL_COMMENT_KEYWORDS = _COMMENT_KEYWORDS_GRP1 + _COMMENT_KEYWORDS_GRP2  # 30 total
_COMMENT_DATE_FILTERS = ["past-24h", "past-week", "past-month"]


def get_comment_search_url():
    """Build a dynamic LinkedIn content-search URL for Task 1.
    Keyword is chosen randomly each call so different posts appear every run."""
    kw = random.choice(_ALL_COMMENT_KEYWORDS)
    kw = _ai_augment_keyword(kw, "legal professionals, advocates, law firms, court cases")
    logger.info(f"  🔑 Keyword: {kw}")
    params = urllib.parse.urlencode({
        "keywords":   kw,
        "origin":     "SWITCH_SEARCH_VERTICAL",
        "sortBy":     "date_posted",
    }, quote_via=urllib.parse.quote)
    return f"https://www.linkedin.com/search/results/content/?{params}"
# -- Task 1B: TPO Comment -----------------------------------------------------
# 30 TPO-specific keywords, same day-of-month cycling as Task 1
_TPO_KEYWORDS = [
    "training & placement office tpo university",
    "training & placement office tpo college",
    "training & placement office tpo engineering college",
    "training & placement office tpo campus recruitment",
    "training & placement office tpo placement cell",
    "training & placement office tpo higher education",
    "training & placement office tpo institute of technology",
    "training & placement office tpo career services",
    "training & placement office tpo student placement",
    "training & placement office tpo internship cell",
    "training & placement office tpo campus hiring",
    "training & placement office tpo recruitment cell",
    "training & placement office tpo alumni relations",
    "training & placement office tpo corporate relations",
    "training & placement office tpo employability",
    "training & placement office tpo skill development",
    "training & placement office tpo placement coordinator",
    "training & placement office tpo campus placements india",
    "training & placement office tpo university placements",
    "training & placement office tpo college placements india",
    "training & placement office tpo career guidance",
    "training & placement office tpo job placement cell",
    "training & placement office tpo internship opportunities",
    "training & placement office tpo placement officer",
    "training & placement office tpo dean placements",
    "training & placement office tpo industry interface",
    "training & placement office tpo campus recruitment drive",
    "training & placement office tpo placement statistics",
    "training & placement office tpo student training programs",
    "training & placement office tpo corporate tie ups",
]

_TPO_DATE_FILTERS = ["past-week", "past-month"]   # TPO posts are sparse — skip past-24h

def get_tpo_search_url():
    """Build a dynamic LinkedIn content-search URL for Task 1B (TPO keywords).
    Keyword is chosen randomly each call so different posts appear every run."""
    kw = random.choice(_TPO_KEYWORDS)
    kw = _ai_augment_keyword(kw, "university placements, campus recruitment, student placements")
    logger.info(f"  🔑 TPO Keyword: {kw}")
    params = urllib.parse.urlencode({
        "keywords":   kw,
        "origin":     "SWITCH_SEARCH_VERTICAL",
        "sortBy":     "date_posted",
    }, quote_via=urllib.parse.quote)
    return f"https://www.linkedin.com/search/results/content/?{params}"

# -- Task 1C: Fundraising Comment (funding required; SaaS optional) ------------
FUNDRAISING_SEARCH_URL = (
    "https://www.linkedin.com/search/results/content/"
    "?keywords=startup%20funding&origin=SWITCH_SEARCH_VERTICAL"
)
_FUNDRAISING_KEYWORDS = [
    "startup funding",
    "startup fundraising",
    "seed round funding",
    "pre-seed funding",
    "Series A funding",
    "Series B funding",
    "venture capital funding",
    "investment round startup",
    "raised funding startup",
    "angel funding startup",
    "fundraising founder journey",
    "closed funding round",
    "growth capital startup",
    "equity fundraising startup",
    "SaaS fundraising",   # optional niche — still valid when funding is present
]
FUNDING_POST_KEYWORDS = [
    "funding", "fundraise", "fund raise", "fundraising",
    "seed round", "pre-seed", "pre seed", "series a", "series b", "series c",
    "venture capital", "vc funding", "vc round", "vc-backed", "vc backed",
    "investment round", "raised funding", "raised $", "raised usd", "raised €",
    "raised inr", "raised ₹", "capital raise", "closed round", "funding round",
    "angel round", "angel funding", "angel investor", "growth round",
    "secured funding", "announced funding", "raised capital", "term sheet",
    "demo day", "pitch competition",
]
FUNDRAISING_SCROLL_MIN = 2
FUNDRAISING_SCROLL_MAX = 5   # bounded random scroll — never infinite


def is_funding_related_post(post_text: str, author: str = "") -> bool:
    """True if post text or author line mentions funding / fundraising (any startup sector)."""
    combined = f"{post_text} {author}".lower()
    return any(kw in combined for kw in FUNDING_POST_KEYWORDS)


def get_fundraising_search_url():
    """LinkedIn content search for startup funding posts (random keyword variant)."""
    kw = random.choice(_FUNDRAISING_KEYWORDS)
    kw = _ai_augment_keyword(kw, "startup funding and fundraising across any sector — seed, Series A, VC, angel")
    logger.info(f"  🔑 Fundraising keyword: {kw}")
    params = urllib.parse.urlencode({
        "keywords":   kw,
        "origin":     "SWITCH_SEARCH_VERTICAL",
    }, quote_via=urllib.parse.quote)
    return f"https://www.linkedin.com/search/results/content/?{params}"

MAX_COMMENTS_PER_RUN   = 2
BETWEEN_COMMENTS_MIN   = 8.0
BETWEEN_COMMENTS_MAX   = 16.0
FALLBACK_COMMENTS = [
    "Insightful post, thanks for sharing!",
    "Great perspective on this topic.",
    "Very interesting read, appreciate you sharing this.",
    "Thanks for the detailed insights here."
]
# AI comments use NVIDIA NIM (local nvidia_keys/, random key per call)
MAX_COMMENT_GENERATION_ATTEMPTS = 2

# First-person career/network phrases that usually misfire on unrelated posts
_SELF_PROMO_COMMENT_PHRASES = (
    "expanding my network",
    "new chapter in my career",
    "embarking on this new chapter",
    "looking forward to collaborating with the right individuals",
    "meaningful partnerships that can help drive growth",
    "as i embark on",
    "open to work",
    "excited to announce my",
    "starting a new role",
    "joining as",
)

# -- Task 2: Congratulate -----------------------------------------------------
# Task 2 keyword pools — one keyword picked by day-of-month, date filter picked randomly
_CONGRATS_KEYWORDS_ANNOUNCE = [
    "excited to share", "delighted to announce", "pleased to share",
    "grateful to announce", "honored to share", "proud to announce",
    "super excited to share", "humbled to share", "happy to announce", "glad to share",
]
_CONGRATS_KEYWORDS_ROLE = [
    "starting a new role", "joining as", "joined as", "stepping into a new role",
    "beginning my journey as", "taking on a new position", "new opportunity",
    "career update", "role transition", "next chapter",
]
_CONGRATS_KEYWORDS_PROMO = [
    "got promoted", "promotion announcement", "stepped into a leadership role",
    "moving into a new position internally", "elevated to", "career milestone",
]
_CONGRATS_KEYWORDS_OFFER = [
    "accepted an offer", "excited for this new journey",
    "looking forward to this new role", "officially starting as",
]
_ALL_CONGRATS_KEYWORDS = (
    _CONGRATS_KEYWORDS_ANNOUNCE +
    _CONGRATS_KEYWORDS_ROLE +
    _CONGRATS_KEYWORDS_PROMO +
    _CONGRATS_KEYWORDS_OFFER
)
_CONGRATS_DATE_FILTERS = ["past-24h", "past-week", "past-month"]


def get_congrats_search_url():
    """Build a randomised LinkedIn search URL for Task 2.
    Keyword is chosen by day-of-month (deterministic per day, cycles through all 34).
    Date filter is chosen randomly each run.
    """
    import urllib.parse
    day   = datetime.now().day                          # 1-31
    kw    = _ALL_CONGRATS_KEYWORDS[(day - 1) % len(_ALL_CONGRATS_KEYWORDS)]
    params = urllib.parse.urlencode({
        "keywords": kw,
        "sortBy": "date_posted",
        "origin": "GLOBAL_SEARCH_HEADER",
    })
    url = f"https://www.linkedin.com/search/results/content/?{params}"
    logger.info(f"  🔍 Congrats search: keyword='{kw}'")
    return url
COMMENT_TEMPLATES = [
    "Congratulations on this achievement! \U0001f389 Well deserved!",
    "Amazing accomplishment! Great job! \U0001f44f",
    "So well deserved! Congratulations! \U0001f680",
    "Congratulations! Wishing you continued success! \U0001f3af",
    "What a great achievement! Congrats! \U0001f31f",
    "So happy for you! Congratulations! \U0001f38a",
    "Outstanding work! Congratulations! \U0001f4aa",
    "This is fantastic news! Congratulations! \U0001f389"
]
ACHIEVEMENT_KEYWORDS = [
    "achieved", "accomplished", "graduated", "promoted",
    "new role", "joined", "started", "celebrate", "milestone",
    "excited to announce", "thrilled to share", "honored to",
    "certification", "award", "recognized"
]

# -- Task 3: Like -------------------------------------------------------------
def get_like_search_url():
    """Build a dynamic LinkedIn content-search URL for Task 3.
    Keyword is chosen randomly each call."""
    kw = random.choice(_ALL_COMMENT_KEYWORDS)
    logger.info(f"  🔑 Keyword: {kw}")
    params = urllib.parse.urlencode({
        "keywords":   kw,
        "origin":     "SWITCH_SEARCH_VERTICAL",
        "sortBy":     "date_posted",
    }, quote_via=urllib.parse.quote)
    return f"https://www.linkedin.com/search/results/content/?{params}"
MAX_LIKES_PER_RUN    = 2
MAX_SCROLL_ROUNDS    = 40
BETWEEN_LIKES_MIN    = 6.0
BETWEEN_LIKES_MAX    = 14.0

# -- Shared timing ------------------------------------------------------------
MAX_POSTS_TO_SCAN       = 50
WAIT_FOR_POSTS_SECONDS  = 45
SCROLL_PX               = 1200
HUMAN_DELAY_MIN         = 2.0
HUMAN_DELAY_MAX         = 4.0

# ==================== LOGGING ====================
def setup_logging():
    fmt  = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = logging.FileHandler(SUITE_LOG, encoding='utf-8')
    fh.setFormatter(fmt)
    root.addHandler(fh)
    return logging.getLogger(__name__)

logger = setup_logging()


def log_ai_provider_config():
    """Log shared NVIDIA key pool at startup (filename only, never the secret)."""
    try:
        key_files = discover_nvidia_key_files()
        names = [p.name for p in key_files]
        logger.info(f"  AI provider : NVIDIA NIM ({NVIDIA_MODEL})")
        logger.info(f"  Keys folder : {NVIDIA_KEYS_DIR}")
        logger.info(f"  Keys pool   : {len(names)} file(s) — {', '.join(names)}")
    except Exception as e:
        logger.error(f"  AI keys unavailable: {e}")


def suite_nvidia_chat(user_prompt: str, system_prompt: str | None = None, **kwargs):
    """Call NVIDIA NIM, log key to suite log, and track keys used this run."""
    comment, key_id = nvidia_chat(
        user_prompt,
        system_prompt,
        log_fn=logger.info,
        **kwargs,
    )
    _ai_keys_used.add(key_id)
    return comment, key_id


def _ai_augment_keyword(base_keyword: str, context: str) -> str:
    """Use AI to slightly modify or generate a synonymous search keyword to diversify the feed."""
    prompt = f"""You are an expert at LinkedIn search operators. 
I have a base keyword/phrase I use to find posts about: {context}.
The base keyword is: "{base_keyword}"

Generate ONE slightly modified, alternative, or synonymous search phrase that will find similar but distinct posts.
For example, if the base is "hiring lawyers", you might suggest "looking for legal counsel" or "joining our law firm".
Output ONLY the raw search string. No quotes, no explanations, no preamble. Keep it under 5 words."""
    try:
        new_kw, _ = suite_nvidia_chat(prompt, max_tokens=20, temperature=0.8)
        new_kw = new_kw.strip('"\'. \n\r')
        if new_kw and len(new_kw) > 3:
            logger.info(f"  🧠 AI augmented keyword: '{base_keyword}' -> '{new_kw}'")
            return new_kw
    except Exception as e:
        logger.warning(f"  ⚠️ AI keyword augmentation failed: {e}")
    return base_keyword


def _parse_validation_verdict(raw: str) -> tuple[bool, str]:
    text = (raw or "").strip()
    upper = text.upper()
    if "VERDICT: PASS" in upper or upper.startswith("PASS"):
        return True, "ok"
    if "VERDICT: FAIL" in upper:
        reason = text.split("—", 1)[-1].split("-", 1)[-1].strip() if "—" in text or "FAIL" in upper else text
        return False, reason or "failed validation"
    if "FAIL" in upper:
        return False, text[:200]
    return False, f"unclear validator response: {text[:120]}"


def _rule_based_comment_check(comment: str, post_text: str) -> tuple[bool, str]:
    """Fast local checks for common bad AI comments (no API call)."""
    c = (comment or "").strip().lower()
    p = (post_text or "").strip().lower()
    if len(c) < 12:
        return False, "comment too short"
    if len(c) > 600:
        return False, "comment too long"
    if p and len(p) > 40 and c == p[: len(c)]:
        return False, "comment duplicates the post"

    post_about_self_career = any(
        kw in p for kw in (
            "starting a new role", "joined as", "new role", "excited to share that i",
            "open to work", "career update", "promotion", "new chapter",
        )
    )
    if not post_about_self_career:
        hits = [phrase for phrase in _SELF_PROMO_COMMENT_PHRASES if phrase in c]
        if hits:
            return False, f"reads like commenter's own career update, not a reply ({hits[0]})"
    return True, "ok"


def validate_linkedin_comment(comment: str, post_text: str, mode: str = "tpo") -> tuple[bool, str]:
    """Check that an AI comment fits the post before posting."""
    ok, reason = _rule_based_comment_check(comment, post_text)
    if not ok:
        logger.info(f"  🧪 Comment validation (rules): FAIL — {reason}")
        return False, reason

    persona = {
        "tpo": "TPO / placement officer",
        "advocate": "legal professional / advocate",
        "fundraising": "startup founder / operator / investor engaging on funding and fundraising",
    }.get(mode, "LinkedIn professional")
    prompt = f"""You are a strict LinkedIn comment quality checker.

Persona the comment should sound like: {persona}

Original post:
{post_text[:1200]}

Proposed comment:
{comment}

Does this comment make sense as a reply to THIS post?
PASS only if ALL are true:
- Directly relevant to the post topic (event, advice, hiring, opinion, etc.)
- NOT generic self-promotion or the commenter's unrelated job search / career journey
- NOT congratulating the commenter themselves
- Professional, grammatical, 1-3 sentences
- Sounds like a peer engaging with the post author

Reply with exactly one line:
VERDICT: PASS
or
VERDICT: FAIL — one short reason"""

    try:
        verdict, key_id = suite_nvidia_chat(
            prompt,
            max_tokens=80,
            temperature=0.1,
        )
        ok, reason = _parse_validation_verdict(verdict)
        if ok:
            logger.info(f"  🧪 Comment validation (AI, key={key_id}): PASS")
        else:
            logger.info(f"  🧪 Comment validation (AI, key={key_id}): FAIL — {reason}")
        return ok, reason
    except Exception as e:
        logger.warning(f"  ⚠️  Comment AI validation error: {e} — allowing rule-checked comment")
        return True, "validator unavailable"


def validate_linkedin_post(content: str) -> tuple[bool, str]:
    """Check that today's post draft is coherent before publishing."""
    text = (content or "").strip()
    if len(text) < 30:
        return False, "post too short"
    if len(text) > 3000:
        return False, "post too long"
    if "TODO" in text or "[insert" in text.lower() or "lorem ipsum" in text.lower():
        return False, "placeholder text detected"

    prompt = f"""You are a strict LinkedIn post quality checker.

Draft post to publish:
{text[:2000]}

Is this ready to publish on LinkedIn?
PASS only if ALL are true:
- Coherent complete thoughts (not fragments or bullet stubs without context)
- Professional tone appropriate for LinkedIn feed
- No obvious placeholders, broken sentences, or nonsense
- Reads like intentional content, not a template accident

Reply with exactly one line:
VERDICT: PASS
or
VERDICT: FAIL — one short reason"""

    try:
        verdict, key_id = suite_nvidia_chat(
            prompt,
            max_tokens=80,
            temperature=0.1,
        )
        ok, reason = _parse_validation_verdict(verdict)
        if ok:
            logger.info(f"  🧪 Post validation (AI, key={key_id}): PASS")
        else:
            logger.info(f"  🧪 Post validation (AI, key={key_id}): FAIL — {reason}")
        return ok, reason
    except Exception as e:
        logger.warning(f"  ⚠️  Post AI validation error: {e} — skipping publish")
        return False, f"validator unavailable: {e}"


# ==================== JAVASCRIPT STRINGS ====================
JS_FIND_TEXT = """
    const element = arguments[0];
    const textSelectors = [
        'span[dir="ltr"]', '.break-words', '.feed-shared-text__text-view',
        '[class*="commentary"]', '[class*="update-components-text"]',
        '[class*="search-result__snippet"]', '[class*="entity-result__snippet"]',
        '[class*="occludable-update"]', '.search-result__text',
        '[class*="entity-result__content"]', '[class*="attributed-text-segment-list"]',
        '.update-components-text', 'p'
    ];
    for (const sel of textSelectors) {
        const found = element.querySelectorAll(sel);
        if (found.length > 0) {
            const text = Array.from(found).map(el => el.innerText || el.textContent).join(' ').trim();
            if (text.length > 10) return text;
        }
    }
    return (element.innerText || element.textContent || '').trim().slice(0, 800);
"""

JS_FIND_PERMALINK = """
    const element = arguments[0];
    const allLinks = element.querySelectorAll('a');
    for (const link of allLinks) {
        const h = link.getAttribute('href') || '';
        if (h.includes('-activity-') && (h.startsWith('/posts/') || h.match(/linkedin\\.com\\/posts\\//))) {
            let cleanUrl = h.startsWith('http') ? h : 'https://www.linkedin.com' + h;
            return cleanUrl.split('?')[0];
        }
    }
    for (const link of allLinks) {
        const h = link.getAttribute('href') || '';
        if (h.includes('/feed/update/') || h.includes('/activity/')) {
            let cleanUrl = h.startsWith('http') ? h : 'https://www.linkedin.com' + h;
            return cleanUrl.split('?')[0];
        }
    }
    let el = element;
    for (let i = 0; i < 8; i++) {
        const urn = el.getAttribute && (
            el.getAttribute('data-urn') ||
            el.getAttribute('data-chameleon-result-urn') ||
            el.getAttribute('data-search-result-urn')
        );
        if (urn && (urn.includes('activity') || urn.includes('ugcPost'))) {
            return 'https://www.linkedin.com/feed/update/' + urn;
        }
        el = el.parentElement;
        if (!el) break;
    }
    const embeds = element.querySelectorAll('[data-urn],[data-chameleon-result-urn],[data-search-result-urn]');
    for (const em of embeds) {
        const urn = em.getAttribute('data-urn') || em.getAttribute('data-chameleon-result-urn') || em.getAttribute('data-search-result-urn');
        if (urn && (urn.includes('activity') || urn.includes('ugcPost'))) {
            return 'https://www.linkedin.com/feed/update/' + urn;
        }
    }
    return '';
"""

JS_FIND_AUTHOR = """
    const element = arguments[0];
    const selectors = [
        'span.feed-shared-actor__name', 'span[data-test-id="actor-name"]',
        'a[data-test-id="actor-name"]', '.feed-shared-actor__name',
        '[class*="actor-name"]', '[class*="update-components-actor__name"]',
        'span[aria-hidden="true"]'
    ];
    for (const selector of selectors) {
        const author = element.querySelector(selector);
        if (author) { const name = author.innerText.trim(); if (name.length > 1) return name; }
    }
    return '';
"""

JS_FIND_POSTS = """
    const namedSelectors = [
        'li.reusable-search__result-container', '[data-chameleon-result-urn]',
        '[data-urn*="activity"]', '[data-urn*="ugcPost"]', '[data-urn*="reshare"]',
        'div.feed-shared-update-v2', 'article', 'div[role="article"]', 'div[role="listitem"]'
    ];
    const hits = new Map();
    for (const sel of namedSelectors) {
        for (const el of document.querySelectorAll(sel)) { hits.set(el, el); }
    }
    if (hits.size > 2) return [...hits.values()];
    const mainLi = Array.from(document.querySelectorAll('main li'));
    const bigLi = mainLi.filter(el => el.innerText && el.innerText.trim().length > 80 && el.offsetHeight > 50);
    if (bigLi.length > 0) return bigLi;
    const fallback = Array.from(document.querySelectorAll('ul > li, main > div > div'));
    return fallback.filter(el => el.innerText && el.innerText.trim().length > 100 && el.offsetHeight > 80);
"""

JS_DIAGNOSTIC = """
    const selectors = [
        '[data-urn*="activity"]','[data-urn*="ugcPost"]','[data-chameleon-result-urn]',
        'li.reusable-search__result-container','article','div[role="article"]',
        '[class*="entity-result"]','[class*="occludable-update"]','[class*="feed-shared-update-v2"]',
        'ul > li','main li'
    ];
    const result = {};
    for (const sel of selectors) { result[sel] = document.querySelectorAll(sel).length; }
    result['total_li'] = document.querySelectorAll('li').length;
    result['data_urn_count'] = document.querySelectorAll('[data-urn]').length;
    return JSON.stringify(result);
"""


# ==================== WINDOW DETECTION (Z.py-style) ====================

_WM_CLOSE = 0x0010


def _hwnd_alive(hwnd) -> bool:
    try:
        return bool(hwnd) and bool(ctypes.windll.user32.IsWindow(hwnd))
    except Exception:
        return False


def _pid_for_hwnd(hwnd) -> int | None:
    try:
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None
    except Exception:
        return None


def close_browser(driver, browser_win=None):
    """Close Firefox after the suite finishes.

    With --connect-existing, driver.quit() only drops the automation session;
    the Firefox window often stays open. We also send WM_CLOSE and, if needed,
    terminate the window's process tree.
    """
    closed = False

    if driver is not None:
        try:
            for handle in list(driver.window_handles):
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            driver.quit()
            logger.info("✓ Selenium session closed")
        except Exception as e:
            logger.warning(f"⚠️  driver.quit() failed: {e}")
            try:
                driver.service.stop()
                logger.info("✓ geckodriver service stopped")
            except Exception as stop_err:
                logger.warning(f"⚠️  Could not stop geckodriver service: {stop_err}")

    hwnd = getattr(browser_win, "_hWnd", None) if browser_win else None
    if hwnd and _hwnd_alive(hwnd):
        try:
            ctypes.windll.user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            logger.info("  Sent close signal to Firefox window")
        except Exception as e:
            logger.warning(f"⚠️  Could not send close signal to window: {e}")
        for _ in range(10):
            time.sleep(0.5)
            if not _hwnd_alive(hwnd):
                closed = True
                break

    if hwnd and _hwnd_alive(hwnd):
        pid = _pid_for_hwnd(hwnd)
        if pid:
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    logger.info(f"✓ Firefox process tree terminated (PID {pid})")
                    closed = True
                else:
                    err = (result.stderr or result.stdout or "").strip()
                    logger.warning(f"⚠️  taskkill PID {pid} failed: {err}")
            except Exception as e:
                logger.warning(f"⚠️  taskkill failed: {e}")
        time.sleep(0.5)
        if not _hwnd_alive(hwnd):
            closed = True
    elif hwnd:
        closed = True

    if closed:
        logger.info("✓ Browser closed")
    elif driver is None and not hwnd:
        pass
    else:
        logger.warning("⚠️  Browser may still be open — close Firefox manually if needed")


def pause_before_exit(seconds=30):
    """
    Give the user time to read the console before the window closes.
    Counts down visibly; also accepts Enter to close immediately.
    """
    import threading
    closed = threading.Event()

    def _wait_for_enter():
        try:
            input()
        except Exception:
            pass
        closed.set()

    t = threading.Thread(target=_wait_for_enter, daemon=True)
    t.start()

    print(f"\n  ⏳ Window closes in {seconds}s — press Enter to close now...")
    for i in range(seconds, 0, -1):
        if closed.is_set():
            break
        print(f"\r  ⏳ Closing in {i:2d}s (press Enter to close now)... ", end="", flush=True)
        time.sleep(1)
    print()


def find_suite_browser_window():
    """
    Find a Firefox window for automation.
    Prefers a window whose title contains 'LinkedIn'; if none, accepts 'Instagram'.
    Requires 'firefox' in the title so File Explorer folders are never matched.
    Returns (window, mode) where mode is 'linkedin' or 'instagram', or (None, None).
    """
    if not PYGETWINDOW_AVAILABLE:
        logger.error("❌ pygetwindow is not installed.")
        logger.error("   Run:  pip install pygetwindow")
        return None, None
    try:
        all_wins = gw.getAllWindows()
        logger.info(f"  Scanning {len(all_wins)} open windows...")
        instagram_win = None
        for win in all_wins:
            title = win.title or ""
            tl = title.lower()
            if "firefox" not in tl:
                continue
            if "linkedin" in tl:
                logger.info(f"  🔍 Found LinkedIn Firefox window: '{title}'")
                return win, "linkedin"
            if "instagram" in tl and instagram_win is None:
                instagram_win = win
        if instagram_win:
            title = instagram_win.title or ""
            logger.info(f"  🔍 LinkedIn not found — using Instagram Firefox window: '{title}'")
            return instagram_win, "instagram"
        for win in all_wins:
            if win.title:
                logger.info(f"    Window: '{win.title}'")
    except Exception as e:
        logger.error(f"❌ pygetwindow scan failed: {e}")
    return None, None


def verify_browser_session(driver, browser_mode: str) -> bool:
    """Confirm the attached Firefox tab looks logged in for the chosen mode."""
    label = "LinkedIn" if browser_mode == "linkedin" else "Instagram"
    logger.info(f"\n🔐 Verifying {label} session...")
    try:
        cur_url = driver.current_url.lower()
    except Exception:
        cur_url = ""

    if browser_mode == "linkedin":
        if any(x in cur_url for x in ["login", "authwall", "signup", "checkpoint"]):
            logger.error("❌ The Firefox window is not logged in to LinkedIn.")
            logger.error("   Please log in at https://www.linkedin.com then run again.")
            return False
    else:
        if any(x in cur_url for x in ["accounts/login", "/login", "authwall", "challenge"]):
            logger.error("❌ The Firefox window is not logged in to Instagram.")
            logger.error("   Please log in at https://www.instagram.com then run again.")
            return False
        if "instagram.com" not in cur_url:
            logger.warning("  ⚠️  Active tab is not instagram.com — continuing (window title matched Instagram)")

    logger.info(f"  ✓ Session OK — current page: {driver.current_url[:80]}")
    return True


def bring_window_to_front(win):
    """
    Focus a window using the ctypes ALT-key trick (same approach as Z.py).
    This bypasses Windows' focus-steal prevention.
    """
    try:
        if win.isMinimized:
            win.restore()
            time.sleep(0.3)
        user32 = ctypes.windll.user32
        user32.keybd_event(0x12, 0, 0, 0)      # ALT key down
        time.sleep(0.05)
        user32.SetForegroundWindow(win._hWnd)
        time.sleep(0.05)
        user32.keybd_event(0x12, 0, 2, 0)      # ALT key up
        win.activate()
        time.sleep(1.0)
        logger.info("  ✅ LinkedIn window brought to front")
        return True
    except Exception as e:
        logger.warning(f"  ⚠️  Window focus warning: {e}")
        return False


def detect_marionette_port():
    """
    Ask Windows which port Firefox's Marionette server is actually listening on.
    Uses netstat to find Firefox.exe TCP LISTENING ports, then filters to known
    Marionette range (2000–65535) preferring 2828 if present.
    Returns an int port number, or None if not found.
    """
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "netstat -ano | Select-String 'LISTENING'"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        # Get Firefox PIDs
        pid_result = subprocess.run(
            ["powershell", "-Command",
             "Get-Process firefox -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace"
        )
        firefox_pids = set(pid_result.stdout.strip().split())
        if not firefox_pids:
            logger.warning("  ⚠️  No Firefox process found via Get-Process")
            return None

        logger.info(f"  Firefox PIDs: {firefox_pids}")
        candidate_ports = []
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            pid = parts[-1].strip()
            if pid not in firefox_pids:
                continue
            # Extract port from local address  (e.g.  0.0.0.0:2828  or  127.0.0.1:57655)
            addr = parts[1] if len(parts) >= 2 else ""
            if ":" in addr:
                try:
                    port_num = int(addr.rsplit(":", 1)[-1])
                    if 1024 <= port_num <= 65535:
                        candidate_ports.append(port_num)
                except ValueError:
                    pass

        if not candidate_ports:
            logger.warning("  ⚠️  No candidate Marionette ports found in netstat output")
            return None

        logger.info(f"  Firefox listening ports: {candidate_ports}")
        # Prefer 2828 if present, otherwise take the lowest port
        if 2828 in candidate_ports:
            return 2828
        # Marionette typically uses higher ephemeral ports; pick the smallest
        return sorted(candidate_ports)[0]
    except Exception as e:
        logger.warning(f"  ⚠️  Port auto-detect failed: {e}")
        return None


def connect_to_existing_firefox(port=MARIONETTE_PORT):
    """
    Attach Selenium to an already-running Firefox instance via
    geckodriver's --connect-existing flag.

    First tries the supplied port; if that fails, auto-detects the actual
    Marionette port Firefox is using via netstat and retries.

    Firefox MUST have been started with --marionette flag.
    Returns a WebDriver instance, or None on failure.
    """
    gecko = GeckoDriverManager().install()

    def _try_connect(p):
        try:
            options = Options()
            options.set_preference("dom.webdriver.enabled", False)
            options.set_preference("useAutomationExtension", False)
            service = Service(
                gecko,
                service_args=['--marionette-port', str(p), '--connect-existing']
            )
            driver = webdriver.Firefox(service=service, options=options)
            driver.set_page_load_timeout(60)
            try:
                driver.execute_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
            except Exception:
                pass
            logger.info(f"  ✓ Attached to existing Firefox (port {p})")
            return driver
        except Exception as e:
            logger.warning(f"  ⚠️  connect on port {p} failed: {e}")
            return None

    # Attempt 1: use the configured port
    logger.info(f"  Trying port {port}...")
    driver = _try_connect(port)
    if driver:
        return driver

    # Attempt 2: auto-detect the actual port from netstat
    logger.info("  Auto-detecting Marionette port via netstat...")
    detected = detect_marionette_port()
    if detected and detected != port:
        logger.info(f"  Retrying with detected port {detected}...")
        driver = _try_connect(detected)
        if driver:
            return driver

    logger.warning("  ⚠️  All connection attempts failed")
    return None


# ==================== SHARED HELPERS ====================
def open_new_tab(driver, url=None):
    """Open a new browser tab, switch to it, optionally navigate to url."""
    driver.execute_script("window.open('about:blank', '_blank');")
    driver.switch_to.window(driver.window_handles[-1])
    if url:
        driver.get(url)
        human_delay(6.0, 9.0)


def js(driver, script, *args):
    try:
        return driver.execute_script(script, *args)
    except Exception as e:
        logger.debug(f"JS exec failed: {e}")
        return None


def human_delay(min_s=HUMAN_DELAY_MIN, max_s=HUMAN_DELAY_MAX):
    time.sleep(random.uniform(min_s, max_s))


def human_mouse_click(driver, element):
    """Move the OS cursor visibly to *element* then click it.
    Uses pyautogui for real screen-level movement so it looks human.
    Falls back to ActionChains → JS click if pyautogui is unavailable."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
        human_delay(0.3, 0.6)

        if VISUAL_POST_AVAILABLE:
            # Element centre in viewport coordinates
            loc = driver.execute_script("""
                var b = arguments[0].getBoundingClientRect();
                return {x: Math.round(b.left + b.width/2),
                        y: Math.round(b.top  + b.height/2)};
            """, element)
            # Browser window position and chrome (toolbar) height
            win_x    = driver.execute_script("return window.screenX;")
            win_y    = driver.execute_script("return window.screenY;")
            outer_h  = driver.execute_script("return window.outerHeight;")
            inner_h  = driver.execute_script("return window.innerHeight;")
            toolbar_h = outer_h - inner_h
            # Apply Windows DPI scaling so pyautogui lands in the right place
            try:
                hdc = ctypes.windll.user32.GetDC(0)
                dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                ctypes.windll.user32.ReleaseDC(0, hdc)
                scale = dpi / 96.0
            except Exception:
                scale = 1.0
            screen_x = int((win_x + loc['x']) * scale)
            screen_y = int((win_y + toolbar_h + loc['y']) * scale)
            # Smooth arc: move cursor visibly (for human appearance only)
            mid_x = screen_x + random.randint(-80, 80)
            mid_y = screen_y + random.randint(-60, 60)
            pyautogui.moveTo(mid_x, mid_y,
                             duration=random.uniform(0.25, 0.45),
                             tween=pyautogui.easeInOutQuad)
            human_delay(0.05, 0.15)
            pyautogui.moveTo(screen_x, screen_y,
                             duration=random.uniform(0.3, 0.6),
                             tween=pyautogui.easeInOutQuad)
            human_delay(0.15, 0.35)
        # Always use ActionChains for the actual click — reliable regardless of DPI
        ActionChains(driver)\
            .move_to_element(element)\
            .pause(random.uniform(0.1, 0.2))\
            .click()\
            .perform()
    except Exception as e:
        logger.debug(f"human_mouse_click fallback: {e}")
        try:
            ActionChains(driver).move_to_element(element).click().perform()
        except Exception:
            driver.execute_script("arguments[0].click();", element)


def scroll_down(driver, px=SCROLL_PX):
    driver.execute_script(f"window.scrollBy({{top: {px}, left: 0, behavior: 'smooth'}});")
    human_delay(1.5, 2.5)   # wait for smooth scroll animation to finish


def log_page_diagnostic(driver):
    logger.info(f"  URL  : {driver.current_url}")
    logger.info(f"  Title: {driver.title}")


def save_debug_html(driver, filename):
    try:
        p = os.path.join(SCRIPT_DIR, filename)
        with open(p, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logger.info(f"  🔍 Debug HTML: {p}")
    except Exception:
        pass


def beep_success(extra_tone=False):
    """3-tone success beep. Optional 4th tone for extra confirmation."""
    try:
        winsound.Beep(800,  400)
        winsound.Beep(1200, 400)
        winsound.Beep(1600, 800)
        if extra_tone:
            winsound.Beep(2000, 400)
    except Exception:
        pass


# ==================== CLIPBOARD HELPERS ====================
def _read_clipboard():
    try:
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace"
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _write_clipboard(text: str) -> bool:
    try:
        user32   = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes   = [wintypes.HWND];  user32.OpenClipboard.restype   = wintypes.BOOL
        user32.EmptyClipboard.argtypes  = [];                user32.EmptyClipboard.restype  = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]; user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes  = [];                user32.CloseClipboard.restype  = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes   = [wintypes.UINT, ctypes.c_size_t]; kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes    = [wintypes.HGLOBAL]; kernel32.GlobalLock.restype  = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes  = [wintypes.HGLOBAL]; kernel32.GlobalUnlock.restype = wintypes.BOOL

        if not user32.OpenClipboard(0):
            return False
        user32.EmptyClipboard()
        encoded   = text.encode('utf-16le') + b'\0\0'
        hMem      = kernel32.GlobalAlloc(0x0002, len(encoded))
        pMem      = kernel32.GlobalLock(hMem)
        ctypes.memmove(pMem, encoded, len(encoded))
        kernel32.GlobalUnlock(hMem)
        user32.SetClipboardData(13, wintypes.HANDLE(hMem))
        user32.CloseClipboard()
        return True
    except Exception as e:
        logger.warning(f"  ⚠️  Clipboard write error: {e}")
        try:
            ctypes.windll.user32.CloseClipboard()
        except Exception:
            pass
        return False


# ==================== COMMENT BOX HELPERS (shared by Tasks 1 & 2) ====================
def open_comments(driver, post):
    """
    Open the LinkedIn comment editor on the current post page.
    Handles both search-result cards and single-post permalink pages.
    """
    def _find_visible_comment_box():
        """Return a visible, focusable comment editor div, or None."""
        for sel in [
            'div[contenteditable="true"][aria-label*="comment" i]',
            'div[contenteditable="true"][data-placeholder*="comment" i]',
            'div[contenteditable="true"][aria-label*="Add a comment" i]',
            'div[role="textbox"][aria-label*="comment" i]',
            'div[contenteditable="true"]',
            'div[role="textbox"]',
        ]:
            try:
                for box in driver.find_elements(By.CSS_SELECTOR, sel):
                    if not box.is_displayed():
                        continue
                    label = (box.get_attribute("aria-label") or "").lower()
                    ph    = (box.get_attribute("data-placeholder") or "").lower()
                    # On permalink pages the box has aria-label but no "comment" keyword —
                    # accept any visible contenteditable that is inside a comments section
                    if "comment" in label or "comment" in ph or "add a comment" in label:
                        return box
            except Exception:
                pass
        return None

    def _comments_disabled():
        """Return True if LinkedIn has disabled comments on this post."""
        try:
            # Text indicator in the page body
            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            if "comments have been turned off" in page_text:
                return True
        except Exception:
            pass
        try:
            # Comment button may carry aria-disabled="true" or disabled attr
            for btn in driver.find_elements(By.CSS_SELECTOR,
                    "button[aria-label*='comment' i], button[aria-label*='Comment' i]"):
                if btn.is_displayed():
                    if (btn.get_attribute("aria-disabled") == "true" or
                            btn.get_attribute("disabled") is not None):
                        return True
        except Exception:
            pass
        return False

    try:
        # ── Pre-check: are comments disabled on this post? ───────────────────
        if _comments_disabled():
            logger.warning("  🚫 Comments are turned off on this post — skipping")
            return False

        # ── Phase 1: comment box already in DOM? ─────────────────────────────
        box = _find_visible_comment_box()
        if box:
            logger.info("  ✅ Comment box already visible — focusing")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
            human_delay(0.5, 1.0)
            driver.execute_script("arguments[0].click(); arguments[0].focus();", box)
            human_delay(0.8, 1.2)
            return True

        # ── Phase 2: scroll down to load comment section ──────────────────────
        # On post permalink pages the comment section is below the fold
        for scroll_step in range(4):
            driver.execute_script(
                f"window.scrollBy({{top: {random.randint(500, 900)}, left: 0, behavior: 'smooth'}});"
            )
            human_delay(1.2, 2.0)
            box = _find_visible_comment_box()
            if box:
                logger.info(f"  ✅ Comment box appeared after scroll step {scroll_step+1}")
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
                human_delay(0.5, 1.0)
                driver.execute_script("arguments[0].click(); arguments[0].focus();", box)
                human_delay(0.8, 1.2)
                return True

        # ── Phase 3: click the Comment action button to activate the editor ───
        # LinkedIn shows a "Comment" button in the post action bar;
        # clicking it makes the contenteditable appear.
        comment_btn_selectors = [
            # Specific LinkedIn selectors
            "button[aria-label*='comment' i]",
            "button[aria-label*='Comment' i]",
            "[data-control-name='comment']",
            "button.comment-button",
            # Generic: button whose visible text is exactly "Comment"
            "//button[normalize-space(.)='Comment']",
            "//button[contains(@aria-label,'Comment')]",
            "//*[@role='button'][contains(@aria-label,'Comment')]",
            # SVG icon-based
            "button[data-test-icon*='comment']",
            "*[data-test-icon*='comment-medium']",
        ]

        # scroll back up to where the post action bar is
        if post:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", post)
                human_delay(1.0, 1.5)
            except Exception:
                pass

        for sel in comment_btn_selectors:
            try:
                if sel.startswith("//") or sel.startswith(".//"):
                    btns = driver.find_elements(By.XPATH, sel)
                else:
                    btns = driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if not btn.is_displayed():
                        continue
                    label = (btn.get_attribute("aria-label") or "").lower()
                    text  = (btn.text or "").lower()
                    # skip the submit "Comment" button (it's near the editor, not the action bar)
                    if btn.get_attribute("aria-expanded") == "true":
                        # already open
                        break
                    if "comment" in label or "comment" in text:
                        logger.info(f"  🖱️  Clicking Comment action button (label='{label or text}')")
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", btn
                        )
                        human_delay(0.4, 0.8)
                        try:
                            btn.click()
                        except Exception:
                            ActionChains(driver).move_to_element(btn).pause(0.2).click().perform()
                        human_delay(2.0, 3.5)

                        # Immediately check if comments are disabled (button click reveals the notice)
                        if _comments_disabled():
                            logger.warning("  🚫 Comments turned off — revealed after click, skipping")
                            return False

                        # Check if editor appeared
                        box = _find_visible_comment_box()
                        if box:
                            logger.info("  ✅ Comment editor appeared after clicking action button")
                            driver.execute_script(
                                "arguments[0].scrollIntoView({block:'center'});", box
                            )
                            human_delay(0.5, 1.0)
                            driver.execute_script(
                                "arguments[0].click(); arguments[0].focus();", box
                            )
                            human_delay(0.8, 1.2)
                            return True
                        break
            except Exception:
                continue

        # ── Phase 4: broad fallback — any visible contenteditable on page ─────
        try:
            for box in driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]'):
                if box.is_displayed():
                    logger.info("  ✅ Fallback: using first visible contenteditable")
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", box)
                    human_delay(0.5, 0.8)
                    driver.execute_script("arguments[0].click(); arguments[0].focus();", box)
                    human_delay(0.8, 1.2)
                    return True
        except Exception:
            pass

        logger.warning("  ⚠️  No comment box found after all strategies")
        return False
    except Exception as e:
        logger.debug(f"open_comments error: {e}")
        return False


def post_comment_to_box(driver, comment_text):
    """
    Find the comment contenteditable, type comment_text via clipboard paste,
    fire React events, then click the submit button.
    """
    try:
        boxes = driver.find_elements(By.CSS_SELECTOR,
            'div[contenteditable="true"], div[role="textbox"]')
        comment_box = None
        for box in boxes:
            label = (box.get_attribute("aria-label") or "").lower()
            ph    = (box.get_attribute("data-placeholder") or "").lower()
            if "comment" in label or "comment" in ph or "add a comment" in label:
                comment_box = box
                break
        if not comment_box:
            for box in boxes:
                if box.is_displayed():
                    comment_box = box
                    break
        if not comment_box:
            logger.warning("  No comment box found on page")
            return False

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", comment_box)
        human_delay(0.5, 1.0)
        try:
            comment_box.click()
        except Exception:
            driver.execute_script("arguments[0].click();", comment_box)
        human_delay(0.6, 1.0)
        driver.execute_script("arguments[0].focus();", comment_box)
        human_delay(0.4, 0.6)

        # Strategy A: clipboard paste
        typed_ok = False
        if _write_clipboard(comment_text):
            human_delay(0.3, 0.5)
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            human_delay(1.0, 1.5)
            cur_text = (comment_box.text or comment_box.get_attribute("textContent") or "").strip()
            if len(cur_text) > 5:
                logger.info(f"  ✍️  Typed via clipboard paste ({len(cur_text)} chars)")
                typed_ok = True

        # Strategy B: execCommand
        if not typed_ok:
            try:
                driver.execute_script(
                    "arguments[0].focus(); document.execCommand('selectAll',false,null);"
                    "document.execCommand('insertText',false,arguments[1]);",
                    comment_box, comment_text
                )
                human_delay(1.0, 1.5)
                cur_text = (comment_box.text or comment_box.get_attribute("textContent") or "").strip()
                if len(cur_text) > 5:
                    typed_ok = True
            except Exception as e:
                logger.warning(f"  execCommand failed: {e}")

        # Strategy C: send_keys
        if not typed_ok:
            try:
                for word in comment_text.split(' '):
                    comment_box.send_keys(word + ' ')
                    human_delay(0.02, 0.05)
                human_delay(1.0, 1.5)
                typed_ok = True
            except Exception as e:
                logger.warning(f"  send_keys failed: {e}")

        if not typed_ok:
            logger.error("  ❌ All typing strategies failed")
            return False

        # Fire React events
        driver.execute_script("""
            const box = arguments[0];
            ['input','change','keyup','keydown'].forEach(ev =>
                box.dispatchEvent(new Event(ev, {bubbles:true,cancelable:true})));
            box.dispatchEvent(new InputEvent('input',{bubbles:true,data:box.textContent}));
        """, comment_box)
        human_delay(3.0, 4.0)

        # Find submit button — multiple strategies in priority order
        posted = False
        box_y = comment_box.location.get('y', 0)

        def _find_submit_btn():
            """Return the best visible submit button near the comment box, or None."""

            # Strategy S0: JS DOM traversal — walk UP from comment_box, find
            # a "Comment" button INSIDE the same container. This avoids matching
            # the action-bar "Comment" button elsewhere on the page.
            try:
                js_btn = driver.execute_script("""
                    const box = arguments[0];
                    // Walk up to 10 ancestor levels
                    let parent = box;
                    for (let i = 0; i < 10; i++) {
                        parent = parent.parentElement;
                        if (!parent) break;
                        const btns = Array.from(parent.querySelectorAll('button'));
                        for (const btn of btns) {
                            const text = (btn.textContent || '').trim();
                            if (text === 'Comment' || text === 'Submit' || text === 'Post') {
                                // Must be below the comment box
                                const boxRect = box.getBoundingClientRect();
                                const btnRect = btn.getBoundingClientRect();
                                // btn should be within 250px below the top of the box
                                if (btnRect.top > boxRect.top - 20 &&
                                    Math.abs(btnRect.top - boxRect.bottom) < 250) {
                                    return btn;
                                }
                            }
                        }
                    }
                    return null;
                """, comment_box)
                if js_btn and js_btn.is_displayed():
                    logger.info("  🎯 Submit btn found via DOM traversal (S0)")
                    return js_btn
                elif js_btn:
                    logger.debug("  S0: btn found but not displayed")
                else:
                    logger.debug("  S0: no btn found in DOM traversal")
            except Exception as _e:
                logger.debug(f"  S0 error: {_e}")

            candidates = []

            # Strategy S1: LinkedIn-specific submit selectors
            for sel in [
                "button.comments-comment-box__submit-button",
                "button[data-control-name='comment.submit']",
                "button[data-control-name='submit_comment']",
                "button.artdeco-button--primary",
                "button[type='submit']",
            ]:
                try:
                    for btn in driver.find_elements(By.CSS_SELECTOR, sel):
                        if btn.is_displayed():
                            candidates.append(btn)
                except Exception:
                    pass

            # Strategy S2: any button whose text is exactly "Comment" (the submit label)
            try:
                for btn in driver.find_elements(By.XPATH,
                        "//button[normalize-space(text())='Comment' or "
                        "normalize-space(.)='Comment']"):
                    if btn.is_displayed():
                        candidates.append(btn)
            except Exception:
                pass

            # Pick the candidate closest to the comment box (within 400px)
            # but BELOW the box (submit is below, action bar is above)
            best, min_dist = None, 999999
            for btn in candidates:
                btn_y = btn.location.get('y', 0)
                dist = abs(btn_y - box_y)
                if btn_y >= box_y and dist < 400 and dist < min_dist:
                    min_dist = dist
                    best = btn
            return best

        submit_btn = _find_submit_btn()
        if submit_btn:
            if submit_btn.get_attribute("disabled"):
                driver.execute_script(
                    "arguments[0].removeAttribute('disabled');"
                    "arguments[0].removeAttribute('aria-disabled');", submit_btn)
                human_delay(0.5, 0.8)
            try:
                human_mouse_click(driver, submit_btn)
                posted = True
                logger.info("  🖱️  Clicked submit button")
            except Exception as e:
                logger.warning(f"  ⚠️  Submit button click failed: {e}")

        # Fallback: Ctrl+Enter in the comment box
        if not posted:
            try:
                comment_box.click()
                human_delay(0.3, 0.5)
                ActionChains(driver).key_down(Keys.CONTROL).send_keys(Keys.ENTER).key_up(Keys.CONTROL).perform()
                posted = True
                logger.info("  ⌨️  Submitted via Ctrl+Enter")
            except Exception:
                pass

        # ── Wait for LinkedIn to process the submission ───────────────────────
        # Group posts and some regular posts take longer to clear the box.
        # Wait up to ~8 seconds in two rounds before declaring failure.
        human_delay(3.5, 5.0)  # longer initial wait

        def _box_is_empty():
            try:
                txt = (comment_box.text or
                       comment_box.get_attribute("textContent") or "").strip()
                return len(txt) <= 5
            except Exception:
                return True  # stale element → box is gone → submitted

        if _box_is_empty():
            logger.info("  ✅ Comment box cleared — submission confirmed")
            human_delay(2.0, 3.0)
            return True

        # Box still has text — wait once more then retry with Ctrl+Enter
        logger.warning("  ⚠️  Box still has text after wait — retrying with Ctrl+Enter")
        human_delay(2.0, 3.0)

        if _box_is_empty():
            logger.info("  ✅ Comment box cleared on second check")
            return True

        # Genuine retry: Ctrl+Enter
        try:
            box_ref = _box_is_empty  # just to keep box in scope
            comment_box.click()
            human_delay(0.3, 0.6)
            ActionChains(driver).key_down(Keys.CONTROL).send_keys(Keys.ENTER).key_up(Keys.CONTROL).perform()
            logger.info("  ⌨️  Ctrl+Enter retry sent")
            human_delay(3.5, 5.0)
        except Exception as e:
            logger.warning(f"  ⚠️  Ctrl+Enter retry failed: {e}")

        if _box_is_empty():
            logger.info("  ✅ Comment submitted via Ctrl+Enter retry")
            human_delay(1.5, 2.5)
            return True

        logger.warning("  ⚠️  Could not submit comment after all attempts")
        return False
    except Exception as e:
        logger.error(f"post_comment_to_box error: {e}")
        return False


# ==================== TASK 1: AI COMMENT ====================

# --- Hiring detection signals ---
EMPLOYER_HIRING_KEYWORDS = [
    # Explicit hiring statements
    "we are hiring", "we're hiring", "now hiring", "currently hiring",
    "we are seeking", "we're seeking", "seeking a", "seeking an",
    "we are looking for", "we're looking for", "looking for a", "looking for an",
    "looking to hire", "looking for candidates", "looking for professionals",
    # Job/role availability
    "job opening", "open position", "open role", "positions open",
    "vacancy", "vacancies", "we have openings", "immediate opening",
    "role available", "position available", "opportunity available",
    # Application prompts
    "apply now", "apply at", "send your cv", "send your resume", "send your profile",
    "share your cv", "share your resume", "share your profile", "share their profile",
    "share their profiles", "interested candidates", "eligible candidates",
    "drop your cv", "drop your resume", "dm your cv", "email your cv",
    "reach out at", "reach out to", "contact us at", "write to us at",
    # Team/role descriptions
    "join our team", "join us", "be part of our team",
    "career opportunity", "job opportunity", "exciting opportunity",
    "internship opportunity", "intern hiring", "hiring interns",
    # Urgency / specifics
    "immediate joiners", "urgent hiring", "urgent requirement",
    "required experience", "experience required", "years of experience",
    "hiring for", "recruiting", "walk-in", "walk in interview",
    "practice area", "practice areas",
]
COLLEGE_HIRING_KEYWORDS = [
    "tpo", "placement coordinator", "placement cell", "campus recruitment",
    "campus hiring", "corporate tie-up", "corporate tie up", "campus tie-up",
    "placement drive", "on-campus", "on campus", "off-campus", "off campus",
    "hiring from campus", "college hiring", "university hiring", "campus placements",
    "reach out for campus", "campus tie ups", "placement officer",
]

def is_employer_hiring_post(post_text):
    lower = post_text.lower()
    return any(kw in lower for kw in EMPLOYER_HIRING_KEYWORDS)

def is_college_hiring_post(post_text):
    lower = post_text.lower()
    return any(kw in lower for kw in COLLEGE_HIRING_KEYWORDS)

# Keep old name as alias so any remaining references don't break
def is_hiring_post(post_text):
    return is_employer_hiring_post(post_text) or is_college_hiring_post(post_text)


def _build_tpo_comment_prompt(post_text, hiring_base=None):
    """Build the AI prompt for TPO-specific comment generation.
    If hiring_base is provided, ask AI to paraphrase that specific message."""
    if hiring_base:
        return f"""You are a professional TPO (Training & Placement Officer) engaging on LinkedIn.
Paraphrase the following comment so it sounds natural and fresh each time, keeping the same intent.
Vary the wording — do not use the exact same phrasing repeatedly.
Keep it 1-2 sentences. Output ONLY the comment text. No quotes, no preamble.

Base message: {hiring_base}

Post excerpt: {post_text[:400]}
"""
    return f"""You are a professional TPO (Training & Placement Officer) engaging with peers on LinkedIn.
Read the post below, silently classify it into ONE of the categories, then write a matching comment.

CATEGORIES AND COMMENT STYLES:

1. Management & Leadership Views — opinions on leadership styles, hiring philosophy, workplace culture
   Style: Agree and add a perspective. E.g. "Attitude and adaptability often matter more than marks — glad more hiring managers are thinking this way."

2. Education System Commentary — curriculum critique, skill gaps, industry vs academia debates
   Style: Validate + add insight. E.g. "The gap between what colleges teach and what industry needs is very real — bridging it needs movement from both sides."

3. Career Advice & Guidance — interview tips, job search advice, resume/placement preparation
   Style: Affirm + share placement experience. E.g. "Students who follow this consistently stand out in our drives — great advice."

4. Hiring Trends & Industry Insights — market observations, sector hiring trends, future of jobs
   Style: Acknowledge + extend with own observation. E.g. "Seeing this shift in our campus drives too — AI-readiness is now a baseline expectation."

5. Student Behavior & Mindset — soft commentary on work ethic, expectations, discipline
   Style: Empathetic but direct. E.g. "Consistency really is the differentiator — recruiters notice it immediately."

6. Motivational / Philosophical — life lessons, success/failure reflections, growth mindset
   Style: Short and genuine. E.g. "Well said — a reminder every student and TPO needs to hear."

7. Institutional Pride — reflective pride about campus, students, or placement outcomes
   Style: Warm acknowledgment. E.g. "The effort your team puts in shows — results like this don't happen by chance."

8. Commentary on Corporate Behavior — criticism or praise of company hiring practices, work culture
   Style: Balanced and thoughtful. E.g. "Unpaid internships are long overdue for scrutiny — glad the conversation is picking up."

9. Personal Career Journey (TPO perspective) — their own experience, lessons from years in placements
   Style: Relate + appreciate. E.g. "Every placement season teaches something new — this resonates deeply."

10. Social / Economic Commentary — macro thoughts on India's workforce, automation, demographics
    Style: Thoughtful engagement. E.g. "The demographic dividend only pays off if we invest seriously in employability right now."

11. Employer Hiring Post — company posting a job, internship, or vacancy
    Style: "Commenting for better reach — great opportunity for students!"

12. College/Campus Hiring — TPO inviting companies for drives, campus tie-ups, placement partnerships
    Style: "Commenting for better reach — hope this connects you with the right partners!"

13. Other / Unclassified
    Style: "Thanks for sharing — always good to see this kind of conversation in the TPO community."

RULES:
- Classify the post silently. Do NOT mention the category name in your output.
- Output ONLY the comment text. No preamble, no quotes, no category label.
- 1-2 sentences, professional, sounds like a real person wrote it.
- Vary wording slightly each time — avoid repeating the exact example phrases.

Post:
{post_text[:1500]}
"""


def _build_advocate_comment_prompt(post_text, hiring_base=None):
    """Build the AI prompt for legal/advocate post comment generation.
    Separate from the TPO prompt — persona is a legal professional, not a TPO."""
    if hiring_base:
        return f"""You are a legal professional engaging on LinkedIn.
Paraphrase the following comment so it sounds natural and fresh each time, keeping the same intent.
Vary the wording — do not use the exact same phrasing repeatedly.
Keep it 1-2 sentences. Output ONLY the comment text. No quotes, no preamble.

Base message: {hiring_base}

Post excerpt: {post_text[:400]}
"""
    return f"""You are a legal professional (advocate, in-house counsel, or law firm lawyer) engaging with peers on LinkedIn.
Read the post below, silently classify it into ONE of the categories, then write a matching comment.

CATEGORIES AND COMMENT STYLES:

1. Legal Updates & Case Law — new judgments, amendments, regulatory changes, court orders
   Style: Acknowledge significance + add a brief observation. E.g. "An important ruling — the implications for pending matters in this space will be significant."

2. Corporate & Compliance Insights — company law, SEBI/RBI/MCA updates, governance, FEMA, contracts
   Style: Engage professionally. E.g. "The revised framework adds clarity, though implementation timelines remain tight for most compliance teams."

3. Career & Professional Growth — job moves, promotions, certifications, networking
   Style: Warm congratulations or affirmation. E.g. "Well deserved — your work in this practice area speaks for itself."

4. Legal Tech & Innovation — AI in law, legaltech tools, e-filing, court digitisation
   Style: Curious and forward-looking. E.g. "The adoption curve is steeper than people expect — but the productivity gains for document review alone make it worthwhile."

5. Dispute Resolution & Litigation — arbitration trends, court delays, litigation strategy, ADR
   Style: Practitioner-level engagement. E.g. "The push toward institutional arbitration is overdue — ad hoc proceedings carry too much uncertainty for commercial disputes."

6. Tax & Finance Law — income tax, GST, transfer pricing, banking, insolvency
   Style: Precise and practical. E.g. "The assessment timelines under the new framework will test even well-prepared compliance teams."

7. Thought Leadership / Legal Philosophy — opinions on justice system, legal education, law reform
   Style: Thoughtful and measured. E.g. "Reform at the structural level matters — procedural changes alone rarely shift outcomes."

8. Motivational / Personal — resilience, work ethic, professional identity, personal milestones
   Style: Genuine and brief. E.g. "Well said — the early years in practice teach things no classroom can."

9. Employer Hiring Post — law firm or company posting a job, internship, or vacancy
   Style: "Commenting for better reach — great opportunity for legal professionals."

10. Event / Seminar / Webinar — legal conferences, CLEs, panel discussions
    Style: Affirm value + encourage participation. E.g. "A timely discussion — this area needs more practitioner-level dialogue."

11. M&A / Transactions / Deal Commentary — deals, investment, fundraising, restructuring
    Style: Insightful, deal-aware. E.g. "Interesting structure — the regulatory clearance timeline on cross-border deals like this is increasingly the critical path."

12. Social / Policy Commentary — broader views on governance, inequality, policy
    Style: Balanced and thoughtful. E.g. "Access to justice remains the gap that most legal reform efforts underestimate."

13. Other / Unclassified
    Style: "Interesting perspective — thanks for sharing this with the legal community."

RULES:
- Classify the post silently. Do NOT mention the category name in your output.
- Output ONLY the comment text. No preamble, no quotes, no category label.
- 1-2 sentences, professional, sounds like a real legal practitioner wrote it.
- Do NOT write as a TPO, placement officer, or educator — write as a legal professional.
- Vary wording slightly each time — avoid repeating the exact example phrases.

Post:
{post_text[:1500]}
"""


def _build_fundraising_comment_prompt(post_text):
    """Build the AI prompt for startup funding comment generation (any sector; SaaS optional)."""
    return f"""You are a startup founder, operator, or early-stage investor active on LinkedIn.
Read the post below, silently classify it, then write a short comment that fits the funding / fundraising context.
The post should be about funding, fundraising, investment rounds, or capital — in any startup sector (SaaS, fintech, healthtech, D2C, deeptech, etc.).

CATEGORIES AND COMMENT STYLES:

1. Funding Announcement — startup closed seed/Series A/pre-seed/angel round
   Style: Congratulate + one sharp observation. E.g. "Huge milestone — traction at this stage speaks louder than the round size."

2. Fundraising Advice / Playbook — how to pitch, what investors look for, term sheets
   Style: Affirm + add one practical insight. E.g. "Investor updates with clear metrics beat polished decks every time."

3. Metrics & Growth tied to funding — ARR, MRR, unit economics, GTM, traction before/after raise
   Style: Engage with the metric or lesson. E.g. "Clear traction narrative is what turns a good pitch into a term sheet conversation."

4. Investor / VC Perspective — market trends, what investors are funding, sector theses
   Style: Thoughtful peer response. E.g. "Founders who show capital efficiency early tend to have much easier follow-on conversations."

5. Founder Journey / Fundraising Story — lessons from raising, rejections, pivots
   Style: Empathetic + relate briefly. E.g. "The no's before the yes teach more than any blog post — thanks for sharing this honestly."

6. Product / Traction Update tied to raise — milestones before or after funding
   Style: Acknowledge progress. E.g. "Clear product-market signal makes every fundraising conversation easier."

7. Hiring Post at Funded Startup — roles at a company that raised
   Style: "Commenting for better reach — exciting team scaling after the raise!"

8. Event / Webinar on Fundraising — panels, demo days, pitch competitions
   Style: "Looks like a valuable session — sharing for reach."

9. Thought Leadership / Opinion on startup ecosystem and capital markets
   Style: Agree or extend with one sentence of substance.

10. Other / Unclassified funding-related post
    Style: "Interesting perspective — thanks for sharing this with the founder community."

RULES:
- Classify the post silently. Do NOT mention the category name in your output.
- Output ONLY the comment text. No preamble, no quotes, no category label.
- 1-2 sentences, professional, sounds like someone in the startup / funding ecosystem.
- Comment ON the post author's topic — do NOT write about your own unrelated job search or network building.
- Do NOT invent funding details not in the post.
- Vary wording each time.

Post:
{post_text[:1500]}
"""


def generate_intelligent_comment(post_text, mode: str = "tpo"):
    """Generate a category-aware comment and validate before returning.
    mode='tpo'         → TPO prompt (Task 1B)
    mode='advocate'    → legal/advocate prompt (Task 1)
    mode='fundraising' → startup funding prompt (Task 1C)
    """
    if not post_text:
        return random.choice(FALLBACK_COMMENTS)

    # Pre-classify hiring posts so the AI gets a hint in the prompt
    hiring_base = None
    if is_employer_hiring_post(post_text):
        hiring_base = (
            "Commenting for better reach — great opportunity for legal professionals!"
            if mode == "advocate"
            else "Commenting for better reach — great opportunity for students!"
        )
    elif is_college_hiring_post(post_text):
        hiring_base = "Commenting for better reach — hope this reaches the right partners!"

    if hiring_base:
        ok, reason = validate_linkedin_comment(hiring_base, post_text, mode=mode)
        if ok:
            logger.info("  🤖 Using fixed hiring comment (validated)")
            return hiring_base
        logger.warning(f"  ⚠️  Hiring comment failed validation: {reason}")

    logger.info(f"  📂 Comment mode: {mode}")
    reject_reason = ""
    for attempt in range(1, MAX_COMMENT_GENERATION_ATTEMPTS + 1):
        if mode == "advocate":
            prompt = _build_advocate_comment_prompt(post_text, hiring_base)
        elif mode == "fundraising":
            prompt = _build_fundraising_comment_prompt(post_text)
        else:
            prompt = _build_tpo_comment_prompt(post_text, hiring_base)
        if reject_reason:
            prompt += (
                f"\n\nIMPORTANT: Your previous draft was rejected: {reject_reason}. "
                "Write a NEW comment that directly responds to the post topic. "
                "Do NOT describe your own unrelated career journey or network building."
            )

        try:
            comment, key_id = suite_nvidia_chat(
                prompt,
                max_tokens=150,
                temperature=0.7 if attempt == 1 else 0.4,
            )
        except Exception as e:
            logger.warning(f"  ⚠️  NVIDIA API failed (attempt {attempt}): {e}")
            break

        if not comment or len(comment) <= 10:
            reject_reason = "empty or too short"
            logger.warning(f"  ⚠️  Generated comment too short (attempt {attempt})")
            continue

        logger.info(f"  🤖 Draft comment via NVIDIA NIM — key file: {key_id}")
        ok, reject_reason = validate_linkedin_comment(comment, post_text, mode=mode)
        if ok:
            logger.info(f"  ✅ Comment approved for posting (attempt {attempt})")
            return comment
        logger.warning(f"  ↳ Rejected draft: {comment[:160]}{'...' if len(comment) > 160 else ''}")

    if hiring_base:
        logger.warning("  ⚠️  Using hiring fallback after validation failures")
        return hiring_base
    fallback = random.choice(FALLBACK_COMMENTS)
    logger.warning(f"  ⚠️  Using static fallback after validation failures: {fallback}")
    return fallback


def fetch_full_post_text(driver):
    selectors = [
        '[class*="update-components-text"] span[dir="ltr"]',
        '[class*="attributed-text-segment-list"] span',
        'div.feed-shared-update-v2__description span[dir="ltr"]',
        '.break-words span[dir="ltr"]', '.feed-shared-text__text-view',
        'article span[dir="ltr"]',
    ]
    for sel in selectors:
        try:
            els  = driver.find_elements(By.CSS_SELECTOR, sel)
            text = " ".join((el.text or "").strip() for el in els if el.is_displayed()).strip()
            if len(text) > 40:
                return text[:2000]
        except Exception:
            continue
    return ""


def get_post_permalink_via_menu(driver, post):
    """Click (...) -> 'Copy link to post' -> return URL string."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", post)
        human_delay(0.8, 1.2)

        menu_btn = None
        for sel in [
            "button[aria-label*='control menu' i]", "button[aria-label*='More options' i]",
            "button[aria-label*='More actions' i]", "button[aria-label*='Open menu' i]",
            "button[aria-label*='ellipsis' i]", "[data-control-name='ellipsis']",
        ]:
            try:
                for btn in post.find_elements(By.CSS_SELECTOR, sel):
                    if btn.is_displayed():
                        menu_btn = btn
                        break
                if menu_btn:
                    break
            except Exception:
                continue
        if not menu_btn:
            return ""

        # Inject clipboard interceptor
        try:
            driver.execute_script("""
                window.__captured_link = '';
                try {
                    const origWrite = navigator.clipboard.writeText.bind(navigator.clipboard);
                    navigator.clipboard.writeText = function(text) {
                        window.__captured_link = text;
                        try { return origWrite(text); } catch(e) { return Promise.resolve(); }
                    };
                } catch(e) {}
            """)
        except Exception:
            pass

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", menu_btn)
        human_delay(0.3, 0.5)
        driver.execute_script("arguments[0].click();", menu_btn)
        human_delay(1.5, 2.0)

        # Find "Copy link to post" item
        copy_btn = None
        try:
            cands = driver.find_elements(By.XPATH,
                "//*[contains(translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                "'abcdefghijklmnopqrstuvwxyz'),'copy link to post')]"
                " | //*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                "'abcdefghijklmnopqrstuvwxyz'),'copy link to post')]/self::button"
                " | //*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                "'abcdefghijklmnopqrstuvwxyz'),'copy link to post')]/self::a"
            )
            for c in cands:
                if c.is_displayed():
                    copy_btn = c
                    break
        except Exception:
            pass
        if not copy_btn:
            try:
                for el in driver.find_elements(By.XPATH,
                    "//*[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                    "'abcdefghijklmnopqrstuvwxyz'),'copy link')]"):
                    if el.is_displayed() and el.tag_name.lower() in ('button','a','span','li'):
                        copy_btn = el
                        break
            except Exception:
                pass

        permalink = ""
        if copy_btn:
            try:
                subprocess.run(["powershell","-Command","Set-Clipboard -Value ''"],
                               capture_output=True, timeout=3)
            except Exception:
                pass
            try:
                driver.execute_script("arguments[0].click();", copy_btn)
            except Exception:
                try:
                    copy_btn.click()
                except Exception:
                    pass
            human_delay(1.5, 2.0)

            # Strategy 1: JS interceptor
            try:
                captured = driver.execute_script("return window.__captured_link || '';")
                if captured and 'linkedin.com' in captured and (
                    '-activity-' in captured or '/posts/' in captured or '/feed/update/' in captured
                ):
                    permalink = captured.split('?')[0]
                    logger.info(f"  🔗 Permalink (JS interceptor): {permalink[:80]}")
            except Exception:
                pass

            # Strategy 2: toast scan
            if not permalink:
                try:
                    for tl in driver.find_elements(By.XPATH,
                        "//div[contains(@class,'artdeco-toast')]//a[contains(@href,'posts')"
                        " or contains(@href,'activity')]"
                        " | //a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
                        "'abcdefghijklmnopqrstuvwxyz'),'view post')]"
                    ):
                        if tl.is_displayed():
                            href = tl.get_attribute('href') or ''
                            if 'linkedin.com' in href and ('/posts/' in href or '-activity-' in href):
                                permalink = href.split('?')[0]
                                break
                except Exception:
                    pass

            # Strategy 3: PowerShell clipboard
            if not permalink:
                clipped = _read_clipboard()
                if clipped and 'linkedin.com' in clipped and (
                    '-activity-' in clipped or '/posts/' in clipped or '/feed/update/' in clipped
                ):
                    permalink = clipped.split('?')[0]

        return permalink
    except Exception as e:
        logger.warning(f"  ⚠️  get_post_permalink_via_menu error: {e}")
        return ""


def init_comments_db():
    conn = sqlite3.connect(COMMENTS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_commented_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, post_url TEXT UNIQUE,
        author TEXT, post_text TEXT, comment TEXT, profile_key TEXT,
        commented_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    existing = {r[1] for r in conn.execute("PRAGMA table_info(ai_commented_posts)")}
    for col, typ in [("author","TEXT"),("post_text","TEXT"),("comment","TEXT"),
                     ("profile_key","TEXT"),("commented_at","TIMESTAMP DEFAULT CURRENT_TIMESTAMP")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE ai_commented_posts ADD COLUMN {col} {typ}")
    conn.commit()
    return conn


def already_commented(conn, post_url, post_text=""):
    if not conn:
        return False
    try:
        if post_url and conn.execute(
            "SELECT id FROM ai_commented_posts WHERE post_url=?", (post_url,)
        ).fetchone():
            return True
        if post_text and len(post_text) > 30:
            prefix = post_text[:100]
            for (db_text,) in conn.execute(
                "SELECT post_text FROM ai_commented_posts ORDER BY id DESC LIMIT 500"
            ).fetchall():
                if db_text and len(db_text) > 30 and db_text[:100] == prefix:
                    return True
    except Exception:
        pass
    return False


def record_comment(conn, post_url, author, post_text, comment):
    if not conn:
        return
    key = post_url or f"unknown_{PROFILE_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ai_commented_posts (post_url,author,post_text,comment,profile_key) VALUES (?,?,?,?,?)",
            (key, author, (post_text or "")[:500], comment, PROFILE_NAME)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"record_comment DB error: {e}")


def run_task1_comment(driver, conn, search_url_override=None, task_label="🤖 TASK 1: AI Comment on Advocate Post",
                      url_generator_fn=None, comment_mode: str = "advocate",
                      random_post_pick: bool = False, scroll_min: int = 2, scroll_max: int = 6):
    """Task 1 / Task 1B / Task 1C: Post 1 AI comment on a search-result post.
    Pass search_url_override for a fixed URL, or url_generator_fn to generate
    a fresh URL on each attempt (used when a keyword pool is exhausted).
    random_post_pick=True shuffles the feed and picks one eligible post at random."""
    logger.info("\n" + "=" * 60)
    logger.info(task_label)
    logger.info("=" * 60)

    search_url = search_url_override if search_url_override else get_comment_search_url()
    already_done = set()

    open_new_tab(driver, search_url)
    cur = driver.current_url.lower()
    if any(x in cur for x in ["login","authwall","signup","checkpoint"]):
        logger.error("❌ Not logged in")
        return False

    log_page_diagnostic(driver)
    human_delay(4.0, 6.0)   # extra settle time — new tab loads slower than in-place navigation

    # Wait for posts
    start = time.time(); posts_found = False
    while time.time() - start < WAIT_FOR_POSTS_SECONDS:
        posts = js(driver, JS_FIND_POSTS) or []
        if len(posts) > 2:
            posts_found = True
            if len(posts) >= 15:
                break
        scroll_down(driver, px=800); human_delay(1.5, 2.5)
    if not posts_found:
        logger.warning("⚠️  No posts found"); return False

    scroll_depth = random.randint(scroll_min, scroll_max)
    logger.info(f"  🎲 Random pre-scroll: {scroll_depth} page(s) (max {scroll_max})")
    for _ in range(scroll_depth):
        scroll_down(driver, px=random.randint(700, 1300))
        human_delay(1.5, 2.5)

    posts = js(driver, JS_FIND_POSTS) or []
    logger.info(f"  Found {len(posts)} posts after scroll")

    scan_pool = posts[:MAX_POSTS_TO_SCAN]
    if random_post_pick:
        random.shuffle(scan_pool)
        logger.info("  🎲 Post order shuffled for random selection")
    else:
        hour_offset = datetime.now().hour % 12
        logger.info(f"  🕐 Hour offset: {hour_offset}")
        total_scan = len(scan_pool)
        scan_pool = [scan_pool[(hour_offset + i) % total_scan] for i in range(total_scan)] if total_scan else []

    # Collect eligible posts
    eligible = []
    for post in scan_pool:
        post_url  = (get_post_permalink_via_menu(driver, post) or js(driver, JS_FIND_PERMALINK, post) or "")
        if not post_url or post_url in already_done:
            continue
        post_text = (js(driver, JS_FIND_TEXT, post) or "").strip()
        if already_commented(conn, post_url, post_text):
            continue
        author = js(driver, JS_FIND_AUTHOR, post) or "Unknown"
        if comment_mode == "fundraising" and not is_funding_related_post(post_text, author):
            continue
        eligible.append((post_url, post_text, author))

    if random_post_pick and eligible:
        candidates = random.sample(eligible, min(len(eligible), MAX_COMMENTS_PER_RUN))
        logger.info(f"  🎲 Random pick: {len(candidates)} post(s) from {len(eligible)} eligible (not top-of-feed)")
    else:
        candidates = eligible[:MAX_COMMENTS_PER_RUN]

    logger.info(f"  {len(candidates)} candidate(s) queued")

    # If this keyword pool is exhausted, try up to 2 more keywords before giving up
    retry_attempts = 0
    while not candidates and url_generator_fn and retry_attempts < 2:
        retry_attempts += 1
        new_url = url_generator_fn()
        logger.info(f"  🔄 Pool exhausted — retry {retry_attempts}: trying new keyword...")
        driver.get(new_url)
        human_delay(5.0, 7.0)
        log_page_diagnostic(driver)
        # Scroll before scanning
        for _ in range(random.randint(1, 3)):
            scroll_down(driver, px=random.randint(700, 1300))
        retry_posts = js(driver, JS_FIND_POSTS) or []
        logger.info(f"  Found {len(retry_posts)} posts on retry keyword")
        for post in retry_posts[:MAX_POSTS_TO_SCAN]:
            post_url  = (get_post_permalink_via_menu(driver, post) or js(driver, JS_FIND_PERMALINK, post) or "")
            if not post_url or post_url in already_done:
                continue
            post_text = (js(driver, JS_FIND_TEXT, post) or "").strip()
            if already_commented(conn, post_url, post_text):
                continue
            author = js(driver, JS_FIND_AUTHOR, post) or "Unknown"
            if comment_mode == "fundraising" and not is_funding_related_post(post_text, author):
                continue
            eligible.append((post_url, post_text, author))
        if random_post_pick and eligible:
            candidates = random.sample(eligible, min(len(eligible), MAX_COMMENTS_PER_RUN))
        else:
            candidates = eligible[:MAX_COMMENTS_PER_RUN]
        logger.info(f"  {len(candidates)} candidate(s) after retry")

    if not candidates:
        logger.info("  No eligible posts found across all keyword attempts"); return False

    successful_comments = 0
    for post_url, post_text, author in candidates:
        logger.info(f"\n  🔗 {post_url}")
        try:
            driver.get(post_url)
            human_delay(5.0, 7.0)
        except Exception:
            continue

        cur = driver.current_url
        if not ('-activity-' in cur or '/posts/' in cur or '/feed/update/' in cur):
            logger.warning(f"  Not a post page: {cur[:60]}"); continue

        # Beep to signal post is open and comment is about to be written
        try:
            winsound.Beep(900, 200)
            winsound.Beep(1100, 200)
        except Exception:
            pass

        full_text    = fetch_full_post_text(driver)
        text_for_ai  = full_text if len(full_text) > 50 else post_text
        if comment_mode == "fundraising" and not is_funding_related_post(text_for_ai, author):
            logger.info("  ⏭️  Skipping — no funding/fundraising signal in post or author")
            continue
        comment_text = generate_intelligent_comment(text_for_ai, mode=comment_mode)
        logger.info(f"  💬 Comment: {comment_text}")

        # Find post element
        post_el = None
        for sel in ['[data-urn*="activity"]','[data-urn*="ugcPost"]','article','div[role="article"]','main']:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    post_el = els[0]; break
            except Exception:
                pass
        if not post_el:
            try:
                post_el = driver.find_element(By.TAG_NAME, "body")
            except Exception:
                pass

        if not open_comments(driver, post_el):
            logger.warning("  Could not open comments"); continue
        human_delay(2.0, 3.0)

        success = post_comment_to_box(driver, comment_text)
        if success:
            record_comment(conn, post_url, author, post_text, comment_text)
            already_done.add(post_url)
            successful_comments += 1
            logger.info(f"  🎉 Comment posted! ({successful_comments}/{MAX_COMMENTS_PER_RUN})")
            beep_success()
            if successful_comments >= MAX_COMMENTS_PER_RUN:
                return True
            else:
                human_delay(BETWEEN_COMMENTS_MIN, BETWEEN_COMMENTS_MAX)
        else:
            logger.warning("  Failed on this post — trying next")
            human_delay(2.0, 3.0)

    logger.info(f"  Finished run. Total comments posted: {successful_comments}"); return successful_comments > 0


# ==================== TASK 2: CONGRATULATE ====================
def init_congrats_db():
    conn = sqlite3.connect(CONGRATS_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS congratulated_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, post_url TEXT UNIQUE,
        author TEXT, post_text TEXT, comment TEXT, profile_key TEXT,
        congratulated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    existing = {r[1] for r in conn.execute("PRAGMA table_info(congratulated_posts)")}
    for col, typ in [("author","TEXT"),("post_text","TEXT"),("comment","TEXT"),
                     ("profile_key","TEXT"),("congratulated_at","TIMESTAMP DEFAULT CURRENT_TIMESTAMP")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE congratulated_posts ADD COLUMN {col} {typ}")
    conn.commit()
    return conn


def _text_hash(text):
    """Short MD5 hash of post text used as a fallback dedup key."""
    if not text:
        return ""
    return "texthash_" + hashlib.md5(text[:300].encode("utf-8", errors="replace")).hexdigest()[:16]


def already_congratulated(conn, post_url, post_text=""):
    if not conn:
        return False
    try:
        if post_url:
            if conn.execute(
                "SELECT id FROM congratulated_posts WHERE post_url=?", (post_url,)
            ).fetchone():
                return True
        # Also check by text hash so posts without a URL aren't re-congratulated
        th = _text_hash(post_text)
        if th:
            if conn.execute(
                "SELECT id FROM congratulated_posts WHERE post_url=?", (th,)
            ).fetchone():
                return True
        return False
    except Exception:
        return False


def record_congratulation(conn, post_url, author, post_text, comment):
    if not conn:
        return
    # Use text hash as key when URL is missing — ensures dedup works across runs
    key = post_url or _text_hash(post_text) or f"unknown_{PROFILE_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        conn.execute(
            "INSERT OR IGNORE INTO congratulated_posts (post_url,author,post_text,comment,profile_key) VALUES (?,?,?,?,?)",
            (key, author, (post_text or "")[:500], comment, PROFILE_NAME)
        )
        conn.commit()
        logger.info(f"  💾 Saved to DB — key: {key[:80]}")
    except Exception as e:
        logger.error(f"record_congratulation DB error: {e}")


def post_congratulations_t2(driver, comment_text):
    """
    Post a congratulatory comment using the robust approach from the standalone script:
    - execCommand('insertText') for reliable typing in LinkedIn's Quill editor
    - Walks up DOM to find the comment form container
    - Searches for submit button INSIDE that container to avoid clicking the wrong button
    - 4 fallback submit strategies
    """
    try:
        # --- Find the comment box ---
        boxes = driver.find_elements(By.CSS_SELECTOR,
            'div[contenteditable="true"], div[role="textbox"]')
        comment_box = None
        for box in boxes:
            label = (box.get_attribute("aria-label") or "").lower()
            ph    = (box.get_attribute("data-placeholder") or "").lower()
            if "comment" in label or "comment" in ph or "add a comment" in label:
                comment_box = box
                break
        if not comment_box:
            for box in boxes:
                if box.is_displayed():
                    comment_box = box
                    break
        if not comment_box:
            logger.warning("  No contenteditable comment box found on page")
            return False

        logger.info(f"  Found comment box, label='{comment_box.get_attribute('aria-label')}'")
        driver.execute_script("arguments[0].scrollIntoView(true);", comment_box)
        human_delay(0.5, 1.0)

        # --- Type via execCommand (most reliable for LinkedIn Quill editor) ---
        driver.execute_script("arguments[0].click(); arguments[0].focus();", comment_box)
        human_delay(0.5, 1.0)
        driver.execute_script(
            "arguments[0].focus(); document.execCommand('insertText', false, arguments[1]);",
            comment_box, comment_text
        )
        human_delay(1.0, 1.5)

        # Verify text was entered
        cur_text = (comment_box.text or comment_box.get_attribute("textContent") or "").strip()
        if len(cur_text) < 5:
            # Fallback: clipboard paste
            logger.info("  execCommand produced no text — trying clipboard paste")
            if _write_clipboard(comment_text):
                ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
                human_delay(1.0, 1.5)

        # --- Fire React events to enable the submit button ---
        driver.execute_script("""
            let box = arguments[0];
            box.dispatchEvent(new InputEvent('input',  { bubbles: true, data: box.textContent }));
            box.dispatchEvent(new Event('change', { bubbles: true }));
            box.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
        """, comment_box)
        human_delay(3.0, 4.0)

        # --- Walk up DOM to find the comment form container ---
        form_container = driver.execute_script("""
            const box = arguments[0];
            let el = box;
            for (let i = 0; i < 15; i++) {
                if (!el || !el.parentElement) break;
                el = el.parentElement;
                const tag = el.tagName && el.tagName.toLowerCase();
                const cls = el.className || '';
                if (tag === 'form' || cls.includes('comment-box') ||
                    cls.includes('comment-editor') || cls.includes('comments-comment-box') ||
                    cls.includes('editor') || cls.includes('ql-editor')) {
                    return el;
                }
                if (el.querySelectorAll('button').length >= 1 &&
                    el.querySelectorAll('div[contenteditable]').length >= 1) {
                    return el;
                }
            }
            return null;
        """, comment_box)
        logger.info(f"  Comment form container found: {form_container is not None}")

        posted = False

        # --- Strategy 1: artdeco-button--primary INSIDE the comment form ---
        if form_container:
            primary_btns = form_container.find_elements(By.CSS_SELECTOR, "button.artdeco-button--primary")
        else:
            primary_btns = driver.find_elements(By.CSS_SELECTOR, "button.artdeco-button--primary")

        logger.info(f"  Found {len(primary_btns)} primary button(s)")
        for btn in primary_btns:
            if not btn.is_displayed():
                continue
            btn_text = (btn.text or "").strip()
            disabled = btn.get_attribute("disabled")
            logger.info(f"  Primary btn: '{btn_text}' disabled={disabled}")
            if disabled:
                driver.execute_script(
                    "arguments[0].removeAttribute('disabled');"
                    "arguments[0].removeAttribute('aria-disabled');", btn)
                human_delay(0.5, 0.8)
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                human_delay(0.5, 0.8)
                driver.execute_script("arguments[0].click();", btn)
                logger.info(f"  Clicked primary submit button: '{btn_text}'")
                posted = True
                break
            except Exception:
                try:
                    ActionChains(driver).move_to_element(btn).click().perform()
                    logger.info(f"  Clicked primary submit button (ActionChains)")
                    posted = True
                    break
                except Exception:
                    pass

        # --- Strategy 2: text-based button search INSIDE the form ---
        if not posted:
            logger.info("  Trying text-based button search inside comment form...")
            all_btns = form_container.find_elements(By.TAG_NAME, "button") if form_container                        else driver.find_elements(By.TAG_NAME, "button")
            for btn in all_btns:
                t    = (btn.text or "").strip().lower()
                aria = (btn.get_attribute("aria-label") or "").lower()
                if t not in ("comment", "post", "post comment") and "post comment" not in aria:
                    continue
                if not btn.is_displayed():
                    continue
                if form_container is None:
                    btn_y = btn.location.get('y', 0)
                    box_y = comment_box.location.get('y', 0)
                    if abs(btn_y - box_y) > 250:
                        continue
                disabled = btn.get_attribute("disabled")
                if disabled:
                    driver.execute_script("arguments[0].removeAttribute('disabled');", btn)
                    human_delay(0.3, 0.5)
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                    human_delay(0.5, 0.8)
                    driver.execute_script("arguments[0].click();", btn)
                    logger.info(f"  Clicked submit button by text: '{t}'")
                    posted = True
                    break
                except Exception:
                    pass

        # --- Strategy 3: Enter key ---
        if not posted:
            try:
                logger.info("  Trying Enter key to submit...")
                comment_box.click()
                human_delay(0.3, 0.5)
                comment_box.send_keys(Keys.ENTER)
                logger.info("  Submitted via Enter")
                posted = True
            except Exception:
                pass

        # --- Strategy 4: Ctrl+Enter ---
        if not posted:
            try:
                logger.info("  Trying Ctrl+Enter to submit...")
                comment_box.send_keys(Keys.CONTROL, Keys.ENTER)
                logger.info("  Submitted via Ctrl+Enter")
                posted = True
            except Exception:
                pass

        if posted:
            human_delay(4.0, 5.0)
            # Verify comment box is gone (text cleared = submitted)
            try:
                final = (comment_box.text or comment_box.get_attribute("textContent") or "").strip()
                if len(final) > 5:
                    logger.warning("  Comment box still has text — submission may have failed")
                    return False
            except Exception:
                pass  # element may be detached = modal closed = success
            return True

        logger.warning("  Could not submit comment")
        return False

    except Exception as e:
        logger.error(f"post_congratulations_t2 error: {e}")
        return False


def run_task2_congratulate(driver, conn):
    """Task 2: Post 1 congratulatory comment on an achievement post.
    Works on the search results page directly (no per-post navigation).
    Uses post_congratulations_t2() for robust submit-button detection."""
    logger.info("\n" + "=" * 60)
    logger.info("🎉 TASK 2: Congratulate Achievement Post")
    logger.info("=" * 60)

    search_url = get_congrats_search_url()
    open_new_tab(driver, search_url)
    human_delay(8.0, 10.0)
    cur = driver.current_url.lower()
    if any(x in cur for x in ["login","authwall","signup","checkpoint"]):
        logger.error("❌ Not logged in"); return False

    log_page_diagnostic(driver)

    # Wait for posts to load
    start = time.time(); posts_found = False
    while time.time() - start < WAIT_FOR_POSTS_SECONDS:
        posts = js(driver, JS_FIND_POSTS) or []
        if len(posts) > 2:
            posts_found = True
            if len(posts) >= 10:
                break
        scroll_down(driver, px=500); human_delay(2.0, 3.0)
    if not posts_found:
        logger.warning("⚠️  No posts found"); return False

    # Random scroll (1-4 times) so the post pool varies each run
    scroll_rounds = random.randint(1, 4)
    logger.info(f"  🎲 Scrolling {scroll_rounds} time(s) to vary post pool...")
    for _ in range(scroll_rounds):
        scroll_down(driver, px=random.randint(600, 1200))
        human_delay(1.5, 2.5)

    posts = js(driver, JS_FIND_POSTS) or []
    logger.info(f"  Found {len(posts)} posts")
    if not posts:
        logger.warning("  No posts after scroll"); return False

    # Hour-based starting offset (0-11) so different posts are tried at different times of day
    hour_offset = datetime.now().hour % 12
    logger.info(f"  🕐 Hour offset: {hour_offset} (current hour {datetime.now().hour})")

    scan_list = posts[:MAX_POSTS_TO_SCAN]
    total = len(scan_list)

    for i in range(total):
        idx  = (hour_offset + i) % total
        post = scan_list[idx]
        logger.info(f"\n  ── Post #{idx+1} (scan position {i+1}/{total}) ──")

        post_url  = js(driver, JS_FIND_PERMALINK, post) or ""
        post_text = (js(driver, JS_FIND_TEXT, post) or "").strip()

        if already_congratulated(conn, post_url, post_text):
            logger.info("  Already congratulated — skip"); continue

        author = js(driver, JS_FIND_AUTHOR, post) or "Unknown"
        post_text_lower = post_text.lower()

        # ── Guard 1: reject job postings / hiring ads ─────────────────────────
        JOB_POST_SIGNALS = [
            "#hiring", "job title:", "pay:", "apply here:", "apply now:",
            "job description:", "responsibilities:", "requirements:",
            "we are hiring", "we're hiring", "now hiring", "currently hiring",
            "we are seeking", "we're seeking", "looking to hire",
            "salary:", "compensation:", "location:", "immediate joiner",
            "urgent requirement", "urgent hiring", "walk-in interview",
        ]
        if is_hiring_post(post_text) or any(sig in post_text_lower for sig in JOB_POST_SIGNALS):
            logger.info(f"  ⏩ Skipping — looks like a job posting: {post_text[:60]}...")
            continue

        # ── Guard 2: reject job-board / recruiter accounts ────────────────────
        author_lower = author.lower()
        JOB_BOARD_SIGNALS = ["jobs in", "jobs at", " jobs,", "hiring ", "recruiter",
                             "recruitment", "staffing", "talent acquisition",
                             "hr solutions", "job portal", "careers at"]
        if any(sig in author_lower for sig in JOB_BOARD_SIGNALS):
            logger.info(f"  ⏩ Skipping — author looks like a job board: {author}")
            continue

        # ── Guard 3: must contain at least one personal achievement signal ────
        if not any(kw in post_text_lower for kw in ACHIEVEMENT_KEYWORDS):
            logger.info(f"  ⏩ Skipping — no achievement keywords found: {post_text[:60]}...")
            continue

        logger.info(f"  👤 {author} | {post_text[:80]}...")

        # Open the comments section inline on the search results page
        logger.info("  🔓 Opening comments section...")
        open_comments(driver, post)
        human_delay(2.0, 3.0)

        comment_text = random.choice(COMMENT_TEMPLATES)
        logger.info(f"  💬 {comment_text}")

        success = post_congratulations_t2(driver, comment_text)
        if success:
            record_congratulation(conn, post_url or driver.current_url, author, post_text, comment_text)
            logger.info("  🎉 Congratulation posted!")
            beep_success()
            return True
        else:
            logger.warning("  Failed on this post — trying next")

    logger.info("  No congratulation posted this run"); return False


# ==================== TASK 3: LIKE ====================
def init_likes_db():
    conn = sqlite3.connect(LIKES_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS liked_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, post_url TEXT UNIQUE,
        author TEXT, post_text TEXT, profile_key TEXT,
        liked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    conn.commit()
    existing = {r[1] for r in conn.execute("PRAGMA table_info(liked_posts)")}
    for col, typ in [("author","TEXT"),("post_text","TEXT"),("profile_key","TEXT"),
                     ("liked_at","TIMESTAMP DEFAULT CURRENT_TIMESTAMP")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE liked_posts ADD COLUMN {col} {typ}")
    conn.commit()
    return conn


def already_liked(conn, post_url):
    if not conn or not post_url:
        return False
    try:
        return conn.execute(
            "SELECT id FROM liked_posts WHERE post_url=?", (post_url,)
        ).fetchone() is not None
    except Exception:
        return False


def record_like(conn, post_url, author, post_text):
    if not conn:
        return
    key = post_url or f"unknown_{PROFILE_NAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        conn.execute(
            "INSERT OR IGNORE INTO liked_posts (post_url,author,post_text,profile_key) VALUES (?,?,?,?)",
            (key, author, (post_text or "")[:500], PROFILE_NAME)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"record_like DB error: {e}")


def _is_like_button(btn):
    """Return True if btn is a genuine 'Like' reaction button (not already-liked, not other reactions)."""
    try:
        label = (btn.get_attribute("aria-label") or "").lower()
        text  = (btn.text or "").lower().strip()
        if "like" not in label and "like" not in text:
            return False
        if "unlike" in label or "unlike" in text:
            return False
        if any(r in label for r in ["love","haha","wow","sad","angry","support","celebrate"]):
            return False
        pressed = btn.get_attribute("aria-pressed")
        if pressed == "true":
            return False
        return True
    except Exception:
        return False


def click_like_button(driver, post):
    """Find and click the Like button on a post. Returns True, False, or 'already_liked'."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", post)
        human_delay(1.0, 1.5)

        all_btns = driver.find_elements(By.CSS_SELECTOR, "button, [role='button']")
        like_candidates = []
        post_rect = driver.execute_script(
            "const r=arguments[0].getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height};", post
        ) or {}
        post_y = post_rect.get('y', 0)
        post_h = post_rect.get('h', 400)

        for btn in all_btns:
            if not btn.is_displayed():
                continue
            label = (btn.get_attribute("aria-label") or "").lower()
            text  = (btn.text or "").lower().strip()

            if "like" not in label and "like" not in text:
                continue

            if "unlike" in label or "unlike" in text or btn.get_attribute("aria-pressed") == "true":
                return "already_liked"

            if not _is_like_button(btn):
                continue

            try:
                btn_rect = driver.execute_script(
                    "const r=arguments[0].getBoundingClientRect(); return {x:r.x,y:r.y};", btn
                ) or {}
                btn_y = btn_rect.get('y', 0)
                dist  = abs(btn_y - (post_y + post_h))
                like_candidates.append((dist, btn))
            except Exception:
                like_candidates.append((9999, btn))

        if not like_candidates:
            logger.warning("  No Like button found")
            return False

        like_candidates.sort(key=lambda x: x[0])
        _, btn = like_candidates[0]

        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        human_delay(0.5, 1.0)
        try:
            btn.click()
            logger.info("  ✅ Liked (native click)")
        except Exception:
            try:
                ActionChains(driver).move_to_element(btn).click().perform()
                logger.info("  ✅ Liked (ActionChains)")
            except Exception:
                driver.execute_script("arguments[0].click();", btn)
                logger.info("  ✅ Liked (JS click)")
        return True
    except Exception as e:
        logger.error(f"click_like_button error: {e}")
        return False


def run_task3_like(driver, conn):
    """Task 3: Like up to MAX_LIKES_PER_RUN advocate posts."""
    logger.info("\n" + "=" * 60)
    logger.info(f"👍 TASK 3: Like Advocate Posts (target: {MAX_LIKES_PER_RUN})")
    logger.info("=" * 60)

    search_url = get_like_search_url()
    open_new_tab(driver, search_url)
    cur = driver.current_url.lower()
    if any(x in cur for x in ["login","authwall","signup","checkpoint"]):
        logger.error("❌ Not logged in"); return 0

    log_page_diagnostic(driver)

    # Wait for posts
    start = time.time(); posts_found = False
    while time.time() - start < WAIT_FOR_POSTS_SECONDS:
        posts = js(driver, JS_FIND_POSTS) or []
        if len(posts) > 2:
            posts_found = True; break
        scroll_down(driver, px=500); human_delay(2.0, 3.0)
    if not posts_found:
        logger.warning("⚠️  No posts found"); return 0

    # Random initial scroll (1-4 rounds) so the post pool varies each run
    init_scrolls = random.randint(1, 4)
    logger.info(f"  🎲 Initial scroll: {init_scrolls} round(s) to vary post pool")
    for _ in range(init_scrolls):
        scroll_down(driver, px=random.randint(600, 1200))
        human_delay(1.5, 2.5)

    likes_done    = 0
    posts_scanned = 0
    scroll_rounds = 0

    while likes_done < MAX_LIKES_PER_RUN and scroll_rounds < MAX_SCROLL_ROUNDS:
        posts    = js(driver, JS_FIND_POSTS) or []
        new_posts = posts[posts_scanned:]

        if not new_posts:
            scroll_down(driver, px=SCROLL_PX); scroll_rounds += 1
            human_delay(2.5, 4.0); continue

        for post in new_posts:
            posts_scanned += 1
            if likes_done >= MAX_LIKES_PER_RUN:
                break

            post_url  = js(driver, JS_FIND_PERMALINK, post) or ""
            post_text = (js(driver, JS_FIND_TEXT, post) or "").strip()
            author    = js(driver, JS_FIND_AUTHOR, post) or "Unknown"
            logger.info(f"\n  Post #{posts_scanned} | {author} | {post_text[:80]}...")

            if post_url and already_liked(conn, post_url):
                logger.info("  Already liked (DB) — skip"); continue

            time.sleep(random.uniform(2.5, 5.5))
            result = click_like_button(driver, post)

            if result == "already_liked":
                if post_url:
                    record_like(conn, post_url, author, post_text)
                continue
            elif result is True:
                url_to_save = post_url or driver.current_url
                record_like(conn, url_to_save, author, post_text)
                likes_done += 1
                logger.info(f"  🎉 LIKED ({likes_done}/{MAX_LIKES_PER_RUN})")
                beep_success()
                if likes_done < MAX_LIKES_PER_RUN:
                    time.sleep(random.uniform(BETWEEN_LIKES_MIN, BETWEEN_LIKES_MAX))
                    scroll_down(driver, px=random.randint(300, 600))
            else:
                logger.warning("  Could not like — trying next")

        if likes_done < MAX_LIKES_PER_RUN:
            scroll_down(driver, px=SCROLL_PX); scroll_rounds += 1
            human_delay(3.0, 5.0)

    logger.info(f"\n  ✅ Task 3 done — {likes_done} like(s)")
    return likes_done


# ==================== TASK 4: POST TODAY'S CONTENT ====================
def load_post_for_today():
    """Load today's post content from the SQLite DB by day-of-month."""
    day = datetime.now().day
    try:
        conn = sqlite3.connect(POSTS_DB)
        row  = conn.execute("SELECT content FROM posts WHERE day=?", (day,)).fetchone()
        conn.close()
        if row:
            logger.info(f"  📅 Loaded post for day {day} from DB")
            return row[0]
        else:
            logger.error(f"  ❌ No post in DB for day {day}")
            return None
    except Exception as e:
        logger.error(f"  ❌ Failed to read posts DB: {e}")
        return None


def _find_start_post_trigger(driver):
    """Find the 'Start a post' trigger button on the LinkedIn feed page."""
    try:
        el = driver.execute_script("""
            const texts = ['Start a post', 'start a post', 'Write an article'];
            for (const text of texts) {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
                let node;
                while (node = walker.nextNode()) {
                    if (node.textContent.trim().toLowerCase() === text.toLowerCase()) {
                        let el = node.parentElement;
                        for (let i = 0; i < 8; i++) {
                            if (!el) break;
                            const tag = el.tagName ? el.tagName.toLowerCase() : '';
                            const role = (el.getAttribute('role') || '').toLowerCase();
                            if (tag === 'button' || role === 'button') return el;
                            el = el.parentElement;
                        }
                    }
                }
            }
            return null;
        """)
        if el and el.is_displayed():
            return el
    except Exception:
        pass

    for sel in [
        "button[aria-label*='post' i]",
        "div[aria-placeholder*='Start a post' i]",
        "div.share-box-feed-entry__trigger",
        "button.share-box-feed-entry__trigger",
        "[class*='share-box'] button",
        "[class*='start-post'] button",
    ]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed():
                    return el
        except Exception:
            continue

    return None


def _wait_for_post_editor(driver, timeout=20):
    """Poll until a contenteditable post editor appears. Returns element or None.
    Tries LinkedIn/Quill-specific selectors first, then generic contenteditable."""
    # Ordered list of CSS selectors — most specific first
    EDITOR_SELECTORS = [
        # LinkedIn Quill editor (most reliable)
        'div.ql-editor[contenteditable="true"]',
        # Generic share-modal contenteditable with placeholder
        'div[contenteditable="true"][data-placeholder]',
        # Any contenteditable in the share dialog / modal overlay
        'div.share-creation-state__text-editor div[contenteditable="true"]',
        'div[class*="share"] div[contenteditable="true"]',
        'div[class*="editor"] div[contenteditable="true"]',
        # Role textbox in modal
        'div[role="dialog"] div[role="textbox"]',
        'div[role="dialog"] div[contenteditable="true"]',
        # Fallback broad selectors
        'div[contenteditable="true"]',
        'div[role="textbox"]',
    ]
    deadline = time.time() + timeout
    while time.time() < deadline:
        for sel in EDITOR_SELECTORS:
            try:
                boxes = driver.find_elements(By.CSS_SELECTOR, sel)
                visible = [b for b in boxes if b.is_displayed() and b.is_enabled()]
                if not visible:
                    continue
                visible.sort(
                    key=lambda b: (b.size or {}).get('width', 0) * (b.size or {}).get('height', 0),
                    reverse=True
                )
                candidate = visible[0]
                label = (candidate.get_attribute("aria-label") or "").lower()
                ph    = (candidate.get_attribute("data-placeholder") or "").lower()
                # Skip comment boxes (we want the POST editor)
                if "comment" in label or "comment" in ph:
                    continue
                w = (candidate.size or {}).get('width', 0)
                h = (candidate.size or {}).get('height', 0)
                if w > 100 and h > 20:
                    logger.info(f"  Editor found via selector: {sel!r} ({w}x{h})")
                    return candidate
            except Exception:
                pass
        time.sleep(0.5)
    return None


def _visual_click_phrase(phrase):
    """OCR scan the screen to find a phrase and click its center. Returns True on success."""
    if not VISUAL_POST_AVAILABLE or not TESSERACT_AVAILABLE:
        logger.warning("  pytesseract/cv2 not available — cannot OCR click")
        return False
    words = phrase.lower().split()
    if not words:
        return False
    try:
        screenshot = ImageGrab.grab()
        gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        d = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
        for i in range(len(d['text'])):
            word = ''.join(c for c in d['text'][i].lower() if c.isalnum())
            target = ''.join(c for c in words[0] if c.isalnum())
            if word != target or not word:
                continue
            match = True
            for j in range(1, len(words)):
                if i + j >= len(d['text']):
                    match = False; break
                nw = ''.join(c for c in d['text'][i+j].lower() if c.isalnum())
                nt = ''.join(c for c in words[j] if c.isalnum())
                if nw != nt:
                    match = False; break
            if not match:
                continue
            last = i + len(words) - 1
            x1 = d['left'][i]
            y1 = d['top'][i]
            w_total = (d['left'][last] + d['width'][last]) - x1
            h = max(d['height'][i:last+1])
            if h > 100 or w_total > 800:
                continue
            cx = x1 + w_total // 2
            cy = y1 + h // 2
            logger.info(f"  OCR: found '{phrase}' at ({cx},{cy})")
            pyautogui.moveTo(cx, cy, duration=0.4)
            time.sleep(0.3)
            pyautogui.mouseDown(); time.sleep(0.08); pyautogui.mouseUp()
            return True
    except Exception as e:
        logger.warning(f"  OCR click error: {e}")
    return False


def _visual_find_post_button():
    """Find the solid LinkedIn-blue 'Post' pill button via CV2 color detection."""
    if not VISUAL_POST_AVAILABLE:
        return False
    try:
        screenshot = ImageGrab.grab()
        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([100,120,120]), np.array([130,255,255]))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if 40 < cw < 150 and 20 < ch < 60:
                cx, cy = x + cw//2, y + ch//2
                logger.info(f"  CV2: found Post button at ({cx},{cy})")
                pyautogui.moveTo(cx, cy, duration=0.4)
                time.sleep(0.3)
                pyautogui.mouseDown(); time.sleep(0.08); pyautogui.mouseUp()
                return True
    except Exception as e:
        logger.warning(f"  CV2 button error: {e}")
    return False


def _visual_human_type(text):
    """Type text with human-like timing, handles unicode/emojis via clipboard."""
    if not VISUAL_POST_AVAILABLE:
        return
    for char in text:
        if random.random() < 0.03 and char.isalpha():
            typo = random.choice([-1, 1])
            if 32 <= (ord(char) + typo) <= 126:
                pyautogui.write(chr(ord(char) + typo))
                time.sleep(random.uniform(0.15, 0.35))
                pyautogui.press('backspace')
                time.sleep(random.uniform(0.15, 0.35))
        if char == '\n':
            pyautogui.press('enter')
            time.sleep(random.uniform(0.3, 0.6))
            continue
        if ord(char) > 127:
            pyperclip.copy(char)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(random.uniform(0.08, 0.2))
        else:
            pyautogui.write(char)
        delay = random.uniform(0.03, 0.12)
        if char in [" ", ".", "?", ",", "!"]:
            delay += random.uniform(0.1, 0.3)
        time.sleep(delay)


def run_task4_post(driver):
    """Task 4: Load today's post and publish using the visual OCR + CV2 approach."""
    logger.info("\n" + "=" * 60)
    logger.info("📝 TASK 4: Post Today's Content")
    logger.info("=" * 60)

    if not VISUAL_POST_AVAILABLE:
        logger.error("  ❌ Visual posting not available — install: cv2, numpy, Pillow, pyautogui, pyperclip")
        return False
    if not TESSERACT_AVAILABLE:
        logger.error("  ❌ pytesseract not available — install Tesseract OCR and pytesseract")
        return False

    content = load_post_for_today()
    if not content:
        logger.error("  ❌ No content found for today — skipping Task 4")
        return False
    logger.info(f"  📄 Content preview: {content[:100]}...")

    ok, reason = validate_linkedin_post(content)
    if not ok:
        logger.error(f"  ❌ Post failed validation — not publishing: {reason}")
        return False

    # Navigate to LinkedIn feed in a new tab via Selenium
    open_new_tab(driver, "https://www.linkedin.com/feed/")
    human_delay(8.0, 10.0)

    # Bring Firefox window to the foreground
    try:
        wins = [w for w in gw.getAllWindows()
                if "linkedin" in w.title.lower() and "firefox" in w.title.lower()]
        if wins:
            win = wins[0]
            if win.isMinimized:
                win.restore()
            ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.SetForegroundWindow(win._hWnd)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
            win.activate()
            time.sleep(1.0)
            logger.info("  ✅ Firefox window brought to front")
    except Exception as e:
        logger.warning(f"  Window focus warning: {e}")

    # Step 1: OCR-click "Start a post"
    logger.info("  🔍 Looking for 'Start a post' on screen (OCR)...")
    clicked = _visual_click_phrase("start a post") or _visual_click_phrase("Start a post")
    if not clicked:
        logger.error("  ❌ Could not find 'Start a post' on screen — is the feed loaded?")
        return False

    logger.info("  ⏳ Waiting for post modal to open...")
    time.sleep(3.5)

    # Step 2: Click inside the text area
    logger.info("  🔍 Anchoring inside the text area...")
    if not _visual_click_phrase("what do you want"):
        # Fallback: click slightly above screen center (where modal text box is)
        logger.warning("  Placeholder text not found — clicking screen center as fallback")
        sw, sh = pyautogui.size()
        pyautogui.moveTo(sw // 2, sh // 2 - 100, duration=0.4)
        pyautogui.mouseDown(); time.sleep(0.08); pyautogui.mouseUp()
        time.sleep(0.5)

    # Clear any existing text
    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.2)
    pyautogui.press('backspace')
    time.sleep(0.5)

    # Step 3: Type the post content
    logger.info(f"  ⌨️  Typing {len(content)} chars with human-like timing...")
    _visual_human_type(content)
    logger.info("  ✓ Typing done — pausing for review...")
    time.sleep(random.uniform(2.5, 4.0))

    # Step 3.5: Validate typed text casing
    try:
        logger.info("  🔍 Validating typed text for case inversion...")
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.3)
        pyautogui.press('right')  # Deselect text
        time.sleep(0.2)
        
        typed_text = pyperclip.paste()
        if typed_text and len(typed_text) >= 5:
            orig_u = sum(1 for c in content if c.isupper())
            orig_l = sum(1 for c in content if c.islower())
            typed_u = sum(1 for c in typed_text if c.isupper())
            typed_l = sum(1 for c in typed_text if c.islower())
            
            is_inverted = False
            # Check 1: Typed upper/lower counts are closer to the flipped original counts
            if (abs(typed_u - orig_l) < abs(typed_u - orig_u)) and (abs(typed_l - orig_u) < abs(typed_l - orig_l)):
                is_inverted = True
            # Check 2: Original was mostly lowercase, but typed is mostly uppercase
            elif (orig_l > orig_u * 2) and (typed_u > typed_l):
                is_inverted = True
                
            if is_inverted:
                logger.error(f"  ❌ CASE INVERSION DETECTED (Caps Lock error).")
                logger.error(f"     Original: Upper={orig_u}, Lower={orig_l}")
                logger.error(f"     Typed:    Upper={typed_u}, Lower={typed_l}")
                logger.error("  ❌ Aborting post.")
                return False
    except Exception as e:
        logger.warning(f"  ⚠️ Could not validate typed text: {e}")

    # Step 4: Click the blue Post button via CV2 color detection
    logger.info("  🔍 Looking for activated blue Post button (CV2)...")
    if not _visual_find_post_button():
        logger.error("  ❌ Could not find the blue Post button — post NOT submitted")
        return False

    logger.info("  ⏳ Waiting for post to submit...")
    time.sleep(5.0)
    logger.info("  🎉 Post published!")
    beep_success(extra_tone=True)
    return True



# ==================== INSTAGRAM HELPERS ====================

def ig_dismiss_popups(driver):
    """Dismiss Instagram notification / cookie / login popups."""
    xpaths = [
        "//button[contains(text(), 'Not Now')]",
        "//button[contains(text(), 'Not now')]",
        "//button[contains(text(), 'Allow all cookies')]",
        "//button[contains(text(), 'Accept All')]",
        "//button[@aria-label='Close']",
    ]
    for xpath in xpaths:
        try:
            btn = driver.find_element(By.XPATH, xpath)
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                logger.info("  ✓ Dismissed IG popup")
                human_delay(1.0, 1.5)
        except Exception:
            pass


def ig_is_already_liked(driver):
    """
    Return True if the current Instagram post is already liked.
    Tries DOM selectors first, then falls back to PNG image matching.
    """
    # DOM check 1: element with aria-label='Unlike'
    try:
        els = driver.find_elements(
            By.XPATH,
            "//*[@role='button' or local-name()='button'][.//svg[@aria-label='Unlike' and @height='24']]"
        )
        for el in els:
            if el.is_displayed():
                return True
    except Exception:
        pass

    try:
        spans = driver.find_elements(By.XPATH, "//span[@aria-label='Unlike']")
        for span in spans:
            if span.is_displayed():
                return True
    except Exception:
        pass

    # DOM check 2: JS scan for Unlike svg
    try:
        els = driver.execute_script("""
            let matched = [];
            let elements = document.querySelectorAll('button, div[role="button"], span');
            for (let el of elements) {
                let svgs = el.querySelectorAll('svg');
                for (let svg of svgs) {
                    let label = (svg.getAttribute('aria-label') || '').toLowerCase();
                    let height = svg.getAttribute('height') || '0';
                    if (label === 'unlike' && parseInt(height) > 20) matched.push(el);
                }
            }
            return matched;
        """)
        if els:
            for el in els:
                if el.is_displayed():
                    return True
    except Exception:
        pass

    # PNG fallback: look for filled heart on screen (already liked)
    if VISUAL_POST_AVAILABLE and os.path.exists(IG_HEART_FILLED_PNG):
        try:
            loc = pyautogui.locateOnScreen(IG_HEART_FILLED_PNG, confidence=0.75)
            if loc:
                logger.info("  🖼️  PNG: filled heart detected — already liked")
                return True
        except Exception:
            pass

    return False


def ig_find_like_button(driver):
    """Find the visible Like button on the open Instagram post page."""
    # Pattern 1: button/div with inner svg aria-label='Like' height='24'
    try:
        btns = driver.find_elements(
            By.XPATH,
            "//*[@role='button' or local-name()='button'][.//svg[@aria-label='Like' and @height='24']]"
        )
        for btn in btns:
            if btn.is_displayed():
                return btn
    except Exception:
        pass

    # Pattern 2: span aria-label='Like'
    try:
        for span in driver.find_elements(By.XPATH, "//span[@aria-label='Like']"):
            if span.is_displayed():
                return span
    except Exception:
        pass

    # Pattern 3: heart SVG path data
    try:
        btns = driver.find_elements(
            By.XPATH,
            "//*[@role='button' or local-name()='button']"
            "[.//svg//*[contains(@d,'34.6') or contains(@d,'M34.6') or contains(@d,'M16.792')]]"
        )
        for btn in btns:
            if btn.is_displayed():
                return btn
    except Exception:
        pass

    # Pattern 4: JS scan
    try:
        btns = driver.execute_script("""
            let matched = [];
            let docs = document.querySelectorAll('button[type="button"], div[role="button"]');
            for (let btn of docs) {
                let svgs = btn.querySelectorAll('svg');
                for (let svg of svgs) {
                    let ariaLabel = (svg.getAttribute('aria-label') || '').toLowerCase();
                    let height = svg.getAttribute('height') || '0';
                    if (ariaLabel === 'like' && parseInt(height) > 20) matched.push(btn);
                }
            }
            return matched;
        """)
        if btns:
            for btn in btns:
                if btn.is_displayed():
                    return btn
    except Exception:
        pass

    # Pattern 5: PNG fallback — locate empty heart, click near it
    if VISUAL_POST_AVAILABLE and os.path.exists(IG_HEART_EMPTY_PNG):
        try:
            loc = pyautogui.locateOnScreen(IG_HEART_EMPTY_PNG, confidence=0.75)
            if loc:
                logger.info("  🖼️  PNG: empty heart found via image match")
                # Return None here — caller will use pyautogui.click on the centre
                return ("png_click", pyautogui.center(loc))
        except Exception:
            pass

    return None


def ig_has_already_commented(driver, username: str) -> bool:
    """Return True if username has already commented on the current post."""
    try:
        driver.execute_script("window.scrollBy(0, 600);")
        time.sleep(1.5)
        author_links = driver.find_elements(
            By.XPATH,
            "//ul//li//a[contains(@href, '/" + username + "/') or "
            "normalize-space(text())='" + username + "']"
        )
        for link in author_links:
            href = (link.get_attribute("href") or "").lower().rstrip("/")
            text = (link.text or "").strip().lower()
            if href.endswith("/" + username.lower()) or text == username.lower():
                logger.info(f"  🔍 Already commented as @{username} — skipping")
                return True

        found = driver.execute_script(f"""
            const uname = '/{username.lower()}/';
            const links = Array.from(document.querySelectorAll('a[href]'));
            for (const a of links) {{
                const href = (a.getAttribute('href') || '').toLowerCase();
                if (href.includes(uname)) {{
                    let node = a.parentElement; let depth = 0;
                    while (node && depth < 8) {{
                        const tag = node.tagName.toLowerCase();
                        if (tag === 'li' || tag === 'ul') return true;
                        node = node.parentElement; depth++;
                    }}
                }}
            }}
            return false;
        """)
        if found:
            logger.info(f"  🔍 Already commented as @{username} (JS scan) — skipping")
            return True
    except Exception as e:
        logger.debug(f"  ig_has_already_commented error: {e}")
    return False


def _ig_find_comment_box(driver):
    """Find the Instagram comment textarea/contenteditable."""
    try:
        for box in driver.find_elements(
            By.XPATH,
            "//textarea[contains(@aria-label,'omment') or contains(@placeholder,'omment')]"
        ):
            if box.is_displayed():
                return box
    except Exception:
        pass
    try:
        for ta in driver.find_elements(By.TAG_NAME, "textarea"):
            if ta.is_displayed():
                return ta
    except Exception:
        pass
    try:
        for box in driver.find_elements(
            By.XPATH,
            "//div[@contenteditable='true' and contains(@aria-label,'omment')]"
        ):
            if box.is_displayed():
                return box
    except Exception:
        pass
    return None


def ig_post_comment(driver, text: str, target_username: str, post_n: int) -> bool:
    """Post a comment on the current Instagram post. Returns True on success."""
    logger.info(f"  💬 Posting comment '{text}' on @{target_username} post #{post_n}")

    box = _ig_find_comment_box(driver)
    if not box:
        logger.warning("  ⚠️  Comment box not found — skipping")
        return False

    try:
        box = _ig_find_comment_box(driver)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", box)
    except Exception:
        pass
    human_delay(0.8, 1.5)

    box = _ig_find_comment_box(driver)
    if not box:
        return False
    try:
        box.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", box)
        except Exception:
            pass
    human_delay(1.5, 2.5)

    box = _ig_find_comment_box(driver)
    if not box:
        return False
    try:
        box.send_keys(text)
    except Exception as e:
        logger.warning(f"  ⚠️  Could not type: {e}")
        return False
    human_delay(2.0, 3.5)

    posted = False
    try:
        post_btns = driver.find_elements(
            By.XPATH,
            "//button[normalize-space(text())='Post' or normalize-space(text())='post']"
            " | //div[@role='button' and "
            "(normalize-space(text())='Post' or normalize-space(text())='post')]"
        )
        for btn in post_btns:
            if btn.is_displayed():
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                human_delay(0.3, 0.6)
                driver.execute_script("arguments[0].click();", btn)
                posted = True
                logger.info("  ✓ Clicked Post button")
                break
    except Exception:
        pass

    if not posted:
        box = _ig_find_comment_box(driver)
        if box:
            try:
                box.send_keys(Keys.RETURN)
                posted = True
                logger.info("  ✓ Comment submitted via Enter")
            except Exception:
                return False

    human_delay(2.5, 4.0)
    logger.info(f"  ✅ Comment '{text}' posted on @{target_username} post #{post_n}")
    return True


def ig_get_post_links(driver):
    """Return unique /p/ post URLs from the current Instagram profile grid."""
    try:
        links = driver.find_elements(By.XPATH, "//a[contains(@href, '/p/')]")
        seen, unique = set(), []
        for link in links:
            href = link.get_attribute("href") or ""
            if href and href not in seen:
                seen.add(href)
                unique.append(href)
        return unique
    except Exception:
        return []


def ig_scroll_until_n_posts(driver, target_count: int):
    """
    Always pre-scroll the profile grid at least 3 pages to go deep,
    then keep scrolling until target_count posts are loaded.
    Randomises scroll amount per step for natural-looking movement.
    """
    # Mandatory pre-scroll: 3–6 pages regardless of how many posts are visible
    pre_pages = random.randint(3, 6)
    logger.info(f"  🎲 IG pre-scroll: {pre_pages} page(s)")
    for i in range(pre_pages):
        px = random.randint(700, 1400)
        driver.execute_script(f"window.scrollBy({{top: {px}, left: 0, behavior: 'smooth'}});")
        human_delay(1.8, 3.0)
        posts_so_far = len(ig_get_post_links(driver))
        logger.info(f"  📜 Scroll {i+1}/{pre_pages}: {posts_so_far} posts visible")

    # Now keep scrolling until we have enough for target_count
    for attempt in range(20):
        posts = ig_get_post_links(driver)
        logger.info(f"  📜 Loading posts: {len(posts)} visible (need {target_count})")
        if len(posts) >= target_count:
            return posts
        px = random.randint(700, 1400)
        driver.execute_script(f"window.scrollBy({{top: {px}, left: 0, behavior: 'smooth'}});")
        human_delay(2.0, 3.5)
    return ig_get_post_links(driver)


def run_task_instagram(driver):
    """
    Task 7: Instagram Like + Comment.
    Uses the EXISTING Firefox (same driver) in a new tab.
    Rule: if already liked → skip BOTH like AND comment.
    Like and comment always go together or not at all.
    Returns (liked_count, commented_count).
    """
    logger.info("\n" + "=" * 60)
    logger.info("📸 TASK 7: Instagram Like & Comment")
    logger.info("=" * 60)

    liked_count     = 0
    commented_count = 0

    # Open a fresh tab for Instagram
    logger.info("  ➕ Opening new tab for Instagram...")
    driver.execute_script("window.open('');")
    human_delay(1.0, 2.0)
    driver.switch_to.window(driver.window_handles[-1])

    try:
        logger.info("  🌐 Navigating to Instagram home to warm up session...")
        driver.get("https://www.instagram.com/")
        human_delay(5.0, 8.0)
        ig_dismiss_popups(driver)
        human_delay(2.0, 3.0)

        profiles = list(IG_TARGET_PROFILES)
        random.shuffle(profiles)
        profiles = profiles[:IG_PROFILES_PER_RUN]

        for idx, target_url in enumerate(profiles):
            target_username = target_url.rstrip("/").split("/")[-1]
            target_n = random.randint(15, 35)  # go deep — earlier posts are already liked

            logger.info("-" * 50)
            logger.info(f"  [{idx+1}/{len(profiles)}] @{target_username} — will target post #{target_n}")

            if idx > 0:
                driver.execute_script("window.open('');")
                human_delay(0.5, 1.0)
                driver.switch_to.window(driver.window_handles[-1])

            driver.get(target_url)
            human_delay(5.0, 7.0)
            ig_dismiss_popups(driver)
            human_delay(2.0, 3.0)

            post_links = ig_scroll_until_n_posts(driver, target_n)
            if not post_links:
                logger.warning(f"  ⚠️  No posts found on @{target_username} — skipping")
                continue

            if len(post_links) < target_n:
                logger.warning(f"  ⚠️  Only {len(post_links)} posts — using last one")
                target_n = len(post_links)

            post_url = post_links[target_n - 1]
            logger.info(f"  🖼️  Post #{target_n}: {post_url}")

            driver.get(post_url)
            human_delay(5.0, 7.0)
            ig_dismiss_popups(driver)
            human_delay(2.0, 3.5)

            # Check already liked — if yes, skip BOTH like and comment
            already_liked = ig_is_already_liked(driver)
            if already_liked:
                logger.info(f"  ⏭ Already liked @{target_username} post #{target_n} — skipping like + comment")
                try:
                    driver.save_screenshot(os.path.join(LOG_DIR, f"ig_already_liked_{target_username}_p{target_n}.png"))
                except Exception:
                    pass
                human_delay(1.0, 2.0)
                continue

            # Like the post
            like_result = ig_find_like_button(driver)
            liked = False
            if like_result is None:
                logger.warning(f"  ⚠️  Like button not found on @{target_username} post #{target_n}")
            elif isinstance(like_result, tuple) and like_result[0] == "png_click":
                # PNG-based click fallback
                cx, cy = like_result[1]
                if VISUAL_POST_AVAILABLE:
                    pyautogui.click(cx, cy)
                    human_delay(3.0, 5.0)
                    liked = ig_is_already_liked(driver)
                    logger.info(f"  👍 PNG-click like: {'✅ confirmed' if liked else '⚠️ not confirmed'}")
            else:
                like_btn = like_result
                logger.info(f"  👍 Clicking Like on @{target_username} post #{target_n}...")
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", like_btn)
                human_delay(1.5, 2.5)
                try:
                    like_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", like_btn)
                human_delay(3.0, 5.0)
                liked = ig_is_already_liked(driver)
                logger.info(f"  {'✅ Like confirmed' if liked else '⚠️ Like not confirmed — will still comment'}")

            if liked:
                liked_count += 1
                try:
                    driver.save_screenshot(os.path.join(LOG_DIR, f"ig_like_{target_username}_p{target_n}.png"))
                except Exception:
                    pass
            else:
                logger.warning(f"  ⚠️  Like not confirmed on @{target_username} post #{target_n} — skipping comment too")
                continue

            # Comment (only if like was confirmed)
            human_delay(2.0, 4.0)
            if ig_has_already_commented(driver, IG_MY_USERNAME):
                logger.info(f"  💬 Already commented on @{target_username} post #{target_n} — skipping")
            else:
                try:
                    ok = ig_post_comment(driver, IG_COMMENT_TEXT, target_username, target_n)
                    if ok:
                        commented_count += 1
                except Exception as e:
                    logger.warning(f"  ⚠️  Comment failed (non-fatal): {e}")

            # Beep feedback
            try:
                winsound.Beep(800, 300)
                winsound.Beep(1200, 300)
            except Exception:
                pass

            human_delay(2.0, 4.0)

    except Exception as e:
        logger.error(f"  ❌ Instagram task error: {e}")
        try:
            driver.save_screenshot(os.path.join(LOG_DIR, "ig_error.png"))
        except Exception:
            pass

    logger.info(f"  📸 Instagram done — liked: {liked_count}, commented: {commented_count}")
    return (liked_count, commented_count)


# ==================== MAIN ORCHESTRATOR ====================
def main():
    logger.info("=" * 60)
    logger.info("🚀 LinkedIn Suite Starting  (Z-edition)")
    logger.info(f"   Log: {SUITE_LOG}")
    log_ai_provider_config()
    logger.info("=" * 60)

    # -- Task selection menu (ask FIRST, before any Selenium work) ------------
    print("\n" + "=" * 50)
    print("  SELECT TASKS TO RUN:")
    print("    1  AI Comment (Advocate)")
    print("    2  Congratulate")
    print("    3  Likes")
    print("    4  Post")
    print("    5  Everything (1+1B+1C+2+3+4+7)")
    print("    6  TPO Comment (1B)")
    print("    7  Instagram Like & Comment")
    print("    8  AI Comment on Fund Raising (any startup sector)")
    print("=" * 50)
    while True:
        try:
            choice = input("  Enter choice [1-8]: ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = "5"
        if choice in ("1","2","3","4","5","6","7","8"):
            break
        print("  Invalid — please enter 1, 2, 3, 4, 5, 6, 7, or 8")

    run_t1  = choice in ("1","5")
    run_t1b = choice in ("5","6")
    run_t1c = choice in ("5", "8")
    run_t2  = choice in ("2","5")
    run_t3  = choice in ("3","5")
    run_t4  = choice in ("4","5")
    run_t7  = choice in ("5","7")
    logger.info(
        f"  Tasks selected: Comment={run_t1} TPO-Comment={run_t1b} "
        f"Fundraising-Comment={run_t1c} Congratulate={run_t2} Likes={run_t3} "
        f"Post={run_t4} Instagram={run_t7}"
    )

    # -- Step 1: Find LinkedIn Firefox window, or Instagram as fallback ---------
    logger.info("\n🔍 Scanning open windows for LinkedIn (or Instagram)...")
    browser_win, browser_mode = find_suite_browser_window()
    if not browser_win:
        logger.error("❌ No Firefox window with 'LinkedIn' or 'Instagram' in the title was found.")
        logger.error("   Please:")
        logger.error("   1. Open Firefox with --marionette")
        logger.error("   2. Log in to https://www.linkedin.com or https://www.instagram.com")
        logger.error("   3. Run this script again")
        pause_before_exit()
        return

    needs_linkedin = run_t1 or run_t1b or run_t1c or run_t2 or run_t3 or run_t4
    if browser_mode == "instagram":
        if needs_linkedin:
            logger.warning("  ⚠️  LinkedIn window not open — skipping LinkedIn tasks (1-4, 6, 8)")
            run_t1 = run_t1b = run_t1c = run_t2 = run_t3 = run_t4 = False
        if not run_t7:
            logger.error("  ❌ Only an Instagram Firefox window was found.")
            logger.error("     Options 1-4, 6, and 8 need LinkedIn open. Use option 7 (Instagram) or open LinkedIn.")
            pause_before_exit()
            return
        logger.info("  ℹ️  Instagram-only mode — will run Task 7 only")

    # -- Step 2: Bring that window to front -----------------------------------
    bring_window_to_front(browser_win)

    # -- Step 3: Attach Selenium to the existing Firefox ----------------------
    logger.info(f"\n🔌 Attaching Selenium to existing Firefox (Marionette port {MARIONETTE_PORT})...")
    driver = connect_to_existing_firefox(MARIONETTE_PORT)
    if not driver:
        logger.error("❌ Could not attach Selenium to the existing Firefox.")
        logger.error("   Firefox must be started with Marionette enabled. Two options:")
        logger.error("")
        logger.error('   Option A — Launch Firefox with a special shortcut:')
        logger.error('     Target:  "C:\\Program Files\\Mozilla Firefox\\firefox.exe" --marionette')
        logger.error("     Use this shortcut instead of the normal one, then log in to LinkedIn.")
        logger.error("")
        logger.error("   Option B — Enable via about:config (one-time setup):")
        logger.error("     1. Type  about:config  in the Firefox address bar")
        logger.error("     2. Search for  marionette.enabled")
        logger.error("     3. Set it to  true")
        logger.error("     4. Restart Firefox, log in to LinkedIn, then run this script again.")
        pause_before_exit()
        return

    comments_conn = congrats_conn = likes_conn = None
    try:
        if not verify_browser_session(driver, browser_mode):
            return

        # -- Initialize all databases ---------------------------------------------
        comments_conn = init_comments_db()
        congrats_conn = init_congrats_db()
        likes_conn    = init_likes_db()

        results = {}

        # -- Task 1: AI Comment (Advocate) ------------------------------------
        if run_t1:
            try:
                results['comment'] = run_task1_comment(driver, comments_conn,
                                                        comment_mode="advocate")
            except Exception as e:
                logger.error(f"❌ Task 1 error: {e}")
                results['comment'] = False
            human_delay(3.0, 6.0)
        else:
            results['comment'] = None

        # -- Task 1B: TPO Comment ---------------------------------------------
        if run_t1b:
            try:
                results['tpo_comment'] = run_task1_comment(driver, comments_conn,
                                                           search_url_override=get_tpo_search_url(),
                                                           task_label="🎓 TASK 1B: AI Comment on TPO Post",
                                                           url_generator_fn=get_tpo_search_url,
                                                           comment_mode="tpo")
            except Exception as e:
                logger.error(f"❌ Task 1B error: {e}")
                results['tpo_comment'] = False
            human_delay(3.0, 6.0)
        else:
            results['tpo_comment'] = None

        # -- Task 1C: Fundraising Comment (funding required) --------------------
        if run_t1c:
            try:
                results['fundraising_comment'] = run_task1_comment(
                    driver, comments_conn,
                    search_url_override=FUNDRAISING_SEARCH_URL,
                    task_label="💰 TASK 1C: AI Comment on Fund Raising",
                    url_generator_fn=get_fundraising_search_url,
                    comment_mode="fundraising",
                    random_post_pick=True,
                    scroll_min=FUNDRAISING_SCROLL_MIN,
                    scroll_max=FUNDRAISING_SCROLL_MAX,
                )
            except Exception as e:
                logger.error(f"❌ Task 1C error: {e}")
                results['fundraising_comment'] = False
            human_delay(3.0, 6.0)
        else:
            results['fundraising_comment'] = None

        # -- Task 2: Congratulate ---------------------------------------------
        if run_t2:
            try:
                results['congratulate'] = run_task2_congratulate(driver, congrats_conn)
            except Exception as e:
                logger.error(f"❌ Task 2 error: {e}")
                results['congratulate'] = False
            human_delay(3.0, 6.0)
        else:
            results['congratulate'] = None

        # -- Task 3: Like -----------------------------------------------------
        if run_t3:
            try:
                results['likes'] = run_task3_like(driver, likes_conn)
            except Exception as e:
                logger.error(f"❌ Task 3 error: {e}")
                results['likes'] = 0
            human_delay(3.0, 6.0)
        else:
            results['likes'] = None

        # -- Task 4: Post -----------------------------------------------------
        if run_t4:
            try:
                results['post'] = run_task4_post(driver)
            except Exception as e:
                logger.error(f"❌ Task 4 error: {e}")
                results['post'] = False
        else:
            results['post'] = None
        if run_t7:
            human_delay(3.0, 6.0)

        # -- Task 7: Instagram ------------------------------------------------
        if run_t7:
            try:
                results['instagram'] = run_task_instagram(driver)
            except Exception as e:
                logger.error(f"❌ Task 7 error: {e}")
                results['instagram'] = (0, 0)
        else:
            results['instagram'] = None

        # -- Summary --------------------------------------------------------------
        logger.info("\n" + "=" * 60)
        logger.info("📋 SUITE SUMMARY")
        logger.info("=" * 60)
        def _fmt(key, labels=("✅ Posted","❌ None","⏭ Skipped")):
            v = results.get(key)
            if v is None: return labels[2]
            if v:         return labels[0]
            return labels[1]
        logger.info(f"  Task 1  — AI Comment (Advocate) : {_fmt('comment')}")
        logger.info(f"  Task 1B — AI Comment (TPO)      : {_fmt('tpo_comment')}")
        logger.info(f"  Task 1C — AI Comment (Fundraise): {_fmt('fundraising_comment')}")
        logger.info(f"  Task 2  — Congratulate          : {_fmt('congratulate')}")
        lv = results.get('likes')
        logger.info(f"  Task 3  — Likes                 : {'⏭ Skipped' if lv is None else str(lv)+' like(s)'}")
        logger.info(f"  Task 4  — Post                  : {_fmt('post', ('✅ Published','❌ None','⏭ Skipped'))}")
        igv = results.get('instagram')
        if igv is None:
            ig_str = "⏭ Skipped"
        else:
            ig_str = f"✅ {igv[0]} like(s), {igv[1]} comment(s)"
        logger.info(f"  Task 7  — Instagram             : {ig_str}")
        if _ai_keys_used:
            logger.info(f"  NVIDIA keys used      : {', '.join(sorted(_ai_keys_used))}")
        else:
            logger.info("  NVIDIA keys used      : (none — AI comment tasks did not run or used fallback)")
        logger.info(f"  Log saved to          : {SUITE_LOG}")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")

    finally:
        for conn in (comments_conn, congrats_conn, likes_conn):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        close_browser(driver, browser_win)

    logger.info("👋 Suite finished. Goodbye!")
    pause_before_exit()


if __name__ == "__main__":
    main()
