"""
Dump raw Document AI entity outputs and normalized payloads for a few representative PDFs.
Saves JSON files to apps/backend/tmp_docai_raw/<classifier>/<filename>.json

This script is for debugging only.
"""
from __future__ import annotations
import os
import json
from pathlib import Path

from google.cloud import storage
try:
    from google.cloud import documentai_v1 as documentai
except Exception:
    documentai = None

from app.services.document_ai_service import DocumentAIService

# Hard-coded processor mapping (kept in DB too)
PROCESSOR_MAP = {
    'lbusd': 'eec9a0bd33bef934',
    'mayfair_high_school': '4bf06de9ecadb866',
    'st_anthony_high_school': '7ec1dfc2705ce10d',
    'others': '7ffd481485bfc9f6',
}

GCS_BASE = 'gs://doc-ai-transcript-us-central1-v1-001/02_Library_Categorized_HS_Transcripts/Fall_2026/transcript'
PATHS = {
    'lbusd': GCS_BASE + '/',
    'mayfair_high_school': GCS_BASE + '/Mayfair_High_School/',
    'st_anthony_high_school': GCS_BASE + '/St_Anthony_High_School/',
}

# Representative filenames (first two from previous runs)
SAMPLES = {
    'lbusd': [
        'Aguilar, Manuel_CABRILLO HIGH SCHOOL.pdf',
        'Ajanel, Juan_CABRILLO HIGH SCHOOL.pdf',
    ],
    'mayfair_high_school': [
        'Caldejon, Dominic_MAYFAIR HIGH SCHOOL.pdf',
        'Lane, Dylan_MAYFAIR HIGH SCHOOL.pdf',
    ],
    'st_anthony_high_school': [
        'Alon, Jordan_ST ANTHONY HIGH SCHOOL.pdf',
        'Perez, Aliyah_ST ANTHONY HIGH SCHOOL.pdf',
    ],
}

OUT_DIR = Path(__file__).resolve().parent / 'tmp_docai_raw'
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROJECT_ID = os.environ.get('DOC_AI_PROJECT', 'doc-ai-transcript')
LOCATION = os.environ.get('DOC_AI_LOCATION', 'us')

# storage_client = storage.Client()

storage_client = None

def get_storage_client():
    global storage_client
    if storage_client is None and USE_GCS:
        storage_client = storage.Client(project=PROJECT_ID)
    return storage_client


def serialize_entity(ent):
    def _t(x):
        return getattr(x, 'type_', '')
    def _text(x):
        return (getattr(x, 'mention_text', '') or '').strip()
    obj = {
        'type': _t(ent),
        'mention_text': _text(ent),
        'confidence': getattr(ent, 'confidence', None),
        'properties': [],
    }
    for p in getattr(ent, 'properties', []) or []:
        obj['properties'].append({'type': getattr(p, 'type_', ''), 'mention_text': _text(p)})
    return obj


def dump_for(classifier_name: str):
    proc = PROCESSOR_MAP.get(classifier_name)
    if not proc:
        print('no processor for', classifier_name)
        return
    proc_id = proc
    # adjust path
    gcs_path = PATHS.get(classifier_name, GCS_BASE)
    bucket_name = gcs_path.split('/')[2]
    prefix = '/'.join(gcs_path.split('/')[3:])
    bucket = get_storage_client().bucket(bucket_name)
    # list blobs under prefix and try to match by filename suffix
    blobs = list(get_storage_client().list_blobs(bucket, prefix=prefix))
    for fname in SAMPLES.get(classifier_name, []):
        found = None
        for b in blobs:
            if b.name.lower().endswith(fname.lower()):
                found = b
                break
        if not found:
            print('missing blob for', fname, 'under prefix', prefix)
            continue
        content = found.download_as_bytes()

        # normalized output
        try:
            service = DocumentAIService(project_id=PROJECT_ID, location=LOCATION, processor_id=proc_id)
            header, course_rows = service.process_pdf(content)
        except Exception as e:
            header, course_rows = {}, []
            print('DocumentAI service error for', fname, e)

        # raw documentai entities
        raw_entities = []
        if documentai is not None:
            client = documentai.DocumentProcessorServiceClient()
            name = client.processor_path(PROJECT_ID, LOCATION, proc_id)
            raw = documentai.RawDocument(content=content, mime_type='application/pdf')
            req = documentai.ProcessRequest(name=name, raw_document=raw)
            try:
                res = client.process_document(request=req)
                doc = res.document
                for ent in getattr(doc, 'entities', []) or []:
                    raw_entities.append(serialize_entity(ent))
            except Exception as e:
                print('raw process error', e)

        out = {
            'file': fname,
            'classifier': classifier_name,
            'processor_id': proc_id,
            'header_normalized': header,
            'courses_normalized': course_rows,
            'raw_entities': raw_entities,
        }
        out_path = OUT_DIR / classifier_name
        out_path.mkdir(parents=True, exist_ok=True)
        target = out_path / (fname + '.json')
        with open(target, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print('wrote', target)


def main():
    for cls in SAMPLES.keys():
        dump_for(cls)

if __name__ == '__main__':
    main()
