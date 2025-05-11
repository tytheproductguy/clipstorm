import os, shutil, subprocess, tempfile, platform
from pathlib import Path
from pydub import AudioSegment, silence
import streamlit as st
from datetime import datetime
import zipfile
import io

st.set_page_config(page_title="Clipstorm", layout="centered")

st.title("🎥 Clipstorm Video Generator")

def trim_silence(fp: Path, tmp: Path):
    try:
        audio = AudioSegment.from_file(fp)
    except Exception as e:
        # Fallback: convert to wav with ffmpeg and try again
        if fp.suffix.lower() == ".m4a":
            converted = tmp / f"{fp.stem}_converted.wav"
            subprocess.run([
                "ffmpeg", "-y", "-i", str(fp), str(converted)
            ], check=True)
            audio = AudioSegment.from_file(converted)
            fp = converted
        else:
            raise e
    chunks = silence.split_on_silence(audio, min_silence_len=300, silence_thresh=audio.dBFS-30, keep_silence=150)
    if not chunks: return fp, len(audio)/1000
    trimmed = sum(chunks, AudioSegment.silent(0))
    out = tmp / f"{fp.stem}_trimmed.wav"
    trimmed.export(out, format="wav")
    return out, len(trimmed)/1000

def get_duration(fp: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(fp)],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return float(r.stdout) if r.stdout else 0.0

def ff(cmd): subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

prefix = st.text_input("Filename prefix", "")
hooks = st.file_uploader("Upload hook videos", type=["mp4", "mov"], accept_multiple_files=True)
voices = st.file_uploader("Upload voiceovers", type=["wav", "mp3", "m4a"], accept_multiple_files=True)
bodies = st.file_uploader("Optional: upload body videos", type=["mp4", "mov"], accept_multiple_files=True)

# Show uploaded file durations immediately after upload
if hooks:
    st.markdown("#### Hook video durations:")
    for h in hooks:
        h_path = Path(tempfile.gettempdir()) / h.name
        with open(h_path, "wb") as f: f.write(h.getbuffer())
        dur = get_duration(h_path)
        st.write(f"{h.name}: {dur:.2f} seconds")
if voices:
    st.markdown("#### Voiceover durations:")
    for v in voices:
        v_path = Path(tempfile.gettempdir()) / v.name
        with open(v_path, "wb") as f: f.write(v.getbuffer())
        dur = get_duration(v_path)
        st.write(f"{v.name}: {dur:.2f} seconds")

if "exported_videos" not in st.session_state:
    st.session_state["exported_videos"] = []

