import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCREENSHOT_DIR_OPTIONS = (
	Path("imgs"),
	Path("videos") / "frames_display_1",
)
TRANSCRIPT_SUFFIX = ".transcript.json"


def resolve_default_data_root() -> Path:
	"""Resolve the default data root relative to this script."""
	return Path(__file__).resolve().parent / "data"


def find_task_directories(data_root: Path) -> List[Path]:
	"""Return a list of subdirectories in data_root that represent tasks."""
	if not data_root.exists() or not data_root.is_dir():
		raise FileNotFoundError(f"Data directory not found: {data_root}")

	task_directories: List[Path] = []
	for entry in os.scandir(data_root):
		if entry.is_dir():
			task_directories.append(Path(entry.path))

	return sorted(task_directories)


def load_session_json(task_directory: Path) -> Dict:
	"""Load session_data.json for a given task directory."""
	session_path = task_directory / "session_data.json"
	if not session_path.exists():
		raise FileNotFoundError(f"Missing session_data.json in {task_directory}")

	with session_path.open("r", encoding="utf-8") as f:
		data = json.load(f)

	return data


def has_screenshots(task_directory: Path) -> bool:
	"""Return True if a known screenshot directory exists for task_directory."""
	return any((task_directory / candidate).is_dir() for candidate in SCREENSHOT_DIR_OPTIONS)


def load_all_tasks(data_root: Path) -> List[Tuple[Path, Dict]]:
	"""Load session JSON for all tasks under data_root.

	Returns a list of (task_directory, session_json) tuples.
	"""
	results: List[Tuple[Path, Dict]] = []
	for task_dir in find_task_directories(data_root):
		if not has_screenshots(task_dir):
			print(f"Warning: Skipping {task_dir.name}: no screenshot directory found.")
			continue
		session_path = task_dir / "session_data.json"
		if not session_path.exists():
			print(f"Warning: Skipping {task_dir.name}: missing session_data.json.")
			continue
		try:
			data = load_session_json(task_dir)
			results.append((task_dir, data))
		except Exception as exc:
			print(f"Warning: Skipping {task_dir.name}: {exc}")

	return results


