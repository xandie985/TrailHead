import os
from llama_cpp import Llama

model_path = "./model/gemma-1.1-2b-it-Q4_K_M.gguf"
model = Llama(
    model_path=model_path,
    n_ctx=2048,
    verbose=False
)

system_prompt = (
    "You are Trailhead Guide, a wilderness first-aid advisor.\n"
    "Answer the query using ONLY the provided guide context.\n"
    "Context:\n### Section 5: Musculoskeletal Injuries (Sprains & Strains)\n"
    "1. Rest: Avoid weight bearing.\n"
    "2. Ice: Apply cold compress.\n"
    "3. Compression: Wrap joint firmly.\n"
    "4. Elevation: Elevate joint above heart level.\n\n"
    "Keep the instructions clear, numbered, and precise.\n"
    "Cite: 'Sources: Section 5'."
)

messages = [
    {"role": "user", "content": f"{system_prompt}\n\nUser Query: knee sprain"}
]

print("Running chat completions...")
response = model.create_chat_completion(
    messages=messages,
    max_tokens=256,
    temperature=0.3,
    stream=False
)

print(response['choices'][0]['message']['content'])
