# ReelRoute – Prototyp

## Start in 5 Minuten

```bash
# 1. Abhängigkeiten
pip install -r requirements.txt

# 2. ffmpeg (macOS)
brew install ffmpeg

# 3. yt-dlp
pip install yt-dlp

# 4. API Keys (optional – ohne Keys läuft die Demo-Version)
cp .env.example .env
# .env öffnen und Keys eintragen

# 5. Starten
export $(cat .env | grep -v '#' | xargs)   # Keys laden
python app.py
# → http://localhost:5000
```

## Ohne API Keys

Die App läuft auch **ohne Keys** – die drei Beispiel-Reels
(Hallstatt, Wien, Salzburg) zeigen den vollen Flow mit Demo-Daten.
Für echte URLs braucht ihr die Keys.

## Was funktioniert

| Feature | Ohne Keys | Mit Keys |
|---|---|---|
| Demo-Reels (3 Beispiele) | ✅ | ✅ |
| Echte URL analysieren | ⚠️ NER only | ✅ Vision + Whisper |
| ÖBB Verbindungen | ✅ Fallback-Daten | ✅ Scotty API |
| Hotel-Links (Booking.com) | ✅ | ✅ |
| Geocoding (OSM) | ✅ kostenlos | ✅ |

## Kosten pro Analyse (mit Keys)

- Google Vision: ~$0.009 (6 Frames)
- Whisper: ~$0.006 / Minute
- Gesamt: **~$0.02 pro Reel**
