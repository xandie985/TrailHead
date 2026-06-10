import os
import math
import json
import requests
import gpxpy

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on the Earth in meters."""
    R = 6371000.0  # Radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def fetch_elevations_open_meteo(coords):
    """
    Fetch elevation coordinates in batches of 100 from the Open-Meteo elevation API.
    Returns a list of floats representing elevation in meters.
    """
    elevations = []
    batch_size = 100
    for i in range(0, len(coords), batch_size):
        batch = coords[i:i+batch_size]
        lats = ",".join(f"{c[0]:.6f}" for c in batch)
        lons = ",".join(f"{c[1]:.6f}" for c in batch)
        url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
        
        try:
            print(f"[gpx_parser] Fetching elevation batch {i//batch_size + 1}...")
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                batch_elevations = data.get("elevation", [])
                if len(batch_elevations) == len(batch):
                    elevations.extend(batch_elevations)
                else:
                    print("[gpx_parser] Elevation list size mismatch. Filling with 0.0")
                    elevations.extend([0.0] * len(batch))
            else:
                print(f"[gpx_parser] API error {response.status_code}. Using 0.0 for batch.")
                elevations.extend([0.0] * len(batch))
        except Exception as e:
            print(f"[gpx_parser] Network/parsing exception: {e}. Using 0.0 for batch.")
            elevations.extend([0.0] * len(batch))
            
    return elevations

def smooth_elevations(elevations, window_size=5):
    """Apply a simple moving average window to smooth out elevation profile data."""
    if not elevations:
        return []
    smoothed = []
    for i in range(len(elevations)):
        start = max(0, i - window_size // 2)
        end = min(len(elevations), i + window_size // 2 + 1)
        window = elevations[start:end]
        smoothed.append(sum(window) / len(window))
    return smoothed

def calculate_elevation_gain_loss(elevations, threshold=2.0):
    """
    Calculate cumulative elevation gain and loss in meters.
    Filters out noise using a threshold value (minimum elevation delta).
    """
    gain = 0.0
    loss = 0.0
    if len(elevations) < 2:
        return gain, loss
        
    last_val = elevations[0]
    for val in elevations[1:]:
        diff = val - last_val
        if abs(diff) >= threshold:
            if diff > 0:
                gain += diff
            else:
                loss += abs(diff)
            last_val = val
    return gain, loss

def fetch_overpass_pois(min_lat, min_lon, max_lat, max_lon):
    """
    Fetch POIs (water, spring, huts, camps, shelter) from Overpass API in the bounding box.
    """
    url = "https://overpass-api.de/api/interpreter"
    query = f"""
    [out:json][timeout:20];
    (
      node["amenity"="drinking_water"]({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f});
      node["natural"="spring"]({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f});
      node["amenity"="water_point"]({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f});
      node["tourism"="alpine_hut"]({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f});
      node["tourism"="camp_site"]({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f});
      node["amenity"="shelter"]({min_lat:.5f},{min_lon:.5f},{max_lat:.5f},{max_lon:.5f});
    );
    out body;
    """
    headers = {
        'User-Agent': 'TrailheadTrekPlanner/1.0 (skushwaha@hckthn.com)'
    }
    try:
        print(f"[gpx_parser] Querying Overpass API for POIs in bbox: [{min_lat:.5f}, {min_lon:.5f}, {max_lat:.5f}, {max_lon:.5f}]...")
        response = requests.post(url, data={'data': query}, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            elements = data.get("elements", [])
            pois = []
            for el in elements:
                lat = el.get("lat")
                lon = el.get("lon")
                tags = el.get("tags", {})
                
                # Determine type
                poi_type = "unknown"
                if "amenity" in tags:
                    poi_type = tags["amenity"]
                elif "natural" in tags:
                    poi_type = tags["natural"]
                elif "tourism" in tags:
                    poi_type = tags["tourism"]
                    
                name = tags.get("name", tags.get("water", poi_type.replace("_", " ").title()))
                pois.append({
                    "id": el.get("id"),
                    "lat": lat,
                    "lon": lon,
                    "type": poi_type,
                    "name": name
                })
            print(f"[gpx_parser] Overpass returned {len(pois)} raw POIs.")
            return pois
        else:
            print(f"[gpx_parser] Overpass API returned status code {response.status_code}: {response.text}")
            return []
    except Exception as e:
        print(f"[gpx_parser] Overpass query failed: {e}")
        return []

def filter_pois_near_track(points, pois, buffer_meters=150.0):
    """
    Filter POIs that are within buffer_meters of the track.
    Returns list of POIs with distance and closest track point index.
    """
    enhanced_pois = []
    if not points or not pois:
        return enhanced_pois
        
    for poi in pois:
        min_dist = float('inf')
        closest_idx = -1
        
        for idx, pt in enumerate(points):
            d = haversine(poi["lat"], poi["lon"], pt["lat"], pt["lon"])
            if d < min_dist:
                min_dist = d
                closest_idx = idx
                
        if min_dist <= buffer_meters:
            enhanced_pois.append({
                "id": poi.get("id", 0),
                "lat": poi["lat"],
                "lon": poi["lon"],
                "type": poi["type"],
                "name": poi["name"],
                "distance": round(min_dist, 1),
                "track_index": closest_idx
            })
            
    print(f"[gpx_parser] Filtered {len(enhanced_pois)} POIs within {buffer_meters}m buffer.")
    return enhanced_pois

def extract_pois_from_gpx(gpx):
    """
    Extract POIs from GPX waypoints and track point extensions.
    Returns a list of POI dictionaries.
    """
    pois = []
    # 1. Parse from waypoints
    for wpt in gpx.waypoints:
        desc = wpt.description or ""
        poi_type = "unknown"
        if "Type: " in desc:
            parts = desc.split(",")
            poi_type = parts[0].replace("Type: ", "").strip()
        elif wpt.name:
            # guess type from name/attributes
            name_l = wpt.name.lower()
            if "water" in name_l or "spring" in name_l or "fountain" in name_l:
                poi_type = "drinking_water"
            elif "camp" in name_l:
                poi_type = "camp_site"
            elif "hut" in name_l or "refuge" in name_l:
                poi_type = "alpine_hut"
            elif "shelter" in name_l:
                poi_type = "shelter"
                
        pois.append({
            "lat": wpt.latitude,
            "lon": wpt.longitude,
            "name": wpt.name or "Waypoint",
            "type": poi_type,
            "distance": 0.0
        })
        
    # 2. Parse from track point extensions
    idx = 0
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                if pt.extensions:
                    for ext in pt.extensions:
                        tag_name = ext.tag if hasattr(ext, 'tag') else ''
                        if 'poi' in tag_name:
                            poi_type = ext.attrib.get('type', 'unknown')
                            poi_name = ext.attrib.get('name', 'Waypoint')
                            try:
                                dist = float(ext.attrib.get('distance', 0.0))
                            except ValueError:
                                dist = 0.0
                            pois.append({
                                "lat": pt.latitude,
                                "lon": pt.longitude,
                                "name": poi_name,
                                "type": poi_type,
                                "distance": dist,
                                "track_index": idx
                            })
                idx += 1
    return pois

def save_enhanced_gpx(original_gpx_path, output_gpx_path, pois):
    """
    Save enhanced GPX file with POIs loaded as waypoints and extensions.
    """
    with open(original_gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
        
    # Overwrite waypoints
    gpx.waypoints = []
    for poi in pois:
        wpt = gpxpy.gpx.GPXWaypoint(latitude=poi['lat'], longitude=poi['lon'], name=poi['name'])
        wpt.description = f"Type: {poi['type']}, Distance from track: {poi['distance']:.1f}m"
        gpx.waypoints.append(wpt)
        
    # Add extensions to trackpoints
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            points.extend(segment.points)
            
    import xml.etree.ElementTree as ET
    for poi in pois:
        idx = poi.get('track_index')
        if idx is not None and 0 <= idx < len(points):
            pt = points[idx]
            # Create sub-element under extensions
            poi_el = ET.Element('poi', type=poi['type'], name=poi['name'], distance=f"{poi['distance']:.1f}")
            pt.extensions.append(poi_el)
            
    with open(output_gpx_path, "w", encoding="utf-8") as f:
        f.write(gpx.to_xml())
    print(f"[gpx_parser] Saved enhanced GPX with {len(pois)} POIs to {output_gpx_path}")

def parse_gpx_file(file_path, cache_dir="./temp", buffer_meters=150.0):
    """
    Parse a GPX file, fetch missing elevations, smooth the profile,
    and compute trek statistics. Caches results locally to allow offline usage.
    """
    # Create cache directory if needed
    os.makedirs(cache_dir, exist_ok=True)
    
    # Check cache first
    file_name = os.path.basename(file_path)
    cache_path = os.path.join(cache_dir, f"{file_name}.cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                print(f"[gpx_parser] Loading cached GPX data from {cache_path}")
                return json.load(f)
        except Exception as e:
            print(f"[gpx_parser] Cache read error: {e}, parsing raw file...")

    print(f"[gpx_parser] Parsing raw GPX file: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)
        
    # Extract track points
    points_raw = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points_raw.append({
                    "lat": pt.latitude,
                    "lon": pt.longitude,
                    "ele": pt.elevation
                })
                
    # If GPX had no track points, look in waypoints or route points
    if not points_raw:
        for route in gpx.routes:
            for pt in route.points:
                points_raw.append({
                    "lat": pt.latitude,
                    "lon": pt.longitude,
                    "ele": pt.elevation
                })
                
    # Still empty? Check waypoints
    if not points_raw and gpx.waypoints:
        for wpt in gpx.waypoints:
            points_raw.append({
                "lat": wpt.latitude,
                "lon": wpt.longitude,
                "ele": wpt.elevation
            })
            
    if not points_raw:
        raise ValueError("No trackpoints, routepoints, or waypoints found in GPX file.")
        
    # Check if elevations are missing (all None or 0.0)
    has_elevation = any(pt["ele"] is not None for pt in points_raw)
    
    if not has_elevation:
        print("[gpx_parser] GPX has no elevation data. Fetching from Open-Meteo elevation API...")
        coords = [(pt["lat"], pt["lon"]) for pt in points_raw]
        elevations = fetch_elevations_open_meteo(coords)
        for i, ele in enumerate(elevations):
            points_raw[i]["ele"] = ele
    else:
        # Fill in any scattered missing elevations
        for pt in points_raw:
            if pt["ele"] is None:
                pt["ele"] = 0.0
                
    # Smooth elevations
    raw_elevations = [pt["ele"] for pt in points_raw]
    smoothed_eles = smooth_elevations(raw_elevations)
    for i, ele in enumerate(smoothed_eles):
        points_raw[i]["ele"] = ele
        
    # Calculate cumulative distances (in meters) and build final points list
    points_data = []
    cum_dist = 0.0
    
    points_data.append({
        "lat": points_raw[0]["lat"],
        "lon": points_raw[0]["lon"],
        "ele": points_raw[0]["ele"],
        "cum_dist": 0.0
    })
    
    for i in range(1, len(points_raw)):
        p1 = points_raw[i-1]
        p2 = points_raw[i]
        d = haversine(p1["lat"], p1["lon"], p2["lat"], p2["lon"])
        cum_dist += d
        points_data.append({
            "lat": p2["lat"],
            "lon": p2["lon"],
            "ele": p2["ele"],
            "cum_dist": cum_dist
        })
        
    # Calculate statistics
    total_distance_m = cum_dist
    total_distance_km = total_distance_m / 1000.0
    
    gain, loss = calculate_elevation_gain_loss(smoothed_eles)
    
    min_ele = min(smoothed_eles) if smoothed_eles else 0.0
    max_ele = max(smoothed_eles) if smoothed_eles else 0.0
    
    # Naismith's Rule: 5 km/h base speed + 1 hour per 600m ascent
    naismith_hours = (total_distance_km / 5.0) + (gain / 600.0)
    estimated_days = max(1.0, naismith_hours / 8.0)
    
    # Pre-parse waypoints if they exist in GPX
    waypoints = []
    for wpt in gpx.waypoints:
        waypoints.append({
            "name": wpt.name or "Waypoint",
            "lat": wpt.latitude,
            "lon": wpt.longitude,
            "ele": wpt.elevation or 0.0,
            "desc": wpt.description or ""
        })
        
    # Generate checkpoints
    checkpoints = []
    if waypoints:
        for wpt in waypoints:
            min_d = float('inf')
            closest_pt = points_data[0]
            for pt in points_data:
                d = haversine(wpt["lat"], wpt["lon"], pt["lat"], pt["lon"])
                if d < min_d:
                    min_d = d
                    closest_pt = pt
            checkpoints.append({
                "name": wpt["name"],
                "lat": wpt["lat"],
                "lon": wpt["lon"],
                "ele": closest_pt["ele"],
                "cum_dist": closest_pt["cum_dist"] / 1000.0
            })
        checkpoints.sort(key=lambda c: c["cum_dist"])
    else:
        checkpoints = generate_checkpoints(points_data, interval_meters=1000.0)
        
    # Parse existing POIs from GPX
    pois = extract_pois_from_gpx(gpx)
    
    # If no POIs exist (like raw user upload), fetch from Overpass API (planning mode online)
    if not pois:
        lats = [pt["lat"] for pt in points_data]
        lons = [pt["lon"] for pt in points_data]
        min_lat, max_lat = min(lats) - 0.002, max(lats) + 0.002
        min_lon, max_lon = min(lons) - 0.002, max(lons) + 0.002
        
        raw_pois = fetch_overpass_pois(min_lat, min_lon, max_lat, max_lon)
        pois = filter_pois_near_track(points_data, raw_pois, buffer_meters)
        
    result = {
        "file_name": file_name,
        "total_distance_km": round(total_distance_km, 2),
        "elevation_gain_m": round(gain, 1),
        "elevation_loss_m": round(loss, 1),
        "min_elevation_m": round(min_ele, 1),
        "max_elevation_m": round(max_ele, 1),
        "estimated_days": round(estimated_days, 1),
        "naismith_hours": round(naismith_hours, 1),
        "points": points_data,
        "checkpoints": checkpoints,
        "pois": pois
    }
    
    # Save cache
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            print(f"[gpx_parser] Saved parsed GPX data cache to {cache_path}")
    except Exception as e:
        print(f"[gpx_parser] Cache write error: {e}")
        
    return result

def generate_checkpoints(points_data, interval_meters=1000.0):
    """Helper to partition track into regular distance checkpoints."""
    if not points_data:
        return []
        
    checkpoints = []
    start_pt = points_data[0]
    checkpoints.append({
        "name": "Start",
        "lat": start_pt["lat"],
        "lon": start_pt["lon"],
        "ele": start_pt["ele"],
        "cum_dist": 0.0
    })
    
    total_dist = points_data[-1]["cum_dist"]
    next_checkpoint_dist = interval_meters
    pt_idx = 1
    
    while next_checkpoint_dist < total_dist:
        while pt_idx < len(points_data) and points_data[pt_idx]["cum_dist"] < next_checkpoint_dist:
            pt_idx += 1
            
        if pt_idx >= len(points_data):
            break
            
        p1 = points_data[pt_idx - 1]
        p2 = points_data[pt_idx]
        
        if abs(p1["cum_dist"] - next_checkpoint_dist) < abs(p2["cum_dist"] - next_checkpoint_dist):
            chosen = p1
        else:
            chosen = p2
            
        checkpoints.append({
            "name": f"Km {next_checkpoint_dist / 1000.0:.1f}",
            "lat": chosen["lat"],
            "lon": chosen["lon"],
            "ele": chosen["ele"],
            "cum_dist": round(chosen["cum_dist"] / 1000.0, 2)
        })
        
        next_checkpoint_dist += interval_meters
        
    end_pt = points_data[-1]
    if len(checkpoints) == 1 or (total_dist / 1000.0 - checkpoints[-1]["cum_dist"]) > 0.1:
        checkpoints.append({
            "name": "End",
            "lat": end_pt["lat"],
            "lon": end_pt["lon"],
            "ele": end_pt["ele"],
            "cum_dist": round(total_dist / 1000.0, 2)
        })
        
    return checkpoints
