#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw


CLICK_REGEX = re.compile(r"click\s*:?[\s]*\(([+-]?\d*\.?\d+)[\s]*,[\s]*([+-]?\d*\.?\d+)\)", re.IGNORECASE)
ATTACHMENT_REGEX = re.compile(r"<attachment:(\d+)>", re.IGNORECASE)

SCREENSHOT_DIR_PREFERENCE = (
    Path("imgs"),
    Path("videos") / "frames_display_1",
    Path("frames_display_1"),
)

def parse_json_or_jsonl(chat_path: Path) -> Dict:
    """Return a dict with keys: messages, attachments (optional), task (optional).

    Supports either a single-JSON object file or a JSONL file with one object.
    """
    try:
        with chat_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            # Ensure shape
            if not isinstance(data, dict) or "messages" not in data:
                raise ValueError("Unexpected JSON format: missing 'messages'")
            return data
    except json.JSONDecodeError:
        # Try JSONL (first valid JSON line)
        messages: Optional[List[Dict]] = None
        attachments: Optional[List[str]] = None
        task: Optional[str] = None
        with chat_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and "messages" in obj:
                    messages = obj.get("messages")
                    attachments = obj.get("attachments")
                    task = obj.get("task")
                    break
        if messages is None:
            raise ValueError("Could not parse chat file as JSON or JSONL with 'messages'")
        result = {"messages": messages}
        if attachments is not None:
            result["attachments"] = attachments
        if task is not None:
            result["task"] = task
        return result


def resolve_image_output_path(image_path: Path) -> Path:
    """Return a sibling directory for annotated output."""
    parent = image_path.parent
    if parent.name.startswith("frames_display_") or parent.name == "imgs":
        out_parent = parent.with_name(parent.name + "_annotated")
    else:
        out_parent = parent / "annotated"
    out_parent.mkdir(parents=True, exist_ok=True)
    return out_parent / image_path.name


def find_alternative_image(image_path: Path) -> Optional[Path]:
    """Attempt to locate the same filename within known screenshot folders."""
    filename = image_path.name
    candidate_parents = [
        image_path.parent,
        image_path.parent.parent if image_path.parent.parent != image_path.parent else None,
    ]
    for parent in filter(None, candidate_parents):
        for relative_dir in SCREENSHOT_DIR_PREFERENCE:
            candidate_dir = parent / relative_dir
            if candidate_dir.is_dir():
                alternative = candidate_dir / filename
                if alternative.exists():
                    return alternative
    return None


def draw_red_dot(image_path: Path, x_ratio: float, y_ratio: float, out_path: Optional[Path] = None) -> Path:
    img = Image.open(image_path).convert("RGBA")
    width, height = img.size

    # Clamp ratios to [0,1] to avoid out-of-bounds
    x_ratio = max(0.0, min(1.0, x_ratio))
    y_ratio = max(0.0, min(1.0, y_ratio))

    x_px = int(round(x_ratio * (width - 1)))
    y_px = int(round(y_ratio * (height - 1)))

    # Dot radius relative to size, with sensible min/max
    base = min(width, height)
    radius = max(4, min(12, int(round(base * 0.01))))

    draw = ImageDraw.Draw(img, "RGBA")
    # Outer white ring for visibility
    ring_r = radius + 2
    draw.ellipse((x_px - ring_r, y_px - ring_r, x_px + ring_r, y_px + ring_r), fill=(255, 255, 255, 180))
    # Inner red dot
    draw.ellipse((x_px - radius, y_px - radius, x_px + radius, y_px + radius), fill=(230, 15, 15, 255))

    if out_path is None:
        out_path = resolve_image_output_path(image_path)
    img.save(out_path)
    return out_path


def parse_click_from_text(text: str) -> Optional[Tuple[float, float]]:
    m = CLICK_REGEX.search(text)
    if not m:
        return None
    try:
        x = float(m.group(1))
        y = float(m.group(2))
        return x, y
    except Exception:
        return None


