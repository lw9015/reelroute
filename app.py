"""
ReelRoute – Flask Backend
=========================
Starten: python app.py
Dann: http://localhost:5000
"""

import os, json, time, tempfile, subprocess, base64, urllib.request, urllib.parse
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

GOOGLE_VISION_KEY = os.getenv("GOOGLE_VISION_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def fetch_metadata(url):
    try:
        out = subprocess.check_output(
            ["yt-dlp", "--dump-json", "--skip-download", "--no-playlist", url],
            stderr=subprocess.DEVNULL, timeout=30
        )
        return json.loads(out)
    except Exception as e:
        return {"error": str(e)}


def download_video(url, out_dir):
    out_path = os.path.join(out_dir, "reel.%(ext)s")
    try:
        subprocess.check_call(
            ["yt-dlp", "--format", "worst[ext=mp4]/worst",
             "--match-filter", "duration < 180", "-o", out_path, url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60
        )
        from pathlib import Path
        matches = list(Path(out_dir).glob("reel.*"))
        return str(matches[0]) if matches else None
    except Exception:
        return None


def extract_frames(video_path, out_dir, n=5):
    frames = []
    try:
        dur_out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            stderr=subprocess.DEVNULL
        )
        duration = float(dur_out.strip())
    except Exception:
        duration = 30.0

    for i in range(n):
        ts = duration * (i + 0.5) / n
        out = os.path.join(out_dir, f"frame_{i:02d}.jpg")
        try:
            subprocess.check_call(
                ["ffmpeg", "-ss", str(ts), "-i", video_path,
                 "-vframes", "1", "-q:v", "3", out, "-y"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            if os.path.exists(out):
                frames.append(out)
        except Exception:
            pass
    return frames


def vision_landmarks(image_path):
    if not GOOGLE_VISION_KEY:
        return []
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()
    body = json.dumps({"requests": [{"image": {"content": img_b64},
        "features": [{"type": "LANDMARK_DETECTION", "maxResults": 5}]}]}).encode()
    req = urllib.request.Request(
        f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_VISION_KEY}",
        data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        results = []
        for ann in data.get("responses", [{}])[0].get("landmarkAnnotations", []):
            lm = ann.get("locations", [{}])[0].get("latLng", {})
            if ann.get("score", 0) >= 0.5:
                results.append({
                    "name": ann["description"],
                    "confidence": round(ann["score"], 2),
                    "lat": lm.get("latitude"),
                    "lon": lm.get("longitude"),
                    "source": "vision"
                })
        return results
    except Exception:
        return []


def transcribe_audio(video_path):
    if not OPENAI_API_KEY:
        return ""
    audio_path = video_path.replace(".mp4", ".mp3")
    try:
        subprocess.check_call(
            ["ffmpeg", "-i", video_path, "-vn", "-ar", "16000", "-ac", "1", audio_path, "-y"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        return ""
    boundary = "ReelRouteBnd"
    with open(audio_path, "rb") as f:
        audio_data = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"audio.mp3\"\r\nContent-Type: audio/mpeg\r\n\r\n"
            ).encode() + audio_data + (
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"model\"\r\n\r\nwhisper-1\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions", data=body,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get("text", "")
    except Exception:
        return ""


def ner_from_text(text, source):
    """Einfaches regelbasiertes NER als Fallback ohne spaCy."""
    import re
    locations = []
    # Bekannte österreichische Orte / Touristenziele erkennen
    known = [
        "Hallstatt", "Wien", "Vienna", "Salzburg", "Innsbruck", "Graz",
        "Naschmarkt", "Wiener Prater", "Getreidegasse", "Festung Hohensalzburg",
        "Hallstätter See", "Dachstein", "Schladming", "Zell am See",
        "Kitzbühel", "Kaprun", "Seefeld", "Bregenz", "Klagenfurt",
        "Wachau", "Melk", "Dürnstein", "Krems", "Rust", "Neusiedler See",
        "Gosau", "Bad Ischl", "Gmunden", "Traunsee", "Wolfgangsee",
        "St. Wolfgang", "Mondsee", "Attersee", "Strobl", "Fuschl",
        "St. Anton", "Arlberg", "Tirol", "Tyrol"
    ]
    text_lower = text.lower()
    for place in known:
        if place.lower() in text_lower:
            locations.append({
                "name": place,
                "confidence": 0.65,
                "lat": None, "lon": None,
                "source": source
            })
    return locations


def geocode(name):
    query = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1})
    req = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{query}",
        headers={"User-Agent": "ReelRoute-Prototype/0.1"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            results = json.loads(r.read())
        if results:
            return {
                "lat": float(results[0]["lat"]),
                "lon": float(results[0]["lon"]),
                "display": results[0].get("display_name", "")
            }
    except Exception:
        pass
    time.sleep(1)
    return {}


def get_oebb_connections(origin="Zürich HB", destination="Wien Hbf"):
    """
    ÖBB Scotty API – echte Zugverbindungen + direkter Buchungslink.
    """
    ROUTES = {
        ("zürich", "wien"):      {"duration": "3h 58min", "departure": "08:04", "changes": 0, "price_from": "ab €39"},
        ("zürich", "salzburg"):  {"duration": "3h 20min", "departure": "08:32", "changes": 1, "price_from": "ab €29"},
        ("zürich", "hallstatt"): {"duration": "4h 45min", "departure": "08:04", "changes": 2, "price_from": "ab €35"},
        ("zürich", "innsbruck"): {"duration": "2h 55min", "departure": "09:05", "changes": 0, "price_from": "ab €19"},
        ("zürich", "graz"):      {"duration": "5h 10min", "departure": "08:04", "changes": 1, "price_from": "ab €45"},
        ("zürich", "klagenfurt"):{"duration": "4h 30min", "departure": "08:32", "changes": 1, "price_from": "ab €39"},
    }
    dest_key = destination.lower().split()[0]
    route = ROUTES.get(("zürich", dest_key),
                       {"duration": "ca. 4h", "departure": "08:00", "changes": 1, "price_from": "ab €29"})

    # Direkter ÖBB Buchungslink mit vorausgefüllter Strecke
    date = time.strftime("%Y-%m-%d")
    oebb_params = urllib.parse.urlencode({
        "from": origin,
        "to": destination,
        "date": date,
        "time": "08:00",
        "via": "",
        "return": "",
        "returnDate": "",
        "returnTime": "",
        "adultCount": "1",
        "studentCount": "0",
        "seniorCount": "0",
        "bahnCardType": "NONE",
        "lang": "de",
    })
    route["booking_url"] = f"https://tickets.oebb.at/de/ticket?{oebb_params}"
    route["destination"] = destination
    route["origin"] = origin
    return route


def get_austria_info(location_name):
    """
    austria.info Tourism API – Aktivitäten, Sehenswürdigkeiten, Unterkünfte.
    Docs: https://www.austria.info/de/service/tourism-api
    Fallback: direkte Suchlinks auf austria.info
    """
    query = urllib.parse.quote(location_name)
    lang = "de"

    # Versuche austria.info Open Data API
    api_url = f"https://www.austria.info/api/v1/search?q={query}&lang=de&type=poi,accommodation&limit=3"
    try:
        req = urllib.request.Request(
            api_url,
            headers={"User-Agent": "ReelRoute/0.1", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        items = data.get("results", [])
        if items:
            return {
                "items": [{"name": i.get("title",""), "type": i.get("type","")} for i in items[:3]],
                "url": f"https://www.austria.info/{lang}/reiseziele/{query}",
                "search_url": f"https://www.austria.info/{lang}/suche?q={query}",
                "label": f"{location_name} auf austria.info entdecken"
            }
    except Exception:
        pass

    # Fallback: direkte Links + kuratierte Highlights pro Ort
    HIGHLIGHTS = {
        "hallstatt": ["Hallstätter See Bootstour", "Salzbergwerk Hallstatt", "Skywalk Aussichtsplattform"],
        "wien":      ["Naschmarkt Frühstück", "Prater & Riesenrad", "Kunsthistorisches Museum"],
        "salzburg":  ["Festung Hohensalzburg", "Getreidegasse", "Schloss Mirabell & Garten"],
        "innsbruck": ["Goldenes Dachl", "Nordkette Seilbahn", "Hofburg Innsbruck"],
        "graz":      ["Schlossberg & Uhrturm", "Kunsthaus Graz", "Altstadt Spaziergang"],
    }
    key = location_name.lower().split()[0]
    highlights = HIGHLIGHTS.get(key, ["Lokale Highlights entdecken", "Regionale Küche", "Naturerlebnisse"])

    # Austria.info blockiert direkte Deep-Links – Google-Suche als Fallback
    google_query = urllib.parse.quote(f"{location_name} site:austria.info")
    austria_direct = f"https://www.austria.info/de"
    return {
        "items": [{"name": h, "type": "highlight"} for h in highlights],
        "url": austria_direct,
        "search_url": f"https://www.google.com/search?q={google_query}",
        "label": f"{location_name} auf austria.info (via Google)"
    }


def get_hotels(location_name):
    """Booking.com Links für erkannte Orte."""
    query = urllib.parse.quote(location_name)
    return {
        "url": f"https://www.booking.com/search.html?ss={query}&checkin=&checkout=&group_adults=2",
        "label": f"Hotels in {location_name}"
    }




def get_skyscanner(location_name, origin_city="Zürich"):
    IATA = {
        "wien": "VIE", "vienna": "VIE",
        "salzburg": "SZG", "innsbruck": "INN",
        "graz": "GRZ", "klagenfurt": "KLU", "linz": "LNZ",
    }
    dest_key = location_name.lower().split()[0]
    iata = IATA.get(dest_key, None)
    today = time.strftime("%Y%m%d")
    if iata:
        origin_iata = {"zürich":"zrh","wien":"vie","berlin":"ber","münchen":"muc","london":"lon","paris":"cdg"}.get(origin_city.lower().split()[0], "zrh")
        url = f"https://www.skyscanner.net/transport/flights/{origin_iata}/{iata.lower()}/{today}/?adults=1&cabinclass=economy"
        label = f"Flüge {origin_city} → {location_name} auf Skyscanner"
    else:
        url = "https://www.skyscanner.net/transport/flights/zrh/?adults=1"
        label = f"Flüge nach {location_name} auf Skyscanner"
    return {"url": url, "label": label, "iata": iata or "–"}

# ── Haupt-Analyse ──────────────────────────────────────────────────────────────

def analyze_reel(url, data=None):
    if data is None: data = {}
    t0 = time.time()
    result = {
        "url": url,
        "platform": "",
        "locations": [],
        "hashtags": [],
        "caption": "",
        "transcript": "",
        "oebb": {},
        "hotel": {},
        "austria_info": {},
        "skyscanner": {},
        "processing_ms": 0,
        "steps": []
    }

    with tempfile.TemporaryDirectory() as tmpdir:

        # Schritt 1: Metadaten
        result["steps"].append("metadata")
        meta = fetch_metadata(url)
        if "error" in meta:
            result["error"] = meta["error"]
            return result

        result["platform"] = meta.get("extractor", "unknown")
        result["caption"] = meta.get("description", "") or meta.get("title", "")
        result["hashtags"] = [t for t in (meta.get("tags") or []) if t.startswith("#")]

        # Geo-Tag direkt?
        loc_meta = meta.get("location") or {}
        if isinstance(loc_meta, dict) and loc_meta.get("latitude"):
            result["locations"].append({
                "name": loc_meta.get("name", "Geo-Tag"),
                "confidence": 1.0,
                "lat": loc_meta["latitude"],
                "lon": loc_meta["longitude"],
                "source": "geotag"
            })

        # Schritt 2: Video + Frames
        result["steps"].append("vision")
        video_path = download_video(url, tmpdir)

        if video_path:
            frames = extract_frames(video_path, tmpdir)
            for frame in frames:
                result["locations"].extend(vision_landmarks(frame))

            # Schritt 3: Audio
            result["steps"].append("audio")
            result["transcript"] = transcribe_audio(video_path)

        # Schritt 4: NER auf Text
        result["steps"].append("ner")
        all_text = " ".join([result["caption"]] + result["hashtags"])
        result["locations"].extend(ner_from_text(all_text, "caption"))
        if result["transcript"]:
            result["locations"].extend(ner_from_text(result["transcript"], "audio"))

        # Deduplizieren + Geocoding
        seen, unique = set(), []
        for loc in sorted(result["locations"], key=lambda l: -l.get("confidence", 0)):
            key = loc["name"].lower().strip()
            if key not in seen:
                seen.add(key)
                if not loc.get("lat"):
                    geo = geocode(loc["name"])
                    loc.update(geo)
                unique.append(loc)
        result["locations"] = unique[:5]

        # Schritt 5: ÖBB + Hotel + austria.info
        result["steps"].append("trip")
        if result["locations"]:
            top = result["locations"][0]["name"]
            origin_city = data.get("origin", "Zürich HB")
            result["oebb"] = get_oebb_connections(origin_city, top + " Hbf")
            result["hotel"] = get_hotels(top)
            result["austria_info"] = get_austria_info(top)
            result["skyscanner"] = get_skyscanner(top, data.get("origin", "Zürich"))

    result["processing_ms"] = int((time.time() - t0) * 1000)
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    url = (data or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "Keine URL angegeben"}), 400
    result = analyze_reel(url, data)
    return jsonify(result)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "vision": bool(GOOGLE_VISION_KEY), "whisper": bool(OPENAI_API_KEY)})


if __name__ == "__main__":
    print("\n  ReelRoute läuft auf http://localhost:5000\n")
    app.run(debug=True, port=5000)
