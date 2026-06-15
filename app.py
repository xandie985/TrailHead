import os
import base64
import requests
import gradio as gr
import pandas as pd
import folium
from src.gpx_parser import parse_gpx_file, haversine, save_enhanced_gpx
import src.llm as llm
import src.rag as rag
import src.database as db

# Initialize cache and temp folders and SQLite database
os.makedirs("./temp", exist_ok=True)
db.init_db()

# Preloaded route path — resolve relative to this file for cross-platform compatibility
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
PRELOADED_ROUTE_PATH = os.path.join(_APP_DIR, "Routes", "track_5-14724236830.gpx")
# Bundled pre-parsed cache for the Trento track (includes POIs — avoids Overpass API on HF)
PRELOADED_CACHE_PATH = os.path.join(_APP_DIR, "src", "data", "trento_route_cache.json")

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
            
            if (typeof L.TileLayer.OfflineFirst === 'undefined') {
                L.TileLayer.OfflineFirst = L.TileLayer.extend({
                    createTile: function(coords, done) {
                        var tile = L.TileLayer.prototype.createTile.call(this, coords, done);
                        L.DomEvent.on(tile, 'error', function() {
                            var osmUrl = 'https://tile.openstreetmap.org/' + coords.z + '/' + coords.x + '/' + coords.y + '.png';
                            if (tile.src !== osmUrl) {
                                tile.src = osmUrl;
                            }
                        });
                        return tile;
                    }
                });
            }
            
            window.activeTileLayer = new L.TileLayer.OfflineFirst('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
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
                    
                    var tilesDir = data.tiles_dir || '';
                    if (tilesDir && window.activeTileLayer) {
                        map.removeLayer(window.activeTileLayer);
                        var localUrl = '/file=' + tilesDir + '/{z}/{x}/{y}.png';
                        window.activeTileLayer = new L.TileLayer.OfflineFirst(localUrl, {
                            maxZoom: 16,
                            minZoom: 13,
                            attribution: '&copy; OpenStreetMap'
                        }).addTo(map);
                    }
                    
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
            
            // --- Live GPS Tracking Logic ---
            window.gpsWatchId = null;
            window.lastGpsTime = 0;
            
            window.toggleLiveGPS = function(enabled) {
                if (!enabled && window.gpsWatchId !== null) {
                    navigator.geolocation.clearWatch(window.gpsWatchId);
                    window.gpsWatchId = null;
                    console.log("Live GPS tracking stopped.");
                    return;
                }
                
                if (enabled && "geolocation" in navigator) {
                    console.log("Requesting Live GPS tracking...");
                    window.gpsWatchId = navigator.geolocation.watchPosition(
                        function(position) {
                            var now = Date.now();
                            // Throttle updates to every 5 seconds (5000 ms)
                            if (now - window.lastGpsTime < 5000) return;
                            window.lastGpsTime = now;
                            
                            var coords = {
                                lat: position.coords.latitude,
                                lon: position.coords.longitude,
                                ele: position.coords.altitude || 0.0,
                                acc: position.coords.accuracy
                            };
                            
                            // Send to hidden textbox for Gradio backend
                            var textbox = document.querySelector("#live-gps-coords textarea");
                            if (!textbox) textbox = document.querySelector("#live-gps-coords input");
                            if (textbox) {
                                textbox.value = JSON.stringify(coords);
                                textbox.dispatchEvent(new Event("input", { bubbles: true }));
                            }
                        },
                        function(error) {
                            console.error("GPS Error:", error);
                            alert("GPS Tracking Error: " + error.message);
                        },
                        {
                            enableHighAccuracy: true,
                            maximumAge: 10000,
                            timeout: 10000
                        }
                    );
                } else if (enabled) {
                    alert("Geolocation is not supported by this browser or not running in a secure context.");
                }
            };
        }
    }, 100);
}
"""


def generate_elevation_plot(points, current_idx=None):
    """
    Generate an offline-ready Plotly elevation profile chart.
    If current_idx is provided, displays a vertical line or marker for the hiker's current position.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None
        
    if not points:
        return None
        
    x = [p["cum_dist"] / 1000.0 for p in points]
    y = [p["ele"] for p in points]
    
    fig = go.Figure()
    
    # Area chart for elevation
    fig.add_trace(go.Scatter(
        x=x, 
        y=y, 
        mode='lines', 
        fill='tozeroy', 
        line=dict(color='#f59e0b', width=2.5),
        fillcolor='rgba(245,158,11,0.15)',
        name='Elevation'
    ))
    
    # Hiker's current position dot
    if current_idx is not None and 0 <= current_idx < len(points):
        hiker_pt = points[current_idx]
        h_x = hiker_pt["cum_dist"] / 1000.0
        h_y = hiker_pt["ele"]
        
        # Add hiker position dot
        fig.add_trace(go.Scatter(
            x=[h_x],
            y=[h_y],
            mode='markers',
            marker=dict(color='#ef4444', size=12, symbol='circle', line=dict(color='#ffffff', width=2)),
            name='You'
        ))
        
        # Add vertical line
        fig.add_vline(x=h_x, line_width=1, line_dash="dash", line_color="#ef4444")
        
    fig.update_layout(
        title="🏔️ ELEVATION PROFILE",
        xaxis_title="Distance (km)",
        yaxis_title="Elevation (m)",
        plot_bgcolor='#0c1014',
        paper_bgcolor='#0c1014',
        font=dict(color='#f59e0b', family='Share Tech Mono, monospace'),
        margin=dict(l=50, r=20, t=50, b=50),
        hovermode="x unified",
        showlegend=False,
        height=280
    )
    
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(245,158,11,0.1)')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(245,158,11,0.1)')
    
    return fig

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

