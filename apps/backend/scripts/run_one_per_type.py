"""
Process one PDF per classifier path, persist, and print the persisted student rows (key fields).
"""
import os
import asyncio
from google.cloud import storage
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app import models
from app.services.transcript_processor import ProcessorConfig, TranscriptProcessor, ExtractionContext

PROJECT_ID = os.environ.get('DOC_AI_PROJECT', 'doc-ai-transcript')
LOCATION = os.environ.get('DOC_AI_LOCATION', 'us')
PROCESSOR_ID = os.environ.get('DOC_AI_PROCESSOR', '4bf06de9ecadb866')
DB_URL = os.environ.get('ASYNC_DATABASE_URL') or os.environ.get('DATABASE_URL')
if DB_URL and not DB_URL.startswith('postgresql+asyncpg'):
    DB_URL = DB_URL.replace('postgresql://', 'postgresql+asyncpg://')

engine = create_async_engine(DB_URL, future=True, echo=False)
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# one-sample prefixes
PATHS = {
    'lbusd': 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/',
    'mayfair_high_school': 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/Mayfair_High_School/',
    'st_anthony_high_school': 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/St_Anthony_High_School/',
}

async def process_one(path: str, classifier_name: str):
    tp = TranscriptProcessor(ProcessorConfig(project_id=PROJECT_ID, location=LOCATION, processor_id=PROCESSOR_ID))
    client = storage.Client()
    bucket_name = path.split('/')[2]
    prefix = '/'.join(path.split('/')[3:])
    blobs = list(client.list_blobs(bucket_name, prefix=prefix))
    pdfs = [b for b in blobs if b.name.lower().endswith('.pdf')]
    if not pdfs:
        print('No PDFs for', classifier_name, 'under', path)
        return
    blob = pdfs[0]
    fname = blob.name.split('/')[-1]
    content = blob.download_as_bytes()

    async with AsyncSessionLocal() as session:
        from sqlalchemy import insert, text

        # Ensure institution with id=1 exists
        res_inst = await session.execute(select(models.Institution).where(models.Institution.id == 1))
        inst_row = res_inst.scalar_one_or_none()
        if not inst_row:
            try:
                await session.execute(
                    text("INSERT INTO institution (id, institution_name, created_at) VALUES (1, 'Default Institution', NOW()) ON CONFLICT (id) DO NOTHING")
                )
                await session.commit()
                print('Ensured institution id=1 exists')
            except Exception as e:
                print(f'Institution insert warning: {e}')
                await session.rollback()

        # Ensure classifier_type row exists for this classifier_name
        res = await session.execute(select(models.ClassifiersType).where(models.ClassifiersType.classifier_name == classifier_name))
        classifier_row = res.scalar_one_or_none()
        if not classifier_row:
            try:
                await session.execute(
                    text("INSERT INTO classifier_type (classifier_name, processor_id) VALUES (:cname, :proc) ON CONFLICT (classifier_name) DO NOTHING"),
                    {"cname": classifier_name, "proc": PROCESSOR_ID}
                )
                await session.commit()
                res = await session.execute(select(models.ClassifiersType).where(models.ClassifiersType.classifier_name == classifier_name))
                classifier_row = res.scalar_one_or_none()
                print(f'Ensured classifier_type for {classifier_name} exists, id={classifier_row.id if classifier_row else "?"}')
            except Exception as e:
                print(f'Classifier insert warning: {e}')
                await session.rollback()

        classifier_type_id = classifier_row.id if classifier_row else 1
        used_proc = classifier_row.processor_id if classifier_row and getattr(classifier_row,'processor_id',None) else PROCESSOR_ID
        ctx = ExtractionContext(extraction_file_id=1, institution_id=1, classifier_type_id=classifier_type_id, used_processor_id=used_proc, file_name=fname, classifier_name=classifier_name)
        print('Processing', fname, 'as', classifier_name, 'using processor', used_proc)
        result = await tp.process_bytes_and_persist(session, ctx, content)
        print('persist result', result)
        # fetch extraction_file id for this file_name (most recent)
        res = await session.execute(
            select(models.ExtractionFileDetails.id)
            .where(models.ExtractionFileDetails.file_name == fname)
            .order_by(models.ExtractionFileDetails.id.desc())
            .limit(1)
        )
        ef_id = res.scalar_one_or_none()
        if not ef_id:
            print('No extraction_file_details found for', fname)
            return
        # fetch student row by source_file id (use ef_id directly to avoid selecting older/non-existent columns)
        res = await session.execute(select(models.Students).where(models.Students.source_file == ef_id))
        stud = res.scalar_one_or_none()
        if not stud:
            print('No student persisted for', fname)
            return
        # print key columns (model uses s_ and hs_ prefixes)
        print('Persisted student for', fname)
        print(' s_id:', getattr(stud, 's_id', None))
        print(' s_name:', getattr(stud, 's_name', None))
        print(' hs_total_gpa_course:', getattr(stud, 'hs_total_gpa_course', None))
        print(' hs_aca_gpa_course:', getattr(stud, 'hs_aca_gpa_course', None))
        print(' hs_university_gpa:', getattr(stud, 'hs_university_gpa', None))
        print(' hs_total_units_earned:', getattr(stud, 'hs_total_units_earned', None))
        print(' hs_enter_date:', getattr(stud, 'hs_enter_date', None))
        print(' hs_graduation_date:', getattr(stud, 'hs_graduation_date', None))
        print(' s_state_id:', getattr(stud, 's_state_id', None))

async def main():
    for cls, path in PATHS.items():
        await process_one(path, cls)

if __name__ == '__main__':
    asyncio.run(main())
