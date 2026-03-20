"""
Free web API integrations for Little Fish.
All functions return plain text strings suitable for TTS.
Uses only free/no-key APIs where possible.
"""

import urllib.request
import urllib.parse
import json
import datetime
from typing import Optional


_TIMEOUT = 6  # seconds


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "LittleFish/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read().decode())


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "LittleFish/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read().decode()


# -------------------------------------------------------------------
# Weather  (wttr.in — no key needed)
# -------------------------------------------------------------------

def weather(city: Optional[str] = None) -> str:
    loc = urllib.parse.quote(city) if city else ""
    try:
        text = _get_text(f"https://wttr.in/{loc}?format=3")
        return text.strip()
    except Exception:
        return "Couldn't get weather right now."


def forecast(city: Optional[str] = None) -> str:
    loc = urllib.parse.quote(city) if city else ""
    try:
        text = _get_text(f"https://wttr.in/{loc}?format=%l:+%c+%t+%w+%h+humidity")
        return text.strip()
    except Exception:
        return "Couldn't get the forecast."


# -------------------------------------------------------------------
# Wikipedia (REST API — no key)
# -------------------------------------------------------------------

def wikipedia_summary(query: str) -> str:
    q = urllib.parse.quote(query)
    try:
        data = _get_json(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}")
        extract = data.get("extract", "")
        # Truncate to ~2 sentences for TTS
        sentences = extract.split(". ")
        short = ". ".join(sentences[:2])
        if short and not short.endswith("."):
            short += "."
        return short or "Didn't find anything on Wikipedia."
    except Exception:
        return "Couldn't search Wikipedia right now."


# -------------------------------------------------------------------
# News (Google News RSS — no key)
# -------------------------------------------------------------------

def top_news() -> str:
    try:
        import xml.etree.ElementTree as ET
        text = _get_text("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en")
        root = ET.fromstring(text)
        items = root.findall(".//item")[:3]
        headlines = [item.find("title").text for item in items if item.find("title") is not None]
        if headlines:
            return "Top news: " + " ... ".join(headlines)
        return "No news found."
    except Exception:
        return "Couldn't fetch news right now."


# -------------------------------------------------------------------
# Dictionary (Free Dictionary API — no key)
# -------------------------------------------------------------------

def define_word(word: str) -> str:
    w = urllib.parse.quote(word.strip())
    try:
        data = _get_json(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{w}")
        if isinstance(data, list) and data:
            meanings = data[0].get("meanings", [])
            if meanings:
                defs = meanings[0].get("definitions", [])
                if defs:
                    defn = defs[0].get("definition", "")
                    pos = meanings[0].get("partOfSpeech", "")
                    return f"{word} ({pos}): {defn}"
        return f"Couldn't find a definition for '{word}'."
    except Exception:
        return f"Couldn't look up '{word}'."


# -------------------------------------------------------------------
# Translation (MyMemory API — no key, 5000 chars/day)
# -------------------------------------------------------------------

def translate_text(text: str, target_lang: str = "en") -> str:
    # Auto-detect source, translate to target
    # Default translates TO English. If already English, translate to Spanish
    lang_map = {
        "spanish": "es", "french": "fr", "german": "de", "italian": "it",
        "portuguese": "pt", "japanese": "ja", "chinese": "zh",
        "korean": "ko", "arabic": "ar", "russian": "ru", "dutch": "nl",
        "hindi": "hi", "english": "en",
    }
    tl = lang_map.get(target_lang.lower(), target_lang.lower())
    q = urllib.parse.quote(text)
    try:
        data = _get_json(
            f"https://api.mymemory.translated.net/get?q={q}&langpair=autodetect|{tl}")
        translated = data.get("responseData", {}).get("translatedText", "")
        if translated:
            return translated
        return "Couldn't translate that."
    except Exception:
        return "Translation service unavailable."


# -------------------------------------------------------------------
# Exchange rates (frankfurter.app — no key)
# -------------------------------------------------------------------

def exchange_rate(from_cur: str = "USD", to_cur: str = "EUR",
                  amount: float = 1.0) -> str:
    f = from_cur.upper().strip()
    t = to_cur.upper().strip()
    try:
        data = _get_json(
            f"https://api.frankfurter.app/latest?amount={amount}&from={f}&to={t}")
        rates = data.get("rates", {})
        if t in rates:
            return f"{amount} {f} = {rates[t]} {t}."
        return f"Couldn't find rate for {f} to {t}."
    except Exception:
        return "Couldn't check exchange rates."


# -------------------------------------------------------------------
# Holidays (date.nager.at — no key)
# -------------------------------------------------------------------

def holiday_check(country: str = "US") -> str:
    year = datetime.date.today().year
    cc = (country or "US").upper().strip()
    try:
        data = _get_json(
            f"https://date.nager.at/api/v3/PublicHolidays/{year}/{cc}")
        today = datetime.date.today().isoformat()
        for h in data:
            if h.get("date") == today:
                return f"Today is {h['localName']}!"
        # Show next holiday
        for h in data:
            if h.get("date", "") > today:
                return f"Next holiday: {h['localName']} on {h['date']}."
        return "No upcoming holidays found."
    except Exception:
        return "Couldn't check holidays."


# -------------------------------------------------------------------
# Sun times (sunrise-sunset.org — no key)
# -------------------------------------------------------------------

def sun_times(lat: float = 0, lng: float = 0) -> str:
    try:
        if lat == 0 and lng == 0:
            # Try to get approximate location from IP
            geo = _get_json("http://ip-api.com/json/?fields=lat,lon")
            lat = geo.get("lat", 40.7128)
            lng = geo.get("lon", -74.0060)
        data = _get_json(
            f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lng}&formatted=0")
        results = data.get("results", {})
        sunrise = results.get("sunrise", "")
        sunset = results.get("sunset", "")
        if sunrise and sunset:
            # Parse ISO times to local
            sr = datetime.datetime.fromisoformat(sunrise.replace("Z", "+00:00"))
            ss = datetime.datetime.fromisoformat(sunset.replace("Z", "+00:00"))
            # Convert to local naive
            sr_local = sr.astimezone().strftime("%I:%M %p")
            ss_local = ss.astimezone().strftime("%I:%M %p")
            return f"Sunrise at {sr_local}, sunset at {ss_local}."
        return "Couldn't get sun times."
    except Exception:
        return "Couldn't get sun times."


# -------------------------------------------------------------------
# Speed test (simple download speed estimate)
# -------------------------------------------------------------------

def speed_test() -> str:
    import time
    url = "https://speed.cloudflare.com/__down?bytes=1000000"  # 1MB
    try:
        start = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "LittleFish/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        elapsed = time.time() - start
        mbps = (len(data) * 8) / (elapsed * 1_000_000)
        return f"Download speed: roughly {mbps:.1f} Mbps."
    except Exception:
        return "Couldn't run speed test."