def handle_route_update(preloaded_sel, uploaded_file):
    file_path = PRELOADED_ROUTE_PATH
    is_preloaded = True
    if uploaded_file is not None:
        is_preloaded = False
        if isinstance(uploaded_file, list) and len(uploaded_file) > 0:
            uploaded_file = uploaded_file[0]
        if isinstance(uploaded_file, dict):
            file_path = uploaded_file.get("path") or uploaded_file.get("name") or PRELOADED_ROUTE_PATH
        else:
            file_path = getattr(uploaded_file, "path", getattr(uploaded_file, "name", PRELOADED_ROUTE_PATH))
        
    try:
        # For the preloaded Trento route, use the bundled cache (includes 4 POIs).
        # This avoids Overpass API calls on Hugging Face Spaces where network access may be restricted.
        import json as _json
        if is_preloaded and os.path.exists(PRELOADED_CACHE_PATH):
            print(f"[app] Loading bundled preloaded route cache from {PRELOADED_CACHE_PATH}")
            with open(PRELOADED_CACHE_PATH, "r", encoding="utf-8") as _f:
                data = _json.load(_f)
        else:
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
            "",
            None
        )
        
    # Load custom waypoints from DB and merge them into POIs
    try:
        custom_wps = db.get_custom_waypoints()
        for wp in custom_wps:
            min_d = float('inf')
            closest_idx = -1
            for idx, pt in enumerate(data["points"]):
                d = haversine(wp["lat"], wp["lon"], pt["lat"], pt["lon"])
                if d < min_d:
                    min_d = d
                    closest_idx = idx
            
            data["pois"].append({
                "id": f"custom_{wp['id']}",
                "lat": wp["lat"],
                "lon": wp["lon"],
                "type": wp["type"],
                "name": f"📍 {wp['name']} (Custom)",
                "distance": round(min_d, 1) if closest_idx != -1 else 0.0,
                "track_index": closest_idx
            })
    except Exception as ex:
        print(f"[app] Error loading custom waypoints: {ex}")

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
    
    # Get absolute path of tiles directory to pass to Leaflet
    tiles_dir_abs = os.path.abspath("./assets/tiles").replace("\\", "/")
    
    route_json = json.dumps({
        "points": data["points"],
        "checkpoints": data["checkpoints"],
        "pois": data.get("pois", []),
        "tiles_dir": tiles_dir_abs
    })
    
    ele_plot = generate_elevation_plot(data["points"], 0)
        
    return stats_html, route_json, checkpoint_table_data, data, 0, gr.update(active=False), "", "", hiker_coords_json, ele_plot

