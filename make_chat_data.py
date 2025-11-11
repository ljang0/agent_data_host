import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from convert_raw import SCREENSHOT_DIR_OPTIONS, write_json

DEFAULT_SYSTEM_PROMPT = (
	"You are an agent viewing a screenshot from the user and then emitting the action. "
	"Clicks are provided as normalized ratios (x/width, y/height)."
)


def resolve_default_users_root() -> Path:
	return Path(__file__).resolve().parent.parent / "users"


def resolve_default_output_root() -> Path:
	return Path(__file__).resolve().parent / "data"


def slugify(value: str) -> str:
	value = value.strip().lower()
	value = re.sub(r"[^a-z0-9]+", "-", value)
	value = re.sub(r"-{2,}", "-", value)
	return value.strip("-")


def iter_task_directories(users_root: Path) -> Iterable[Tuple[str, Path]]:
	if not users_root.exists():
		return
	for user_dir in sorted((path for path in users_root.iterdir() if path.is_dir()), key=lambda p: p.name.lower()):
		for task_dir in sorted((path for path in user_dir.iterdir() if path.is_dir()), key=lambda p: p.name.lower()):
			if not (task_dir / "session_data.json").exists():
				continue
			if not any((task_dir / candidate).is_dir() for candidate in SCREENSHOT_DIR_OPTIONS):
				continue
			yield user_dir.name, task_dir


def read_json(path: Path) -> Any:
	with path.open("r", encoding="utf-8") as handle:
		return json.load(handle)


def normalise_relative_path(path: Path) -> Path:
	parts = [segment for segment in path.parts if segment not in {".", ""}]
	for index, part in enumerate(parts):
		if part in {"imgs", "videos", "frames_display_1"}:
			return Path(*parts[index:])
	if len(parts) > 2:
		return Path(*parts[-2:])
	if parts:
		return Path(*parts)
	return Path("event.png")


def resolve_screenshot(task_dir: Path, ss_path: Optional[str], fallback_index: int) -> Tuple[Optional[Path], Path]:
	if ss_path:
		raw_path = Path(ss_path)
	else:
		raw_path = Path("imgs") / f"event_{fallback_index}.png"

	if raw_path.is_absolute() and raw_path.exists():
		return raw_path, normalise_relative_path(raw_path)

	relative_candidate = raw_path
	candidate = task_dir / relative_candidate
	if candidate.exists():
		return candidate, normalise_relative_path(relative_candidate)

	for alt in SCREENSHOT_DIR_OPTIONS:
		alt_candidate = task_dir / alt / raw_path.name
		if alt_candidate.exists():
			return alt_candidate, alt / raw_path.name

	return None, normalise_relative_path(relative_candidate)


def compute_display_path(path: Path, bases: Sequence[Path]) -> str:
	for base in bases:
		try:
			return str(path.relative_to(base))
		except ValueError:
			continue
	return str(path)


def copy_asset(
	source: Optional[Path],
	assets_root: Path,
	slug: str,
	relative_path: Path,
	copied_assets: Set[str],
) -> Tuple[Optional[str], bool]:
	if source is None:
		return None, False

	destination = assets_root / slug / relative_path
	destination.parent.mkdir(parents=True, exist_ok=True)

	key = destination.as_posix()
	if key not in copied_assets:
		if not source.exists():
			print(f"Warning: missing screenshot {source}")
			return None, False
		try:
			if source.resolve() == destination.resolve():
				copied = False
			else:
				shutil.copy2(source, destination)
				copied = True
		except FileNotFoundError:
			print(f"Warning: missing screenshot {source}")
			return None, False
		copied_assets.add(key)
	else:
		copied = False

	asset_path = Path("data") / "assets" / slug / relative_path
	return asset_path.as_posix(), copied


def derive_annotated_relative_path(relative_path: Path) -> Path:
	"""Return the relative path for an annotated variant based on the source relative path."""
	parts = list(relative_path.parts)
	if not parts:
		return Path("annotated") / "event.png"

	filename = parts[-1]
	parent_parts = list(parts[:-1])

	if not parent_parts:
		annotated_parts = ["annotated"]
	else:
		annotated_parts = parent_parts.copy()
		last_segment = annotated_parts[-1]
		if last_segment == "imgs":
			annotated_parts[-1] = "imgs_annotated"
		elif last_segment.startswith("frames_display_"):
			annotated_parts[-1] = f"{last_segment}_annotated"
		elif last_segment.endswith("_annotated") or last_segment == "annotated":
			# Already annotated; leave as-is.
			pass
		else:
			annotated_parts.append("annotated")

	return Path(*annotated_parts) / filename


