#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import whisper  # or import faster_whisper

AUDIO_EXT = ".wav"

def find_mov_files(users_root: Path) -> List[Path]:
    return sorted(users_root.glob("**/videos/*.mov"))

def extract_audio(source: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(source),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dest

def transcribe_audio(model, audio_path: Path) -> Tuple[str, List[dict]]:
    result = model.transcribe(str(audio_path))
    text = result["text"].strip()
    segments = result.get("segments") or []
    return text, segments

def main(users_root: Path, model_name: str, overwrite: bool) -> None:
    model =  whisper.load_model(model_name, device="cpu")
    mov_files = find_mov_files(users_root)

    for mov in mov_files:
        audio_path = mov.with_suffix(AUDIO_EXT)
        transcript_path = mov.with_suffix(".transcript.json")

        if transcript_path.exists() and not overwrite:
            print(f"Skip (exists): {transcript_path}")
            continue

        print(f"Processing {mov}")
        extract_audio(mov, audio_path)

        text, segments = transcribe_audio(model, audio_path)
        payload = {
            "video": str(mov),
            "audio": str(audio_path),
            "model": model_name,
            "text": text,
            "segments": segments,
        }
        with transcript_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe MOV videos under users/*/videos/")
    parser.add_argument("--users-root", default="users", type=Path, help="Path to the users/ directory")
    parser.add_argument("--model", default="base", help="Whisper model name (tiny/base/small/medium/large)")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate transcripts even if they exist")
    args = parser.parse_args()
    main(args.users_root.resolve(), args.model, args.overwrite)
