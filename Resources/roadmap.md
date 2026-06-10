# Trailhead — Three-Phase Roadmap (v3)
**Track: Backyard AI · Owner: Person D · ~5 days to June 15**

**Affirmed core assumption:** *plan online at basecamp, trek offline.* Online work (route fetch, tile download) is allowed during planning; everything during the trek degrades gracefully to offline.

**Keystone — the Position Abstraction.** All contextual features read position from one interface with two sources:
- **Simulated playback** — steps along the uploaded GPX. Always works; demo with this; doubles as a "preview your trek" feature.
- **Live `watchPosition`** (optional, on-device, screen-on only).

Continuous browser GPS on a multi-day offline trek is unreliable (assisted-GPS cold start wants network; backgrounded tabs suspend). Demo on simulation; offer live as a bonus; never promise live tracking as a guarantee.

---

## Online data sources — PLANNING PHASE ONLY
External calls happen at basecamp with signal, never on the trail.

- **Primary input: upload your own GPX** — it's the hiker's real route; most reliable.
- **OpenRouteService (ORS)** — free OSM-based routing, `foot-hiking` profile, direct GPX out: `GET https://api.openrouteservice.org/v2/directions/{profile}/gpx`. **Caveats:** needs an API key + has rate limits (online-only); it *routes between coordinates*, it does **not** look up a named trek's established trail; OSM trail coverage in remote/high terrain is patchy. Use it to *generate* a route from waypoints, then validate it. Not authoritative for serious treks.
- **GPX repositories** (e.g. the track sites you've identified) — fine as a source of pre-made GPX to download at basecamp; then proceed exactly as the upload path.

> Design rule: any online fetch produces a local GPX that the rest of the app treats identically to an uploaded one. Nothing downstream depends on connectivity.

---

## Reconsiderations — verdicts

| Proposed feature | Verdict | Why |
|---|---|---|
| GPX upload | **Keep (primary)** | The real route; most reliable. |
| Online route fetch (ORS / GPX repos) | **Keep — planning phase only** | Convenience at basecamp. Routing ≠ named-trek lookup; validate output; never called offline. |
| Proximity checkpoint narration | **Keep — headline AI moment** | Driven by the position abstraction. |
| Progress: % complete / ETA / pace | **Keep** | Deterministic. |
| Deviation (off-route) alert | **Keep, advisory** | Distance-to-polyline. |
| Pace-adjusted ETA | **Keep** | Deterministic; recompute from actual elapsed vs distance. |
| Risk note (pace + daylight + altitude) | **Adapt + constrain** | Rule-based, conservative, **advisory only**. LLM phrases it; rules decide. |
| Voice via whisper.cpp | **Keep (bonus)** | Reuse Kisan-Sathi; value with gloves/cold. |
| Voice trek journaling → SQLite (w/ location) | **Keep (should-have)** | Speak → transcribe → log transcript + position + time. Offline. Feeds the post-trek report. **Raw transcript is the record of truth.** |
| Audio landmark alerts (TTS) | **Optional, low priority** | Fine if position + TTS work. |
| Post-trek report (stats + AI story) | **Promote (should-have)** | Safe, delightful, shareable; ideal honest-fit LLM use. |
| Offline map tiles (MBTiles) | **Keep (should-have)** | Map works with no signal; strengthens Off the Grid. |
| Storage (SQLite/files on disk) | **Backend owns it** | Model + persistence on disk; browser only does UI + geolocation. No weights in IndexedDB. |
| Battery-aware low-power mode | **Keep** | Lower `n_ctx` + GPS poll interval. Good Field Notes detail. |

---

## PHASE 1 — MVP: "The Route Brief"
**Goal: the grounded planning loop works end-to-end on the hiker's real GPX. Understandable in 10 seconds.**

- [ ] **GPX ingest:** accept an uploaded GPX *or* a basecamp ORS/repo fetch that lands as a local GPX; from here everything is offline-identical.
- [ ] **GPX parse** (`gpxpy`): tracks/segments/waypoints; concatenate segments; handle missing elevation/timestamps without crashing.
- [ ] **Route stats (deterministic):** haversine distance; **elevation gain with smoothing** (moving average / min-change threshold — raw sums are badly inflated); min/max; estimated days (Naismith ÷ realistic hours/day, assumption shown).
- [ ] **Interactive map — use `folium`, not Plotly mapbox.** Render polyline + waypoint markers; embed as HTML; verify on a phone. **Avoid Plotly's `open-street-map` style — it pulls tiles online and goes blank in airplane mode.** (Reserve Plotly for the elevation chart in Phase 3, where there are no tiles.)
- [ ] **Static checkpoint readout:** first waypoint — cumulative distance + elevation. No AI yet; prove the data pipeline.
- [ ] **Deploy to HF Space** (Docker + llama-cpp-python GGUF, reuse Kisan-Sathi Dockerfile); open on a phone.

**Gate:** the hiker's actual GPX yields correct distance, sane (smoothed) elevation gain, estimated days, and a map. Test on the real file — synthetic GPX hides the edge cases.

---

## PHASE 2 — Functional: All Basic Hackathon Criteria Met
**Goal: full demo-able loop incl. the contextual AI layer; real hiker has used it; all hard constraints met. The 60-second video is recordable from here.**

- [ ] **Position abstraction:** simulated GPX playback ("play" advances along the route) + optional live `watchPosition`. Everything below consumes it.
- [ ] **Proximity checkpoint narration (load-bearing moment):** as position nears a waypoint, the LLM narrates grounded advice — distance/ascent to next point, altitude caution from the loaded guide, water/hazard **only from tagged waypoints/data** (never invented).
- [ ] **Progress + pace + ETA + deviation:** % complete, pace vs Naismith, ETA to next checkpoint, off-route alert. Deterministic.
- [ ] **Advisory risk note:** rule-based — daylight remaining vs distance/ascent to next safe camp → "you'll arrive ~late, consider the alternate camp." Conservative, advisory, not a guarantee. LLM phrases; rules decide.
- [ ] **Gear list:** rule engine (distance + elevation + days + max altitude + season) → LLM narrates.
- [ ] **First-aid RAG:** MiniLM over the wilderness first-aid guide; retrieve + **cite section**; static no-signal emergency card; "this is a field guide — carry a PLB/satellite messenger."
- [ ] **Mobile-first UI** (reuse your FastAPI custom frontend): large targets, outdoor-readable, high contrast.
- [ ] **Dual deploy + offline verify:** Pixel 10 via Termux; **airplane mode, full loop works.**
- [ ] **Real hiker uses it + record footage** reviewing their actual route.
- [ ] **README + social post:** track, real hiker + trek, model + param count, honest-fit rationale, run instructions, teammates' HF usernames.

**Gate:** record the full 60s demo from this phase — ingest GPX → map + stats → press play → proximity narration + pace/ETA fire → gear list → first-aid query — **offline**. Constraints: Gradio ✓ · HF Space ✓ · ≤32B ✓ · video + social ✓ · real user ✓.

---

## PHASE 3 — Final Touch & Bonus Quests
**Goal: polish + badges. None of this blocks the video.**

- [ ] **🎨 Off-Brand — trail-computer HUD:** amber/green tactical theme; **elevation profile chart** under the map (Plotly is great here — no tiles, deterministic, looks great on camera).
- [ ] **🦙 Llama Champion:** document GGUF + llama.cpp; battery-saver mode (lower `n_ctx`, slower GPS poll).
- [ ] **🔌 Off the Grid:** make the airplane-mode run the hero shot; add **offline map tiles (MBTiles)** so the folium map works with no signal.
- [ ] **🎙 Voice trek journaling:** speak → whisper.cpp → log transcript + position + timestamp to SQLite. Offline. Raw transcript is the record of truth.
- [ ] **📓 Post-trek report (should-have):** route + stats + an AI-narrated story built from the journal logs — a shareable artifact that feeds your social post. LLM summarizes/tags; never rewrites the logged facts.
- [ ] **📓 Field Notes:** the build story — elevation smoothing, simulation vs real GPS, offline tiles, offline edge LLM on a phone (Kisan-Sathi Termux notes carry over).
- [ ] **Local waypoint tagging (bonus):** hiker marks water/camp/hazard, saved to SQLite — enriches checkpoint advice without inventing anything.
- [ ] **Live `watchPosition` (bonus):** wire the real-GPS source into the abstraction; screen-on demo only.
- [ ] **Final checklist:** Space public under the org; loads cleanly; no keys; `.gitignore` excludes weights + uploaded GPX; video + social published before June 15.

---

## What to Hand the Vibe-Coding LLM
1. **The real GPX file** — build/test against it, not synthetic.
2. **First-aid corpus** (chunked) + **static emergency card** text — model can't originate medical content.
3. **Altitude/AMS thresholds + gear rules + seasonal averages** — verified data files, not invented.
4. Reused Kisan-Sathi contracts: `src/llm.py` backend interface, Dockerfile, RAG setup, SQLite layer, whisper.cpp ASR.
5. The **position abstraction** interface (simulated + live) so every contextual feature is source-agnostic.
6. **ORS integration note:** planning-phase only; output is a local GPX treated identically to an upload; validate routes.
7. **Acceptance tests:** distance ±2% on a known GPX; smoothed (not raw) elevation gain; map renders offline (no online tiles); first-aid answers always cite a section; checkpoint advice never names a water source absent from waypoints; risk note advisory-only; journal entries store the raw transcript + position.

## Carry-Through Gotchas
- Smooth elevation before summing (the #1 GPX error).
- **No online map tiles** — folium + local MBTiles, or the demo dies in airplane mode.
- ORS is planning-phase routing, not named-trek lookup — validate it.
- No invented water/hazards — grounded in waypoints/data only.
- First-aid + risk are high-stakes — ground, cite, advisory framing, static emergency floor.
- Demo on simulated position; live GPS is a bonus.
- Test on the real GPX early; verify `folium` on-device.