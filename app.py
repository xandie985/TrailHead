import os
import base64
import requests
import gradio as gr
import pandas as pd
import folium
from src.gpx_parser import parse_gpx_file, haversine, save_enhanced_gpx
import src.llm as llm
import src.rag as rag

# Initialize cache and temp folders
os.makedirs("./temp", exist_ok=True)

# Preloaded route path
PRELOADED_ROUTE_PATH = r"C:\Users\skushwaha\Documents\hckthn\TrailHead\Routes\track_5-14724236830.gpx"

MAP_HTML_INITIALIZER = """
<div id="trailhead-leaflet-map" style="height: 520px; width: 100%; border:1px solid rgba(245,158,11,0.2); border-radius: 12px; background: #0c1014; z-index: 1;"></div>
"""

MAP_INIT_JS = r"""
() => {
    // 1. Dynamically append Leaflet CSS
    if (!document.getElementById("leaflet-css")) {
        var link = document.createElement("link");
        link.id = "leaflet-css";
        link.rel = "stylesheet";
        link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(link);
    }

    // 2. Dynamically append Leaflet JS
    if (!document.getElementById("leaflet-js")) {
        var script = document.createElement("script");
        script.id = "leaflet-js";
        script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
        document.head.appendChild(script);
    }

    // 3. Wait for Leaflet to load and initialize map
    var checkExist = setInterval(function() {
        if (typeof L !== 'undefined' && L.map) {
            var mapContainer = document.getElementById("trailhead-leaflet-map");
            if (!mapContainer) return; // Wait for Gradio to mount the container
            
            clearInterval(checkExist);
            if (window.myLeafletMap) return; // Already initialized
            
            var map = L.map("trailhead-leaflet-map").setView([46.0734974, 11.1717214], 13);
            window.myLeafletMap = map;
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; OpenStreetMap'
            }).addTo(map);
            
            window.mapLayers = L.layerGroup().addTo(map);
            window.hikerMarker = null;

            // Define window.routeDataChangeHandler
            window.routeDataChangeHandler = function(routeJson) {
                if (!routeJson) return;
                try {
                    var data = JSON.parse(routeJson);
                    var map = window.myLeafletMap;
                    if (!map) return;
                    
                    if (window.mapLayers) {
                        window.mapLayers.clearLayers();
                    }
                    if (window.hikerMarker) {
                        window.hikerMarker.remove();
                        window.hikerMarker = null;
                    }
                    
                    var points = data.points || [];
                    var checkpoints = data.checkpoints || [];
                    var pois = data.pois || [];
                    
                    if (points.length === 0) return;
                    
                    var latlngs = points.map(p => [p.lat, p.lon]);
                    var polyline = L.polyline(latlngs, {
                        color: "#f59e0b",
                        weight: 5,
                        opacity: 0.85
                    }).addTo(window.mapLayers);
                    
                    map.fitBounds(polyline.getBounds());
                    
                    checkpoints.forEach(cp => {
                        var color = "cadetblue";
                        if (cp.name === "Start") color = "green";
                        else if (cp.name === "End") color = "red";
                        
                        var popupText = `
                        <div style="font-family: 'Outfit', sans-serif; font-size: 11px; color: #111;">
                            <b>${cp.name}</b><br>
                            Distance: ${cp.cum_dist.toFixed(2)} km<br>
                            Elevation: ${cp.ele.toFixed(1)} m
                        </div>`;
                        
                        L.circleMarker([cp.lat, cp.lon], {
                            radius: cp.name === "Start" || cp.name === "End" ? 8 : 6,
                            fillColor: color,
                            color: "#ffffff",
                            weight: 1.5,
                            fillOpacity: 0.9
                        })
                        .bindPopup(popupText)
                        .addTo(window.mapLayers);
                    });
                    
                    pois.forEach(poi => {
                        var color = "purple";
                        var type = poi.type;
                        
                        if (["drinking_water", "water_point", "fountain"].includes(type)) {
                            color = "#3b82f6";
                        } else if (type === "spring") {
                            color = "#60a5fa";
                        } else if (["alpine_hut", "wilderness_hut"].includes(type)) {
                            color = "#047857";
                        } else if (type === "camp_site") {
                            color = "#f97316";
                        } else if (type === "shelter") {
                            color = "#10b981";
                        } else if (type === "viewpoint") {
                            color = "#a855f7";
                        } else if (type === "peak") {
                            color = "#7c3aed";
                        } else if (type === "phone") {
                            color = "#ef4444";
                        }
                        
                        var popupText = `
                        <div style="font-family: 'Outfit', sans-serif; font-size: 11px; color: #111;">
                            <b>${poi.name}</b><br>
                            Type: ${type.replace(/_/g, ' ').toUpperCase()}<br>
                            Distance to Route: ${poi.distance.toFixed(1)} m
                        </div>`;
                        
                        L.circleMarker([poi.lat, poi.lon], {
                            radius: 5,
                            fillColor: color,
                            color: "#ffffff",
                            weight: 1.2,
                            fillOpacity: 0.95
                        })
                        .bindPopup(popupText)
                        .addTo(window.mapLayers);
                    });
                } catch(e) {
                    console.error("Error drawing route:", e);
                }
            };

            // Define window.updateHikerPosHandler
            window.updateHikerPosHandler = function(coords) {
                if (!coords) return;
                try {
                    var data = JSON.parse(coords);
                    var map = window.myLeafletMap;
                    if (!map) return;
                    
                    var pos = [data.lat, data.lon];
                    
                    if (!window.hikerMarker) {
                        window.hikerMarker = L.circleMarker(pos, {
                            radius: 9,
                            fillColor: "#ef4444",
                            color: "#ffffff",
                            weight: 2.5,
                            fillOpacity: 1.0
                        }).addTo(map);
                    } else {
                        window.hikerMarker.setLatLng(pos);
                    }
                    
                    var popupText = `
                    <div style="font-family: 'Outfit', sans-serif; font-size: 11px; color: #111;">
                        <b>Current simulated position</b><br>
                        Distance Walked: ${data.cum_dist.toFixed(2)} km<br>
                        Altitude: ${data.ele.toFixed(1)} m
                    </div>`;
                    window.hikerMarker.bindPopup(popupText);
                    map.panTo(pos);
                } catch(e) {
                    console.error("Error updating hiker position:", e);
                }
            };

            // Trigger handlers immediately with any pending data
            if (window.pendingRouteData) {
                window.routeDataChangeHandler(window.pendingRouteData);
            }
            if (window.pendingHikerCoords) {
                window.updateHikerPosHandler(window.pendingHikerCoords);
            }
        }
    }, 100);
}
"""


