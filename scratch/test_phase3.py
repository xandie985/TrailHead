import os
import sys
import json
import sqlite3

# Ensure src directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.database as db
import src.gpx_parser as gpx_parser
from app import generate_elevation_plot, handle_generate_story

def run_tests():
    print("=== STARTING PHASE 3 FUNCTIONAL TESTS ===")
    
    # 1. Test SQLite Database Operations
    print("\n--- Test 1: SQLite Database Operations ---")
    db.init_db()
    
    # Clear tables to start clean
    db.clear_journal_logs()
    db.clear_custom_waypoints()
    
    # Insert custom waypoint
    db.add_custom_waypoint(46.0734, 11.1717, 350.0, "drinking_water", "Test Water Source", "Fresh cold spring")
    wps = db.get_custom_waypoints()
    assert len(wps) == 1, "Waypoint count should be 1"
    assert wps[0]["name"] == "Test Water Source", "Waypoint name mismatch"
    assert wps[0]["type"] == "drinking_water", "Waypoint type mismatch"
    print("✅ Custom waypoint read/write verified successfully.")
    
    # Insert journal log
    db.add_journal_entry(46.0735, 11.1718, 352.0, 0.5, "Hiked up the trail, found fresh water at custom tagged point.")
    logs = db.get_journal_entries()
    assert len(logs) == 1, "Journal logs count should be 1"
    assert logs[0]["transcript"] == "Hiked up the trail, found fresh water at custom tagged point.", "Transcript mismatch"
    print("✅ Voice log entry read/write verified successfully.")
    
    # 2. Test Tile Coordinate Conversion
    print("\n--- Test 2: OSM Tile Conversion Maths ---")
    lat, lon, zoom = 46.0734974, 11.1717214, 13
    x, y = gpx_parser.deg2num(lat, lon, zoom)
    print(f"Coordinates {lat}, {lon} at Zoom {zoom} -> Tile X: {x}, Y: {y}")
    assert x == 4350, f"Expected X = 4350, got {x}"
    assert y == 2911, f"Expected Y = 2911, got {y}"
    print("✅ OSM tile maths verified successfully (match Trento coordinates Z13).")
    
    # 3. Test Plotly Elevation Chart Generation
    print("\n--- Test 3: Plotly Elevation Chart Generation ---")
    mock_points = [
        {"lat": 46.073, "lon": 11.171, "ele": 300.0, "cum_dist": 0.0},
        {"lat": 46.074, "lon": 11.172, "ele": 320.0, "cum_dist": 150.0},
        {"lat": 46.075, "lon": 11.173, "ele": 350.0, "cum_dist": 300.0},
        {"lat": 46.076, "lon": 11.174, "ele": 380.0, "cum_dist": 450.0}
    ]
    fig = generate_elevation_plot(mock_points, current_idx=2)
    assert fig is not None, "Plotly figure should not be None"
    # Inspect plotly layout
    assert fig.layout.title.text == "🏔️ ELEVATION PROFILE", "Title mismatch"
    print("✅ Plotly elevation profile chart generated successfully.")
    
    # 4. Test Post-Trek AI Storyteller prompt compile & fallback generation
    print("\n--- Test 4: AI Storyteller Narrative ---")
    mock_route = {
        "total_distance_km": 0.45,
        "elevation_gain_m": 80.0,
        "min_elevation_m": 300.0,
        "max_elevation_m": 380.0
    }
    story, file_path = handle_generate_story(mock_route)
    assert story is not None, "Generated story should not be None"
    assert "Hiker" in story or "Trail" in story or "adventure" in story, "Story content is too generic"
    assert os.path.exists(file_path), f"Story file should be saved at {file_path}"
    print(f"✅ AI Storyteller executed successfully. Story saved to {file_path}")
    print(f"Story teaser:\n{story[:150]}...")
    
    print("\n=== ALL PHASE 3 FUNCTIONAL TESTS PASSED SUCCESSFULLY! ===")
    
if __name__ == "__main__":
    run_tests()