def derive_annotated_absolute_path(source_path: Path) -> Path:
	"""Return an absolute path pointing to the annotated variant of source_path."""
	parent = source_path.parent
	filename = source_path.name

	if parent.name == "imgs":
		return parent.with_name("imgs_annotated") / filename
	if parent.name.startswith("frames_display_"):
		return parent.with_name(f"{parent.name}_annotated") / filename
	if parent.name.endswith("_annotated") or parent.name == "annotated":
		return parent / filename

	return parent / "annotated" / filename


def resolve_annotated_variant(
	source_path: Optional[Path],
	relative_path: Path,
	task_dir: Path,
	assets_root: Path,
	slug: str,
) -> Tuple[Optional[Path], Path]:
	"""Locate an existing annotated variant for a screenshot, if present."""
	annotated_relative = derive_annotated_relative_path(relative_path)

	candidates = []
	if source_path and source_path.exists():
		candidates.append(derive_annotated_absolute_path(source_path))

	# Attempt lookup relative to the task directory (covers most annotation scripts).
	candidates.append(task_dir / annotated_relative)

	# Fallback: previously copied annotated asset under data/assets.
	candidates.append(assets_root / slug / annotated_relative)

	for candidate in candidates:
		if candidate and candidate.exists():
			return candidate, annotated_relative

	return None, annotated_relative


def build_assistant_event(event: Dict[str, Any]) -> Dict[str, Any]:
	action_type = event.get("type") or "unknown"
	assistant: Dict[str, Any] = {"type": action_type, "raw": action_type}

	if action_type == "click":
		x = event.get("x")
		y = event.get("y")
		width = event.get("width_display") or event.get("width")
		height = event.get("height_display") or event.get("height")
		if isinstance(x, (int, float)) and isinstance(y, (int, float)) and isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > 0 and height > 0:
			x_norm = x / width
			y_norm = y / height
			assistant["coordinates"] = {
				"x": round(x_norm, 6),
				"y": round(y_norm, 6),
				"xPercent": round(x_norm * 100, 4),
				"yPercent": round(y_norm * 100, 4),
			}
			assistant["raw"] = f"click: ({x_norm:.6f}, {y_norm:.6f})"
		else:
			assistant["raw"] = f"click: ({x}, {y})"
		if event.get("button"):
			assistant["button"] = event.get("button")
	elif action_type == "type":
		text = event.get("key") or ""
		assistant["text"] = text
		assistant["raw"] = f"type: {text}" if text else "type"
	elif action_type == "drag":
		start_x = event.get("start_x")
		start_y = event.get("start_y")
		end_x = event.get("end_x")
		end_y = event.get("end_y")
		width = event.get("width_display") or event.get("width")
		height = event.get("height_display") or event.get("height")
		start_coords = None
		end_coords = None
		if all(isinstance(value, (int, float)) for value in (start_x, start_y, width, height)) and width and height:
			start_x_norm = start_x / width
			start_y_norm = start_y / height
			start_coords = {
				"x": round(start_x_norm, 6),
				"y": round(start_y_norm, 6),
				"xPercent": round(start_x_norm * 100, 4),
				"yPercent": round(start_y_norm * 100, 4),
			}
		if all(isinstance(value, (int, float)) for value in (end_x, end_y, width, height)) and width and height:
			end_x_norm = end_x / width
			end_y_norm = end_y / height
			end_coords = {
				"x": round(end_x_norm, 6),
				"y": round(end_y_norm, 6),
				"xPercent": round(end_x_norm * 100, 4),
				"yPercent": round(end_y_norm * 100, 4),
			}
		if start_coords:
			assistant["startCoordinates"] = start_coords
		if end_coords:
			assistant["endCoordinates"] = end_coords
		if start_coords and end_coords:
			assistant["raw"] = (
				f"drag: ({start_coords['x']:.6f}, {start_coords['y']:.6f}) → ({end_coords['x']:.6f}, {end_coords['y']:.6f})"
			)
		else:
			assistant["raw"] = f"drag: ({start_x}, {start_y}) → ({end_x}, {end_y})"
		if event.get("button") is not None:
			assistant["button"] = event.get("button")
		if event.get("distance") is not None:
			assistant["distance"] = event.get("distance")
		if event.get("start_timestamp") is not None:
			assistant["startTimestamp"] = event.get("start_timestamp")
		if event.get("end_timestamp") is not None:
			assistant["endTimestamp"] = event.get("end_timestamp")
		if event.get("duration") is not None:
			assistant["duration"] = event.get("duration")
	elif action_type == "key_combination":
		combination = event.get("key") or ""
		translation = event.get("translation") or ""
		if combination:
			assistant["combination"] = combination
		if translation:
			assistant["translation"] = translation
		label = translation or combination
		assistant["raw"] = f"key_combination: {label}" if label else "key_combination"
	elif action_type == "scroll":
		direction = event.get("direction")
		total_amount = event.get("total_amount")
		duration = event.get("duration")
		individual = event.get("individual_scrolls")
		if isinstance(individual, list):
			individual_value = len(individual)
		elif isinstance(individual, (int, float)):
			individual_value = individual
		else:
			individual_value = None
		parts = [str(part) for part in (direction, total_amount, duration, individual_value) if part not in (None, "")]
		if parts:
			parameters = " ".join(parts)
			assistant["parameters"] = parameters
			assistant["raw"] = f"scroll: {parameters}"
		else:
			assistant["raw"] = "scroll"
	elif action_type == "stop":
		assistant["raw"] = "stop"

	chain_of_thought = (event.get("chain_of_thought") or "").strip()
	if chain_of_thought:
		assistant["chainOfThought"] = chain_of_thought
	thought_segments = event.get("thought_segments")
	if isinstance(thought_segments, list) and thought_segments:
		assistant["thoughtSegments"] = thought_segments

	assistant["ss_path"] = event.get("ss_path")
	return assistant


