# RunPod GPU Video Worker

GPU-accelerated video rendering with Ken Burns effects using NVIDIA NVENC.

## Deployment Steps

### 1. Build and Push Docker Image

```bash
# Login to Docker Hub (or your registry)
docker login

# Build the image
cd /Users/jacquelineyeung/AutoAiGen/history-gen-ai/runpod-video-worker
docker build -t YOUR_DOCKERHUB_USERNAME/history-video-worker:latest .

# Push to registry
docker push YOUR_DOCKERHUB_USERNAME/history-video-worker:latest
```

### 2. Create RunPod Serverless Endpoint

1. Go to [RunPod Serverless](https://www.runpod.io/console/serverless)
2. Click **"New Endpoint"**
3. Configure:
   - **Name**: `history-video-gpu`
   - **Container Image**: `YOUR_DOCKERHUB_USERNAME/history-video-worker:latest`
   - **GPU Type**: RTX 4090 (recommended) or RTX A4000
   - **Workers**:
     - Min: 0 (scale to zero)
     - Max: 2 (adjust based on usage)
   - **Idle Timeout**: 30 seconds
   - **Execution Timeout**: 3600 seconds (1 hour)

4. Click **"Create Endpoint"**
5. Copy the **Endpoint ID** (looks like `abc123xyz`)

### 3. Configure Your Render API

Add to your render-api `.env`:

```bash
RUNPOD_VIDEO_ENDPOINT_ID=YOUR_ENDPOINT_ID_HERE
RUNPOD_API_KEY=YOUR_RUNPOD_API_KEY
```

### 4. Update Code to Use GPU for Ken Burns

In `render-video.ts`, the GPU path is already implemented. Just ensure `useGpu: true` is passed for Ken Burns renders.

## Expected Performance

| GPU Type | 200 Images Ken Burns |
|----------|---------------------|
| RTX 4090 | ~5-8 minutes |
| RTX A4000 | ~10-15 minutes |
| CPU (32 vCPU) | ~30-45 minutes |

## Cost Estimate

- RTX 4090: ~$0.69/hr
- RTX A4000: ~$0.36/hr

A typical 30-min video with 200 images:
- RTX 4090: ~$0.08/render
- RTX A4000: ~$0.09/render

## Troubleshooting

### Check if NVENC is available
```bash
ffmpeg -hide_banner -encoders | grep nvenc
```

### View worker logs
Go to RunPod Console → Your Endpoint → Logs

### Common issues
- **OOM errors**: Reduce IMAGES_PER_CHUNK in handler.py
- **Slow cold start**: Increase min workers to 1
- **Timeout**: Increase execution timeout in endpoint settings
