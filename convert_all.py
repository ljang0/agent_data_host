import argparse
from pathlib import Path
from typing import List, Tuple

from convert_raw import convert_to_llm_format, load_all_tasks, write_json
from make_chat_data import build_chat_dataset, resolve_default_output_root


def resolve_default_users_root() -> Path:
	"""Resolve the default users root relative to this script."""
	return Path(__file__).resolve().parent.parent / "users"


def iter_user_directories(users_root: Path) -> List[Path]:
	if not users_root.exists():
		return []
	return sorted(
		[entry for entry in users_root.iterdir() if entry.is_dir()],
		key=lambda path: path.name.lower(),
	)


def convert_user_tasks(user_dir: Path) -> List[Tuple[Path, Path]]:
	"""Convert all tasks for a single user directory.

	Returns a list of (task_dir, output_path) tuples that were generated.
	"""
	results: List[Tuple[Path, Path]] = []
	for task_dir, session_json in load_all_tasks(user_dir):
		llm_events = convert_to_llm_format(task_dir, session_json)
		output_path = task_dir / "llm_events.json"
		write_json(output_path, llm_events)
		results.append((task_dir, output_path))
	return results


def main() -> None:
	parser = argparse.ArgumentParser(description="Convert session_data.json files for every user directory under /users.")
	parser.add_argument(
		"--users-root",
		type=str,
		default=str(resolve_default_users_root()),
		help="Root directory containing per-user subdirectories.",
	)
	parser.add_argument(
		"--output-root",
		type=str,
		default=str(resolve_default_output_root()),
		help="Destination root for aggregated chat data (default: ./data).",
	)
	parser.add_argument(
		"--skip-chat-data",
		action="store_true",
		help="Skip rebuilding chat data artifacts after conversion.",
	)
	args = parser.parse_args()

	users_root = Path(args.users_root).expanduser().resolve()
	output_root = Path(args.output_root).expanduser().resolve()

	if not users_root.exists():
		raise FileNotFoundError(f"Users root does not exist: {users_root}")

	user_dirs = iter_user_directories(users_root)

	print(f"Scanning user directories in {users_root}")
	total_converted = 0
	for user_dir in user_dirs:
		converted = convert_user_tasks(user_dir)
		if converted:
			print(f"- {user_dir.name}: converted {len(converted)} task(s)")
			total_converted += len(converted)
		else:
			print(f"- {user_dir.name}: no tasks found")

	suffix = "y" if len(user_dirs) == 1 else "ies"
	print(f"Converted {total_converted} task(s) across {len(user_dirs)} user director{suffix}.")

	if args.skip_chat_data:
		return

	dataset_stats = build_chat_dataset(users_root, output_root)
	print(
		f"Chat dataset updated: {dataset_stats['taskCount']} task(s), "
		f"{dataset_stats['assetCount']} asset file(s) copied to {dataset_stats['assetsRoot']}",
	)


if __name__ == "__main__":
	main()