def build_task_entry(
	user_name: str,
	task_dir: Path,
	task_name: str,
	llm_events: List[Dict[str, Any]],
	session_data: Dict[str, Any],
	assets_root: Path,
	project_root: Path,
	users_root: Path,
	slug: str,
	copied_assets: Set[str],
) -> Tuple[Dict[str, Any], int]:
	steps: List[Dict[str, Any]] = []
	timeline: List[Dict[str, str]] = [{"role": "system", "content": DEFAULT_SYSTEM_PROMPT}]
	bases = [users_root.parent, users_root, project_root]
	asset_copies = 0

	for event in sorted(llm_events, key=lambda item: item.get("id", 0)):
		step_index = int(event.get("id", len(steps)))
		user_raw = f"<attachment:{step_index}>"
		user_text = ""
		if not steps:
			user_text = f"TASK:{task_name}"
			user_raw = f"{user_text} <attachment:{step_index}>"

		source_path, relative_asset_path = resolve_screenshot(task_dir, event.get("ss_path"), step_index)
		asset_path, copied = copy_asset(source_path, assets_root, slug, relative_asset_path, copied_assets)
		if copied:
			asset_copies += 1

		attachments: List[Dict[str, Any]] = []
		if asset_path:
			original_source = source_path if source_path else task_dir / relative_asset_path
			original_display = compute_display_path(original_source, bases)
			attachment_entry: Dict[str, Any] = {
				"index": step_index,
				"originalPath": original_display,
				"assetPath": asset_path,
			}

			annotated_source, annotated_relative = resolve_annotated_variant(source_path, relative_asset_path, task_dir, assets_root, slug)
			if annotated_source:
				annotated_asset_path, annotated_copied = copy_asset(annotated_source, assets_root, slug, annotated_relative, copied_assets)
				if annotated_copied:
					asset_copies += 1
				if annotated_asset_path:
					annotated_display = compute_display_path(annotated_source, bases)
					attachment_entry["annotatedAssetPath"] = annotated_asset_path
					attachment_entry["annotatedOriginalPath"] = annotated_display

			attachments.append(attachment_entry)

		assistant_event = build_assistant_event(event)

		step_entry = {
			"step": step_index,
			"user": {
				"raw": user_raw,
				"text": user_text,
				"attachments": attachments,
			},
			"assistant": assistant_event,
		}
		steps.append(step_entry)

		timeline.append({"role": "user", "content": user_raw})
		timeline.append({"role": "assistant", "content": format_assistant_timeline_entry(assistant_event)})

	action_breakdown: Dict[str, int] = {}
	for step in steps:
		action_type = step["assistant"].get("type", "unknown")
		action_breakdown[action_type] = action_breakdown.get(action_type, 0) + 1

	task_entry = {
		"name": task_name,
		"slug": slug,
		"sourceDir": compute_display_path(task_dir, bases),
		"systemPrompt": DEFAULT_SYSTEM_PROMPT,
		"stats": {
			"totalSteps": len(steps),
			"actionBreakdown": action_breakdown,
		},
		"steps": steps,
		"timeline": timeline,
		"metadata": session_data.get("metadata"),
		"user": user_name,
	}

	return task_entry, asset_copies


