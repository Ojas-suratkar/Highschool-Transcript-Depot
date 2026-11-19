"""Google Document AI processor discovery.

Lists the custom *extraction* processors that live in the project and reports
each one's training lifecycle so the Transcript Types pages can mirror the Doc AI
console:

  - ready    -> has a DEPLOYED version (fully trained), ready to integrate
  - in_setup -> a version is still being built/trained (CREATING/DEPLOYING)

Only CUSTOM_EXTRACTION_PROCESSOR types are returned — the classifier / OCR /
form-parser processors are infrastructure, not transcript-type extractors.

Authentication + project/location reuse the same env + ADC the rest of the Doc AI
integration uses (DOC_AI_PROJECT / DOC_AI_LOCATION). All calls here are blocking
gRPC, so callers in async contexts must wrap them in asyncio.to_thread.
"""

from __future__ import annotations

import os
from typing import Any

try:  # SDK may be absent in some environments; fail soft.
    from google.cloud import documentai_v1 as documentai
    from google.api_core.client_options import ClientOptions
except Exception:  # noqa: BLE001
    documentai = None  # type: ignore
    ClientOptions = None  # type: ignore

EXTRACTION_PROCESSOR_TYPE = "CUSTOM_EXTRACTION_PROCESSOR"

# Version states that mean "still being built" on the Doc AI console.
_TRAINING_VERSION_STATES = {"CREATING", "DEPLOYING", "IMPORTING"}


def _is_foundation_version(version_id: str | None) -> bool:
    """Google ships every custom-extraction processor with built-in foundation
    model versions (ids start with 'pretrained-'). Those are always DEPLOYED and
    are NOT the result of training on a school's transcripts — so they must be
    ignored when deciding whether a processor is actually trained."""
    return bool(version_id) and version_id.startswith("pretrained-")


def docai_project() -> str:
    return os.environ.get("DOC_AI_PROJECT", "doc-ai-transcript")


def docai_location() -> str:
    return os.environ.get("DOC_AI_LOCATION", "us")


def layout_classifier_id() -> str:
    """The layout classifier whose labels ARE the transcript types."""
    return os.environ.get("DOC_AI_LAYOUT_CLASSIFIER", "a860d0a957566bc2")


def list_layout_classifier_labels() -> list[str]:
    """Return the transcript-type labels the layout classifier is trained on.

    Read from the processor's **dataset schema** (the only place Doc AI exposes a
    custom classifier's class labels — the version document_schema is empty).
    Blocking gRPC — wrap in asyncio.to_thread. Returns [] on any failure.
    """
    try:
        from google.cloud import documentai_v1beta3 as documentai_v1beta3
        from google.api_core.client_options import ClientOptions as _ClientOptions
    except Exception:  # noqa: BLE001
        return []

    location = docai_location()
    client = documentai_v1beta3.DocumentServiceClient(
        client_options=_ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    )
    schema_name = (
        f"projects/{docai_project()}/locations/{location}"
        f"/processors/{layout_classifier_id()}/dataset/datasetSchema"
    )
    schema = client.get_dataset_schema(name=schema_name)
    labels: list[str] = []
    for entity_type in getattr(schema.document_schema, "entity_types", []) or []:
        name = getattr(entity_type, "name", None) or getattr(entity_type, "display_name", None)
        if name:
            labels.append(name)
    return labels


def _build_client():
    if documentai is None:
        raise RuntimeError("google-cloud-documentai is not installed.")
    location = docai_location()
    # Doc AI is regional; the list APIs require the regional endpoint.
    return documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    )


def _version_id(version_name: str | None) -> str | None:
    if not version_name:
        return None
    return version_name.split("/")[-1]


def list_extraction_processors() -> list[dict[str, Any]]:
    """Return every custom-extraction processor with lifecycle info.

    Blocking call — wrap in asyncio.to_thread from async code.
    """
    client = _build_client()
    parent = client.common_location_path(docai_project(), docai_location())

    processors: list[dict[str, Any]] = []

    for proc in client.list_processors(parent=parent):
        if getattr(proc, "type_", None) != EXTRACTION_PROCESSOR_TYPE:
            continue

        processor_id = proc.name.split("/")[-1]
        proc_state = proc.state.name if proc.state else "STATE_UNSPECIFIED"

        # Only CUSTOM-trained versions count — Google's foundation versions are
        # ignored (see _is_foundation_version).
        custom_deployed = False
        custom_training = False
        custom_count = 0
        versions: list[dict[str, Any]] = []

        try:
            for ver in client.list_processor_versions(parent=proc.name):
                version_id = _version_id(ver.name)
                vstate = ver.state.name if ver.state else "STATE_UNSPECIFIED"
                if _is_foundation_version(version_id):
                    continue
                custom_count += 1
                if vstate == "DEPLOYED":
                    custom_deployed = True
                if vstate in _TRAINING_VERSION_STATES:
                    custom_training = True
                versions.append(
                    {"id": version_id, "display_name": ver.display_name, "state": vstate}
                )
        except Exception:  # noqa: BLE001 — versions are best-effort enrichment
            pass

        # Ready ONLY when a custom-trained version is deployed (training finished).
        # Everything else stays In Setup (option A): actively training, trained but
        # not yet deployed, or created-but-never-trained (foundation models only).
        lifecycle = "ready" if custom_deployed else "in_setup"

        processors.append(
            {
                "id": processor_id,
                "display_name": proc.display_name,
                "type": proc.type_,
                "state": proc_state,  # ENABLED / DISABLED / ENABLING / ...
                "lifecycle": lifecycle,
                "trained": custom_deployed,           # has a deployed custom version
                "training": custom_training,          # a custom version is building now
                "has_custom_version": custom_count > 0,
                "default_version": _version_id(proc.default_processor_version),
                "versions": versions[:8],
            }
        )

    return processors
