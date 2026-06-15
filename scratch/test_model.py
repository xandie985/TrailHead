import os
from llama_cpp import Llama
from huggingface_hub import hf_hub_download

MODEL_REPO = "bartowski/gemma-1.1-2b-it-GGUF"
MODEL_FILE = "gemma-1.1-2b-it-Q4_K_M.gguf"
LOCAL_MODEL_DIR = "./model"

model_path = os.path.join(LOCAL_MODEL_DIR, MODEL_FILE)
if not os.path.exists(model_path):
    print("Downloading model...")
    hf_hub_download(
        repo_id=MODEL_REPO,
        filename=MODEL_FILE,
        local_dir=LOCAL_MODEL_DIR,
        local_dir_use_symlinks=False
    )

print("File exists:", os.path.exists(model_path))
print("File size:", os.path.getsize(model_path))

try:
    model = Llama(
        model_path=model_path,
        n_ctx=2048,
        verbose=True
    )
    print("Success loading model!")
except Exception as e:
    import traceback
    traceback.print_exc()
