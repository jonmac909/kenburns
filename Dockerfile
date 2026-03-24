FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    ffmpeg \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Note: Ubuntu's ffmpeg doesn't have NVENC by default
# We'll use a custom FFmpeg build with NVIDIA support
RUN wget -q https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz \
    && tar -xf ffmpeg-master-latest-linux64-gpl.tar.xz \
    && cp ffmpeg-master-latest-linux64-gpl/bin/* /usr/local/bin/ \
    && rm -rf ffmpeg-master-latest-linux64-gpl* \
    && ffmpeg -version

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    runpod \
    supabase \
    requests \
    aiohttp

WORKDIR /app

# Copy handler
COPY handler.py .

# RunPod serverless handler
CMD ["python3", "-u", "handler.py"]