EMERGENCY_CARD = """
## 🚨 IMMEDIATE BACKCOUNTRY EMERGENCY CARD (OFFLINE)
If you encounter a medical crisis with no cellular signal, follow these basic steps:

1. **Severe Bleeding:** Apply direct pressure with clean dressing. Elevate limb. Use tourniquet if blood is spurting.
2. **Hypothermia:** Wrap in windproof shell/sleeping bag. Replace wet clothes. Provide warm sweet drinks.
3. **Heat Stroke:** Move to shade. Actively cool by wetting skin and fanning. Sip cool water.
4. **Altitude Illness (AMS/HAPE/HACE):** Descend immediately. Do not ascend. Administer oxygen if available.
5. **Ankle Sprain (R.I.C.E):** Rest the joint. Ice or apply cold pack. Compress with elastic bandage. Elevate limb.

*Disclaimer: This guide is for offline reference only. Always carry a PLB/satellite communicator on remote trails.*
"""

def generate_folium_map(points, checkpoints, pois, hiker_pos=None):
    """
    Generate interactive folium map rendering track, checkpoints, POIs, and current hiker pos.
    """
    if not points:
        m = folium.Map(location=[46.0734974, 11.1717214], zoom_start=13)
        return m._repr_html_()
        
    # Center map on current hiker position or middle of track
    if hiker_pos:
        center_lat, center_lon = hiker_pos["lat"], hiker_pos["lon"]
        zoom_val = 15
    else:
        mid_idx = len(points) // 2
        center_lat, center_lon = points[mid_idx]["lat"], points[mid_idx]["lon"]
        zoom_val = 14
        
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_val)
    
    # Draw track polyline
    locations = [(p["lat"], p["lon"]) for p in points]
    folium.PolyLine(locations, color="#f59e0b", weight=5, opacity=0.85).add_to(m)
    
    # Draw checkpoints
    for cp in checkpoints:
        name = cp["name"]
        lat = cp["lat"]
        lon = cp["lon"]
        ele = cp["ele"]
        dist = cp["cum_dist"]
        
        if name == "Start":
            color = "green"
            icon = "play"
        elif name == "End":
            color = "red"
            icon = "flag"
        else:
            color = "cadetblue"
            icon = "info-sign"
            
        popup_text = f"""
        <div style="font-family: 'Outfit', sans-serif; font-size: 11px;">
            <b>{name}</b><br>
            Distance: {dist:.2f} km<br>
            Elevation: {ele:.1f} m
        </div>
        """
        folium.Marker(
            location=[lat, lon],
            popup=popup_text,
            tooltip=name,
            icon=folium.Icon(color=color, icon=icon)
        ).add_to(m)
        
    # Draw POIs
    for poi in pois:
        poi_type = poi["type"]
        icon_color = "purple"
        icon_name = "info-sign"
        
        # Color coding:
        # - drinking_water / water_point / fountain -> blue / glass
        # - spring -> lightblue / tint
        # - alpine_hut / wilderness_hut -> darkgreen / home
        # - camp_site -> orange / fire
        # - shelter -> green / leaf
        # - viewpoint -> purple / camera
        # - peak -> darkpurple / flag
        # - phone -> red / phone
        
        if poi_type in ["drinking_water", "water_point", "fountain"]:
            icon_color = "blue"
            icon_name = "glass"
        elif poi_type == "spring":
            icon_color = "lightblue"
            icon_name = "tint"
        elif poi_type in ["alpine_hut", "wilderness_hut"]:
            icon_color = "darkgreen"
            icon_name = "home"
        elif poi_type == "camp_site":
            icon_color = "orange"
            icon_name = "fire"
        elif poi_type == "shelter":
            icon_color = "green"
            icon_name = "leaf"
        elif poi_type == "viewpoint":
            icon_color = "purple"
            icon_name = "camera"
        elif poi_type == "peak":
            icon_color = "darkpurple"
            icon_name = "flag"
        elif poi_type == "phone":
            icon_color = "red"
            icon_name = "phone"
            
        popup_text = f"""
        <div style="font-family: 'Outfit', sans-serif; font-size: 11px;">
            <b>{poi['name']}</b><br>
            Type: {poi_type.replace('_', ' ').title()}<br>
            Distance to Route: {poi['distance']:.1f} m
        </div>
        """
        folium.Marker(
            location=[poi["lat"], poi["lon"]],
            popup=popup_text,
            tooltip=poi['name'],
            icon=folium.Icon(color=icon_color, icon=icon_name)
        ).add_to(m)
        
    return m._repr_html_()