def extract_attachment_paths(task_entry: Dict[str, Any]) -> List[str]:
	"""Collect attachment asset paths ordered by index."""
	index_to_path: Dict[int, str] = {}
	steps = task_entry.get("steps") or []
	for step in steps:
		user_section = step.get("user") or {}
		for attachment in user_section.get("attachments") or []:
			index = attachment.get("index")
			if isinstance(index, int):
				path_value = attachment.get("assetPath") or attachment.get("originalPath")
				if isinstance(path_value, str) and path_value and index not in index_to_path:
					index_to_path[index] = path_value

	if not index_to_path:
		return []

	return [index_to_path[idx] for idx in sorted(index_to_path.keys())]


def write_chat_record(task_entry: Dict[str, Any], output_root: Path) -> Path:
	"""Write a chat.jsonl file for the given task entry."""
	task_slug = task_entry["slug"]
	task_dir = output_root / task_slug
	task_dir.mkdir(parents=True, exist_ok=True)

	record = {
		"task": task_entry.get("name"),
		"slug": task_slug,
		"messages": task_entry.get("timeline"),
		"attachments": extract_attachment_paths(task_entry),
	}

	chat_path = task_dir / "chat.jsonl"
	write_json(chat_path, record)
	return chat_path


def build_chat_dataset(users_root: Path, output_root: Path) -> Dict[str, Any]:
	project_root = Path(__file__).resolve().parent
	output_root.mkdir(parents=True, exist_ok=True)
	assets_root = output_root / "assets"
	assets_root.mkdir(parents=True, exist_ok=True)

	tasks: List[Dict[str, Any]] = []
	copied_assets: Set[str] = set()
	total_copied = 0
	used_slugs: Set[str] = set()

	for user_name, task_dir in iter_task_directories(users_root):
		session_path = task_dir / "session_data.json"
		llm_events_path = task_dir / "llm_events.json"

		if not llm_events_path.exists():
			print(f"Warning: missing llm_events.json for {task_dir}, skipping.")
			continue

		try:
			session_data = read_json(session_path)
			llm_events = read_json(llm_events_path)
		except Exception as exc:
			print(f"Warning: unable to load data for {task_dir}: {exc}")
			continue

		if not isinstance(llm_events, list):
			print(f"Warning: llm_events.json for {task_dir} is not a list, skipping.")
			continue

		task_name = session_data.get("taskName") or task_dir.name
		slug_base = slugify(f"{user_name}-{task_name}") or slugify(task_dir.name) or slugify(user_name) or "task"
		slug = slug_base
		counter = 2
		while slug in used_slugs:
			slug = f"{slug_base}-{counter}"
			counter += 1
		used_slugs.add(slug)

		task_entry, copied = build_task_entry(
			user_name=user_name,
			task_dir=task_dir,
			task_name=task_name,
			llm_events=llm_events,
			session_data=session_data,
			assets_root=assets_root,
			project_root=project_root,
			users_root=users_root,
			slug=slug,
			copied_assets=copied_assets,
		)

		write_chat_record(task_entry, output_root)
		tasks.append(task_entry)
		total_copied += copied

	tasks.sort(key=lambda item: item["name"].lower())

	payload = {
		"generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
		"taskCount": len(tasks),
		"tasks": tasks,
	}

	write_json(output_root / "trajectories.json", payload)

	return {
		"taskCount": len(tasks),
		"assetCount": total_copied,
		"assetsRoot": assets_root.as_posix(),
		"outputPath": (output_root / "trajectories.json").as_posix(),
	}


def format_assistant_timeline_entry(assistant_event: Dict[str, Any]) -> str:
	"""Compose a chat timeline entry that includes chain-of-thought when available."""
	parts: List[str] = []
	chain = (assistant_event.get("chainOfThought") or "").strip()
	if chain:
		parts.append(f"[thought] {chain}")
	raw = assistant_event.get("raw") or assistant_event.get("type") or ""
	if raw:
		parts.append(raw)
	return "\n".join(parts)


def main() -> None:
	parser = argparse.ArgumentParser(description="Build chat-friendly trajectory data from converted user sessions.")
	parser.add_argument(
		"--users-root",
		type=str,
		default=str(resolve_default_users_root()),
		help="Root directory containing per-user session folders (default: ../users).",
	)
	parser.add_argument(
		"--output-root",
		type=str,
		default=str(resolve_default_output_root()),
		help="Directory where trajectories.json and assets/ will be written (default: ./data).",
	)
	args = parser.parse_args()

	users_root = Path(args.users_root).expanduser().resolve()
	output_root = Path(args.output_root).expanduser().resolve()

	if not users_root.exists():
		raise FileNotFoundError(f"Users root does not exist: {users_root}")

	stats = build_chat_dataset(users_root, output_root)
	print(
		f"Wrote trajectories.json with {stats['taskCount']} task(s); "
		f"{stats['assetCount']} asset file(s) copied to {stats['assetsRoot']}.",
	)


if __name__ == "__main__":
	main()
