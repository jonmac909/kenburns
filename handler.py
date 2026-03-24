#!/usr/bin/env python3
"""
RunPod GPU Video Rendering Worker
Renders videos with Ken Burns effect using NVIDIA GPU acceleration
"""

import os
import subprocess
import tempfile
import time
import requests
import runpod
from supabase import create_client

# Constants
IMAGES_PER_CHUNK = 10
FFMPEG_PRESET = "p4"  # NVENC preset (p1=fastest, p7=best quality)
FFMPEG_CQ = "26"  # Constant quality (lower = better, 18-28 typical)


def download_file(url: str, dest_path: str) -> bool:
    """Download a file from URL to local path"""
    try:
        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()
        with open(dest_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False


def update_job_status(supabase, job_id: str, status: str, progress: int, message: str, video_url: str = None):
    """Update render job status in Supabase"""
    try:
        data = {
            "status": status,
            "progress": progress,
            "message": message,
            "updated_at": "now()"
        }
        if video_url:
            data["video_url"] = video_url

        supabase.table("render_jobs").update(data).eq("id", job_id).execute()
        print(f"[{job_id}] {progress}% - {message}")
    except Exception as e:
        print(f"Failed to update job status: {e}")


def get_ken_burns_filters(image_index: int, duration: float) -> tuple:
    """
    Generate Ken Burns effect filters for an image.
    Returns (first_half_filter, second_half_filter)

    Pattern:
    - Even images: Zoom IN then OUT
    - Odd images: Pan L→R then R→L
    """
    half_duration = duration / 2
    half_frames = int(half_duration * 30)
    is_zoom = image_index % 2 == 0

    total_zoom = 0.12  # 12% zoom
    zoom_increment = total_zoom / half_frames
    end_zoom = 1 + total_zoom

    if is_zoom:
        # Zoom: IN for first half, OUT for second half
        first = f"scale=8000:-1,zoompan=z='zoom+{zoom_increment:.6f}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={half_frames}:s=1920x1080:fps=30"
        second = f"scale=8000:-1,zoompan=z='{end_zoom:.2f}-{zoom_increment:.6f}*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={half_frames}:s=1920x1080:fps=30"
    else:
        # Pan: L→R for first half, R→L for second half
        first = f"scale=2500:-1,crop=1920:1080:'(in_w-1920)*t/{half_duration}':0"
        second = f"scale=2500:-1,crop=1920:1080:'(in_w-1920)*(1-t/{half_duration})':0"

    return first, second


def render_ken_burns_clip(image_path: str, output_path: str, filter_str: str, duration: float, use_gpu: bool = True):
    """Render a single Ken Burns clip with GPU or CPU encoding"""

    # Always use CPU for now - zoompan filter is CPU-based anyway
    # GPU is only beneficial for the final encode, not per-clip
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", filter_str,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        output_path
    ]

    print(f"Running FFmpeg: {' '.join(cmd[:8])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg stderr: {result.stderr[:500]}")
        raise Exception(f"FFmpeg failed: {result.returncode}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FFmpeg error: {result.stderr}")
        raise Exception(f"FFmpeg failed: {result.returncode}")


