"""Download pre-built skill datasets from HuggingFace Hub.

Each function downloads a single artifact and returns the cached path.
The CLI layer decides how to use these files (copy, merge, etc.).
"""

from __future__ import annotations

from pathlib import Path

HF_REPO = "zcheng256/skillretrieval-data"

# The default pre-built index on HuggingFace
DEFAULT_INDEX_BACKEND = "sentence-transformers"
DEFAULT_INDEX_MODEL = "all-MiniLM-L6-v2"


def _hf_download(filename: str) -> Path:
    """Download a single file from HuggingFace Hub. Returns cached path."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit(
            "HuggingFace Hub is required for pull. Install with:\n"
            "  pip install skill-retrieval-mcp[hf]"
        )
    return Path(hf_hub_download(
        repo_id=HF_REPO,
        filename=filename,
        repo_type="dataset",
    ))


def download_skills_db() -> Path:
    """Download pre-built skills.db. Returns path to HF-cached file."""
    return _hf_download("processed/skills.db")


def download_index(
    backend: str = DEFAULT_INDEX_BACKEND,
    model: str = DEFAULT_INDEX_MODEL,
) -> dict[str, Path]:
    """Download pre-built FAISS index for a specific embedding backend/model.

    Files are stored under indices/{backend}/{model}/ on HuggingFace.
    Falls back to indices/ (flat layout) for backward compatibility.
    """
    prefix = f"indices/{backend}/{model}"
    try:
        return {
            "faiss": _hf_download(f"{prefix}/index.faiss"),
            "meta": _hf_download(f"{prefix}/skill_ids.json"),
        }
    except Exception:
        # Fallback: try flat layout (legacy)
        return {
            "faiss": _hf_download("indices/index.faiss"),
            "meta": _hf_download("indices/skill_ids.json"),
        }
