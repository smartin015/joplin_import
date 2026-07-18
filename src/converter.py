"""
Convert fetched Todoist data into JEX archive format.
"""

import hashlib
import time
from datetime import datetime, timezone

from todoist_api_python.models import Task, Comment

from .jex_builder import (
    JexArchive, JexFolder, JexNote, JexTag, JexResource,
)
from .recurrence_parser import RecurrenceData, parse_recurrence


def _to_unix(dt) -> int:
    """Convert a Todoist date/datetime/string/int to a Unix timestamp in SECONDS.

    Handles every format the Todoist API may return:
      - datetime objects        → .timestamp()
      - date objects            → via .year/.month/.day
      - ISO 8601 strings        → parsed
      - epoch millisecond ints  → divided by 1000
      - epoch second ints       → passed through
      - None / junk             → 0

    Never returns NaN, None, or negative values.
    """
    if dt is None:
        return 0

    # --- datetime (most common from todoist-api-python v2+) ---
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int(dt.timestamp()))

    # --- raw numbers: could be seconds or milliseconds ---
    if isinstance(dt, (int, float)):
        try:
            val = int(dt)
        except (ValueError, OverflowError):
            return 0
        # Heuristic: timestamps >= 1e12 (~year 33658) are milliseconds
        if val >= 1_000_000_000_000:
            val //= 1000
        return max(0, val)

    # --- ISO 8601 string ---
    if isinstance(dt, str):
        try:
            s = dt.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(s)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0, int(parsed.timestamp()))
        except (ValueError, AttributeError):
            return 0

    # --- date objects, ApiDate, and other types with .year/.month/.day ---
    try:
        d = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        return max(0, int(d.timestamp()))
    except (AttributeError, TypeError):
        pass

    # --- PatternBase (dataclass-wizard opaque type from older todoist-api-python) ---
    # Try .timestamp() as a last resort
    try:
        return max(0, int(dt.timestamp()))
    except (AttributeError, TypeError, ValueError):
        pass

    return 0


# Deterministic UUID generation from Todoist IDs
# We use a namespace UUID to generate deterministic UUIDs so that
# repeated imports don't create duplicates.
TODOIST_NAMESPACE = hashlib.md5(b"joplin-import-todoist").hexdigest()


def _make_uuid(todoist_id: str) -> str:
    """Generate a deterministic UUID from a Todoist ID."""
    return hashlib.md5(f"{TODOIST_NAMESPACE}:{todoist_id}".encode()).hexdigest()


