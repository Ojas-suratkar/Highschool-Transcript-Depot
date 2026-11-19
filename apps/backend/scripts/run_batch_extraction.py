"""
CLI runner for batch transcript extraction.

Usage: Configure processor and context, then run over a folder of PDFs.
No Excel output. Prints summary; intended to be wired to DB insertion later.
"""

from __future__ import annotations

import os
from typing import List


from app.services.transcript_processor import (
    ProcessorConfig,
    ExtractionContext,
    TranscriptProcessor,
)

import io
import re
from typing import List

def is_gcs_path(path: str) -> bool:
    return path.startswith("gs://")

def parse_gcs_path(gcs_path: str):
    # Returns (bucket, prefix)
    m = re.match(r"gs://([^/]+)/(.+)", gcs_path)
    if not m:
        raise ValueError(f"Invalid GCS path: {gcs_path}")
    return m.group(1), m.group(2)



def run(input_path: str, project_id: str, location: str, processor_id: str, ctx: ExtractionContext):
    tp = TranscriptProcessor(ProcessorConfig(project_id=project_id, location=location, processor_id=processor_id))

    pdfs: List[str] = []
    pdf_blobs: List[tuple[str, bytes]] = []

    if is_gcs_path(input_path):
        # GCS mode
        from google.cloud import storage
        bucket_name, prefix = parse_gcs_path(input_path)
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blobs = list(client.list_blobs(bucket, prefix=prefix))
        for blob in blobs:
            if blob.name.lower().endswith(".pdf"):
                print(f"Downloading: gs://{bucket_name}/{blob.name}")
                pdf_blobs.append((os.path.basename(blob.name), blob.download_as_bytes()))
    else:
        # Local mode
        pdfs = [
            os.path.join(input_path, f)
            for f in os.listdir(input_path)
            if f.lower().endswith(".pdf")
        ]
        pdfs.sort()
        for pdf in pdfs:
            with open(pdf, "rb") as f:
                pdf_blobs.append((os.path.basename(pdf), f.read()))

    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker

    # Use your actual DB URL here (should be async, e.g., postgresql+asyncpg://)
    db_url = os.environ.get("ASYNC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if db_url and not db_url.startswith("postgresql+asyncpg"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url, future=True, echo=False)
    AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def process_all():
        total_students = 0
        total_courses = 0
        async with AsyncSessionLocal() as session:
            for fname, content in pdf_blobs:
                print(f"Processing: {fname}")
                ctx.file_name = fname
                result = await tp.process_bytes_and_persist(session, ctx, content)
                total_students += result.get("students", 0)
                total_courses += result.get("courses", 0)
                print(f" -> persisted student_details: {result.get('students', 0)}, course_details: {result.get('courses', 0)}")
        print(f"Completed. Students: {total_students}, Courses: {total_courses}")

    asyncio.run(process_all())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Batch transcript extraction runner.")
    parser.add_argument("--input_dir", type=str, default=None, help="Input directory or GCS path (gs://bucket/prefix)")
    parser.add_argument("--project_id", type=str, default=None, help="Google Cloud project ID")
    parser.add_argument("--location", type=str, default=None, help="Document AI processor location")
    parser.add_argument("--processor_id", type=str, default=None, help="Document AI processor ID")
    parser.add_argument("--extraction_file_id", type=int, default=None, help="Extraction file ID")
    parser.add_argument("--institution_id", type=int, default=None, help="Institution ID")
    parser.add_argument("--classifier_type_id", type=int, default=None, help="Classifier type ID")

    args = parser.parse_args()

    input_dir = args.input_dir or os.environ.get("TRANSCRIPTS_DIR", "./transcripts")
    project_id = args.project_id or os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript")
    location = args.location or os.environ.get("DOC_AI_LOCATION", "us")
    processor_id = args.processor_id or os.environ.get("DOC_AI_PROCESSOR", "4bf06de9ecadb866")
    extraction_file_id = args.extraction_file_id or int(os.environ.get("EXTRACTION_FILE_ID", "1"))
    institution_id = args.institution_id or int(os.environ.get("INSTITUTION_ID", "1"))
    classifier_type_id = args.classifier_type_id or int(os.environ.get("CLASSIFIER_TYPE_ID", "1"))

    ctx = ExtractionContext(
        extraction_file_id=extraction_file_id,
        institution_id=institution_id,
        classifier_type_id=classifier_type_id,
        used_processor_id=processor_id,
        file_name="",
    )

    run(input_dir, project_id, location, processor_id, ctx)
