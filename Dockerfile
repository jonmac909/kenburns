# Use NVIDIA's CUDA devel image for NVENC support
FROM nvidia/cuda:12.2.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

# Install dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    wget \
    curl \
    git \
    nasm \
    yasm \
    pkg-config \
    libx264-dev \
    libx265-dev \
    libnuma-dev \
    && rm -rf /var/lib/apt/lists/*

# Install NVIDIA Video Codec SDK headers (required for NVENC)
RUN git clone --depth 1 https://github.com/FFmpeg/nv-codec-headers.git \
    && cd nv-codec-headers \
    && make install \
    && cd .. \
    && rm -rf nv-codec-headers

# Build FFmpeg with NVENC support
RUN git clone --depth 1 https://github.com/FFmpeg/FFmpeg.git ffmpeg-src \
    && cd ffmpeg-src \
    && ./configure \
        --enable-nonfree \
        --enable-cuda-nvcc \
        --enable-libnpp \
        --enable-nvenc \
        --enable-nvdec \
        --enable-cuvid \
        --enable-gpl \
        --enable-libx264 \
        --enable-libx265 \
        --extra-cflags=-I/usr/local/cuda/include \
        --extra-ldflags=-L/usr/local/cuda/lib64 \
    && make -j$(nproc) \
    && make install \
    && cd .. \
    && rm -rf ffmpeg-src

# Verify NVENC is available
RUN ffmpeg -hide_banner -encoders | grep nvenc

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
