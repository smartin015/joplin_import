"""
Build JEX (Joplin Export Format) archives.

JEX is a .tar file containing:
  {uuid}.md               # Note files (type_: 1)
  {uuid}.md               # Folder files (type_: 2)
  {uuid}.md               # Resource metadata files (type_: 4)
  {uuid}.md               # Tag files (type_: 5)
  {uuid}_{uuid}.md        # Note-Tag association files (type_: 6)
  resources/{uuid}.{ext}  # Binary resource files

Each .md file has:
  Title (first line)
  (blank line)
  Body (markdown, for notes)
  (blank line)
  key: value pairs (metadata) — timestamps are ISO 8601 strings
  type_: N (last line)
"""

import os
import tarfile
import uuid
import time
import io
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass


def _ts_to_iso(ts: int) -> str:
    """Convert a Unix timestamp (seconds) to Joplin ISO 8601 format.

    Joplin uses strings like: 2026-05-02T23:50:54.769Z
    Our converter produces Unix epoch ints, so we format them here.
    """
    if ts <= 0:
        return ""
    try:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (ValueError, OSError, OverflowError):
        return ""


def _safe_int(val, default: int = 0) -> int:
    """Coerce a value to int, returning *default* on NaN, None, or junk."""
    if val is None:
        return default
    try:
        i = int(val)
        if i != i:  # NaN check (NaN != NaN)
            return default
        return i
    except (ValueError, TypeError, OverflowError):
        return default


@dataclass
class JexNote:
    """Represents a note (task) in the JEX format."""
    title: str
    body: str = ""
    parent_id: Optional[str] = None
    is_todo: int = 1
    todo_due: int = 0           # Unix timestamp, 0 = no due date
    todo_completed: int = 0     # Unix timestamp, 0 = not completed
    created_time: int = 0       # Unix timestamp (seconds)
    updated_time: int = 0       # Unix timestamp (seconds)
    source_url: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    author: str = ""
    source: str = ""
    source_application: str = ""
    markup_language: int = 1    # 1 = Markdown
    is_shared: int = 0
    application_data: str = ""
    note_id: Optional[str] = None

    def get_id(self) -> str:
        if self.note_id is None:
            self.note_id = uuid.uuid4().hex
        return self.note_id

    def serialize(self) -> str:
        """Serialize to JEX .md format matching Joplin's own export."""
        lines = [self.title, ""]
        if self.body:
            lines.append(self.body)
            lines.append("")

        ct = _safe_int(self.created_time)
        ut = _safe_int(self.updated_time)

        props = [
            f"id: {self.get_id()}",
            f"parent_id: {self.parent_id or ''}",
            f"created_time: {_ts_to_iso(ct)}",
            f"updated_time: {_ts_to_iso(ut)}",
            "is_conflict: 0",
            f"latitude: {self.latitude:.7f}",
            f"longitude: {self.longitude:.7f}",
            f"altitude: {self.altitude:.4f}",
            f"author: {self.author}",
            f"source_url: {self.source_url}",
            f"is_todo: {_safe_int(self.is_todo)}",
            f"todo_due: {_safe_int(self.todo_due)}",
            f"todo_completed: {_safe_int(self.todo_completed)}",
            f"source: {self.source}",
            f"source_application: {self.source_application}",
            f"application_data: {self.application_data}",
            "order: 0",
            f"user_created_time: {_ts_to_iso(ct)}",
            f"user_updated_time: {_ts_to_iso(ut)}",
            "encryption_cipher_text: ",
            "encryption_applied: 0",
            f"markup_language: {_safe_int(self.markup_language)}",
            f"is_shared: {_safe_int(self.is_shared)}",
            "share_id: ",
            "conflict_original_id: ",
            "master_key_id: ",
            "user_data: ",
            "deleted_time: 0",
            "type_: 1",
        ]

        lines.append("\n".join(props))
        return "\n".join(lines)


@dataclass
class JexFolder:
    """Represents a folder (notebook) in the JEX format."""
    title: str
    parent_id: str = ""
    folder_id: Optional[str] = None
    created_time: int = 0
    updated_time: int = 0
    is_shared: int = 0

    def get_id(self) -> str:
        if self.folder_id is None:
            self.folder_id = uuid.uuid4().hex
        return self.folder_id

    def serialize(self) -> str:
        lines = [self.title, ""]
        props = [
            f"id: {self.get_id()}",
            f"parent_id: {self.parent_id}",
            f"created_time: {_ts_to_iso(_safe_int(self.created_time))}",
            f"updated_time: {_ts_to_iso(_safe_int(self.updated_time))}",
            f"is_shared: {_safe_int(self.is_shared)}",
            "type_: 2",
        ]
        lines.append("\n".join(props))
        return "\n".join(lines)


@dataclass
class JexTag:
    """Represents a tag in the JEX format."""
    title: str
    tag_id: Optional[str] = None
    created_time: int = 0
    updated_time: int = 0

    def get_id(self) -> str:
        if self.tag_id is None:
            self.tag_id = uuid.uuid4().hex
        return self.tag_id

    def serialize(self) -> str:
        lines = [self.title, ""]
        props = [
            f"id: {self.get_id()}",
            f"created_time: {_ts_to_iso(_safe_int(self.created_time))}",
            f"updated_time: {_ts_to_iso(_safe_int(self.updated_time))}",
            "type_: 5",
        ]
        lines.append("\n".join(props))
        return "\n".join(lines)