def handle_ors_fetch_click(start_coords, end_coords, profile, api_key):
    try:
        route_file = fetch_ors_route(start_coords, end_coords, profile, api_key)
        data = parse_gpx_file(route_file)
        
        # Load custom waypoints from DB and merge them into POIs
        try:
            custom_wps = db.get_custom_waypoints()
            for wp in custom_wps:
                min_d = float('inf')
                closest_idx = -1
                for idx, pt in enumerate(data["points"]):
                    d = haversine(wp["lat"], wp["lon"], pt["lat"], pt["lon"])
                    if d < min_d:
                        min_d = d
                        closest_idx = idx
                
                data["pois"].append({
                    "id": f"custom_{wp['id']}",
                    "lat": wp["lat"],
                    "lon": wp["lon"],
                    "type": wp["type"],
                    "name": f"📍 {wp['name']} (Custom)",
                    "distance": round(min_d, 1) if closest_idx != -1 else 0.0,
                    "track_index": closest_idx
                })
        except Exception as ex:
            print(f"[app] Error loading custom waypoints: {ex}")

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
        
        tiles_dir_abs = os.path.abspath("./assets/tiles").replace("\\", "/")
        
        route_json = json.dumps({
            "points": data["points"],
            "checkpoints": data["checkpoints"],
            "pois": data.get("pois", []),
            "tiles_dir": tiles_dir_abs
        })
        
        ele_plot = generate_elevation_plot(data["points"], 0)
        return stats_html, route_json, checkpoint_table_data, data, 0, gr.update(active=False), "", "", hiker_coords_json, ele_plot
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
            "",
            None
        )

# --- Playback Simulation Loop ---
def step_simulation(current_idx, route_data, speed):
    if not route_data or "points" not in route_data:
        return current_idx, gr.update(), gr.update(), gr.update(), "", gr.update(), gr.update()
        
    points = route_data["points"]
    checkpoints = route_data["checkpoints"]
    pois = route_data.get("pois", [])
    
    if current_idx >= len(points) - 1:
        return current_idx, gr.update(), gr.update(), gr.update(), "", gr.update(), gr.update(active=False)
        
    step_size = int(speed)
    next_idx = current_idx + step_size
    timer_update = gr.update()
    if next_idx >= len(points) - 1:
        next_idx = len(points) - 1
        timer_update = gr.update(active=False)
        
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
    
    # Throttled Plotly update (every 10 simulation steps)
    plot_update = gr.update()
    if next_idx == 0 or next_idx == len(points) - 1 or next_idx % 10 == 0:
        fig = generate_elevation_plot(points, next_idx)
        if fig:
            plot_update = fig
            
    return next_idx, hud_html, alerts_html, narration_html, hiker_coords_json, plot_update, timer_update


