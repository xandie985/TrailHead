import os
import json
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GUIDES_FILE = os.path.join(DATA_DIR, "first_aid_guide.json")

def retrieve_first_aid(query_text):
    """
    Search first_aid_guide.json for sections relevant to the query.
    Returns (markdown_grounding_text, source_list) or (None, [])
    """
    if not os.path.exists(GUIDES_FILE):
        print(f"[rag.py] Guide file not found at {GUIDES_FILE}")
        return None, []

    try:
        with open(GUIDES_FILE, "r", encoding="utf-8") as f:
            guides = json.load(f)
    except Exception as e:
        print(f"[rag.py] Error reading guides: {e}")
        return None, []

    query_text_lower = query_text.lower()
    query_words = set(re.findall(r"\w+", query_text_lower))
    
    matches = []
    
    # Pre-defined keyword map for high relevance scores
    keywords_map = {
        "section 1": ["bleed", "wound", "cut", "blood", "bandage", "tourniquet", "injury"],
        "section 2": ["cold", "hypothermia", "freeze", "frostbite", "shiver", "rewarm"],
        "section 3": ["heat", "exhaustion", "dehydration", "stroke", "hot", "sunstroke", "sweat"],
        "section 4": ["altitude", "ams", "hape", "hace", "headache", "dizzy", "mountain sickness", "nausea", "pulmonary", "cerebral"],
        "section 5": ["sprain", "fracture", "break", "splint", "ankle", "joint", "bone", "rice", "strain"]
    }
    
    for guide in guides:
        score = 0
        section = guide.get("section", "")
        text = guide.get("text", "")
        section_lower = section.lower()
        
        # 1. Map based matching
        for key, words in keywords_map.items():
            if key in section_lower:
                for w in words:
                    if w in query_text_lower:
                        score += 3
                        
        # 2. General overlap matching
        combined_text = (section + " " + text).lower()
        for word in query_words:
            if len(word) > 2 and word in combined_text:
                score += 1
                
        if score > 0:
            matches.append((score, guide))
            
    # Sort matches by score descending
    matches.sort(key=lambda x: x[0], reverse=True)
    
    if not matches:
        return None, []
        
    grounding_parts = []
    sources = []
    
    # Take top matching guide to ground the model response
    for idx, (score, guide) in enumerate(matches[:1]):
        sec = guide["section"]
        txt = guide["text"]
        
        grounding_parts.append(
            f"### {sec}\n"
            f"{txt}\n"
        )
        sources.append(sec)
        
    grounding_text = "\n---\n".join(grounding_parts)
    return grounding_text, sources
