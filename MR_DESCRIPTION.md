# Merge Request / Pull Request Description: Phase 2 - Functional + POI Integration

## 📝 Overview
This Merge Request delivers **Phase 2: Functional + POI Integration** for the **Trailhead** project. It introduces live and offline Points of Interest (POI) extraction via OpenStreetMap (Overpass API), integrates a local Wilderness First-Aid medical manual RAG search, and implements a full route simulation player with metrics HUD and proximity alert indicators.

## 🚀 Key Changes
1. **POI Integration (`gpx_parser.py`)**:
   * Fetches key POIs (drinking water, spring, huts, shelters, campsites) dynamically within a custom bounding box of the track via the **OSM Overpass API**.
   * Filters amenities locally using the **Haversine formula** within a 150m buffer of the route.
   * Serializes/saves POIs into GPX XML `<extensions>` and `<wpt>` tags via `save_enhanced_gpx` for offline capabilities.
2. **Wilderness First-Aid Guide (`first_aid_guide.json` & `rag.py`)**:
   * Created a wilderness medical corpus covering 5 key sections (bleeding, hypothermia, heat, altitude sickness, musculoskeletal).
   * Implemented keyword intersection matching in `rag.py` to ground first-aid queries, returning relevant guide text along with section citations.
3. **Simulation HUD & Playback UI (`app.py`)**:
   * Added simulation controls (Play, Pause, Speed slider, Reset).
   * Displays dashboard metrics (Route progress %, distance walked, altitude, and dynamic ETA to next checkpoint).
   * Sounds/shows offline proximity alerts when within 150m of any drinking water, camp, or hut.
   * Integrated Wilderness First-Aid tab with static emergency cards and RAG manual search.

## 🛠️ Verification Done
* Created [test_overpass.py](file:///c:/Users/skushwaha/Documents/hckthn/TrailHead/test_overpass.py) to parse the preloaded Trento Track.
* Verified Overpass API (`https://overpass-api.de/api/interpreter`) fetched, filtered, and returned 2 drinking water amenities successfully within a 150m buffer.
* Validated that the first-aid RAG keyword search retrieves correct sections and references them.

---

## 📋 Steps to Push to GitHub
```bash
# Add the remote repository (if not already linked)
git remote add origin <your-github-repo-url>

# Push all files to main
git push -u origin main
```

