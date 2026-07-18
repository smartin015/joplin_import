#!/usr/bin/env python3
"""
Todoist → Joplin Migration Tool

Fetches all tasks, projects, sections, labels, comments, and file attachments
from Todoist via the REST API and produces:
  1. A JEX (.tar) file that can be imported into Joplin via File → Import
  2. A post-import data directory for recurring task recurrence settings
     (because JEX cannot store the userData that the Repeating TODOs plugin needs)

Usage:
    python todoist_to_jex.py --api-token <token> [options]

Options:
    --output-dir DIR      Output directory (default: ./output)
    --project-filter NAME Only export tasks from projects matching this name
    --include-completed   Include completed tasks (default: exclude)
    --skip-attachments    Skip downloading file attachments
"""

import argparse
import os
import sys

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.todoist_fetcher import fetch_all
from src.converter import convert
from src.post_import import generate_post_import_data


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Todoist tasks to Joplin JEX format"
    )
    parser.add_argument(
        "--api-token", "-t",
        required=True,
        help="Todoist API token (from https://todoist.com/app/settings/integrations/developer)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="./output",
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--project-filter", "-p",
        help="Only export tasks from projects whose name contains this string",
    )
    parser.add_argument(
        "--include-completed",
        action="store_true",
        help="Include completed tasks (default: skip completed)",
    )
    parser.add_argument(
        "--skip-attachments",
        action="store_true",
        help="Skip downloading file attachments",
    )

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # Phase 1: Fetch from Todoist
    print("=" * 60)
    print("PHASE 1: Fetching data from Todoist API")
    print("=" * 60)
    data = fetch_all(args.api_token)

    # Apply filters
    if args.project_filter:
        filter_lower = args.project_filter.lower()
        filtered_projects = {
            pid: proj
            for pid, proj in data["projects"].items()
            if filter_lower in proj.name.lower()
        }
        if not filtered_projects:
            print(f"ERROR: No projects matching '{args.project_filter}' found.")
            print(f"Available projects: {[p.name for p in data['projects'].values()]}")
            sys.exit(1)

        valid_project_ids = set(filtered_projects.keys())
        data["projects"] = filtered_projects

        # Filter sections
        data["sections"] = {
            sid: sec
            for sid, sec in data["sections"].items()
            if sec.project_id in valid_project_ids
        }

        # Filter tasks
        filtered_tasks = {}
        filtered_order = []
        for tid in data["task_order"]:
            entry = data["tasks"].get(tid)
            if entry and entry["task"].project_id in valid_project_ids:
                filtered_tasks[tid] = entry
                filtered_order.append(tid)
        data["tasks"] = filtered_tasks
        data["task_order"] = filtered_order

        print(f"Filtered to {len(filtered_projects)} project(s)")
        print(f"  Tasks remaining: {len(filtered_order)}")

    # Filter completed tasks unless --include-completed
    if not args.include_completed:
        before = len(data["task_order"])
        filtered_tasks = {}
        filtered_order = []
        for tid in data["task_order"]:
            entry = data["tasks"].get(tid)
            if entry and not entry["task"].completed_at:
                filtered_tasks[tid] = entry
                filtered_order.append(tid)
        data["tasks"] = filtered_tasks
        data["task_order"] = filtered_order
        removed = before - len(filtered_order)
        if removed > 0:
            print(f"Excluded {removed} completed tasks")

    # Phase 2: Convert to JEX
    print()
    print("=" * 60)
    print("PHASE 2: Converting to JEX format")
    print("=" * 60)
    archive, recurrence_map, metadata = convert(data)

    # Phase 3: Write output
    print()
    print("=" * 60)
    print("PHASE 3: Writing output")
    print("=" * 60)

    jex_path = os.path.join(args.output_dir, "todoist_export.jex")
    archive.write(jex_path)

    # Post-import data
    post_import_dir = os.path.join(args.output_dir, "post_import")
    if recurrence_map:
        json_path = generate_post_import_data(recurrence_map, post_import_dir)
        print(f"\nRecurrence data written to: {json_path}")
        print(f"  {len(recurrence_map)} recurring tasks need post-import processing")
        print(f"  See: {os.path.join(post_import_dir, 'apply_recurrence.md')}")
    else:
        print("\nNo recurring tasks found — no post-import processing needed.")

    print()
    print("=" * 60)
    print("IMPORT COMPLETE")
    print("=" * 60)
    print(f"""
Next Steps:
  1. In Joplin, go to File → Import → JEX and select:
     {jex_path}

  2. Install the "Repeating TODOs" plugin from:
     Tools → Options → Plugins → search "Repeating To-Dos"
""")
    if recurrence_map:
        print(f"""
  3. Apply recurrence settings by following the instructions in:
     {os.path.join(post_import_dir, 'apply_recurrence.md')}
""")


if __name__ == "__main__":
    main()
