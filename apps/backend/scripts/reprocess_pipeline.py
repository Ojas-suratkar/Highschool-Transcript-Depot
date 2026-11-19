"""
Full reprocess pipeline.

Actions:
- Archive `tmp_docai_raw` directory
- Truncate all public tables and RESTART IDENTITY CASCADE (destructive)
- For each classifier path, list PDFs in GCS, call the classifier's processor on each PDF,
  normalize and persist header + course rows into Cloud SQL using existing services.

This is intentionally destructive: it truncates all public tables. Use only when you
intend to completely reset the DB.
"""
import os
import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path

from google.cloud import storage
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select, insert

from app import models
from app.services.document_ai_service import DocumentAIService
from app.services.persistence_service import PersistenceService

DB_URL = os.environ.get('ASYNC_DATABASE_URL') or os.environ.get('DATABASE_URL')
if DB_URL and not DB_URL.startswith('postgresql+asyncpg'):
    DB_URL = DB_URL.replace('postgresql://', 'postgresql+asyncpg://')

PROJECT_ID = os.environ.get('DOC_AI_PROJECT', 'doc-ai-transcript')
LOCATION = os.environ.get('DOC_AI_LOCATION', 'us')
DEFAULT_PROCESSOR = os.environ.get('DOC_AI_PROCESSOR', '4bf06de9ecadb866')

# Classifier -> GCS prefix map (adjust as needed)
PATHS = {
    'lbusd': 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/',
    'mayfair_high_school': 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/Mayfair_High_School/',
    'st_anthony_high_school': 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript/St_Anthony_High_School/',
}

engine = create_async_engine(DB_URL, future=True, echo=False)
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def archive_tmp_dump():
    base = Path(__file__).resolve().parents[1] / 'scripts' / 'tmp_docai_raw'
    if base.exists():
        dst = base.parent / f"tmp_docai_raw_archive_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
        shutil.move(str(base), str(dst))
        print('Archived', base, '->', dst)
    base.mkdir(parents=True, exist_ok=True)


async def truncate_all_tables():
    async with AsyncSessionLocal() as session:
        # get public tables
        res = await session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public';"))
        tables = [r[0] for r in res.fetchall()]
        if not tables:
            print('No public tables found')
            return
        tbl_list = ','.join([f'"{t}"' for t in tables])
        sql = f'TRUNCATE TABLE {tbl_list} RESTART IDENTITY CASCADE;'
        print('Executing:', sql)
        await session.execute(text(sql))
        await session.commit()
        print('Truncated tables:', tables)


def save_raw_dump(classifier: str, fname: str, header: dict, courses: list):
    base = Path(__file__).resolve().parents[1] / 'scripts' / 'tmp_docai_raw' / classifier
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"{fname}.json"
    with open(out, 'w', encoding='utf-8') as f:
        json.dump({'file': fname, 'classifier': classifier, 'header': header, 'courses': courses}, f, indent=2, ensure_ascii=False)
    print('Wrote dump', out)


async def process_bucket_prefix(client: storage.Client, bucket_name: str, prefix: str, classifier_name: str):
    tp = None
    async with AsyncSessionLocal() as session:
        # resolve/create classifier row
        res = await session.execute(select(models.ClassifiersType).where(models.ClassifiersType.classifier_name == classifier_name))
        classifier_row = res.scalar_one_or_none()
        if not classifier_row:
            # create an entry with default processor
            stmt = insert(models.ClassifiersType).values(classifier_name=classifier_name, processor_id=DEFAULT_PROCESSOR, status=f'enabled_{classifier_name}').returning(models.ClassifiersType)
            try:
                result = await session.execute(stmt)
                await session.commit()
                classifier_row = result.scalar_one()
            except Exception:
                await session.rollback()
                res = await session.execute(select(models.ClassifiersType).where(models.ClassifiersType.classifier_name == classifier_name))
                classifier_row = res.scalar_one_or_none()

        used_proc = getattr(classifier_row, 'processor_id', DEFAULT_PROCESSOR)
        service = DocumentAIService(project_id=PROJECT_ID, location=LOCATION, processor_id=used_proc)
        bucket = client.bucket(bucket_name)
        blobs = list(client.list_blobs(bucket_name, prefix=prefix))
        pdfs = [b for b in blobs if b.name.lower().endswith('.pdf')]
        print(f'Found {len(pdfs)} pdfs for {classifier_name} in {bucket_name}/{prefix}')

        for blob in pdfs:
            fname = blob.name.split('/')[-1]
            print('Processing', fname, 'as', classifier_name, 'with processor', used_proc)
            content = blob.download_as_bytes()

            # create extraction_file_details row
            ins = insert(models.ExtractionFileDetails).values(file_name=fname, process_status='processing', institution_id=1, classifier_type=classifier_row.id).returning(models.ExtractionFileDetails.id)
            result = await session.execute(ins)
            await session.commit()
            ef_id = result.scalar_one()

            # process via Document AI
            header, courses = service.process_pdf(content)

            # save raw dump
            save_raw_dump(classifier_name, fname, header, courses)

            # prepare routed student payload (include all header keys to maximize mapping)
            routed_student = {k: v for k, v in header.items()}
            routed_student.update({
                'source_file': ef_id,
                'student_id': header.get('student_id') or header.get('student_external_id'),
            })

            # persist using PersistenceService
            persistence = PersistenceService(session)
            student_row = await persistence.upsert_student_by_classifier(classifier_name, routed_student)
            if student_row:
                committed_student_id = student_row.id
                # prepare routed courses, attach committed_student_id
                routed_courses = []
                for idx, c in enumerate(courses):
                    rc = {k: v for k, v in c.items()}
                    rc['source_file'] = ef_id
                    rc['student_id'] = committed_student_id
                    routed_courses.append(rc)
                course_count = await persistence.insert_courses_by_classifier(classifier_name, routed_courses)
                print('Persisted', 'student_id=', student_row.s_id, 'courses=', course_count)
            else:
                print('Student upsert returned None for', fname)

            # mark completed
            await persistence.mark_file_status(ef_id, 'completed')


async def main():
    # archive prior raw dumps
    archive_tmp_dump()

    # truncate all public tables and restart identities (destructive)
    await truncate_all_tables()

    # Ensure a default institution exists (so extraction_file_details.institution_id FK has a target)
    async with AsyncSessionLocal() as session:
        # after TRUNCATE RESTART IDENTITY the next id will be 1; insert a minimal institution row
        from sqlalchemy import insert, select
        res = await session.execute(select(models.Institution).limit(1))
        inst = res.scalars().first()
        if not inst:
            stmt = insert(models.Institution).values(institution_name='Default Institution', city=None, state=None, zip_code=None).returning(models.Institution.id)
            try:
                r = await session.execute(stmt)
                await session.commit()
                new_id = r.scalar_one()
                print('Inserted default institution id=', new_id)
            except Exception:
                await session.rollback()
                print('Warning: failed to insert default institution; FK errors may occur')

    client = storage.Client()
    for classifier, path in PATHS.items():
        # parse gs://bucket/prefix
        if not path.startswith('gs://'):
            print('Skipping invalid gs path', path)
            continue
        parts = path[5:].split('/', 1)
        bucket_name = parts[0]
        prefix = parts[1] if len(parts) > 1 else ''
        await process_bucket_prefix(client, bucket_name, prefix, classifier)

if __name__ == '__main__':
    asyncio.run(main())
