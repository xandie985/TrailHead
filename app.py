import os
import base64
import requests
import gradio as gr
import pandas as pd
import folium
from src.gpx_parser import parse_gpx_file
import src.llm as llm

# Initialize cache and temp folders
os.makedirs("./temp", exist_ok=True)

# Preloaded route path
PRELOADED_ROUTE_PATH = r"C:\Users\skushwaha\Documents\hckthn\TrailHead\Routes\track_5-14724236830.gpx"

def generate_folium_map(points, checkpoints):
    """
    Generate interactive folium map.
    """
    if not points:
        # Default centered map
        m = folium.Map(location=[46.0734974, 11.1717214], zoom_start=13)
        return m._repr_html_()
        
    # Center map on the middle point of the track
    mid_idx = len(points) // 2
    start_lat = points[mid_idx]["lat"]
    start_lon = points[mid_idx]["lon"]
    
    m = folium.Map(location=[start_lat, start_lon], zoom_start=14)
    
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
        
        # Color code markers
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
        
    return m._repr_html_()

def get_map_iframe(map_html):
    """
    Helper to bundle raw HTML into a secure, sandboxed base64 data URI iframe.
    """
    b64_html = base64.b64encode(map_html.encode('utf-8')).decode('utf-8')
    iframe_src = f"data:text/html;base64,{b64_html}"
    return f'<iframe src="{iframe_src}" width="100%" height="520px" style="border:1px solid rgba(245,158,11,0.2); border-radius: 12px;"></iframe>'

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
        # Create a mock straight-line GPX (3 coordinates: start, mid, end) for demo purposes
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
        # Fallback straight-line
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

def handle_route_update(preloaded_sel, uploaded_file, start_coords, end_coords, profile, api_key, request: gr.Request = None):
    # Determine which file to parse
    file_path = PRELOADED_ROUTE_PATH
    
    # Check trigger source
    # We can inspect input priority or simply prioritize upload -> fetch -> preloaded
    if uploaded_file is not None:
        file_path = uploaded_file.name
    elif start_coords and end_coords:
        # If coordinates are changed and user hits the trigger, we can fetch
        # However, to avoid automatic fetching on load, we only fetch when this is called via button click.
        # Since this function handles all triggers, we'll let app buttons set a temporary flag.
        pass

    try:
        data = parse_gpx_file(file_path)
    except Exception as e:
        return (
            f"<div style='color:#ef4444; padding:15px; border:1px solid #ef4444; border-radius:8px;'>Error loading GPX: {e}</div>",
            f"<iframe srcdoc='<h3 style=\"color:red;\">Error rendering map: {e}</h3>' width='100%' height='520px'></iframe>",
            []
        )
        
    # Generate Stats HUD
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
    
    # Generate Folium Map
    map_html = generate_folium_map(data["points"], data["checkpoints"])
    map_iframe = get_map_iframe(map_html)
    
    # Format Checkpoint List for Dataframe
    checkpoint_table_data = []
    for cp in data["checkpoints"]:
        checkpoint_table_data.append([
            cp["name"],
            f"{cp['lat']:.5f}, {cp['lon']:.5f}",
            f"{cp['cum_dist']:.2f} km",
            f"{cp['ele']:.1f} m"
        ])
        
    return stats_html, map_iframe, checkpoint_table_data

def handle_ors_fetch_click(start_coords, end_coords, profile, api_key):
    """Button click handler for fetching online routes."""
    try:
        route_file = fetch_ors_route(start_coords, end_coords, profile, api_key)
        return handle_route_update(None, None, start_coords, end_coords, profile, api_key)
    except Exception as e:
        return (
            f"<div style='color:#ef4444; padding:15px; border:1px solid #ef4444; border-radius:8px;'>ORS Routing Error: {e}</div>",
            gr.update(),
            gr.update()
        )

# --- Gradio Chatbot Integration ---
def respond(message, history):
    # Enforce streaming for better UX
    response_accumulator = ""
    system_prompt = (
        "You are Trailhead Guide, a helpful and knowledgeable wilderness trekking expert.\n"
        "You help hikers prepare for routes, review gear checklists, and learn wilderness first-aid.\n"
        "Be professional, concise, and safety-oriented. Emphasize offline preparedness."
    )
    for token in llm.generate(message, system=system_prompt, history=history, stream=True):
        response_accumulator += token
        yield response_accumulator

