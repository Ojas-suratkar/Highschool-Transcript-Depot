# Transcript Extraction Lab (isolated experiment)

A **separate** pipeline + UI for testing a training-free, format-agnostic transcript
extractor. It shares **no code, DB, or ports** with the main app in `apps/`.

- **VLM:** local, open-source, free — **Qwen2.5-VL** via **Ollama** (no API credits).
- **Architecture tested:** OCR anchor (PDF text layer) → one VLM pass → deterministic
  verification gates (anchor match, grade whitelist, credit-sum reconcile, row-count,
  confidence). Every value is either verified or flagged. No per-format training.

## Run
```sh
# 1. one-time: pull the vision model (~6 GB)
ollama pull qwen2.5vl:7b

# 2. start the lab
sh lab/run.sh
# open http://localhost:8900
```
Click **Generate sample transcript** (or upload a PDF) → **Run extraction**.
The UI shows the page image next to the extracted rows, per-field confidence,
verification flags, and the raw VLM output for side-by-side value matching.

## Swap the VLM (all via env, no code change)
```sh
LAB_VLM_MODEL=qwen2.5vl:3b   sh lab/run.sh          # smaller/faster local model
# or a free hosted OpenAI-compatible endpoint (e.g. NVIDIA build.nvidia.com):
LAB_VLM_PROVIDER=openai LAB_OPENAI_BASE=https://integrate.api.nvidia.com/v1 \
LAB_OPENAI_KEY=nvapi-xxx LAB_VLM_MODEL=qwen/qwen2.5-vl-7b-instruct sh lab/run.sh
```

## Files
- `backend/pipeline.py` — anchor + VLM + verification (the architecture under test)
- `backend/vlm.py` — Ollama / OpenAI-compatible client
- `backend/app.py` — FastAPI routes, serves the UI
- `backend/sample.py` — synthetic transcript generator (real text layer)
- `frontend/index.html` — the single-file UI
- `data/` — SQLite DB + uploaded PDFs + page images (safe to delete)
