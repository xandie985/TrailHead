# Use a slim Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PORT=7860 \
    BACKEND=llama_cpp \
    MODEL_DIR=/code/model

# Set working directory
WORKDIR /code

# Install basic runtime dependencies (git is useful for huggingface_hub downloads)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install llama-cpp-python using the pre-compiled CPU wheels index
RUN pip install --no-cache-dir llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

# Copy requirements and install remaining python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the Gemma 4 E2B model GGUF so the container boots instantly
RUN mkdir -p /code/model && \
    python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='bartowski/google_gemma-4-E2B-it-GGUF', filename='google_gemma-4-E2B-it-Q4_K_M.gguf', local_dir='/code/model')"

# Copy the application source code
COPY . .

# Expose Gradio's port
EXPOSE 7860

# Launch the Gradio app
CMD ["python", "app.py"]
