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
		shutil.copy2(source, destination)
		copied_assets.add(key)
		copied = True
	else:
		copied = False

	asset_path = Path("data") / "assets" / slug / relative_path
	return asset_path.as_posix(), copied


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
			original_display = compute_display_path(source_path if source_path else task_dir / relative_asset_path, bases)
			attachments.append(
				{
					"index": step_index,
					"originalPath": original_display,
					"assetPath": asset_path,
				},
			)

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
		timeline.append({"role": "assistant", "content": assistant_event.get("raw", assistant_event.get("type", ""))})

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
