"""Download pre-built skill datasets from HuggingFace Hub."""

from __future__ import annotations

import shutil
from pathlib import Path

HF_REPO = "zcheng256/skillretrieval-data"

# Files available on HuggingFace and their relative paths in the repo
HF_FILES = {
    "db": "processed/skills.db",
}


def pull_dataset(dest_dir: Path, force: bool = False) -> dict[str, Path]:
    """Download the pre-built skills.db from HuggingFace Hub.

    Returns a dict mapping file type to local path.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise SystemExit(
            "HuggingFace Hub is required for pull. Install with:\n"
            "  pip install skill-retrieval-mcp[hf]"
        )

    dest_dir = Path(dest_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)

    db_dest = dest_dir / "skills.db"
    if db_dest.exists() and not force:
        raise FileExistsError(
            f"Database already exists at {db_dest}. Use --force to overwrite."
        )

    downloaded = hf_hub_download(
        repo_id=HF_REPO,
        filename=HF_FILES["db"],
        repo_type="dataset",
    )
    # hf_hub_download returns a cache path; copy to destination
    shutil.copy2(downloaded, db_dest)

    return {"db": db_dest}