def get_map_iframe(map_html):
    """
    Helper to bundle raw HTML into a secure, sandboxed base64 data URI iframe.
    """
    injected_js = """
    <script>
    // Poll for Leaflet to load and override L.map to capture the map object
    (function() {
        var checkExist = setInterval(function() {
            if (typeof L !== 'undefined' && L.map) {
                clearInterval(checkExist);
                var originalMap = L.map;
                L.map = function(id, options) {
                    var m = originalMap(id, options);
                    window.myLeafletMap = m;
                    return m;
                };
            }
        }, 50);
    })();

    // Listen for coordinates update from parent Gradio frame
    window.addEventListener("message", function(event) {
        if (event.data && event.data.type === "update_hiker_pos") {
            var lat = event.data.lat;
            var lon = event.data.lon;
            var ele = event.data.ele;
            var dist = event.data.dist;
            
            var map = window.myLeafletMap;
            if (!map) return;
            
            // Check if hikerMarker exists, otherwise create it
            if (!window.hikerMarker) {
                var redIcon = L.icon({
                    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowSize: [41, 41]
                });
                window.hikerMarker = L.marker([lat, lon], {icon: redIcon}).addTo(map);
            } else {
                window.hikerMarker.setLatLng([lat, lon]);
            }
            
            window.hikerMarker.bindPopup(
                "<div style='font-family: \\\"Outfit\\\", sans-serif; font-size: 11px;'>" +
                "<b>Current Position</b><br>" +
                "Distance: " + dist.toFixed(2) + " km<br>" +
                "Altitude: " + ele.toFixed(1) + " m" +
                "</div>"
            );
            
            // Center the map smoothly on the updated coordinate
            map.panTo([lat, lon]);
        }
    });
    </script>
    """
    if "</body>" in map_html:
        map_html = map_html.replace("</body>", injected_js + "</body>")
    else:
        map_html = map_html + injected_js
        
    b64_html = base64.b64encode(map_html.encode('utf-8')).decode('utf-8')
    iframe_src = f"data:text/html;base64,{b64_html}"
    return f'<div id="trailhead-map-iframe"><iframe src="{iframe_src}" width="100%" height="520px" style="border:1px solid rgba(245,158,11,0.2); border-radius: 12px;"></iframe></div>'

