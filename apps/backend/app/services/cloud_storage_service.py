from __future__ import annotations

import os
from typing import List
from google.cloud import storage


def _normalize_prefix_segment(value: str | None, fallback: str) -> str:
    segment = (value or fallback).strip().strip("/")
    return segment or fallback


def _normalize_term_segment(value: str | None, fallback: str = "default-term") -> str:
    """Normalize term names to Title-case leading letter to avoid duplicate prefixes."""
    segment = (value or fallback).strip()
    if not segment:
        segment = fallback
    # Capitalize first letter, leave rest as-is to preserve year/intake formatting
    return segment[0].upper() + segment[1:] if segment else fallback


class CloudStorageService:
    def __init__(self, project: str | None = None):
        # if project is None, client will use default credentials project
        self.client = storage.Client(project=project)

    def get_bucket_name(self) -> str:
        """Return the fixed bucket name used for transcript storage."""
        return os.environ.get(
            "CLOUD_STORAGE_BUCKET_NAME",
            "doc-ai-transcript-us-central1-v1-001",
        )

    def ensure_bucket(self) -> str:
        """Verify that the configured GCS bucket exists and is accessible."""
        bucket_name = self.get_bucket_name()
        bucket = self.client.lookup_bucket(bucket_name)
        if bucket is None:
            raise FileNotFoundError(
                f"GCS bucket '{bucket_name}' was not found or is not accessible to the current credentials"
            )
        return bucket_name

    def get_root_prefix(self) -> str:
        """Return the base folder inside the bucket where *raw uploads* are organized."""
        return _normalize_prefix_segment(
            os.environ.get("CLOUD_STORAGE_ROOT_PREFIX", "01_Inbox_Raw_HS_Transcripts"),
            "01_Inbox_Raw_HS_Transcripts",
        )

    def get_classified_root_prefix(self) -> str:
        """Return the base folder where classified transcripts live (school-wise library)."""
        return _normalize_prefix_segment(
            os.environ.get("CLASSIFIED_STORAGE_ROOT_PREFIX", "02_Library_Categorized_HS_Transcripts"),
            "02_Library_Categorized_HS_Transcripts",
        )

    def ensure_prefix(self, bucket_name: str, prefix: str) -> str:
        """Create a placeholder object to represent a folder (prefix) if it doesn't already exist.
        Returns the prefix used (always ending with '/').
        """
        if not prefix:
            raise ValueError('prefix is required')
        prefix = prefix.strip().lstrip('/')
        if not prefix.endswith('/'):
            prefix = prefix + '/'
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(prefix)
        # blob.exists requires a client
        try:
            if not blob.exists(client=self.client):
                blob.upload_from_string('', content_type='application/x-empty')
        except Exception:
            # best-effort: try to list to see if anything exists under prefix
            blobs = list(self.client.list_blobs(bucket_name, prefix=prefix, max_results=1))
            if not blobs:
                # create placeholder
                blob.upload_from_string('', content_type='application/x-empty')
        return prefix

    def ensure_term_and_course_prefixes(
        self,
        institution_id: int,
        year_intake: str,
        program_name: str | None = None,  # kept for backwards compatibility; ignored
        courses: List[str] | None = None,
    ) -> dict:
        """Ensure term-level folders exist inside the fixed transcript bucket.
        Program dimension has been removed; everything is organized under the term.
        """
        _ = institution_id  # bucket selection is no longer institution-scoped
        bucket_name = self.ensure_bucket()
        root_prefix = f"{self.get_root_prefix()}/"
        term_segment = _normalize_term_segment(year_intake, "default-term")
        term_prefix = f"{root_prefix}{term_segment}/"
        created = {
            'bucket': bucket_name,
            'root_prefix': None,
            'term_prefix': None,
            'program_prefix': None,  # legacy key retained for callers; equals term_prefix
            'course_prefixes': [],
        }
        created['root_prefix'] = self.ensure_prefix(bucket_name, root_prefix)
        created['term_prefix'] = self.ensure_prefix(bucket_name, term_prefix)
        created['program_prefix'] = created['term_prefix']
        if courses:
            for c in courses:
                if not c:
                    continue
                course_segment = _normalize_prefix_segment(str(c), "uploads")
                p = f"{term_prefix}{course_segment}/"
                created['course_prefixes'].append(self.ensure_prefix(bucket_name, p))
        return created

    def build_upload_prefix(
        self,
        year_intake: str,
        program_name: str | None,
        course: str | None = None,
    ) -> str:
        root_prefix = self.get_root_prefix()
        term_segment = _normalize_term_segment(year_intake, "default-term")
        # Program segment removed; keep param for signature compatibility.
        if course and course.strip():
            course_segment = _normalize_prefix_segment(course, "uploads")
            return f"{root_prefix}/{term_segment}/{course_segment}/"
        return f"{root_prefix}/{term_segment}/"

    def build_classified_upload_prefix(
        self,
        year_intake: str,
        course: str | None = None,
    ) -> str:
        """Prefix under the classified library (02...)."""
        root_prefix = self.get_classified_root_prefix()
        term_segment = _normalize_term_segment(year_intake, "default-term")
        if course and course.strip():
            course_segment = _normalize_prefix_segment(course, "uploads")
            return f"{root_prefix}/{term_segment}/{course_segment}/"
        return f"{root_prefix}/{term_segment}/"

    def list_files(self, bucket_name: str, prefix: str) -> list[dict]:
        normalized_prefix = prefix.strip().lstrip("/")
        if normalized_prefix and not normalized_prefix.endswith("/"):
            normalized_prefix = f"{normalized_prefix}/"

        files: list[dict] = []
        for blob in self.client.list_blobs(bucket_name, prefix=normalized_prefix):
            if blob.name.endswith("/"):
                continue
            relative_name = blob.name[len(normalized_prefix):] if normalized_prefix else blob.name
            if not relative_name:
                continue
            files.append(
                {
                    "name": relative_name,
                    "path": blob.name,
                    "size_bytes": blob.size,
                    "updated_at": blob.updated,
                }
            )
        return sorted(files, key=lambda item: (item["updated_at"] is None, item["name"]))

    def list_children(self, bucket_name: str, base_prefix: str, path: str | None = None) -> dict:
        """List immediate folders and files under base_prefix/path (non-recursive)."""
        prefix = base_prefix.strip().lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"
        if path:
            sub = path.strip().strip("/")
            if sub:
                prefix = f"{prefix}{sub}/"
        folders: set[str] = set()
        files: list[dict] = []
        for blob in self.client.list_blobs(bucket_name, prefix=prefix, delimiter=None):
            if blob.name.endswith("/"):
                # ignore placeholder objects; we'll derive folders from names
                continue
            rel = blob.name[len(prefix):] if prefix else blob.name
            if not rel:
                continue
            parts = rel.split("/", 1)
            if len(parts) == 1:
                files.append(
                    {
                        "name": parts[0],
                        "path": f"{path.rstrip('/') if path else ''}/{parts[0]}" if path else parts[0],
                        "size_bytes": blob.size,
                        "updated_at": blob.updated,
                    }
                )
            else:
                folders.add(parts[0])
        return {
            "folders": sorted(folders),
            "files": sorted(files, key=lambda f: (f["updated_at"] is None, f["name"])),
        }

    def download_file(self, bucket_name: str, blob_path: str) -> bytes:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        if not blob.exists(client=self.client):
            raise FileNotFoundError(f"GCS object '{blob_path}' was not found in bucket '{bucket_name}'")
        return blob.download_as_bytes()

    # ------------------------------------------------------------------
    # Per-term handbook folder (created/deleted with the term). Stores the
    # uploaded admissions handbook so rule extraction can re-fetch it reliably.
    # ------------------------------------------------------------------

    def handbook_prefix(self, year_intake: str) -> str:
        """The per-term handbook folder prefix, e.g.
        '01_Inbox_Raw_HS_Transcripts/<term>/handbook/'."""
        term_segment = _normalize_term_segment(year_intake, "default-term")
        return f"{self.get_root_prefix()}/{term_segment}/handbook/"

    def ensure_handbook_folder(self, year_intake: str) -> str:
        bucket_name = self.ensure_bucket()
        return self.ensure_prefix(bucket_name, self.handbook_prefix(year_intake))

    def upload_bytes(
        self, bucket_name: str, blob_path: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        return blob_path

    def delete_prefix(self, bucket_name: str, prefix: str) -> int:
        """Delete every object under a prefix (the folder). Returns the count."""
        prefix = prefix.strip().lstrip("/")
        count = 0
        for blob in self.client.list_blobs(bucket_name, prefix=prefix):
            try:
                blob.delete()
                count += 1
            except Exception:
                pass
        return count

    def first_file_in_prefix(self, bucket_name: str, prefix: str) -> str | None:
        """Path of the first non-placeholder object under a prefix, or None."""
        prefix = prefix.strip().lstrip("/")
        for blob in self.client.list_blobs(bucket_name, prefix=prefix):
            if not blob.name.endswith("/") and blob.size:
                return blob.name
        return None

    def store_handbook(self, year_intake: str, data: bytes, filename: str) -> tuple[str, str]:
        """Replace the term's handbook with the uploaded PDF. Clears any prior
        handbook first (one active handbook per term). Returns (bucket, blob_path)."""
        bucket_name = self.ensure_bucket()
        prefix = self.handbook_prefix(year_intake)
        # Wipe the old handbook so a new upload overrides it.
        self.delete_prefix(bucket_name, prefix)
        self.ensure_prefix(bucket_name, prefix)
        safe_name = _normalize_prefix_segment(filename or "handbook.pdf", "handbook.pdf")
        if not safe_name.lower().endswith(".pdf"):
            safe_name = f"{safe_name}.pdf"
        blob_path = f"{prefix}{safe_name}"
        self.upload_bytes(bucket_name, blob_path, data, content_type="application/pdf")
        return bucket_name, blob_path
