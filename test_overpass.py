import os
import sys
from src.gpx_parser import parse_gpx_file, fetch_overpass_pois, filter_pois_near_track

def run_test():
    gpx_path = r"C:\Users\skushwaha\Documents\hckthn\TrailHead\Routes\track_5-14724236830.gpx"
    print(f"--- Testing GPX parsing and Overpass integration on: {gpx_path} ---")
    
    if not os.path.exists(gpx_path):
        print(f"Error: GPX file not found at {gpx_path}")
        sys.exit(1)
        
    # 1. Parse GPX file and see what's loaded
    print("\n1. Running parse_gpx_file...")
    result = parse_gpx_file(gpx_path)
    
    print(f"File Name: {result['file_name']}")
    print(f"Total Distance: {result['total_distance_km']} km")
    print(f"Elevation Gain: {result['elevation_gain_m']} m")
    print(f"Elevation Loss: {result['elevation_loss_m']} m")
    print(f"Min/Max Elevation: {result['min_elevation_m']}m / {result['max_elevation_m']}m")
    print(f"Number of points: {len(result['points'])}")
    print(f"Number of checkpoints: {len(result['checkpoints'])}")
    
    pois = result.get("pois", [])
    print(f"Number of POIs parsed/fetched: {len(pois)}")
    for i, poi in enumerate(pois[:10]):
        print(f"  [{i+1}] Name: {poi['name']}, Type: {poi['type']}, Distance from route: {poi.get('distance', 0.0)}m, Lat/Lon: {poi['lat']}, {poi['lon']}")
        
    # 2. Test live Overpass API query directly using the bounding box of the track
    print("\n2. Direct Test of Overpass API Query...")
    points_data = result["points"]
    lats = [pt["lat"] for pt in points_data]
    lons = [pt["lon"] for pt in points_data]
    min_lat, max_lat = min(lats) - 0.002, max(lats) + 0.002
    min_lon, max_lon = min(lons) - 0.002, max(lons) + 0.002
    
    print(f"Bounding box: [{min_lat:.5f}, {min_lon:.5f}, {max_lat:.5f}, {max_lon:.5f}]")
    raw_pois = fetch_overpass_pois(min_lat, min_lon, max_lat, max_lon)
    print(f"Overpass returned {len(raw_pois)} raw POIs.")
    
    filtered_pois = filter_pois_near_track(points_data, raw_pois, buffer_meters=150.0)
    print(f"Filtered {len(filtered_pois)} POIs within 150m buffer.")
    for i, poi in enumerate(filtered_pois[:10]):
         print(f"  [{i+1}] Name: {poi['name']}, Type: {poi['type']}, Buffer Dist: {poi['distance']}m")

if __name__ == "__main__":
    run_test()