def fetch_ors_route(start_coords, end_coords, profile, api_key):
    """
    Fetches hiking route between coordinates using OpenRouteService.
    Falls back to a straight-line GPX segment if API key is empty or request fails.
    """
    try:
        start_lat, start_lon = map(float, start_coords.split(","))
        end_lat, end_lon = map(float, end_coords.split(","))
    except Exception:
        raise gr.Error("Invalid coordinate format. Ensure format is 'lat, lon'.")
        
    temp_dir = "./temp"
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, "ors_fetched_route.gpx")
    
    if not api_key:
        mid_lat = (start_lat + end_lat) / 2.0
        mid_lon = (start_lon + end_lon) / 2.0
        gpx_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Trailhead Mock" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="{start_lat}" lon="{start_lon}"></trkpt>
      <trkpt lat="{mid_lat}" lon="{mid_lon}"></trkpt>
      <trkpt lat="{end_lat}" lon="{end_lon}"></trkpt>
    </trkseg>
  </trk>
</gpx>"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(gpx_content)
        gr.Warning("No ORS API Key provided. Generated a mock direct route segment.")
        return file_path
        
    url = f"https://api.openrouteservice.org/v2/directions/{profile}/gpx"
    headers = {
        'Accept': 'application/gpx+xml',
        'Authorization': api_key,
        'Content-Type': 'application/json'
    }
    body = {
        "coordinates": [[start_lon, start_lat], [end_lon, end_lat]]
    }
    
    try:
        response = requests.post(url, json=body, headers=headers, timeout=12)
        if response.status_code == 200:
            with open(file_path, "wb") as f:
                f.write(response.content)
            gr.Info("Successfully fetched route from OpenRouteService!")
            return file_path
        else:
            raise ValueError(f"ORS returned status {response.status_code}")
    except Exception as e:
        mid_lat = (start_lat + end_lat) / 2.0
        mid_lon = (start_lon + end_lon) / 2.0
        gpx_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Trailhead Fallback" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="{start_lat}" lon="{start_lon}"></trkpt>
      <trkpt lat="{mid_lat}" lon="{mid_lon}"></trkpt>
      <trkpt lat="{end_lat}" lon="{end_lon}"></trkpt>
    </trkseg>
  </trk>
</gpx>"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(gpx_content)
        gr.Warning(f"ORS Fetch failed ({e}). Generated straight-line fallback route.")
        return file_path

def format_route_view(data):
    """
    Format route data for presentation inside stats display and checkpoint lists.
    """
    stats_html = f"""
    <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 15px; margin-bottom: 20px;'>
        <div class='hud-stat-box'>
            <div class='hud-stat-val'>{data['total_distance_km']:.2f}</div>
            <div class='hud-stat-lbl'>Distance (km)</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val'>{data['elevation_gain_m']:.1f}</div>
            <div class='hud-stat-lbl'>Elevation Gain (m)</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val'>{data['elevation_loss_m']:.1f}</div>
            <div class='hud-stat-lbl'>Elevation Loss (m)</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val'>{data['min_elevation_m']:.0f} - {data['max_elevation_m']:.0f}</div>
            <div class='hud-stat-lbl'>Altitude Range (m)</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val'>{data['estimated_days']:.1f}</div>
            <div class='hud-stat-lbl'>Est. Hiking Days</div>
        </div>
    </div>
    """
    
    map_html = generate_folium_map(data["points"], data["checkpoints"], data.get("pois", []))
    map_iframe = get_map_iframe(map_html)
    
    checkpoint_table_data = []
    for cp in data["checkpoints"]:
        checkpoint_table_data.append([
            cp["name"],
            f"{cp['lat']:.5f}, {cp['lon']:.5f}",
            f"{cp['cum_dist']:.2f} km",
            f"{cp['ele']:.1f} m"
        ])
        
    return stats_html, map_iframe, checkpoint_table_data