def convert(data: dict) -> tuple[JexArchive, dict, dict]:
    """
    Convert fetched Todoist data into a JexArchive.

    Returns:
        (archive, recurrence_map, metadata)

        recurrence_map: {note_uuid: RecurrenceData} for post-import processing
        metadata: dict with stats for the post-import script
    """
    archive = JexArchive()
    recurrence_map: dict[str, RecurrenceData] = {}

    projects = data["projects"]
    sections = data["sections"]
    labels = data["labels"]
    tasks = data["tasks"]
    task_order = data["task_order"]
    task_map = data["task_map"]

    # ID mapping: Todoist ID → JEX UUID
    folder_id_map: dict[str, str] = {}   # project/section id → folder uuid
    note_id_map: dict[str, str] = {}     # task id → note uuid
    tag_id_map: dict[str, str] = {}      # label id → tag uuid
    tag_name_map: dict[str, str] = {}    # label name → tag uuid

    # --- FOLDERS (Projects) ---
    print("Converting projects to folders...")
    for proj in projects.values():
        folder = JexFolder(
            title=proj.name,
            folder_id=_make_uuid(proj.id),
            created_time=_to_unix(proj.created_at),
            updated_time=_to_unix(proj.updated_at),
        )
        fid = archive.add_folder(folder)
        folder_id_map[proj.id] = fid

    # --- FOLDERS (Sections → sub-folders) ---
    print("Converting sections to sub-folders...")
    for sec in sections.values():
        parent_folder_id = folder_id_map.get(sec.project_id, "")
        folder = JexFolder(
            title=sec.name,
            parent_id=parent_folder_id,
            folder_id=_make_uuid(sec.id),
            created_time=int(time.time()),
            updated_time=int(time.time()),
        )
        fid = archive.add_folder(folder)
        folder_id_map[sec.id] = fid

    # --- TAGS (Labels) ---
    print("Converting labels to tags...")
    for label in labels.values():
        tag = JexTag(
            title=label.name,
            tag_id=_make_uuid(label.id),
            created_time=int(time.time()),
            updated_time=int(time.time()),
        )
        tid = archive.add_tag(tag)
        tag_id_map[label.id] = tid
        tag_name_map[label.name.lower()] = tid

    # --- NOTES (Tasks) ---
    print(f"Converting {len(task_order)} tasks to notes...")
    completed_count = 0
    recurring_count = 0

    for tid in task_order:
        task_entry = tasks.get(tid)
        if not task_entry:
            continue

        task: Task = task_entry["task"]
        comments: list[Comment] = task_entry["comments"]
        attachment_data: list[tuple] = task_entry["attachments"]

        # Determine parent folder (section takes precedence over project)
        parent_folder_id = ""
        if task.section_id and task.section_id in folder_id_map:
            parent_folder_id = folder_id_map[task.section_id]
        elif task.project_id and task.project_id in folder_id_map:
            parent_folder_id = folder_id_map[task.project_id]

        # Determine if completed
        is_completed = task.completed_at is not None
        if is_completed:
            completed_count += 1

        # Build body from description + comments + attachments
        body_parts = []

        # Task description
        if task.description:
            body_parts.append(task.description.strip())

        # Duration
        if task.duration:
            amount = task.duration.get("amount") if isinstance(task.duration, dict) else getattr(task.duration, 'amount', None)
            unit = task.duration.get("unit") if isinstance(task.duration, dict) else getattr(task.duration, 'unit', None)
            if amount and unit:
                body_parts.append(f"\n---\n**Duration:** {amount} {unit}(s)")

        # Priority
        if task.priority and task.priority > 1:
            priority_label = {2: "p3", 3: "p2", 4: "p1"}.get(task.priority, f"p{task.priority}")
            body_parts.append(f"**Priority:** {priority_label}")

        # Source URL
        source_url = f"https://todoist.com/showTask?id={task.id}"

        # Process attachments from comments with markdown body embedding
        resource_refs = []
        for att, file_data in attachment_data:
            filename = att.file_name or "attachment"
            mime = att.file_type or _mime_from_filename(filename)

            res = JexResource(
                filename=filename,
                mime_type=mime,
                data=file_data,
                title=att.title or filename,
                resource_id=_make_uuid(f"{task.id}-{att.file_name}-{att.file_size}"),
                created_time=_to_unix(task.created_at),
            )
            rid = archive.add_resource(res)

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            is_image = mime and mime.startswith("image/")

            if is_image:
                resource_refs.append(f"![](:/{rid})")
            else:
                resource_refs.append(f"[{filename}](:/{rid})")

        if resource_refs:
            body_parts.append("\n**Attachments:**\n" + "\n".join(resource_refs))

        # Comments
        if comments:
            body_parts.append("\n---\n## Comments\n")
            for comment in comments:
                # Skip comments that are just attachment placeholders with no text
                if not comment.content and comment.attachment:
                    continue
                posted = comment.posted_at
                if isinstance(posted, datetime):
                    date_str = posted.strftime("%Y-%m-%d %H:%M")
                else:
                    date_str = str(posted) if posted else "unknown date"
                poster = comment.poster_id or "unknown"
                body_parts.append(f"**{poster}** ({date_str}):\n{comment.content}\n")

        body = "\n\n".join(body_parts)

        # Determine due date
        todo_due = 0
        if task.due:
            # due.date can be a date or datetime
            due_date = task.due.date
            if due_date:
                todo_due = _to_unix(due_date)

        # Completion time
        todo_completed = _to_unix(task.completed_at) if task.completed_at else 0

        note = JexNote(
            title=task.content,
            body=body,
            note_id=_make_uuid(task.id),
            parent_id=parent_folder_id,
            is_todo=1,
            todo_due=todo_due,
            todo_completed=todo_completed,
            created_time=_to_unix(task.created_at),
            updated_time=_to_unix(task.updated_at),
            source_url=source_url,
            source="todoist",
            source_application="todoist_to_jex",
        )

        note_id = archive.add_note(note)
        note_id_map[task.id] = note_id

        # Link labels to this note
        if task.labels:
            for label_name in task.labels:
                label_key = label_name.lower()
                if label_key in tag_name_map:
                    archive.add_note_tag(note_id, tag_name_map[label_key])

        # Handle recurrence
        if task.due and task.due.is_recurring:
            rec = parse_recurrence(task.due.string, task.due.is_recurring)
            if rec:
                recurrence_map[note_id] = rec
                recurring_count += 1

    print(f"  Completed tasks: {completed_count}")
    print(f"  Recurring tasks: {recurring_count}")

    metadata = {
        "total_projects": len(projects),
        "total_sections": len(sections),
        "total_labels": len(labels),
        "total_tasks": len(task_order),
        "completed_tasks": completed_count,
        "recurring_tasks": recurring_count,
    }

    return archive, recurrence_map, metadata


def _mime_from_filename(filename: str) -> str:
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"
