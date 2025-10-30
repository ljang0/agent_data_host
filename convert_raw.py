import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCREENSHOT_DIR_OPTIONS = (
	Path("imgs"),
	Path("videos") / "frames_display_1",
)


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
			})
			counter += 1
		elif action_type == "key_combination":
			current_key = event.get("combination", "")
			translation = event.get("combinationName")
			llm_format.append({
				"id": counter,
				"type": "key_combination",
				"key": current_key,
				"translation": translation,
				"ss_path": ss_path,
			})		
			counter += 1	
		elif action_type == "type":
			current_key = event.get("key", "")
			if first_key_path is None:
				first_key_path = ss_path
			if current_key == "SPACE":
				current_key = " "
			if current_key == "NUMPAD_ENTER":
				current_key = " + ENTER"
			key_accumulated += current_key
			next_is_key = False
			if i + 1 < len(events):
				next_type = events[i + 1].get("type")
				next_is_key = (next_type == "type")
			if next_is_key:
				continue
			llm_format.append({
				"id": counter,
				"type": "type",
				"key": key_accumulated,
				"ss_path": first_key_path,
			})
			key_accumulated = ""
			first_key_path = None
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
			})
			counter += 1
	# Flush any remaining accumulated keys at the end
	if key_accumulated:
		llm_format.append({
			"id": counter,
			"type": "type",
			"key": key_accumulated,
			"ss_path": first_key_path,
		})
		key_accumulated = ""
		first_key_path = None
		counter += 1
	# Append a final stop event with the next id
	llm_format.append({
		"id": counter,
		"type": "stop",
		"ss_path": make_screenshot_path(len(events)),
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