def handle_route_update(preloaded_sel, uploaded_file, start_coords, end_coords, profile, api_key):
    file_path = PRELOADED_ROUTE_PATH
    if uploaded_file is not None:
        file_path = uploaded_file.name
        
    try:
        data = parse_gpx_file(file_path)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return (
            f"<div style='color:#ef4444;'>Error parsing GPX: {e}</div>",
            "",
            [],
            {},
            0,
            gr.update(active=False),
            "",
            "",
            ""
        )
        
    stats_html, map_iframe, checkpoint_table_data = format_route_view(data)
    # Save a copy with POIs saved to disk
    try:
        enhanced_file = os.path.join("./temp", "trek_with_poi.gpx")
        save_enhanced_gpx(file_path, enhanced_file, data.get("pois", []))
    except Exception as ex:
        print(f"[app] Error saving enhanced GPX: {ex}")
        
    import json
    start_pt = data["points"][0]
    hiker_coords_json = json.dumps({
        "lat": start_pt["lat"],
        "lon": start_pt["lon"],
        "ele": start_pt["ele"],
        "cum_dist": start_pt["cum_dist"] / 1000.0
    })
    
    route_json = json.dumps({
        "points": data["points"],
        "checkpoints": data["checkpoints"],
        "pois": data.get("pois", [])
    })
        
    return stats_html, route_json, checkpoint_table_data, data, 0, gr.update(active=False), "", "", hiker_coords_json

def handle_ors_fetch_click(start_coords, end_coords, profile, api_key):
    try:
        route_file = fetch_ors_route(start_coords, end_coords, profile, api_key)
        data = parse_gpx_file(route_file)
        stats_html, map_iframe, checkpoint_table_data = format_route_view(data)
        
        try:
            enhanced_file = os.path.join("./temp", "trek_with_poi.gpx")
            save_enhanced_gpx(route_file, enhanced_file, data.get("pois", []))
        except Exception as ex:
            print(f"[app] Error saving enhanced GPX: {ex}")
            
        import json
        start_pt = data["points"][0]
        hiker_coords_json = json.dumps({
            "lat": start_pt["lat"],
            "lon": start_pt["lon"],
            "ele": start_pt["ele"],
            "cum_dist": start_pt["cum_dist"] / 1000.0
        })
        
        route_json = json.dumps({
            "points": data["points"],
            "checkpoints": data["checkpoints"],
            "pois": data.get("pois", [])
        })
        return stats_html, route_json, checkpoint_table_data, data, 0, gr.update(active=False), "", "", hiker_coords_json
    except Exception as e:
        return (
            f"<div style='color:#ef4444;'>Error: {e}</div>",
            "",
            [],
            {},
            0,
            gr.update(active=False),
            "",
            "",
            ""
        )






