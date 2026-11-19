"""
Runner to execute batch extraction for multiple GCS prefixes with appropriate classifier names.
"""
import os
from app.services.transcript_processor import ProcessorConfig, ExtractionContext, TranscriptProcessor
from app.services.transcript_processor import ExtractionContext
from app.services.transcript_processor import ProcessorConfig
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import asyncio
from app import models

# use env or defaults
PROJECT_ID = os.environ.get('DOC_AI_PROJECT', 'doc-ai-transcript')
LOCATION = os.environ.get('DOC_AI_LOCATION', 'us')
PROCESSOR_ID = os.environ.get('DOC_AI_PROCESSOR', '4bf06de9ecadb866')
DB_URL = os.environ.get('ASYNC_DATABASE_URL') or os.environ.get('DATABASE_URL')
if DB_URL and not DB_URL.startswith('postgresql+asyncpg'):
    DB_URL = DB_URL.replace('postgresql://', 'postgresql+asyncpg://')

engine = create_async_engine(DB_URL, future=True, echo=False)
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# mapping from path to classifier name
paths = {
    'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/LBUSD': 'lbusd',
    'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/Mayfair_High_School': 'mayfair_high_school',
    'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/St_Anthony_High_School': 'st_anthony_high_school',
    'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/Others': 'others',
}

async def run_path(gcs_path: str, classifier_name: str):
    tp = TranscriptProcessor(ProcessorConfig(project_id=PROJECT_ID, location=LOCATION, processor_id=PROCESSOR_ID))
    # download blobs
    from google.cloud import storage
    bucket_name = gcs_path.split('/')[2]
    prefix = '/'.join(gcs_path.split('/')[3:])
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = list(client.list_blobs(bucket, prefix=prefix))
    pdf_blobs = []
    for blob in blobs:
        if blob.name.lower().endswith('.pdf'):
            pdf_blobs.append((blob.name.split('/')[-1], blob.download_as_bytes()))
    # sample only N PDFs per path for quicker verification
    SAMPLE_N = 3
    if len(pdf_blobs) > SAMPLE_N:
        pdf_blobs = pdf_blobs[:SAMPLE_N]
    print(f'Found {len(pdf_blobs)} PDFs in {gcs_path}')

    total_students = 0
    total_courses = 0
    async with AsyncSessionLocal() as session:
        for fname, content in pdf_blobs:
            # resolve classifier_type row to get real processor_id if present
            from sqlalchemy import select
            res = await session.execute(select(models.ClassifiersType).where(models.ClassifiersType.classifier_name == classifier_name))
            classifier_row = res.scalar_one_or_none()
            used_proc = PROCESSOR_ID
            classifier_type_id = 1
            if classifier_row:
                used_proc = getattr(classifier_row, 'processor_id', used_proc) or used_proc
                classifier_type_id = classifier_row.id
            ctx = ExtractionContext(extraction_file_id=1, institution_id=2, classifier_type_id=classifier_type_id, used_processor_id=used_proc, file_name=fname, classifier_name=classifier_name)
            print('Processing', fname, 'as', classifier_name)
            result = await tp.process_bytes_and_persist(session, ctx, content)
            total_students += result.get('students', 0)
            total_courses += result.get('courses', 0)
            print(f" -> persisted student_details: {result.get('students', 0)}, course_details: {result.get('courses', 0)}")
    print(f'Completed {gcs_path}: Students={total_students}, Courses={total_courses}')

async def main():
    for p, cn in paths.items():
        await run_path(p, cn)

if __name__ == '__main__':
    asyncio.run(main())
