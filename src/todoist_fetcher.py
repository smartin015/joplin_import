"""
Fetch all relevant data from Todoist API.
"""

import requests
from datetime import datetime, timezone
from collections.abc import Iterator
from typing import Optional
from todoist_api_python.api import TodoistAPI
from todoist_api_python.models import Task, Project, Section, Comment, Label, Attachment


def _to_unix(dt) -> int:
    """Convert an ApiDate/ApiDue (date or datetime) to Unix timestamp."""
    if dt is None:
        return 0
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    # It's a date object
    d = datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    return int(d.timestamp())


def _download_file(url: str, token: str) -> Optional[bytes]:
    """Download a file attachment from Todoist."""
    try:
        # Todoist attachment URLs need Authorization header
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        print(f"  WARNING: Failed to download attachment {url}: {e}")
        return None


def _mime_from_filename(filename: str) -> str:
    """Guess MIME type from filename extension."""
    import mimetypes
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def _collect_pages(paginated: Iterator[list]) -> list:
    """Flatten a paginated API response (Iterator[list[X]]) into a single list."""
    result = []
    for page in paginated:
        result.extend(page)
    return result


def fetch_all(api_token: str) -> dict:
    """
    Fetch all data from Todoist and return a structured dict.

    Returns:
        {
            "projects": {id: Project},
            "sections": {id: Section},
            "labels": {id: Label},
            "tasks": dict of enriched task dicts:
                {
                    "task": Task,
                    "comments": [Comment],
                    "attachments": [(Attachment, bytes)],  # (attachment, file_data)
                },
            "task_order": list of task ids in dependency order (parents before children),
        }
    """
    api = TodoistAPI(api_token)

    print("Fetching projects...")
    projects = {}
    for page in api.get_projects():
        for p in page:
            projects[p.id] = p
    print(f"  Got {len(projects)} projects")

    print("Fetching sections...")
    sections = {}
    for page in api.get_sections():
        for s in page:
            sections[s.id] = s
    print(f"  Got {len(sections)} sections")

    print("Fetching labels...")
    labels = {}
    for page in api.get_labels():
        for l in page:
            labels[l.id] = l
    print(f"  Got {len(labels)} labels")

    print("Fetching tasks...")
    all_tasks = _collect_pages(api.get_tasks())
    print(f"  Got {len(all_tasks)} tasks")

    # Build task map and parent→children relationship
    task_map: dict[str, Task] = {}
    children_map: dict[str, list[str]] = {}  # parent_id → [child_id]
    root_tasks: list[str] = []

    for task in all_tasks:
        task_map[task.id] = task
        if task.parent_id:
            children_map.setdefault(task.parent_id, []).append(task.id)
        else:
            root_tasks.append(task.id)

    # Build task order: parents before children (topological)
    task_order = []
    visited = set()

    def add_task(tid):
        if tid in visited:
            return
        visited.add(tid)
        task_order.append(tid)
        for child_id in children_map.get(tid, []):
            add_task(child_id)

    for tid in root_tasks:
        add_task(tid)
    # Also add any remaining tasks not reached (shouldn't happen normally)
    for tid in task_map:
        add_task(tid)

    print(f"  Task order: {len(task_order)} tasks (parents before children)")

    # Fetch comments and attachments for each task
    print("Fetching comments and attachments...")
    task_data: dict[str, dict] = {}
    total_comments = 0
    total_attachments = 0

    for i, task in enumerate(all_tasks):
        if i % 50 == 0 and i > 0:
            print(f"  Progress: {i}/{len(all_tasks)} tasks...")

        comments = []
        attachments = []

        try:
            for page in api.get_comments(task_id=task.id):
                for comment in page:
                    comments.append(comment)
                    total_comments += 1

                    if comment.attachment:
                        att = comment.attachment
                        # Download the file
                        file_url = att.file_url
                        if not file_url:
                            # Some attachments use the url field instead
                            file_url = getattr(att, 'url', None)

                        if file_url:
                            file_data = _download_file(file_url, api_token)
                            if file_data:
                                attachments.append((att, file_data))
                                total_attachments += 1

        except Exception as e:
            print(f"  WARNING: Failed to fetch comments for task {task.id}: {e}")

        task_data[task.id] = {
            "task": task,
            "comments": comments,
            "attachments": attachments,
        }

    print(f"  Total comments: {total_comments}")
    print(f"  Total attachments: {total_attachments}")

    return {
        "projects": projects,
        "sections": sections,
        "labels": labels,
        "tasks": task_data,
        "task_order": task_order,
        "task_map": task_map,
    }