# --- Playback Simulation Loop ---
def step_simulation(current_idx, route_data, speed):
    if not route_data or "points" not in route_data:
        return current_idx, gr.update(), gr.update(), gr.update(), ""
        
    points = route_data["points"]
    checkpoints = route_data["checkpoints"]
    pois = route_data.get("pois", [])
    
    if current_idx >= len(points):
        return current_idx, gr.update(), gr.update(), gr.update(), ""
        
    step_size = int(speed)
    next_idx = current_idx + step_size
    if next_idx >= len(points):
        next_idx = len(points) - 1
        
    current_pt = points[next_idx]
    
    lat = current_pt["lat"]
    lon = current_pt["lon"]
    ele = current_pt["ele"]
    cum_dist = current_pt["cum_dist"]
    
    total_dist = points[-1]["cum_dist"]
    pct_complete = (cum_dist / total_dist) * 100.0 if total_dist > 0 else 0.0
    
    # Proximity alerts check
    active_alerts = []
    for poi in pois:
        d = haversine(lat, lon, poi["lat"], poi["lon"])
        if d <= 150.0:
            icon_map = {
                "drinking_water": "💧",
                "spring": "💧",
                "water_point": "💧",
                "fountain": "⛲",
                "alpine_hut": "🏡",
                "wilderness_hut": "🏡",
                "camp_site": "⛺",
                "shelter": "🛡️",
                "viewpoint": "👁️",
                "peak": "🏔️",
                "phone": "📞"
            }
            icon = icon_map.get(poi["type"], "📍")
            active_alerts.append(f"<div style='background:rgba(245,158,11,0.15); border:1px solid #f59e0b; padding:10px; border-radius:8px; margin-bottom:5px; color:#f59e0b;'>{icon} <b>PROXIMITY:</b> {poi['name']} is {d:.0f}m away! ({poi['type'].replace('_', ' ').title()})</div>")
            
    # Checkpoint ETA progress
    next_cp = None
    for cp in checkpoints:
        if cp["cum_dist"] * 1000.0 > cum_dist:
            next_cp = cp
            break
            
    eta_text = "N/A"
    if next_cp:
        dist_to_cp = (next_cp["cum_dist"] * 1000.0) - cum_dist
        eta_sec = dist_to_cp / 1.38
        eta_text = f"{int(eta_sec // 60)}m {int(eta_sec % 60)}s"
        
    alerts_html = "".join(active_alerts) if active_alerts else "<div style='color:var(--text-muted);'>No active proximity alerts.</div>"
    
    # Live HUD Panel
    hud_html = f"""
    <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 15px; margin-bottom: 20px;'>
        <div class='hud-stat-box'>
            <div class='hud-stat-val mono-display'>{pct_complete:.1f}%</div>
            <div class='hud-stat-lbl'>Route Progress</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val mono-display'>{cum_dist/1000.0:.2f} km</div>
            <div class='hud-stat-lbl'>Distance Hiked</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val mono-display'>{ele:.1f} m</div>
            <div class='hud-stat-lbl'>Current Altitude</div>
        </div>
        <div class='hud-stat-box'>
            <div class='hud-stat-val mono-display'>{eta_text}</div>
            <div class='hud-stat-lbl'>ETA to Next Point</div>
        </div>
    </div>
    """
    
    # Proximity narration brief
    narration_html = ""
    for cp in checkpoints:
        cp_dist_m = cp["cum_dist"] * 1000.0
        if abs(cum_dist - cp_dist_m) <= 150.0:
            cautions = ""
            if ele > 2400:
                cautions = " WARNING: Altitude is above 2400m. Watch for AMS symptoms (headache, dizziness)."
            narration_html = f"""
            <div style='border-left: 4px solid var(--accent-primary); background: rgba(245,158,11,0.05); padding: 15px; border-radius: 0 8px 8px 0;'>
                <b style='color:var(--accent-primary);'>📻 RADIO BRIEFING FOR {cp['name'].upper()}:</b>
                <p style='margin-top: 5px; font-style: italic;'>
                    "Hiker, you have arrived at {cp['name']}. Current altitude is {ele:.1f}m.{cautions}"
                </p>
            </div>
            """
            break
            
    import json
    hiker_coords_json = json.dumps({
        "lat": lat,
        "lon": lon,
        "ele": ele,
        "cum_dist": cum_dist / 1000.0
    })
    return next_idx, hud_html, alerts_html, narration_html, hiker_coords_json



# --- First-Aid Manual Search ---
def handle_first_aid_search(query):
    if not query.strip():
        return "Please enter symptoms or injury to search the manual."
        
    grounding_text, sources = rag.retrieve_first_aid(query)
    if not grounding_text:
        return "No matching first-aid sections found in the manual. (Please carry a PLB/satellite communicator on remote trails)."
        
    system_prompt = (
        "You are Trailhead Guide, an expert wilderness medicine counselor.\n"
        "Provide a concise, direct, and actionable step-by-step first-aid protocol based on the provided guide context.\n"
        "Cite the section at the end."
    )
    prompt = f"Context:\n{grounding_text}\n\nQuestion: {query}\n\nAnswer:"
    response = llm.generate(prompt, system=system_prompt, stream=False)
    
    return f"### Retrieval Results ({', '.join(sources)})\n\n{response}"