def check_gpu_available() -> bool:
    """Check if NVIDIA GPU encoding is available"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True
        )
        return "h264_nvenc" in result.stdout
    except:
        return False


def handler(job):
    """Main RunPod handler function"""
    job_input = job["input"]

    # Extract input parameters
    image_urls = job_input.get("image_urls", [])
    timings = job_input.get("timings", [])
    audio_url = job_input.get("audio_url")
    project_id = job_input.get("project_id")
    apply_effects = job_input.get("apply_effects", False)
    ken_burns = job_input.get("ken_burns", True)  # Default to Ken Burns
    intro_clips = job_input.get("intro_clips", [])

    # Supabase connection
    supabase_url = job_input.get("supabase_url")
    supabase_key = job_input.get("supabase_key")
    render_job_id = job_input.get("render_job_id")

    if not all([image_urls, audio_url, supabase_url, supabase_key, render_job_id]):
        return {"error": "Missing required parameters"}

    supabase = create_client(supabase_url, supabase_key)

    # Check GPU availability
    use_gpu = check_gpu_available()
    print(f"GPU encoding available: {use_gpu}")

    start_time = time.time()

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            update_job_status(supabase, render_job_id, "downloading", 5, "Downloading assets...")

            # Download images
            image_paths = []
            for i, url in enumerate(image_urls):
                path = os.path.join(temp_dir, f"image_{i:04d}.jpg")
                if download_file(url, path):
                    image_paths.append(path)
                else:
                    return {"error": f"Failed to download image {i}"}

                if i % 20 == 0:
                    pct = int(5 + (i / len(image_urls)) * 15)
                    update_job_status(supabase, render_job_id, "downloading", pct,
                                     f"Downloaded {i+1}/{len(image_urls)} images")

            # Download audio
            audio_path = os.path.join(temp_dir, "audio.mp3")
            if not download_file(audio_url, audio_path):
                return {"error": "Failed to download audio"}

            # Convert audio to AAC
            audio_aac_path = os.path.join(temp_dir, "audio.aac")
            subprocess.run([
                "ffmpeg", "-y", "-i", audio_path,
                "-c:a", "aac", "-b:a", "192k",
                audio_aac_path
            ], check=True, capture_output=True)

            # Download intro clips
            intro_clip_paths = []
            for i, clip in enumerate(intro_clips):
                clip_url = clip.get("url") if isinstance(clip, dict) else clip
                path = os.path.join(temp_dir, f"intro_{i}.mp4")
                if download_file(clip_url, path):
                    intro_clip_paths.append(path)
                    print(f"Downloaded intro clip {i+1}/{len(intro_clips)}")

            update_job_status(supabase, render_job_id, "rendering", 25, "Starting Ken Burns rendering...")

            # Render Ken Burns clips
            total_images = len(image_paths)
            num_chunks = (total_images + IMAGES_PER_CHUNK - 1) // IMAGES_PER_CHUNK
            chunk_paths = []

            for chunk_idx in range(num_chunks):
                chunk_start = chunk_idx * IMAGES_PER_CHUNK
                chunk_end = min((chunk_idx + 1) * IMAGES_PER_CHUNK, total_images)
                chunk_images = image_paths[chunk_start:chunk_end]
                chunk_timings = timings[chunk_start:chunk_end]

                clip_paths = []

                for i, img_path in enumerate(chunk_images):
                    global_idx = chunk_start + i
                    timing = chunk_timings[i]
                    duration = timing["endSeconds"] - timing["startSeconds"]
                    half_duration = duration / 2

                    first_filter, second_filter = get_ken_burns_filters(global_idx, duration)

                    # Render first half
                    clip1_path = os.path.join(temp_dir, f"kb_{chunk_idx}_{i}_1.mp4")
                    render_ken_burns_clip(img_path, clip1_path, first_filter, half_duration, use_gpu)
                    clip_paths.append(clip1_path)

                    # Render second half
                    clip2_path = os.path.join(temp_dir, f"kb_{chunk_idx}_{i}_2.mp4")
                    render_ken_burns_clip(img_path, clip2_path, second_filter, half_duration, use_gpu)
                    clip_paths.append(clip2_path)

                    # Update progress
                    overall_pct = int(25 + ((chunk_idx * IMAGES_PER_CHUNK + i + 1) / total_images) * 45)
                    update_job_status(supabase, render_job_id, "rendering", overall_pct,
                                     f"Ken Burns: chunk {chunk_idx+1}/{num_chunks}, image {i+1}/{len(chunk_images)}")

                # Concatenate chunk clips
                concat_file = os.path.join(temp_dir, f"concat_{chunk_idx}.txt")
                with open(concat_file, 'w') as f:
                    for p in clip_paths:
                        f.write(f"file '{p}'\n")

                chunk_output = os.path.join(temp_dir, f"chunk_{chunk_idx}.mp4")
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c", "copy",
                    chunk_output
                ], check=True, capture_output=True)

                chunk_paths.append(chunk_output)

                # Cleanup clip files
                for p in clip_paths:
                    try:
                        os.remove(p)
                    except:
                        pass

            update_job_status(supabase, render_job_id, "muxing", 72, "Re-encoding intro clips...")

            # Re-encode intro clips to match format
            reencoded_intros = []
            for i, intro_path in enumerate(intro_clip_paths):
                reencoded_path = os.path.join(temp_dir, f"intro_reenc_{i}.mp4")

                encode_cmd = [
                    "ffmpeg", "-y", "-i", intro_path,
                    "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
                    "-r", "30", "-an"  # Remove audio from intros
                ]

                if use_gpu:
                    encode_cmd.extend(["-c:v", "h264_nvenc", "-preset", FFMPEG_PRESET, "-cq", FFMPEG_CQ])
                else:
                    encode_cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "26"])

                encode_cmd.extend(["-pix_fmt", "yuv420p", reencoded_path])

                subprocess.run(encode_cmd, check=True, capture_output=True)
                reencoded_intros.append(reencoded_path)

            update_job_status(supabase, render_job_id, "muxing", 75, "Joining video segments...")

            # Concatenate all: intro clips + image chunks
            all_video_paths = reencoded_intros + chunk_paths
            final_concat_file = os.path.join(temp_dir, "final_concat.txt")
            with open(final_concat_file, 'w') as f:
                for p in all_video_paths:
                    f.write(f"file '{p}'\n")

            concatenated_path = os.path.join(temp_dir, "concatenated.mp4")
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", final_concat_file,
                "-c", "copy",
                concatenated_path
            ], check=True, capture_output=True)

            update_job_status(supabase, render_job_id, "muxing", 80, "Adding audio...")

            # Add audio
            with_audio_path = os.path.join(temp_dir, "with_audio.mp4")
            subprocess.run([
                "ffmpeg", "-y",
                "-i", concatenated_path,
                "-i", audio_aac_path,
                "-c:v", "copy",
                "-c:a", "copy",
                "-shortest",
                with_audio_path
            ], check=True, capture_output=True)

            update_job_status(supabase, render_job_id, "muxing", 85, "Scrubbing metadata...")

            # Scrub metadata
            final_path = os.path.join(temp_dir, "final.mp4")
            subprocess.run([
                "ffmpeg", "-y",
                "-i", with_audio_path,
                "-map_metadata", "-1",
                "-c:v", "copy",
                "-c:a", "copy",
                "-movflags", "+faststart",
                final_path
            ], check=True, capture_output=True)

            update_job_status(supabase, render_job_id, "uploading", 90, "Uploading to storage...")

            # Upload to Supabase Storage
            file_size = os.path.getsize(final_path)
            print(f"Final video size: {file_size / 1024 / 1024:.2f} MB")

            timestamp = int(time.time())
            storage_path = f"videos/{project_id}/ken_burns_{timestamp}.mp4"

            with open(final_path, 'rb') as f:
                supabase.storage.from_("generated-assets").upload(
                    storage_path,
                    f,
                    {"content-type": "video/mp4"}
                )

            # Get public URL
            video_url = supabase.storage.from_("generated-assets").get_public_url(storage_path)

            render_time = time.time() - start_time
            print(f"Render complete in {render_time:.1f}s")

            # Update project with Ken Burns video URL
            supabase.table("projects").update({
                "ken_burns_video_url": video_url
            }).eq("id", project_id).execute()

            update_job_status(supabase, render_job_id, "complete", 100,
                            f"Video rendered successfully (GPU: {render_time:.1f}s)",
                            video_url)

            return {
                "video_url": video_url,
                "render_time_seconds": render_time,
                "gpu_used": use_gpu
            }

    except Exception as e:
        error_msg = str(e)
        print(f"Render failed: {error_msg}")
        update_job_status(supabase, render_job_id, "failed", 0, f"Error: {error_msg}")
        return {"error": error_msg}


# Start RunPod serverless handler
runpod.serverless.start({"handler": handler})