# --- Gradio Blocks UI ---
with gr.Blocks(css="assets/custom.css", title="Trailhead — Tactical Trail Computer") as demo:
    gr.HTML("""
    <div style='text-align: center; padding: 10px 0;'>
        <h1>🌲 Trailhead 🌲</h1>
        <p style='color: #f59e0b; font-family: "Share Tech Mono", monospace; letter-spacing: 0.1em; text-transform: uppercase; font-size: 1rem; margin-top: -5px;'>
            Off-the-Grid Trail Computer & Route Planner
        </p>
    </div>
    """)
    
    with gr.Tabs():
        with gr.TabItem("🧭 Trek Planner & HUD"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### 📂 Route Ingestion")
                    
                    preloaded_route = gr.Dropdown(
                        choices=["Preloaded Route: Trento Track"],
                        value="Preloaded Route: Trento Track",
                        label="Preloaded Routes (Trento, Italy)"
                    )
                    
                    upload_file = gr.File(
                        file_types=[".gpx"],
                        label="Upload GPX Route File"
                    )
                    
                    with gr.Accordion("🔌 Fetch Online Route (Basecamp Mode)", open=False):
                        gr.Markdown("Generate route paths between waypoints using OpenRouteService.")
                        start_pt = gr.Textbox(
                            value="46.0734974, 11.1717214",
                            label="Start Coordinates (Lat, Lon)"
                        )
                        end_pt = gr.Textbox(
                            value="46.0788233, 11.1777218",
                            label="End Coordinates (Lat, Lon)"
                        )
                        ors_profile = gr.Dropdown(
                            choices=["foot-hiking", "foot-walking", "cycling-mountain"],
                            value="foot-hiking",
                            label="Profile"
                        )
                        ors_api_key = gr.Textbox(
                            type="password",
                            label="OpenRouteService API Key (Optional)",
                            placeholder="Paste your API key here..."
                        )
                        fetch_route_btn = gr.Button("Fetch & Load Route", variant="secondary")
                        
                with gr.Column(scale=2):
                    # Stats display
                    stats_display = gr.HTML()
                    
                    # Interactive Map display
                    map_display = gr.HTML()
                    
            with gr.Accordion("📋 Route Checkpoint Briefing", open=True):
                checkpoint_table = gr.DataFrame(
                    headers=["Checkpoint", "Coordinates", "Cumulative Distance", "Altitude"],
                    datatype=["str", "str", "str", "str"],
                    column_count=(4, "fixed")
                )
                
        with gr.TabItem("💬 Wilderness Guide AI"):
            gr.ChatInterface(
                respond,
                examples=[
                    "What gear checklist do I need for a 3-day high-altitude trek?",
                    "How do I treat a sprained ankle on the trail?",
                    "What is Naismith's Rule for calculating hiking time?"
                ]
            )

    # --- Triggers ---
    # Load default route on startup
    demo.load(
        fn=handle_route_update,
        inputs=[preloaded_route, upload_file, gr.State(""), gr.State(""), gr.State(""), gr.State("")],
        outputs=[stats_display, map_display, checkpoint_table]
    )
    
    # Preloaded selection change
    preloaded_route.change(
        fn=handle_route_update,
        inputs=[preloaded_route, gr.State(None), gr.State(""), gr.State(""), gr.State(""), gr.State("")],
        outputs=[stats_display, map_display, checkpoint_table]
    )
    
    # Uploaded file change
    upload_file.change(
        fn=handle_route_update,
        inputs=[gr.State(None), upload_file, gr.State(""), gr.State(""), gr.State(""), gr.State("")],
        outputs=[stats_display, map_display, checkpoint_table]
    )
    
    # Fetch route button click
    fetch_route_btn.click(
        fn=handle_ors_fetch_click,
        inputs=[start_pt, end_pt, ors_profile, ors_api_key],
        outputs=[stats_display, map_display, checkpoint_table]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    try:
        demo.launch(server_name="0.0.0.0", server_port=port)
    except OSError:
        print(f"[app] Port {port} is busy. Falling back to automatic port selection...")
        demo.launch(server_name="127.0.0.1")