# --- Chatbot Integration ---
def respond(message, history):
    response_accumulator = ""
    grounding_text, sources = rag.retrieve_first_aid(message)
    
    if grounding_text:
        source_cite = "Sources: " + ", ".join(sources)
        system_prompt = (
            "You are Trailhead Guide, a wilderness first-aid advisor.\n"
            "Answer the query using ONLY the provided guide context.\n"
            f"Context:\n{grounding_text}\n"
            "Keep the instructions clear, numbered, and precise.\n"
            f"Cite: '{source_cite}'."
        )
    else:
        system_prompt = (
            "You are Trailhead Guide, an expert hiking guide.\n"
            "Provide helpful, concise trekking advice."
        )
        
    for token in llm.generate(message, system=system_prompt, history=history, stream=True):
        response_accumulator += token
        yield response_accumulator

# --- Gradio Blocks UI ---
with gr.Blocks(css="assets/custom.css", title="Trailhead — Tactical Trail Computer") as demo:
    route_state = gr.State({})
    current_point_idx = gr.State(0)
    hiker_pos_coords = gr.Textbox(visible=False, elem_id="hiker-pos-coords")
    route_data_json = gr.Textbox(visible=False, elem_id="route-data-json")
    
    hiker_pos_coords.change(
        fn=None,
        inputs=[hiker_pos_coords],
        outputs=None,
        js="""
        (coords) => {
            window.pendingHikerCoords = coords;
            if (window.updateHikerPosHandler) {
                window.updateHikerPosHandler(coords);
            }
        }
        """
    )
    
    route_data_json.change(
        fn=None,
        inputs=[route_data_json],
        outputs=None,
        js="""
        (routeJson) => {
            window.pendingRouteData = routeJson;
            if (window.routeDataChangeHandler) {
                window.routeDataChangeHandler(routeJson);
            }
        }
        """
    )


    
    gr.HTML("""
    <div style='text-align: center; padding: 10px 0;'>
        <h1>🌲 Trailhead 🌲</h1>
        <p style='color: #f59e0b; font-family: "Share Tech Mono", monospace; letter-spacing: 0.1em; text-transform: uppercase; font-size: 1rem; margin-top: -5px;'>
            Off-the-Grid Trail Computer & Route Planner
        </p>
    </div>
    """)
    
    # Timer loop for simulation
    timer = gr.Timer(value=0.2, active=False)
    
    with gr.Tabs():
        with gr.TabItem("🧭 Trek Planner & HUD"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 📂 Route Ingestion")
                    
                    preloaded_route = gr.Dropdown(
                        choices=["Preloaded Route: Trento Track"],
                        value="Preloaded Route: Trento Track",
                        label="Preloaded Routes"
                    )
                    
                    upload_file = gr.File(
                        file_types=[".gpx"],
                        label="Upload GPX Route File"
                    )
                    
                    with gr.Accordion("🔌 Fetch Online Route (Basecamp Mode)", open=False):
                        start_pt = gr.Textbox(
                            value="46.0734974, 11.1717214",
                            label="Start Coordinates (Lat, Lon)"
                        )
                        end_pt = gr.Textbox(
                            value="46.0788233, 11.1777218",
                            label="End Coordinates (Lat, Lon)"
                        )
                        ors_profile = gr.Dropdown(
                            choices=["foot-hiking", "foot-walking"],
                            value="foot-hiking",
                            label="Profile"
                        )
                        ors_api_key = gr.Textbox(
                            type="password",
                            label="OpenRouteService API Key (Optional)"
                        )
                        fetch_route_btn = gr.Button("Fetch & Load Route", variant="secondary")
                        
                    gr.Markdown("### 🎮 Trek Simulation Controls")
                    with gr.Row():
                        play_btn = gr.Button("▶ PLAY", variant="primary")
                        pause_btn = gr.Button("⏸ PAUSE", variant="secondary")
                        reset_btn = gr.Button("🔄 RESET", variant="secondary")
                    speed_slider = gr.Slider(minimum=1, maximum=20, step=1, value=1, label="Simulation Speed (Points per tick)")
                    
                    gr.Markdown("### ⚠️ Active Proximity Alerts")
                    alerts_output = gr.HTML(value="<div style='color:var(--text-muted);'>No active proximity alerts.</div>")
                    
                with gr.Column(scale=2):
                    # Stats display
                    stats_display = gr.HTML()
                    
                    # Interactive Map display
                    map_display = gr.HTML(value=MAP_HTML_INITIALIZER)
                    # Narration briefing output
                    narration_output = gr.HTML(value="")
                    
            with gr.Accordion("📋 Route Checkpoint Briefing", open=True):
                checkpoint_table = gr.DataFrame(
                    headers=["Checkpoint", "Coordinates", "Cumulative Distance", "Altitude"],
                    datatype=["str", "str", "str", "str"],
                    column_count=(4, "fixed")
                )
                
        with gr.TabItem("🩺 Wilderness First-Aid"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.HTML(EMERGENCY_CARD)
                with gr.Column(scale=1):
                    gr.Markdown("## 🔍 Wilderness First-Aid manual RAG Search")
                    rag_query = gr.Textbox(placeholder="What symptoms or injury do you want to query?", label="Query Symptoms")
                    rag_search_btn = gr.Button("Search manual", variant="primary")
                    rag_output = gr.Markdown(value="*Manual results will be displayed here.*")
                    
        with gr.TabItem("💬 Wilderness Guide AI"):
            gr.ChatInterface(
                respond,
                examples=[
                    "What gear checklist do I need for a 3-day high-altitude trek?",
                    "How do I treat a sprained ankle on the trail?",
                    "What is Naismith's Rule for calculating hiking time?"
                ]
            )


    

    
    # --- Simulation player bindings ---
    timer.tick(
        fn=step_simulation,
        inputs=[current_point_idx, route_state, speed_slider],
        outputs=[current_point_idx, stats_display, alerts_output, narration_output, hiker_pos_coords]
    )
    
    play_btn.click(
        fn=lambda: gr.update(active=True),
        inputs=[],
        outputs=[timer]
    )
    
    pause_btn.click(
        fn=lambda: gr.update(active=False),
        inputs=[],
        outputs=[timer]
    )
    


    def handle_reset(route):
        pts = route.get("points", [])
        if pts:
            stats_html, map_iframe, checkpoint_table_data = format_route_view(route)
            import json
            start_pt = pts[0]
            hiker_coords_json = json.dumps({
                "lat": start_pt["lat"],
                "lon": start_pt["lon"],
                "ele": start_pt["ele"],
                "cum_dist": start_pt["cum_dist"] / 1000.0
            })
            return 0, gr.update(active=False), stats_html, "", "", hiker_coords_json
        return 0, gr.update(active=False), gr.update(), "", "", ""
        
    reset_btn.click(
        fn=handle_reset,
        inputs=[route_state],
        outputs=[current_point_idx, timer, stats_display, alerts_output, narration_output, hiker_pos_coords]
    )



    
    # --- Route Ingestion Triggers ---
    # Load default route on startup
    demo.load(
        fn=handle_route_update,
        inputs=[preloaded_route, upload_file, gr.State(""), gr.State(""), gr.State(""), gr.State("")],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords],
        js=MAP_INIT_JS
    )
    
    # Preloaded selection change
    preloaded_route.change(
        fn=handle_route_update,
        inputs=[preloaded_route, gr.State(None), gr.State(""), gr.State(""), gr.State(""), gr.State("")],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords]
    )
    
    # Uploaded file change
    upload_file.change(
        fn=handle_route_update,
        inputs=[gr.State(None), upload_file, gr.State(""), gr.State(""), gr.State(""), gr.State("")],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords]
    )
    
    # Fetch route button click
    fetch_route_btn.click(
        fn=handle_ors_fetch_click,
        inputs=[start_pt, end_pt, ors_profile, ors_api_key],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords]
    )

    
    # --- RAG Trigger ---
    rag_search_btn.click(
        fn=handle_first_aid_search,
        inputs=[rag_query],
        outputs=[rag_output]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    try:
        demo.launch(server_name="0.0.0.0", server_port=port)
    except OSError:
        print(f"[app] Port {port} is busy. Falling back to automatic port selection...")
        demo.launch(server_name="127.0.0.1")