def convert_to_llm_format(task_directory: Path, data: Dict, screenshot_subdir: Optional[str] = None) -> List[Dict]:
	"""Convert events to an LLM-friendly format."""
	llm_format: List[Dict] = []
	events = data.get("events", [])
	key_accumulated = ""
	first_key_path = None
	counter = 0
	if screenshot_subdir is not None:
		screenshot_dir = Path(screenshot_subdir)
	else:
		for candidate in SCREENSHOT_DIR_OPTIONS:
			if (task_directory / candidate).exists():
				screenshot_dir = candidate
				break
		else:
			# Default to imgs to keep paths stable even if the folder is unexpectedly absent.
			screenshot_dir = Path("imgs")

	def make_screenshot_path(index: int) -> str:
		filename = f"event_{index}.png"
		return str((screenshot_dir / filename).as_posix())

	for i, event in enumerate(events):
		event_id = event.get("id")
		if event_id is None:
			event_id = i
		action_type = event.get("type")
		ss_path = make_screenshot_path(event_id)
		timestamp = event.get("timestamp")
		absolute_timestamp = event.get("absoluteTimestamp")
		shift_letter = normalize_shift_letter(event) if action_type == "key_combination" else None

		if action_type == "click":
			x = event["x"]
			y = event["y"]
			screen_info = event.get("screenInfo") or {}
			current_display = screen_info.get("currentDisplay") or {}
			bounds = current_display.get("bounds") or {}
			width_display = bounds.get("width")
			height_display = bounds.get("height")
			llm_format.append({
				"id": counter,
				"type": action_type,
				"x": x,
				"y": y,
				"width_display": width_display,
				"height_display": height_display,
				"ss_path": ss_path,
				"button": event.get("button"),
				"timestamp": timestamp,
				"absolute_timestamp": absolute_timestamp,
			})
			counter += 1
		elif action_type == "drag":
			start_x = event.get("startX")
			start_y = event.get("startY")
			end_x = event.get("endX")
			end_y = event.get("endY")
			screen_info = event.get("screenInfo") or {}
			current_display = screen_info.get("currentDisplay") or {}
			bounds = current_display.get("bounds") or {}
			width_display = bounds.get("width")
			height_display = bounds.get("height")
			start_ts = event.get("startTimestamp")
			end_ts = event.get("timestamp")
			duration = None
			if isinstance(start_ts, (int, float)) and isinstance(end_ts, (int, float)):
				duration = max(0.0, end_ts - start_ts)
			llm_format.append({
				"id": counter,
				"type": "drag",
				"start_x": start_x,
				"start_y": start_y,
				"end_x": end_x,
				"end_y": end_y,
				"start_timestamp": start_ts,
				"end_timestamp": end_ts,
				"duration": duration,
				"distance": event.get("distance"),
				"button": event.get("button"),
				"width_display": width_display,
				"height_display": height_display,
				"ss_path": ss_path,
				"timestamp": timestamp,
				"absolute_timestamp": absolute_timestamp,
			})
			counter += 1
		elif action_type == "type" or shift_letter:
			current_key = shift_letter if shift_letter is not None else event.get("key", "")
			if current_key in {"LEFT_SHIFT", "RIGHT_SHIFT", "SHIFT"}:
				continue
			if current_key == "SPACE":
				current_key = " "
			if current_key == "NUMPAD_ENTER":
				current_key = " + ENTER"
			if not current_key:
				continue
			if current_key == "BACKSPACE":
				if key_accumulated:
					key_accumulated = key_accumulated[:-1]
					if not key_accumulated:
						first_key_path = None
				else:
					llm_format.append({
						"id": counter,
						"type": "type",
						"key": "BACKSPACE",
						"ss_path": ss_path,
						"timestamp": timestamp,
						"absolute_timestamp": absolute_timestamp,
					})
					counter += 1
				continue
			if first_key_path is None:
				first_key_path = ss_path
			key_accumulated += current_key
			next_is_key = False
			if i + 1 < len(events):
				next_is_key = is_typing_event(events[i + 1])
			if next_is_key:
				continue
			if key_accumulated:
				llm_format.append({
					"id": counter,
					"type": "type",
					"key": key_accumulated,
					"ss_path": first_key_path or ss_path,
					"timestamp": timestamp,
					"absolute_timestamp": absolute_timestamp,
				})
				counter += 1
			key_accumulated = ""
			first_key_path = None
		elif action_type == "key_combination":
			current_key = event.get("combination", "")
			translation = event.get("combinationName")
			llm_format.append({
				"id": counter,
				"type": "key_combination",
				"key": current_key,
				"translation": translation,
				"ss_path": ss_path,
				"timestamp": timestamp,
				"absolute_timestamp": absolute_timestamp,
			})		
			counter += 1	
		elif action_type == "scroll_sequence":
			direction = event.get("direction")
			total_amount = event.get("totalAmount")
			duration = event.get("duration")
			individual_scrolls = event.get("individualScrolls")
			llm_format.append({
				"id": counter,
				"type": "scroll",
				"direction": direction,
				"total_amount": total_amount,
				"duration": duration,
				"individual_scrolls": individual_scrolls,
				"ss_path": ss_path,
				"timestamp": timestamp,
				"absolute_timestamp": absolute_timestamp,
			})
			counter += 1
	# Flush any remaining accumulated keys at the end
	if key_accumulated:
		llm_format.append({
			"id": counter,
			"type": "type",
			"key": key_accumulated,
			"ss_path": first_key_path or ss_path,
			"timestamp": timestamp,
			"absolute_timestamp": absolute_timestamp,
		})
		key_accumulated = ""
		first_key_path = None
		counter += 1
	transcript_segments = load_transcript_segments(task_directory, data)
	if transcript_segments:
		attach_chain_of_thought(llm_format, transcript_segments)
	# Append a final stop event with the next id
	llm_format.append({
		"id": counter,
		"type": "stop",
		"ss_path": make_screenshot_path(len(events)),
		"timestamp": events[-1].get("timestamp") if events else None,
		"absolute_timestamp": events[-1].get("absoluteTimestamp") if events else None,
	})
	return llm_format


def write_json(path: Path, payload: List[Dict]) -> None:
	"""Write payload to JSON file with UTF-8 encoding."""
	path.parent.mkdir(parents=True, exist_ok=True)
	with path.open("w", encoding="utf-8") as f:
		json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
	parser = argparse.ArgumentParser(description="Load session_data.json for each task in data/")
	parser.add_argument(
		"--data-root",
		type=str,
		help="Path to data directory containing task subdirectories",
		default=str(resolve_default_data_root()),
	)
	args = parser.parse_args()
	data_root = Path(args.data_root)

	all_tasks = load_all_tasks(data_root)

	if not all_tasks:
		print("No tasks loaded.")
		return

	print(f"Loaded {len(all_tasks)} task(s) from {data_root}")
	for task_dir, data in sorted(all_tasks, key=lambda item: item[0].name.lower()):
		task_name = task_dir.name
		num_events = len(data.get("events", [])) if isinstance(data, dict) else 0
		llm_events = convert_to_llm_format(task_dir, data)
		output_path = task_dir / "llm_events.json"
		write_json(output_path, llm_events)
		print(f"- {task_name}: events={num_events}")

if __name__ == "__main__":
	main()


def load_transcript_segments(task_directory: Path, session_data: Dict) -> List[Dict]:
	"""Load Whisper transcript segments for the task directory."""
	videos_dir = task_directory / "videos"
	if not videos_dir.is_dir():
		return []

	transcript_files = sorted(videos_dir.glob(f"*{TRANSCRIPT_SUFFIX}"))
	if not transcript_files:
		return []

	selected = select_best_transcript(transcript_files, session_data.get("metadata") or {})
	if selected is None:
		return []

	try:
		with selected.open("r", encoding="utf-8") as handle:
			payload = json.load(handle)
	except (json.JSONDecodeError, OSError) as exc:
		print(f"Warning: unable to read transcript {selected}: {exc}")
		return []

	segments = payload.get("segments")
	if not isinstance(segments, list):
		return []

	results: List[Dict] = []
	for segment in segments:
		start = coerce_float(segment.get("start"))
		end = coerce_float(segment.get("end"))
		text = (segment.get("text") or "").strip()
		if start is None or end is None or not text:
			continue
		if end < start:
			start, end = end, start
		results.append({"start": start, "end": end, "text": text})

	results.sort(key=lambda item: item["start"])
	return results


