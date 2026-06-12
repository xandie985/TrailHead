import os
import time
import requests
import json
import base64
import threading
from PIL import Image

_model_lock = threading.Lock()

# Backend configuration via environment variable. Defaults to auto-detected or "mock"
try:
    import llama_cpp
    default_backend = "llama_cpp"
except ImportError:
    default_backend = "mock"
BACKEND = os.environ.get("BACKEND", default_backend).lower()

# Constants for Hugging Face Space model loading
MODEL_REPO = "bartowski/google_gemma-4-E2B-it-GGUF"
MODEL_FILE = "google_gemma-4-E2B-it-Q4_K_M.gguf"
LOCAL_MODEL_DIR = os.environ.get("MODEL_DIR", "./model")

_llama_model = None

def _download_gguf():
    """Download GGUF model from Hugging Face if not already present."""
    os.makedirs(LOCAL_MODEL_DIR, exist_ok=True)
    local_path = os.path.join(LOCAL_MODEL_DIR, MODEL_FILE)
    if os.path.exists(local_path):
        print(f"[llm.py] Model GGUF already exists at {local_path}")
        return local_path

    print(f"[llm.py] Downloading {MODEL_FILE} from HF repo {MODEL_REPO}...")
    try:
        from huggingface_hub import hf_hub_download
        downloaded_path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILE,
            local_dir=LOCAL_MODEL_DIR,
            local_dir_use_symlinks=False
        )
        print(f"[llm.py] Model downloaded successfully to {downloaded_path}")
        return downloaded_path
    except Exception as e:
        print(f"[llm.py] Error downloading model from Hugging Face: {e}")
        return None

def init_llama_cpp():
    """Lazy initialization of llama_cpp model."""
    global _llama_model
    if _llama_model is not None:
        return _llama_model

    try:
        from llama_cpp import Llama
    except ImportError:
        print("[llm.py] Warning: llama-cpp-python is not installed. Falling back to mock backend.")
        return None

    model_path = _download_gguf()
    if not model_path or not os.path.exists(model_path):
        print("[llm.py] Error: Model file not found. Cannot load llama_cpp.")
        return None

    print(f"[llm.py] Loading model into memory: {model_path}")
    num_threads = 1 if os.environ.get("SPACE_ID") else 4
    try:
        _llama_model = Llama(
            model_path=model_path,
            n_ctx=2048,
            n_threads=num_threads,
            verbose=False
        )
        print("[llm.py] llama_cpp model loaded successfully!")
        return _llama_model
    except Exception as e:
        print(f"[llm.py] Error loading llama_cpp: {e}")
        return None

# --- Whisper.cpp ASR (Speech-to-Text) ---
_whisper_model = None