# --- Live GPS Processing ---
def handle_live_gps_update(coords_str, route_data):
    if not route_data or "points" not in route_data or not coords_str:
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        
    import json
    try:
        coords = json.loads(coords_str)
        lat = coords["lat"]
        lon = coords["lon"]
        ele = coords["ele"]
    except Exception:
        return gr.update(), gr.update(), gr.update(), gr.update(), gr.update()
        
    points = route_data["points"]
    checkpoints = route_data["checkpoints"]
    pois = route_data.get("pois", [])
    
    # Snap to nearest point on route to determine cum_dist
    min_d = float('inf')
    closest_idx = 0
    for idx, pt in enumerate(points):
        d = haversine(lat, lon, pt["lat"], pt["lon"])
        if d < min_d:
            min_d = d
            closest_idx = idx
            
    cum_dist = points[closest_idx]["cum_dist"]
    total_dist = points[-1]["cum_dist"]
    pct_complete = (cum_dist / total_dist) * 100.0 if total_dist > 0 else 0.0
    
    # Update hiker coords json for map JS
    hiker_coords_json = json.dumps({
        "lat": lat,
        "lon": lon,
        "ele": ele,
        "cum_dist": cum_dist / 1000.0
    })
    
    # Proximity alerts check
    active_alerts = []
    for poi in pois:
        d = haversine(lat, lon, poi["lat"], poi["lon"])
        if d <= 150.0:
            icon_map = {
                "drinking_water": "💧", "spring": "💧", "water_point": "💧",
                "fountain": "⛲", "alpine_hut": "🏡", "wilderness_hut": "🏡",
                "camp_site": "⛺", "shelter": "🛡️", "viewpoint": "👁️",
                "peak": "🏔️", "phone": "📞"
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
    
    hud_html = f'''
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 15px; margin-bottom: 20px;">
        <div class="hud-stat-box">
            <div class="hud-stat-val mono-display">{pct_complete:.1f}%</div>
            <div class="hud-stat-lbl">Route Progress</div>
        </div>
        <div class="hud-stat-box">
            <div class="hud-stat-val mono-display">{cum_dist/1000.0:.2f} km</div>
            <div class="hud-stat-lbl">Distance Hiked</div>
        </div>
        <div class="hud-stat-box">
            <div class="hud-stat-val mono-display">{ele:.1f} m</div>
            <div class="hud-stat-lbl">Current Altitude</div>
        </div>
        <div class="hud-stat-box">
            <div class="hud-stat-val mono-display">{eta_text}</div>
            <div class="hud-stat-lbl">ETA to Next Point</div>
        </div>
    </div>
    '''
    
    # Proximity narration brief
    narration_html = ""
    for cp in checkpoints:
        cp_dist_m = cp["cum_dist"] * 1000.0
        if abs(cum_dist - cp_dist_m) <= 150.0:
            cautions = ""
            if ele > 2400:
                cautions = " WARNING: Altitude is above 2400m. Watch for AMS symptoms (headache, dizziness)."
            narration_html = f'''
            <div style="border-left: 4px solid var(--accent-primary); background: rgba(245,158,11,0.05); padding: 15px; border-radius: 0 8px 8px 0;">
                <b style="color:var(--accent-primary);">📻 RADIO BRIEFING FOR {cp['name'].upper()}:</b>
                <p style="margin-top: 5px; font-style: italic;">
                    "Hiker, you have arrived at {cp['name']}. Current altitude is {ele:.1f}m.{cautions}"
                </p>
            </div>
            '''
            break
            
    plot_update = gr.update()
    fig = generate_elevation_plot(points, closest_idx)
    if fig:
        plot_update = fig
            
    return hud_html, alerts_html, narration_html, hiker_coords_json, plot_update


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

# --- Phase 3 Callbacks (Waypoint Tagging, Voice Logs, AI Storytelling) ---
def handle_tag_waypoint(wp_type, wp_name, hiker_pos_coords_str, route_state_val):
    if not hiker_pos_coords_str:
        return gr.update(), route_state_val, "<span style='color:#ef4444;'>Error: No active simulated hiker position to tag!</span>", []
    if not wp_name.strip():
        return gr.update(), route_state_val, "<span style='color:#ef4444;'>Error: Waypoint name cannot be empty!</span>", []
        
    import json
    try:
        h_coords = json.loads(hiker_pos_coords_str)
        lat = h_coords["lat"]
        lon = h_coords["lon"]
        ele = h_coords["ele"]
    except Exception as e:
        return gr.update(), route_state_val, f"<span style='color:#ef4444;'>Error parsing coordinates: {e}</span>", []
        
    # Save to DB
    db.add_custom_waypoint(lat, lon, ele, wp_type, wp_name)
    
    # Load updated waypoints
    custom_wps = db.get_custom_waypoints()
    wp_list = [[wp["timestamp"], wp["type"].upper(), wp["name"], f"{wp['lat']:.5f}, {wp['lon']:.5f}", f"{wp['ele']:.1f} m"] for wp in custom_wps]
    
    # Merge into map POIs
    route_json_str = gr.update()
    if route_state_val and "points" in route_state_val:
        min_d = float('inf')
        closest_idx = -1
        for idx, pt in enumerate(route_state_val["points"]):
            d = haversine(lat, lon, pt["lat"], pt["lon"])
            if d < min_d:
                min_d = d
                closest_idx = idx
        
        if "pois" not in route_state_val:
            route_state_val["pois"] = []
            
        route_state_val["pois"].append({
            "id": f"custom_{len(custom_wps)}",
            "lat": lat,
            "lon": lon,
            "type": wp_type,
            "name": f"📍 {wp_name} (Custom)",
            "distance": round(min_d, 1) if closest_idx != -1 else 0.0,
            "track_index": closest_idx
        })
        
        tiles_dir_abs = os.path.abspath("./assets/tiles").replace("\\", "/")
        
        route_json_str = json.dumps({
            "points": route_state_val["points"],
            "checkpoints": route_state_val["checkpoints"],
            "pois": route_state_val["pois"],
            "tiles_dir": tiles_dir_abs
        })
        
    msg = f"<span style='color:#10b981;'>Successfully tagged '{wp_name}' ({wp_type.replace('_', ' ').title()}) at your position!</span>"
    return route_json_str, route_state_val, msg, wp_list

def handle_clear_waypoints(route_state_val):
    db.clear_custom_waypoints()
    
    route_json_str = gr.update()
    if route_state_val and "pois" in route_state_val:
        # Remove POIs that were added custom
        route_state_val["pois"] = [p for p in route_state_val["pois"] if not str(p.get("id", "")).startswith("custom_")]
        
        tiles_dir_abs = os.path.abspath("./assets/tiles").replace("\\", "/")
        route_json_str = json.dumps({
            "points": route_state_val["points"],
            "checkpoints": route_state_val["checkpoints"],
            "pois": route_state_val["pois"],
            "tiles_dir": tiles_dir_abs
        })
        
    return route_json_str, route_state_val, "<span style='color:#ef4444;'>Cleared all custom waypoints.</span>", []

def handle_save_journal(audio_path, hiker_pos_coords_str):
    if not audio_path:
        return "", [], "<span style='color:#ef4444;'>Error: No recorded voice audio found!</span>", gr.update()
        
    lat, lon, ele, cum_dist = 0.0, 0.0, 0.0, 0.0
    if hiker_pos_coords_str:
        try:
            import json
            h_coords = json.loads(hiker_pos_coords_str)
            lat = h_coords["lat"]
            lon = h_coords["lon"]
            ele = h_coords["ele"]
            cum_dist = h_coords["cum_dist"]
        except Exception as e:
            print(f"[app] Error parsing simulation coordinates for journal: {e}")
            
    print(f"[app] Transcribing journal audio file from {audio_path}...")
    transcript = llm.transcribe_audio(audio_path, prompt="Wilderness trek journal log")
    
    if not transcript or not transcript.strip():
        return "", [], "<span style='color:#ef4444;'>Error: ASR transcription returned empty text!</span>", gr.update()
        
    # Save to SQLite
    db.add_journal_entry(lat, lon, ele, cum_dist, transcript)
    
    # Fetch updated logs
    logs = db.get_journal_entries()
    logs_table = [[l["timestamp"], f"{l['lat']:.5f}, {l['lon']:.5f}", f"{l['cum_dist']:.2f} km", l["transcript"]] for l in logs]
    
    msg = f"<span style='color:#10b981;'>Saved journal entry at Km {cum_dist:.2f} successfully!</span>"
    return transcript, logs_table, msg, None

def handle_clear_journal():
    db.clear_journal_logs()
    return "", [], "<span style='color:#ef4444;'>Cleared all voice journal logs.</span>"

def handle_generate_story(route_state_val, style):
    logs = db.get_journal_entries()
    if not logs:
        return "### 📖 No Voice Logs Found\n\nPlease record and save some voice journal entries during your simulated trek before generating your AI story!", None
        
    # Compile journal logs chronologically (oldest first)
    logs_chron = list(reversed(logs))
    journal_text = ""
    for idx, l in enumerate(logs_chron):
        journal_text += f"\n- Log #{idx+1} ({l['timestamp']}) at Km {l['cum_dist']:.2f} (Alt: {l['ele']:.1f}m):\n  \"{l['transcript']}\"\n"
        
    # 1. Compile route stats (Trek details)
    stats_text = "Trek Details:\n"
    if route_state_val and "total_distance_km" in route_state_val:
        stats_text += f"- Total Distance: {route_state_val['total_distance_km']:.2f} km\n"
        stats_text += f"- Total Elevation Gain: {route_state_val['elevation_gain_m']:.1f} m\n"
        stats_text += f"- Total Elevation Loss: {route_state_val.get('elevation_loss_m', 0.0):.1f} m\n"
        stats_text += f"- Altitude Range: {route_state_val['min_elevation_m']:.1f}m - {route_state_val['max_elevation_m']:.1f}m\n"
    else:
        stats_text += "- Trento Route Simulation\n"
        
    # 2. Compile checkpoints
    checkpoints_text = "Checkpoints & Milestones:\n"
    if route_state_val and "checkpoints" in route_state_val and route_state_val["checkpoints"]:
        for cp in route_state_val["checkpoints"]:
            checkpoints_text += f"- {cp['name']} at Km {cp['cum_dist']:.2f} (Altitude: {cp['ele']:.1f}m)\n"
    else:
        checkpoints_text += "- Start and End checkpoints along the trail.\n"
        
    # 3. Compile amenities (POIs)
    amenities_text = "Amenities & Points of Interest along the Route:\n"
    if route_state_val and "pois" in route_state_val and route_state_val["pois"]:
        for poi in route_state_val["pois"]:
            poi_name = poi.get("name", "Unnamed")
            poi_type = poi.get("type", "Point of Interest").replace("_", " ").title()
            dist = poi.get("distance", 0.0)
            track_idx = poi.get("track_index", -1)
            dist_str = ""
            if track_idx != -1 and "points" in route_state_val and track_idx < len(route_state_val["points"]):
                poi_cum_dist = route_state_val["points"][track_idx]["cum_dist"] / 1000.0
                dist_str = f"at approx. Km {poi_cum_dist:.2f}"
            amenities_text += f"- {poi_name} ({poi_type}) {dist_str} (located {dist:.1f} meters off the trail)\n"
    else:
        amenities_text += "- General alpine huts, shelters, and water streams close to the path.\n"
        
    if style == "Minimal Technical Gist":
        style_instruction = (
            "Write a concise, bullet-pointed, and highly technical summary of the trek. "
            "Focus on the exact telemetry (distances, altitudes, checkpoints reached), voice note transcripts, "
            "and amenities used (water sources, huts, campsites, viewpoints). Keep it factual, objective, and brief."
        )
    else:  # "Social Media Post (Elaborative)"
        style_instruction = (
            "Write a highly engaging, elaborative, and inspiring story formatted as a social media post (e.g., for Instagram or LinkedIn) "
            "targeted at an audience of outdoor enthusiasts.\n"
            "Include emojis, a narrative hook, paragraphs of descriptions of the journey's highs and lows, "
            "reflections on the voice notes, details about the amenities (water sources, viewpoints, campsites) encountered, "
            "and end with relevant hashtags (e.g., #HikingAdventurer, #Trailhead, #BackcountryExploration)."
        )

    system_prompt = (
        "You are a classic wilderness novelist and explorer. Write a compelling, first-person "
        "adventure story summarizing the trek based on the provided trek details, checkpoints, amenities, "
        "and the hiker's voice journal logs.\n"
        f"Format Style: {style_instruction}\n"
        "Emphasize the hiker's voice notes, detailing their personal reflections, physical state, and "
        "wilderness observations. Incorporate the trek details (distance, elevation, altitude) to frame the physical challenge. "
        "Weave in the amenities (water sources, campsites, alpine huts, shelters, viewpoints) as milestones or locations where the hiker is resting, "
        "refilling water, or finding shelter.\n"
        "Do not invent external landmarks, voice notes, or major events not provided. Keep the tone rugged, epic, and highly tactical. "
        "Organize the story using headings corresponding to distance milestones.\n"
        "At the end, sign off as 'Trailhead AI Storyteller'."
    )
    
    prompt = f"""Here are the details of my wilderness journey:

{stats_text}

{checkpoints_text}

{amenities_text}

Here are my recorded voice logs during the trek:
{journal_text}

Please write a cohesive first-person adventure story of my trek."""

    story = llm.generate(prompt, system=system_prompt, stream=False)
    
    # Save to a file in temp
    os.makedirs("./temp", exist_ok=True)
    story_file = os.path.abspath("./temp/post_trek_story.md")
    with open(story_file, "w", encoding="utf-8") as f:
        f.write(story)
        
    return story, story_file

# --- Gradio Blocks UI ---
with gr.Blocks(css="assets/custom.css", title="Trailhead — Tactical Trail Computer") as demo:
    route_state = gr.State(None)
    null_state = gr.State(None)
    current_point_idx = gr.State(0)
    hiker_pos_coords = gr.Textbox(visible=False, elem_id="hiker-pos-coords")
    live_gps_coords = gr.Textbox(visible=False, elem_id="live-gps-coords")
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
                    live_gps_toggle = gr.Checkbox(label="📡 Enable Live GPS Tracking (Updates every 5s)")
                    
                    gr.Markdown("### ⚠️ Active Proximity Alerts")
                    alerts_output = gr.HTML(value="<div style='color:var(--text-muted);'>No active proximity alerts.</div>")
                    
                    with gr.Accordion("📍 Tag Custom Waypoint (Offline)", open=False):
                        wp_type = gr.Dropdown(
                            choices=["drinking_water", "shelter", "camp_site", "viewpoint", "hazard"],
                            value="drinking_water",
                            label="Waypoint Type"
                        )
                        wp_name = gr.Textbox(placeholder="Name (e.g. Fresh Stream)", label="Waypoint Name")
                        tag_wp_btn = gr.Button("Tag Current Location", variant="primary")
                        clear_wps_btn = gr.Button("Clear Tagged Waypoints", variant="stop")
                        tag_status = gr.HTML(value="")
                        
                        tagged_wps_table = gr.DataFrame(
                            headers=["Timestamp", "Type", "Name", "Coordinates", "Altitude"],
                            datatype=["str", "str", "str", "str", "str"],
                            value=[]
                        )
                    
                with gr.Column(scale=2):
                    # Stats display
                    stats_display = gr.HTML()
                    
                    # Interactive Map display
                    map_display = gr.HTML(value=MAP_HTML_INITIALIZER)
                    
                    # Elevation Profile display
                    elevation_profile_plot = gr.Plot(label="Elevation Profile", elem_id="elevation-plot")
                    
                    # Narration briefing output
                    narration_output = gr.HTML(value="")
                    
            with gr.Accordion("📋 Route Checkpoint Briefing", open=True):
                checkpoint_table = gr.DataFrame(
                    headers=["Checkpoint", "Coordinates", "Cumulative Distance", "Altitude"],
                    datatype=["str", "str", "str", "str"],
                    col_count=(4, "fixed")
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
            # Dynamically configure chatbot to use "messages" type if on Gradio 5
            gradio_version = getattr(gr, "__version__", "5.0.0")
            if gradio_version.startswith("6"):
                chatbot_component = gr.Chatbot()
            else:
                chatbot_component = gr.Chatbot(type="messages")
                
            gr.ChatInterface(
                respond,
                chatbot=chatbot_component,
                examples=[
                    "What gear checklist do I need for a 3-day high-altitude trek?",
                    "How do I treat a sprained ankle on the trail?",
                    "What is Naismith's Rule for calculating hiking time?"
                ]
            )

        with gr.TabItem("🎙️ Voice Journal & Reports"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("## 🎙️ Hands-Free Voice Trek Journal")
                    gr.Markdown("Record audio logs during your journey. They will be automatically transcribed and geotagged with your current coordinates and altitude.")
                    
                    journal_audio = gr.Audio(sources=["microphone"], type="filepath", label="Record Voice Log")
                    save_journal_btn = gr.Button("💾 Save Voice Log", variant="primary")
                    clear_journal_btn = gr.Button("🗑️ Clear Logs", variant="stop")
                    
                    journal_status = gr.HTML(value="")
                    last_transcription = gr.Textbox(label="Last Transcription (ASR)", interactive=False)
                    
                with gr.Column(scale=1):
                    gr.Markdown("## 📓 Saved Journal Logs")
                    journal_logs_table = gr.DataFrame(
                        headers=["Timestamp", "Coordinates", "Distance Hiked", "Transcript"],
                        datatype=["str", "str", "str", "str"],
                        value=[]
                    )
                    
            gr.Markdown("---")
            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown("## 📖 Post-Trek AI Storyteller")
                    gr.Markdown("Click below to compile all your saved voice journal logs and route statistics into an AI-narrated story of your adventure!")
                    story_style = gr.Radio(
                        choices=["Minimal Technical Gist", "Social Media Post (Elaborative)"],
                        value="Social Media Post (Elaborative)",
                        label="Story Style / Format"
                    )
                    generate_story_btn = gr.Button("🎬 Generate AI Trek Story", variant="primary")
                    story_output = gr.Markdown(value="*Your adventure narrative will be generated here.*")
                with gr.Column(scale=1):
                    gr.Markdown("### 📥 Download Story")
                    story_download = gr.File(label="Download Story (Markdown)", interactive=False)


    

    
    # --- Simulation player bindings ---
    timer.tick(
        fn=step_simulation,
        inputs=[current_point_idx, route_state, speed_slider],
        outputs=[current_point_idx, stats_display, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot, timer]
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
        pts = route.get("points", []) if route else []
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
            ele_plot = generate_elevation_plot(pts, 0)
            return 0, gr.update(active=False), stats_html, "", "", hiker_coords_json, ele_plot
        return 0, gr.update(active=False), gr.update(), "", "", "", None
        
    reset_btn.click(
        fn=handle_reset,
        inputs=[route_state],
        outputs=[current_point_idx, timer, stats_display, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot]
    )



    
    # --- Route Ingestion Triggers ---
    # Load default route on startup
    demo.load(
        fn=handle_route_update,
        inputs=[preloaded_route, upload_file],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot],
        js=MAP_INIT_JS
    )
    
    # Preloaded selection change
    preloaded_route.change(
        fn=handle_route_update,
        inputs=[preloaded_route, null_state],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot]
    )
    
    # Uploaded file change
    upload_file.change(
        fn=handle_route_update,
        inputs=[null_state, upload_file],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot]
    )
    
    # Fetch route button click
    fetch_route_btn.click(
        fn=handle_ors_fetch_click,
        inputs=[start_pt, end_pt, ors_profile, ors_api_key],
        outputs=[stats_display, route_data_json, checkpoint_table, route_state, current_point_idx, timer, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot]
    )

    # --- Custom Waypoint Tagging Triggers ---
    tag_wp_btn.click(
        fn=handle_tag_waypoint,
        inputs=[wp_type, wp_name, hiker_pos_coords, route_state],
        outputs=[route_data_json, route_state, tag_status, tagged_wps_table]
    )
    
    clear_wps_btn.click(
        fn=handle_clear_waypoints,
        inputs=[route_state],
        outputs=[route_data_json, route_state, tag_status, tagged_wps_table]
    )

    # --- Voice Journal & Reports Triggers ---
    save_journal_btn.click(
        fn=handle_save_journal,
        inputs=[journal_audio, hiker_pos_coords],
        outputs=[last_transcription, journal_logs_table, journal_status, journal_audio]
    )
    
    clear_journal_btn.click(
        fn=handle_clear_journal,
        inputs=[],
        outputs=[last_transcription, journal_logs_table, journal_status]
    )
    
    generate_story_btn.click(
        fn=handle_generate_story,
        inputs=[route_state, story_style],
        outputs=[story_output, story_download]
    )
    
    # --- RAG Trigger ---
    rag_search_btn.click(
        fn=handle_first_aid_search,
        inputs=[rag_query],
        outputs=[rag_output]
    )

    # --- Live GPS Triggers ---
    live_gps_toggle.change(
        fn=None,
        inputs=[live_gps_toggle],
        outputs=None,
        js="(enabled) => { if (window.toggleLiveGPS) window.toggleLiveGPS(enabled); }"
    )
    
    live_gps_coords.change(
        fn=handle_live_gps_update,
        inputs=[live_gps_coords, route_state],
        outputs=[stats_display, alerts_output, narration_output, hiker_pos_coords, elevation_profile_plot]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    try:
        demo.launch(server_name="0.0.0.0", server_port=port)
    except OSError:
        print(f"[app] Port {port} is busy. Falling back to automatic port selection...")
        demo.launch(server_name="127.0.0.1")

