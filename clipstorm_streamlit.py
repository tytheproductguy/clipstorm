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
    audio = AudioSegment.from_file(fp)
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
voices = st.file_uploader("Upload voiceovers", type=["wav", "mp3"], accept_multiple_files=True)
bodies = st.file_uploader("Optional: upload body videos", type=["mp4", "mov"], accept_multiple_files=True)

if st.button("Generate"):
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
                if get_duration(h_path) < dur: continue

                h_cut = tmp / f"{h_path.stem}_cut.mp4"
                ff(["ffmpeg","-y","-i",str(h_path),"-t",str(dur),"-c:v","libx264","-c:a","aac",str(h_cut)])
                h_vo = tmp / f"{h_path.stem}_{v_path.stem}_ov.mp4"
                ff(["ffmpeg","-y","-i",str(h_cut),"-i",str(trimmed),"-c:v","copy","-map","0:v","-map","1:a","-shortest",str(h_vo)])

                if bodies:
                    for b in bodies:
                        b_path = tmp / b.name
                        with open(b_path, "wb") as f: f.write(b.getbuffer())
                        cat = tmp / "list.txt"
                        with open(cat, "w") as f: f.write(f"file '{h_vo}'\nfile '{b_path}'\n")
                        final = out / f"{prefix}_{h.name}_{v.name}_{b.name}.mp4"
                        ff(["ffmpeg","-y","-f","concat","-safe","0","-i",str(cat),"-c","copy",str(final)])
                        exported_videos.append(final)
                else:
                    final = out / f"{prefix}_{h.name}_{v.name}.mp4"
                    shutil.copy(h_vo, final)
                    exported_videos.append(final)

            except Exception as e:
                st.error(f"Error: {e}")

    st.success(f"Done! Your videos are ready to download below.")
    st.markdown("### Download your videos:")
    st.info("Click the buttons below to download your videos. They will be saved to your browser's default downloads folder.")

    # Individual download buttons
    for video_path in exported_videos:
        with open(video_path, "rb") as video_file:
            st.download_button(
                label=f"Download {video_path.name}",
                data=video_file.read(),
                file_name=video_path.name,
                mime="video/mp4"
            )

    # Download all as ZIP
    if exported_videos:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zipf:
            for video_path in exported_videos:
                zipf.write(video_path, arcname=video_path.name)
        zip_buffer.seek(0)
        st.download_button(
            label="Download All Videos as ZIP",
            data=zip_buffer,
            file_name="all_videos.zip",
            mime="application/zip"
        )