def parse_attachment_index(text: str) -> Optional[int]:
    m = ATTACHMENT_REGEX.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def is_image_path_text(text: str) -> bool:
    # Heuristic: looks like a path and ends with image extension
    t = text.strip()
    return t.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and ("/" in t or "\\" in t)


def annotate_chat(chat_path: Path, workspace_root: Optional[Path] = None) -> List[Path]:
    data = parse_json_or_jsonl(chat_path)
    messages: List[Dict] = data.get("messages", [])
    attachments: List[str] = []

    def normalise_attachment(entry: Any) -> Optional[str]:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            for key in ("assetPath", "originalPath", "path", "relativePath"):
                value = entry.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None

    raw_attachments = data.get("attachments", []) or []
    if isinstance(raw_attachments, Iterable) and not isinstance(raw_attachments, (str, bytes)):
        for entry in raw_attachments:
            path_value = normalise_attachment(entry)
            if path_value:
                attachments.append(path_value)

    if workspace_root is None:
        # Assume script is inside workspace root
        workspace_root = chat_path.parents[2] if len(chat_path.parents) >= 2 else Path.cwd()

    out_paths: List[Path] = []

    current_image: Optional[Path] = None

    def resolve_path(p: str) -> Path:
        pp = Path(p)
        if pp.is_absolute():
            return pp
        candidates = [
            workspace_root / pp,
            chat_path.parent / pp,
            Path.cwd() / pp,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""

        # Update current image when an attachment reference appears
        idx = parse_attachment_index(content)
        if idx is not None and 0 <= idx < len(attachments):
            current_image = resolve_path(attachments[idx])

        # Update current image when assistant posts an explicit image path
        if role == "assistant" and is_image_path_text(content):
            path_text = content.strip()
            current_image = resolve_path(path_text)

        # If we see a click, annotate on the current image
        click = parse_click_from_text(content)
        if click and current_image:
            x_ratio, y_ratio = click
            if not current_image.exists():
                # Try to resolve relative to chat file directory as fallback
                alt_candidates = [
                    chat_path.parent / current_image,
                    workspace_root / current_image,
                    find_alternative_image(current_image),
                ]
                for alt in alt_candidates:
                    if alt and alt.exists():
                        current_image = alt
                        break
            if current_image.exists():
                out_paths.append(draw_red_dot(current_image, x_ratio, y_ratio))

    return out_paths


def iter_chat_files(chat: Optional[Path], chat_root: Optional[Path]) -> Iterable[Path]:
    if chat:
        yield chat
        return
    if not chat_root:
        return
    root = chat_root.resolve()
    if root.is_file() and root.name == "chat.jsonl":
        yield root
        return
    if not root.exists():
        raise FileNotFoundError(f"Chat root does not exist: {root}")
    for path in sorted(root.rglob("chat.jsonl"), key=lambda p: p.as_posix()):
        yield path


def main() -> None:
    parser = argparse.ArgumentParser(description="Annotate click actions on images using normalized (x,y) ratios.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--chat", type=Path, help="Path to a single chat.jsonl file.")
    group.add_argument("--chat-root", type=Path, help="Directory to search for chat.jsonl files (annotates all found).")
    parser.add_argument("--workspace", type=Path, default=None, help="Workspace root (defaults to repo root)")
    args = parser.parse_args()

    any_outputs = False
    for chat_path in iter_chat_files(args.chat, args.chat_root):
        print(f"Annotating chat: {chat_path}")
        try:
            outputs = annotate_chat(chat_path, args.workspace)
        except Exception as exc:
            print(f"  Failed to annotate {chat_path}: {exc}")
            continue
        if outputs:
            any_outputs = True
            for out in outputs:
                print(f"  -> {out}")
        else:
            print("  No annotations produced (no clicks found or no images resolved).")

    if not any_outputs:
        print("Finished without creating any new annotations.")


if __name__ == "__main__":
    main()