processing = False
if st.button("Generate"):
    processing = True
    if not prefix: st.error("Enter a prefix"); st.stop()
    if not hooks or not voices: st.error("Upload at least one hook and voice"); st.stop()

    tmp = Path(tempfile.mkdtemp())
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path("rendered_videos") / f"{prefix}_{timestamp}"
    out.mkdir(parents=True, exist_ok=True)
    total = len(hooks) * len(voices) * max(1, len(bodies))
    progress = st.progress(0)
    idx = 0
    exported_videos = []
    short_hook_warnings = []

    for h in hooks:
        h_path = tmp / h.name
        with open(h_path, "wb") as f: f.write(h.getbuffer())
        for v in voices:
            idx += 1
            progress.progress(idx/total)
            st.write(f"{h.name} + {v.name}")
            v_path = tmp / v.name
            with open(v_path, "wb") as f: f.write(v.getbuffer())

            try:
                trimmed, dur = trim_silence(v_path, tmp)
                hook_dur = get_duration(h_path)
                if hook_dur < dur:
                    short_hook_warnings.append(f"Warning: Hook video '{h.name}' ({hook_dur:.2f}s) is shorter than trimmed audio '{v.name}' ({dur:.2f}s). Video will be padded to match audio.")
                if get_duration(h_path) < dur: continue

                h_cut = tmp / f"{h_path.stem}_cut.mp4"
                ff(["ffmpeg","-y","-i",str(h_path),"-t",str(dur),"-c:v","libx264","-c:a","aac",str(h_cut)])
                h_vo = tmp / f"{h_path.stem}_{v_path.stem}_ov.mp4"
                ff(["ffmpeg","-y","-i",str(h_cut),"-i",str(trimmed),"-c:v","copy","-map","0:v","-map","1:a","-shortest",str(h_vo)])

                if bodies:
                    for b in bodies:
                        b_path = tmp / b.name
                        with open(b_path, "wb") as f: f.write(b.getbuffer())
                        # Always use robust concat filter for body+hook
                        h_vo_reenc = tmp / f"{h_vo.stem}_reenc.mp4"
                        ff([
                            "ffmpeg", "-y", "-i", str(h_vo),
                            "-c:v", "libx264", "-c:a", "aac", str(h_vo_reenc)
                        ])
                        body_reenc = tmp / f"{b_path.stem}_reenc.mp4"
                        ff([
                            "ffmpeg", "-y", "-i", str(b_path),
                            "-c:v", "libx264", "-c:a", "aac", str(body_reenc)
                        ])
                        concat_out = tmp / f"{prefix}_{h.name}_{v.name}_{b.name}_concat.mp4"
                        ff([
                            "ffmpeg", "-y",
                            "-i", str(h_vo_reenc),
                            "-i", str(body_reenc),
                            "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
                            "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-c:a", "aac",
                            str(concat_out)
                        ])
                        try:
                            clean_name = strip_all_extensions(f"{prefix}_{h.name}_{v.name}_{b.name}") + ".mp4"
                        except Exception:
                            clean_name = f"output_{idx}.mp4"
                        final = out / clean_name
                        shutil.copy(concat_out, final)
                        if final.exists():
                            exported_videos.append(str(final.resolve()))
                        else:
                            st.error(f"Failed to generate video: {final}")
                else:
                    # Use fast concat for hook+voiceover only
                    try:
                        clean_name = strip_all_extensions(f"{prefix}_{h.name}_{v.name}") + ".mp4"
                    except Exception:
                        clean_name = f"output_{idx}.mp4"
                    final = out / clean_name
                    cat = tmp / "list.txt"
                    with open(cat, "w") as f: f.write(f"file '{h_vo}'\n")
                    try:
                        ff([
                            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(cat), "-c", "copy", str(final)
                        ])
                    except Exception as e:
                        st.warning(f"Fast concat failed for {final.name}, falling back to re-encoding. Reason: {e}")
                        h_vo_reenc = tmp / f"{h_vo.stem}_reenc.mp4"
                        ff([
                            "ffmpeg", "-y", "-i", str(h_vo),
                            "-c:v", "libx264", "-c:a", "aac", str(h_vo_reenc)
                        ])
                        shutil.copy(h_vo_reenc, final)
                    if final.exists():
                        exported_videos.append(str(final.resolve()))
                    else:
                        st.error(f"Failed to generate video: {final}")

            except Exception as e:
                st.error(f"Error: {e}")

    st.session_state["exported_videos"] = exported_videos
    st.success(f"Done! Your videos are ready to download below.")

    if short_hook_warnings:
        for w in short_hook_warnings:
            st.warning(w)

    processing = False
    st.session_state["generate_pressed"] = True
else:
    st.session_state["generate_pressed"] = False

# After processing, always show download buttons if videos exist
st.markdown("### Download your videos:")

if processing:
    with st.spinner("Processing videos, please wait..."):
        pass
elif st.session_state["exported_videos"]:
    st.info("Click the download icon next to each video to download it. They will be saved to your browser's default downloads folder.")
    for i, video_path in enumerate(st.session_state["exported_videos"]):
        video_path = Path(video_path)
        if video_path.exists():
            cols = st.columns([0.08, 0.72, 0.2])
            with cols[0]:
                st.markdown(":arrow_down:", unsafe_allow_html=True)
            with cols[1]:
                st.markdown(f"**{video_path.name}**")
            with cols[2]:
                with open(video_path, "rb") as video_file:
                    st.download_button(
                        label="Download",
                        data=video_file.read(),
                        file_name=video_path.name,
                        mime="video/mp4",
                        key=f"download_{i}"
                    )
        else:
            st.error(f"File not found: {video_path}")
    # Download all as ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zipf:
        for video_path in st.session_state["exported_videos"]:
            video_path = Path(video_path)
            if video_path.exists():
                zipf.write(video_path, arcname=video_path.name)
    zip_buffer.seek(0)
    st.download_button(
        label="Download All Videos as ZIP",
        data=zip_buffer,
        file_name="all_videos.zip",
        mime="application/zip",
        key="download_zip"
    )
elif st.session_state.get("generate_pressed", False):
    st.warning("No videos were generated. Please check your inputs and try again.")
else:
    st.info("Upload your files and click Generate to create videos.")

