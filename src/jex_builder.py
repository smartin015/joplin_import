"""
Build JEX (Joplin Export Format) archives.

JEX is a .tar file containing:
  {uuid}.md               # Note files (type_: 1)
  {uuid}.md               # Folder files (type_: 2)
  {uuid}.md               # Resource metadata files (type_: 4)
  {uuid}.md               # Tag files (type_: 5)
  {uuid}.md               # Note-Tag association files (type_: 6)
  resources/{uuid}.{ext}  # Binary resource files

Each .md file has:
  Title (first line)
  (blank line)
  Body (markdown, for notes)
  (blank line)
  key: value pairs (metadata)
  type_: N (last line)
"""

import os
import tarfile
import uuid
import time
import io
from typing import Optional
from dataclasses import dataclass


@dataclass
class JexNote:
    """Represents a note (task) in the JEX format."""
    title: str
    body: str = ""
    parent_id: Optional[str] = None
    is_todo: int = 1
    todo_due: int = 0           # Unix timestamp, 0 = no due date
    todo_completed: int = 0     # Unix timestamp, 0 = not completed
    created_time: int = 0       # Unix timestamp
    updated_time: int = 0       # Unix timestamp
    source_url: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    author: str = ""
    source: str = ""
    source_application: str = ""
    markup_language: int = 1    # 1 = Markdown
    is_locked: int = 0
    is_shared: int = 0
    application_data: str = ""
    note_id: Optional[str] = None  # If None, a UUID is generated

    def get_id(self) -> str:
        if self.note_id is None:
            self.note_id = uuid.uuid4().hex
        return self.note_id

    def serialize(self) -> str:
        """Serialize to the JEX .md format."""
        lines = [self.title, ""]
        if self.body:
            lines.append(self.body)
            lines.append("")

        props = [
            f"id: {self.get_id()}",
            f"parent_id: {self.parent_id or ''}",
            f"is_todo: {self.is_todo}",
            f"todo_due: {self.todo_due}",
            f"todo_completed: {self.todo_completed}",
            f"created_time: {self.created_time}",
            f"updated_time: {self.updated_time}",
        ]

        if self.source_url:
            props.append(f"source_url: {self.source_url}")
        if self.latitude:
            props.append(f"latitude: {self.latitude}")
        if self.longitude:
            props.append(f"longitude: {self.longitude}")
        if self.altitude:
            props.append(f"altitude: {self.altitude}")
        if self.author:
            props.append(f"author: {self.author}")
        if self.source:
            props.append(f"source: {self.source}")
        if self.source_application:
            props.append(f"source_application: {self.source_application}")
        if self.application_data:
            props.append(f"application_data: {self.application_data}")

        props.extend([
            f"markup_language: {self.markup_language}",
            f"is_locked: {self.is_locked}",
            f"is_shared: {self.is_shared}",
            "type_: 1",
        ])

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
            f"created_time: {self.created_time}",
            f"updated_time: {self.updated_time}",
            f"is_shared: {self.is_shared}",
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
            f"created_time: {self.created_time}",
            f"updated_time: {self.updated_time}",
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

    def get_id(self) -> str:
        if self.resource_id is None:
            self.resource_id = uuid.uuid4().hex
        return self.resource_id

    def serialize_metadata(self) -> str:
        """Serialize the resource metadata .md file."""
        title = self.title or self.filename
        # Extract extension
        _, ext = os.path.splitext(self.filename)
        size = len(self.data)

        lines = [title, ""]
        props = [
            f"id: {self.get_id()}",
            f"filename: {self.filename}",
            f"mime: {self.mime_type}",
            f"size: {size}",
            f"title: {title}",
            f"file_extension: {ext}",
            f"created_time: {self.created_time}",
            "type_: 4",
        ]
        lines.append("\n".join(props))
        return "\n".join(lines)

    def get_resource_filename(self) -> str:
        """Get the filename used for the binary blob in resources/."""
        # Joplin stores resources as resources/{uuid}.{ext}
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
        """Add a folder. Returns its UUID."""
        fid = folder.get_id()
        self.folders.append(folder)
        return fid

    def add_note(self, note: JexNote) -> str:
        """Add a note. Returns its UUID."""
        nid = note.get_id()
        self.notes.append(note)
        return nid

    def add_tag(self, tag: JexTag) -> str:
        """Add a tag. Returns its UUID."""
        tid = tag.get_id()
        self.tags.append(tag)
        return tid

    def add_note_tag(self, note_id: str, tag_id: str):
        """Link a note to a tag."""
        self.note_tags.append(JexNoteTag(note_id=note_id, tag_id=tag_id))

    def add_resource(self, resource: JexResource) -> str:
        """Add a resource (attachment). Returns its UUID."""
        rid = resource.get_id()
        self.resources.append(resource)
        return rid

    def write(self, output_path: str):
        """Write the JEX archive (tar file) to output_path."""
        with tarfile.open(output_path, "w") as tar:
            # Write folders
            for folder in self.folders:
                content = folder.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=f"{folder.get_id()}.md")
                info.size = len(content)
                info.mtime = folder.updated_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

            # Write notes
            for note in self.notes:
                content = note.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=f"{note.get_id()}.md")
                info.size = len(content)
                info.mtime = note.updated_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

            # Write tags
            for tag in self.tags:
                content = tag.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=f"{tag.get_id()}.md")
                info.size = len(content)
                info.mtime = tag.updated_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

            # Write note-tag associations
            for nt in self.note_tags:
                content = nt.serialize().encode("utf-8")
                info = tarfile.TarInfo(name=nt.get_filename())
                info.size = len(content)
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(content))

            # Write resource metadata + blobs
            for res in self.resources:
                # Metadata .md file
                content = res.serialize_metadata().encode("utf-8")
                info = tarfile.TarInfo(name=f"{res.get_id()}.md")
                info.size = len(content)
                info.mtime = res.created_time or int(time.time())
                tar.addfile(info, io.BytesIO(content))

                # Binary blob
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