@dataclass
class JexNoteTag:
    """Represents a note-tag association in JEX format."""
    note_id: str
    tag_id: str

    def get_filename(self) -> str:
        """JEX note-tag file naming: {note_id}_{tag_id}.md"""
        return f"{self.note_id}_{self.tag_id}.md"

    def serialize(self) -> str:
        lines = ["", ""]
        props = [
            f"id: {self.note_id}_{self.tag_id}",
            f"note_id: {self.note_id}",
            f"tag_id: {self.tag_id}",
            "type_: 6",
        ]
        lines.append("\n".join(props))
        return "\n".join(lines)


@dataclass
class JexResource:
    """Represents a resource (attachment) in JEX format."""
    filename: str
    mime_type: str
    data: bytes
    title: str = ""
    resource_id: Optional[str] = None
    created_time: int = 0
    updated_time: int = 0

    def get_id(self) -> str:
        if self.resource_id is None:
            self.resource_id = uuid.uuid4().hex
        return self.resource_id

    def serialize_metadata(self) -> str:
        """Serialize the resource metadata .md file."""
        title = self.title or self.filename
        # file_extension without leading dot (Joplin format: "jpg", not ".jpg")
        _, ext = os.path.splitext(self.filename)
        ext = ext.lstrip(".")
        size = len(self.data)
        ct = _safe_int(self.created_time)
        ut = _safe_int(self.updated_time)

        lines = [title, ""]
        props = [
            f"id: {self.get_id()}",
            f"mime: {self.mime_type}",
            # Joplin often leaves filename empty for resources
            "filename: ",
            f"created_time: {_ts_to_iso(ct)}",
            f"updated_time: {_ts_to_iso(ut)}",
            f"user_created_time: {_ts_to_iso(ct)}",
            f"user_updated_time: {_ts_to_iso(ut)}",
            f"file_extension: {ext}",
            "encryption_cipher_text: ",
            "encryption_applied: 0",
            "encryption_blob_encrypted: 0",
            f"size: {size}",
            "is_shared: 0",
            "share_id: ",
            "master_key_id: ",
            "user_data: ",
            "blob_updated_time: 0",
            "ocr_text: ",
            "ocr_details: ",
            "ocr_status: 0",
            "ocr_error: ",
            "ocr_driver_id: 0",
            "type_: 4",
        ]
        lines.append("\n".join(props))
        return "\n".join(lines)

    def get_resource_filename(self) -> str:
        """Get the filename used for the binary blob in resources/."""
        _, ext = os.path.splitext(self.filename)
        return f"{self.get_id()}{ext}"


class JexArchive:
    """Builds a complete JEX archive from collected items."""

    def __init__(self):
        self.notes: list[JexNote] = []
        self.folders: list[JexFolder] = []
        self.tags: list[JexTag] = []
        self.note_tags: list[JexNoteTag] = []
        self.resources: list[JexResource] = []

    def add_folder(self, folder: JexFolder) -> str:
        fid = folder.get_id()
        self.folders.append(folder)
        return fid

    def add_note(self, note: JexNote) -> str:
        nid = note.get_id()
        self.notes.append(note)
        return nid

    def add_tag(self, tag: JexTag) -> str:
        tid = tag.get_id()
        self.tags.append(tag)
        return tid

    def add_note_tag(self, note_id: str, tag_id: str):
        self.note_tags.append(JexNoteTag(note_id=note_id, tag_id=tag_id))

    def add_resource(self, resource: JexResource) -> str:
        rid = resource.get_id()
        self.resources.append(resource)
        return rid

    def write(self, output_path: str):
        """Write the JEX archive (tar file) to output_path."""
        with tarfile.open(output_path, "w") as tar:
            for folder in self.folders:
                content = folder.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=f"{folder.get_id()}.md")
                info.size = len(content)
                info.mtime = folder.updated_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

            for note in self.notes:
                content = note.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=f"{note.get_id()}.md")
                info.size = len(content)
                info.mtime = note.updated_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

            for tag in self.tags:
                content = tag.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=f"{tag.get_id()}.md")
                info.size = len(content)
                info.mtime = tag.updated_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

            for nt in self.note_tags:
                content = nt.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=nt.get_filename())
                info.size = len(content)
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(content))

            for res in self.resources:
                content = res.serialize_metadata().encode("utf-8")
                info = tarfile.TarInfo(name=f"{res.get_id()}.md")
                info.size = len(content)
                info.mtime = res.created_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

                res_filename = f"resources/{res.get_resource_filename()}"
                info = tarfile.TarInfo(name=res_filename)
                info.size = len(res.data)
                info.mtime = res.created_time or int(time.time())
                tar.addfile(info, io.BytesIO(res.data))

        print(f"JEX archive written: {output_path}")
        print(f"  Folders:  {len(self.folders)}")
        print(f"  Notes:    {len(self.notes)}")
        print(f"  Tags:     {len(self.tags)}")
        print(f"  NoteTags: {len(self.note_tags)}")
        print(f"  Resources:{len(self.resources)}")