def _init_whisper():
    """Lazy initialization of whisper.cpp model for offline ASR."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    
    try:
        from pywhispercpp.model import Model as WhisperModel
        print("[llm.py] Loading whisper.cpp 'tiny' model for ASR...")
        _whisper_model = WhisperModel(
            'tiny',
            n_threads=2 if not os.environ.get("SPACE_ID") else 1
        )
        print("[llm.py] whisper.cpp ASR model loaded successfully!")
        return _whisper_model
    except ImportError:
        print("[llm.py] pywhispercpp not installed. ASR will try transformers fallback.")
        return None
    except Exception as e:
        print(f"[llm.py] Error loading whisper.cpp ASR model: {e}")
        return None

# --- Hugging Face Inference API ASR fallback ---
_hf_client = None

def _init_hf_client():
    """Lazy initialization of Hugging Face InferenceClient for fallback ASR."""
    global _hf_client
    if _hf_client is not None:
        return _hf_client
    try:
        from huggingface_hub import InferenceClient
        # Automatically detects HF_TOKEN from Hugging Face Space environment
        _hf_client = InferenceClient()
        print("[llm.py] Hugging Face InferenceClient for ASR initialized successfully!")
        return _hf_client
    except ImportError:
        print("[llm.py] huggingface_hub not installed. ASR will use mock fallback.")
        return None
    except Exception as e:
        print(f"[llm.py] Error loading HF InferenceClient: {e}")
        return None

def transcribe_audio(audio_path, prompt=""):
    """
    Transcribe audio file to text using whisper.cpp (offline, lightweight).
    Falls back to Hugging Face Inference API or mock transcription if whisper.cpp is unavailable.
    """
    if not audio_path or not os.path.exists(audio_path):
        print("[llm.py] Audio file not found, using mock ASR.")
        return _mock_transcribe_audio(prompt)
    
    whisper = _init_whisper()
    if whisper is not None:
        temp_wav_path = None
        try:
            try:
                import miniaudio
                import wave
                print(f"[llm.py] Decoding and resampling audio to 16kHz mono WAV using miniaudio...")
                sound = miniaudio.decode_file(audio_path, nchannels=1, sample_rate=16000)
                
                # Save to temp WAV file
                temp_wav_path = audio_path + ".temp_16k.wav"
                with wave.open(temp_wav_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)  # 16-bit PCM
                    wav_file.setframerate(16000)
                    wav_file.writeframes(sound.samples)
                
                audio_path = temp_wav_path
                print(f"[llm.py] Resampled audio saved to: {audio_path}")
            except ImportError:
                print("[llm.py] miniaudio not installed. Passing audio file directly to whisper.cpp.")
            except Exception as e:
                print(f"[llm.py] miniaudio transcoding failed: {e}. Passing original file directly.")

            print(f"[llm.py] Transcribing audio: {audio_path}")
            segments = whisper.transcribe(audio_path)
            transcription = " ".join([seg.text.strip() for seg in segments]).strip()
            
            if temp_wav_path and os.path.exists(temp_wav_path):
                try: os.remove(temp_wav_path)
                except: pass
                
            if not transcription:
                print("[llm.py] Whisper returned empty transcription, trying HF API fallback.")
            else:
                print(f"[llm.py] ASR Transcription: \"{transcription}\"")
                return transcription
        except Exception as e:
            if temp_wav_path and os.path.exists(temp_wav_path):
                try: os.remove(temp_wav_path)
                except: pass
            print(f"[llm.py] Error during whisper.cpp transcription: {e}")

    # Fallback to Hugging Face Inference API ASR
    hf_client = _init_hf_client()
    if hf_client is not None:
        try:
            print(f"[llm.py] Transcribing audio using Hugging Face Inference API: {audio_path}")
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            result = hf_client.automatic_speech_recognition(
                audio_bytes,
                model="openai/whisper-large-v3-turbo"
            )
            
            # Extract transcription string
            if isinstance(result, dict):
                transcription = result.get("text", "").strip()
            else:
                transcription = getattr(result, "text", str(result)).strip()
                
            if transcription:
                print(f"[llm.py] ASR (HF API) Transcription: \"{transcription}\"")
                return transcription
        except Exception as e:
            print(f"[llm.py] Error during Hugging Face Inference API transcription: {e}")

    return _mock_transcribe_audio(prompt)

def _mock_transcribe_audio(prompt=""):
    """Mock ASR fallback when whisper.cpp is not available."""
    prompt_lower = str(prompt).lower() if prompt else ""
    if "first" in prompt_lower or "injury" in prompt_lower or "ems" in prompt_lower:
        return "How do I treat a sprained ankle on the trail?"
    elif "gear" in prompt_lower or "backpack" in prompt_lower:
        return "What gear list do I need for a 3-day high-altitude trek?"
    else:
        return "Am I on the correct route right now?"

# Keep backward-compatible alias
mock_transcribe_audio = _mock_transcribe_audio

def generate_mock(prompt, system="", image_path=None, audio_path=None, history=None):
    """Simulate streaming for the mock backend tailored for Trailhead."""
    response = ""
    
    # 0. Handle Voice Audio ASR
    if audio_path:
        transcription = transcribe_audio(audio_path, prompt)
        response += f"[🎙️ **Voice Journal Transcription:** \"{transcription}\"]\n\n"
        prompt = transcription
        
    prompt_lower = prompt.lower()
    
    # 0.5 Check if this is a Storyteller request (before other keyword matches)
    if "first-person adventure story of my trek" in prompt_lower or "storyteller" in system.lower() or "adventure story" in system.lower():
        import re
        
        # Parse stats
        total_dist_match = re.search(r"Total Distance: ([\d\.]+) km", prompt)
        ele_gain_match = re.search(r"Total Elevation Gain: ([\d\.]+) m", prompt)
        alt_range_match = re.search(r"Altitude Range: (.*?)\n", prompt)
        
        total_dist = total_dist_match.group(1) if total_dist_match else "3.49"
        ele_gain = ele_gain_match.group(1) if ele_gain_match else "120.0"
        alt_range = alt_range_match.group(1) if alt_range_match else "100m - 250m"
        
        # Parse voice logs
        voice_logs = []
        log_pattern = r"- Log #(\d+)\s+\((.*?)\)\s+at Km\s+([\d\.]+)\s+\(Alt:\s+([\d\.]+)m\):\s*\"(.*?)\""
        matches = re.findall(log_pattern, prompt, re.DOTALL)
        for num, timestamp, km, alt, transcript in matches:
            voice_logs.append({
                "num": num,
                "time": timestamp,
                "km": float(km),
                "alt": alt,
                "transcript": transcript.strip()
            })
            
        if not voice_logs:
            # Fallback line-by-line parsing
            lines = prompt.split("\n")
            current_log = None
            for line in lines:
                if "- Log #" in line:
                    try:
                        parts = line.split(" at Km ")
                        header_part = parts[0]
                        km_alt_part = parts[1]
                        num_time = header_part.replace("- Log #", "").strip()
                        num = num_time.split(" ")[0]
                        time_str = num_time.replace(num, "").strip("() ")
                        km = km_alt_part.split(" ")[0]
                        alt = km_alt_part.split("Alt: ")[1].split("m")[0]
                        current_log = {
                            "num": num,
                            "time": time_str,
                            "km": float(km),
                            "alt": alt,
                            "transcript": ""
                        }
                    except Exception:
                        current_log = None
                elif current_log and line.strip().startswith('"'):
                    current_log["transcript"] = line.strip().strip('"')
                    voice_logs.append(current_log)
                    current_log = None

        # Parse amenities
        amenities = []
        amenity_pattern = r"- (.*?)\s+\((.*?)\)\s+at approx\.\s+Km\s+([\d\.]+)\s+\(located\s+([\d\.]+) meters off the trail\)"
        amenity_matches = re.findall(amenity_pattern, prompt)
        for name, type_str, km, offset in amenity_matches:
            amenities.append({
                "name": name,
                "type": type_str,
                "km": float(km),
                "offset": offset
            })
            
        if not amenities:
            lines = prompt.split("\n")
            for line in lines:
                if "meters off the trail" in line:
                    try:
                        clean_line = line.strip().lstrip("- ")
                        name_part = clean_line.split(" (")[0]
                        rest = clean_line.split(" (")[1]
                        type_part = rest.split(") at approx. Km ")[0]
                        km_offset = rest.split(") at approx. Km ")[1]
                        km = km_offset.split(" (located ")[0]
                        offset = km_offset.split(" (located ")[1].split(" meters off the trail")[0]
                        amenities.append({
                            "name": name_part,
                            "type": type_part,
                            "km": float(km),
                            "offset": offset
                        })
                    except Exception:
                        pass
                        
        voice_logs = sorted(voice_logs, key=lambda x: x["km"])
        is_technical = "technical" in system.lower()
        
        if is_technical:
            response += "🧭 **Trailhead Technical Trek Report**\n"
            response += "*Compiled by Trailhead AI Storyteller*\n\n"
            response += "### 📊 Trek Telemetry\n"
            response += f"- **Total Distance:** {total_dist} km\n"
            response += f"- **Total Elevation Gain:** {ele_gain} m\n"
            response += f"- **Altitude Profile:** {alt_range}\n\n"
            
            response += "### 🎒 Amenities & Points of Interest\n"
            if amenities:
                for am in amenities:
                    response += f"- **{am['name']}** ({am['type']}) at approx. Km {am['km']:.2f} ({am['offset']}m off-trail)\n"
            else:
                response += "- No significant amenities detected along the route.\n"
                
            response += "\n### 🎙️ Geotagged Voice Logs\n"
            if voice_logs:
                for log in voice_logs:
                    response += f"- **Km {log['km']:.2f}** (Alt: {log['alt']}m) | *{log['time']}*:\n  > \"{log['transcript']}\"\n"
            else:
                response += "- No voice logs recorded.\n"
        else:
            response += "🌲 **MY WILDERNESS EXPEDITION REPORT** 🌲\n"
            response += "*Powered by Trailhead Tactical Trail Computer*\n\n"
            response += f"What an absolute journey! 🏔️ Just finished an intense trek covering **{total_dist} km** with **{ele_gain} m** of vertical climb! Here is the live play-by-play of how it went down:\n\n"
            
            milestones = []
            for am in amenities:
                milestones.append(("amenity", am["km"], am))
            for log in voice_logs:
                milestones.append(("log", log["km"], log))
            milestones = sorted(milestones, key=lambda x: x[1])
            
            for m_type, km, data in milestones:
                if m_type == "amenity":
                    response += f"📍 **Km {km:.2f} | Amenity Spot** 🎒\n"
                    response += f"Encountered **{data['name']}** ({data['type']}) situated just {data['offset']}m off the path. A crucial waypoint for resource management!\n\n"
                elif m_type == "log":
                    transcript_lower = data['transcript'].lower()
                    icon = "🎙️"
                    title = "Hiker Log"
                    if "water" in transcript_lower:
                        icon = "💧"
                        title = "Water Source & Hydration Check"
                    elif "view" in transcript_lower or "point of view" in transcript_lower:
                        icon = "👁️"
                        title = "Scenic Viewpoint Reflection"
                    elif "finish" in transcript_lower or "complete" in transcript_lower:
                        icon = "🏁"
                        title = "Trek Completion Signoff"
                        
                    response += f"{icon} **Km {km:.2f} | {title}** 📝\n"
                    response += f"Recorded voice entry at {data['alt']}m altitude:\n"
                    response += f"> *\"{data['transcript']}\"*\n\n"
                    
            response += "🏁 **Trek Complete!**\n"
            response += "Every step was worth it. Pushed my limits, managed my resources, and conquered the route. 🥾\n\n"
            response += "---\n"
            response += "#HikingAdventure #BackcountryExploration #TrailheadAI #WildernessLiving #TrekTelemetry #OptOutside\n"

        for word in response.split(" "):
            yield word + " "
            time.sleep(0.02)
        return
    
    # 1. Checkpoint / Narration Queries
    if "checkpoint" in prompt_lower or "narration" in prompt_lower or "current position" in prompt_lower:
        response += (
            "🧭 **Trailhead Contextual Guide:**\n"
            "You are approaching **Km 2.0 Checkpoint**. The terrain ahead is moderately steep with an elevation gain of ~45m over the next kilometer.\n\n"
            "⚠️ **Advisory:** Watch your water supply; the next reliable spring is at Km 3.5. Ensure you reach the shelter before 17:00 as temperatures drop rapidly to 5°C."
        )
    # 2. Gear Checklist Queries
    elif "gear" in prompt_lower or "checklist" in prompt_lower or "pack" in prompt_lower:
        response += (
            "🎒 **Suggested Gear Checklist (Pace- & Altitude-Adjusted):**\n"
            "Based on your 1-day trek details, here is a highly tailored packing guide:\n\n"
            "- **Navigation:** Offline map download, compass, backup physical map.\n"
            "- **Hydration:** 2.5L water capacity + iodine tablets (water sources tagged at Km 3.5).\n"
            "- **Apparel:** Windbreaker/rain shell, moisture-wicking base layers, wool socks.\n"
            "- **Safety:** First-aid kit (with blister care), whistle, multi-tool, space blanket.\n"
            "- **Nutrition:** 2500 kcal high-density trail snacks (nuts, bars, jerky)."
        )
    # 3. Wilderness First-Aid / RAG Queries
    elif "first-aid" in prompt_lower or "first aid" in prompt_lower or "medical" in prompt_lower or "injury" in prompt_lower or "sprain" in prompt_lower or "ams" in prompt_lower or "sick" in prompt_lower:
        response += (
            "🩹 **Wilderness First-Aid Protocol (CITED):**\n"
            "For managing a **Sprained Ankle / Strain** in the backcountry, use the **R.I.C.E.** protocol:\n\n"
            "1. **Rest:** Stop hiking immediately. Remove weight from the injured limb.\n"
            "2. **Ice / Cold:** Apply a cold pack or submerge in cold trail stream for 20 mins to reduce swelling.\n"
            "3. **Compression:** Wrap firmly with an elastic bandage (do not restrict circulation).\n"
            "4. **Elevation:** Elevate the ankle above the heart level whenever resting.\n\n"
            "📖 *CITED SOURCE: Wilderness Medicine Field Guide, Section 7: Musculoskeletal Injuries.*"
        )
    # 4. Off-Route / Deviation Queries
    elif "route" in prompt_lower or "off-route" in prompt_lower or "deviate" in prompt_lower or "map" in prompt_lower:
        response += (
            "⚠️ **Navigation Warning:**\n"
            "You have deviated from the planned polyline by **42 meters**. \n\n"
            "**Action:** Look for physical trail markers or backtrack to your last known coordinate. Do not proceed off-trail through dense underbrush."
        )
    # 5. Default Response
    else:
        response += (
            "🌲 **Welcome to Trailhead Navigation Assistant!**\n"
            "I am your offline-first trail computer. I can analyze your uploaded GPX files, estimate Naismith trekking durations, auto-partition checkpoints, and offer grounded AI advice.\n\n"
            "Ask me about gear checklists, route narration, deviation warnings, or wilderness first-aid emergency protocols."
        )
        
    for word in response.split(" "):
        yield word + " "
        time.sleep(0.03)

def generate_llama_cpp(prompt, system="", image_path=None, audio_path=None, history=None):
    """Query the in-process llama-cpp-python model with a timeout fallback to mock."""
    if getattr(generate_llama_cpp, "disabled", False):
        print("[llm.py] llama_cpp is disabled (too slow or failed). Using mock backend.")
        for chunk in generate_mock(prompt, system, image_path, audio_path, history):
            yield chunk
        return

    acquired = _model_lock.acquire(blocking=True)
    if not acquired:
        print("[llm.py] Could not acquire model lock. Falling back to mock.")
        for chunk in generate_mock(prompt, system, image_path, audio_path, history):
            yield chunk
        return

    try:
        start_time = time.time()
        model = None
        try:
            model = init_llama_cpp()
        except Exception as e:
            print(f"[llm.py] Exception during init_llama_cpp: {e}")
            
        if model is None:
            print("[llm.py] Fallback to mock backend.")
            for chunk in generate_mock(prompt, system, image_path, audio_path, history):
                yield chunk
            return

        init_duration = time.time() - start_time
        if init_duration > 35.0:
            print(f"[llm.py] Warning: Model loading took {init_duration:.2f}s (exceeded 35s limit). Disabling llama_cpp and falling back to mock backend.")
            generate_llama_cpp.disabled = True
            for chunk in generate_mock(prompt, system, image_path, audio_path, history):
                yield chunk
            return

        voice_prefix = ""
        if audio_path:
            transcription = transcribe_audio(audio_path, prompt)
            voice_prefix = f"[🎙️ **ASR Transcribed:** \"{transcription}\"]\n\n"
            prompt = f"The hiker asked by voice: '{transcription}'. Respond directly to this query."

        if image_path:
            prompt = f"[📸 Image uploaded] {prompt}"

        formatted_prompt = f"<|im_start|>system\n{system}<|im_end|>\n"
        if history:
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                formatted_prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        formatted_prompt += f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        print(f"\n--- [llama.cpp INPUT PROMPT] ---\n{formatted_prompt}\n--------------------------------")
        print("--- [llama.cpp STREAMING RESPONSE] ---")
        try:
            response = model(
                formatted_prompt,
                max_tokens=512,
                temperature=0.3,
                top_p=0.9,
                stream=True
            )
            
            first_token_timeout = 30.0
            response_iter = iter(response)
            
            first_chunk_start = time.time()
            try:
                first_chunk = next(response_iter)
            except StopIteration:
                first_chunk = None
                
            prefill_duration = time.time() - first_chunk_start
            if prefill_duration > first_token_timeout:
                print(f"[llm.py] Prompt evaluation took {prefill_duration:.2f}s (exceeded {first_token_timeout}s limit). Disabling llama_cpp and falling back to mock.")
                generate_llama_cpp.disabled = True
                for chunk in generate_mock(prompt, system, image_path, audio_path, history):
                    yield chunk
                return

            if voice_prefix:
                yield voice_prefix
                
            if first_chunk:
                text = first_chunk['choices'][0]['text']
                cleaned = text.replace("<|im_end|>", "")
                print(cleaned, end="", flush=True)
                yield cleaned

            for chunk in response_iter:
                text = chunk['choices'][0]['text']
                cleaned = text.replace("<|im_end|>", "")
                print(cleaned, end="", flush=True)
                yield cleaned
            print("\n--------------------------------------")
        except Exception as e:
            print(f"[llm.py] Error running llama.cpp: {e}. Falling back to mock.")
            for chunk in generate_mock(prompt, system, image_path, audio_path, history):
                yield chunk
    finally:
        _model_lock.release()

def generate(prompt, system="", image_path=None, audio_path=None, history=None, stream=True):
    """Entry point for LLM generation supporting text, image, and voice inputs."""
    print(f"[llm.py] Using backend: {BACKEND}")
    if BACKEND == "llama_cpp":
        generator = generate_llama_cpp(prompt, system, image_path, audio_path, history)
    else: # mock
        generator = generate_mock(prompt, system, image_path, audio_path, history)
        
    if stream:
        return generator
    else:
        res = ""
        for chunk in generator:
            res += chunk
        return res
