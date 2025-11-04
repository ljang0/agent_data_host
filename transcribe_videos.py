#!/usr/bin/env python3
"""
Batch-transcribe .mov screen recordings under users/*/<task>/videos/.

For each MOV file we:
  1. Extract a mono 16 kHz WAV using ffmpeg.
  2. Run OpenAI Whisper (or FasterWhisper) to generate a transcript.
  3. Write JSON with the text + segment metadata next to the original.

Usage:
  python3 transcribe_videos.py --users-root users --model medium
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

try:
	# Prefer faster-whisper if installed for speed
	from faster_whisper import WhisperModel  # type: ignore

	FASTER_WHISPER_AVAILABLE = True
except Exception:  # pragma: no cover - optional import
	FASTER_WHISPER_AVAILABLE = False

try:
	import whisper  # type: ignore

	WHISPER_AVAILABLE = True
except Exception:  # pragma: no cover - optional import
	WHISPER_AVAILABLE = False

AUDIO_SUFFIX = ".wav"
TRANSCRIPT_SUFFIX = ".transcript.json"


@dataclass
class TranscriptResult:
	text: str
	segments: List[dict]


def run_ffmpeg_extract(source: Path, destination: Path) -> None:
	destination.parent.mkdir(parents=True, exist_ok=True)
	cmd = [
		"ffmpeg",
		"-hide_banner",
		"-loglevel",
		"error",
		"-y",
		"-i",
		str(source),
		"-vn",
		"-acodec",
		"pcm_s16le",
		"-ar",
		"16000",
		"-ac",
		"1",
		str(destination),
	]
	subprocess.run(cmd, check=True)


def iter_mov_files(users_root: Path) -> Iterable[Path]:
	for path in sorted(users_root.glob("**/videos/*.mov")):
		if path.is_file():
			yield path


def load_model(model_name: str, device: Optional[str]) -> object:
	if FASTER_WHISPER_AVAILABLE:
		return WhisperModel(model_name, device=device or "auto", compute_type="float16")
	if not WHISPER_AVAILABLE:
		raise RuntimeError(
			"Neither faster-whisper nor openai-whisper is installed. "
			"Run 'pip install faster-whisper' or 'pip install openai-whisper'.",
		)
	return whisper.load_model(model_name, device=device or "cuda")


def transcribe_audio(model: object, audio_path: Path) -> TranscriptResult:
	if FASTER_WHISPER_AVAILABLE and isinstance(model, WhisperModel):
		segments, info = model.transcribe(str(audio_path), beam_size=5)
		text_chunks = []
		segment_payloads = []
		for segment in segments:
			text_chunks.append(segment.text.strip())
			segment_payloads.append(
				{
					"id": segment.id,
					"start": segment.start,
					"end": segment.end,
					"text": segment.text,
					"words": [
						{"start": word.start, "end": word.end, "probability": word.probability, "word": word.word}
						for word in segment.words or []
					],
				},
			)
		return TranscriptResult(text=" ".join(text_chunks).strip(), segments=segment_payloads)

	# Fallback to openai-whisper
	assert WHISPER_AVAILABLE
	result = whisper.transcribe(model, str(audio_path))
	return TranscriptResult(text=result.get("text", "").strip(), segments=result.get("segments", []) or [])


def write_transcript(path: Path, payload: dict) -> None:
	with path.open("w", encoding="utf-8") as handle:
		json.dump(payload, handle, ensure_ascii=False, indent=2)


def process_video(mov_path: Path, model, overwrite: bool) -> None:
	audio_path = mov_path.with_suffix(AUDIO_SUFFIX)
	transcript_path = mov_path.with_suffix(TRANSCRIPT_SUFFIX)

	if transcript_path.exists() and not overwrite:
		print(f"Skip existing transcript: {transcript_path}")
		return

	print(f"Transcribing {mov_path}")
	run_ffmpeg_extract(mov_path, audio_path)
	result = transcribe_audio(model, audio_path)
	payload = {
		"video": mov_path.as_posix(),
		"audio": audio_path.as_posix(),
		"text": result.text,
		"segments": result.segments,
		"model": getattr(model, "model_size", getattr(model, "model_name", "unknown")),
	}
	write_transcript(transcript_path, payload)


def main() -> None:
	parser = argparse.ArgumentParser(description="Transcribe MOV files under users/*/<task>/videos/")
	parser.add_argument("--users-root", type=Path, default=Path("users"), help="Root directory containing user task folders.")
	parser.add_argument("--model", type=str, default="base", help="Whisper/faster-whisper model size.")
	parser.add_argument("--device", type=str, default=None, help="Device override (e.g. cuda, cpu).")
	parser.add_argument("--overwrite", action="store_true", help="Regenerate transcripts even if already present.")
	args = parser.parse_args()

	users_root = args.users_root.resolve()
	if not users_root.exists():
		sys.exit(f"Users root not found: {users_root}")

	model = load_model(args.model, args.device)

	matches = list(iter_mov_files(users_root))
	if not matches:
		print(f"No .mov files found under {users_root}")
		return

	for mov_path in matches:
		try:
			process_video(mov_path, model, overwrite=args.overwrite)
		except subprocess.CalledProcessError as exc:
			print(f"ffmpeg failed on {mov_path}: {exc}", file=sys.stderr)
		except Exception as exc:  # pragma: no cover - best effort logging
			print(f"Failed to transcribe {mov_path}: {exc}", file=sys.stderr)


if __name__ == "__main__":
	main()