def select_best_transcript(files: Sequence[Path], metadata: Dict) -> Optional[Path]:
	"""Select the transcript file whose timestamp best matches the session metadata."""
	if not files:
		return None

	target_start_ms = None
	video_meta = metadata.get("video") if isinstance(metadata, dict) else None
	if isinstance(video_meta, dict):
		target_start_ms = coerce_float(video_meta.get("startTime"))

	def score(path: Path) -> float:
		if target_start_ms is None:
			return 0.0
		ts = parse_timestamp_from_name(path)
		if ts is None:
			return float("inf")
		return abs(ts * 1000 - target_start_ms)

	sorted_files = sorted(files, key=score)
	best = sorted_files[0]
	if target_start_ms is not None and not is_finite(score(best)):
		# All candidates failed to parse a timestamp; fall back to the first file.
		return files[0]
	return best


def parse_timestamp_from_name(path: Path) -> Optional[float]:
	"""Parse the timestamp embedded in a transcript filename (seconds since epoch)."""
	name = path.name
	if name.endswith(TRANSCRIPT_SUFFIX):
		name = name[: -len(TRANSCRIPT_SUFFIX)]
	if name.endswith(".json"):
		name = name[:-5]
	if name.endswith(".transcript"):
		name = name[: -len(".transcript")]
	try:
		parsed = datetime.strptime(name, "%Y-%m-%d %H-%M-%S")
	except ValueError:
		return None
	return parsed.timestamp()


def coerce_float(value: Optional[float]) -> Optional[float]:
	if isinstance(value, (int, float)):
		return float(value)
	return None


def is_finite(value: float) -> bool:
	return value == value and value not in (float("inf"), float("-inf"))


def attach_chain_of_thought(events: List[Dict], segments: List[Dict]) -> None:
	"""Attach transcript snippets to the earliest overlapping event."""
	if not events or not segments:
		return

	event_ranges: List[Optional[Tuple[float, float]]] = [compute_event_window(event) for event in events]
	search_index = 0
	for segment in segments:
		start = coerce_float(segment.get("start"))
		end = coerce_float(segment.get("end"))
		text = (segment.get("text") or "").strip()
		if start is None or end is None or not text:
			continue
		if end < start:
			start, end = end, start
		idx = max(search_index, 0)
		while idx < len(events):
			event = events[idx]
			if (event.get("type") or "").lower() == "stop":
				idx += 1
				continue
			window = event_ranges[idx]
			if window is None:
				idx += 1
				continue
			window_start, window_end = window
			if window_end >= start and window_start <= end:
				event.setdefault("thought_segments", []).append({
					"start": start,
					"end": end,
					"text": text,
				})
				search_index = idx
				break
			if window_start > end:
				break
			idx += 1

	for event in events:
		segments_for_event = event.get("thought_segments")
		if not segments_for_event:
			continue
		text_parts = [seg.get("text", "").strip() for seg in segments_for_event if seg.get("text")]
		if text_parts:
			event["chain_of_thought"] = " ".join(text_parts).strip()


def compute_event_window(event: Dict) -> Optional[Tuple[float, float]]:
	"""Return (start, end) timestamps for an event in video-time seconds."""
	timestamp = coerce_float(event.get("timestamp"))
	start = coerce_float(event.get("start_timestamp"))
	end = coerce_float(event.get("end_timestamp"))

	if start is None and end is None:
		if timestamp is None:
			return None
		start = end = timestamp
	elif start is None:
		start = timestamp if timestamp is not None else end
	elif end is None:
		end = timestamp if timestamp is not None else start

	if start is None or end is None:
		return None

	if end < start:
		start, end = end, start
	return float(start), float(end)


def normalize_shift_letter(event: Dict[str, Any]) -> Optional[str]:
	"""Return uppercase letter if event is a Shift+letter combination."""
	combination_sources = [
		event.get("combination"),
		event.get("combinationName"),
	]
	for source in combination_sources:
		if not source:
			continue
		cleaned = source.replace(" ", "")
		match = re.fullmatch(r"(?i)shift\+([a-z])", cleaned)
		if match:
			return match.group(1).upper()
	return None


def is_typing_event(event: Dict[str, Any]) -> bool:
	"""Return True if the event contributes characters to a typing sequence."""
	if not isinstance(event, dict):
		return False
	event_type = event.get("type")
	if event_type == "type":
		return True
	if event_type == "key_combination" and normalize_shift_letter(event):
		return True
	return False
