"""Restructure HuggingFace index layout and build sentence-transformers index.

Steps:
1. Download existing OpenAI index from indices/
2. Upload to indices/openai/text-embedding-3-large/ with embedding metadata
3. Download skills.db, build sentence-transformers index
4. Upload to indices/sentence-transformers/all-MiniLM-L6-v2/
5. Delete old flat indices/ files

Usage:
    pip install "skill-retrieval-mcp[local,hf]"
    python scripts/restructure_hf_index.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

REPO = "zcheng256/skillretrieval-data"


def main():
    api = HfApi()
    work_dir = Path(tempfile.mkdtemp(prefix="hf-restructure-"))
    print(f"Working in {work_dir}")

    # ── Step 1: Download existing index ──────────────────────────────
    print("\n[1/5] Downloading existing index...")
    old_faiss = Path(hf_hub_download(REPO, "indices/index.faiss", repo_type="dataset"))
    old_meta = Path(hf_hub_download(REPO, "indices/skill_ids.json", repo_type="dataset"))

    with open(old_meta) as f:
        meta = json.load(f)

    print(f"  Existing index: {len(meta.get('skill_ids', []))} skills, dim={meta.get('dimension')}")

    # ── Step 2: Upload to openai/text-embedding-3-large/ ─────────────
    print("\n[2/5] Uploading to indices/openai/text-embedding-3-large/...")

    # Add embedding metadata if missing
    if "embedding" not in meta:
        meta["embedding"] = {
            "backend": "openai",
            "model": "text-embedding-3-large",
        }
        openai_meta_path = work_dir / "openai_skill_ids.json"
        with open(openai_meta_path, "w") as f:
            json.dump(meta, f)
    else:
        openai_meta_path = old_meta

    api.upload_file(
        path_or_fileobj=str(old_faiss),
        path_in_repo="indices/openai/text-embedding-3-large/index.faiss",
        repo_id=REPO,
        repo_type="dataset",
        commit_message="move OpenAI index to indices/openai/text-embedding-3-large/",
    )
    api.upload_file(
        path_or_fileobj=str(openai_meta_path),
        path_in_repo="indices/openai/text-embedding-3-large/skill_ids.json",
        repo_id=REPO,
        repo_type="dataset",
        commit_message="move OpenAI index metadata with embedding info",
    )
    print("  Done.")

    # ── Step 3: Build sentence-transformers index ────────────────────
    print("\n[3/5] Downloading skills.db and building sentence-transformers index...")
    db_path = Path(hf_hub_download(REPO, "processed/skills.db", repo_type="dataset"))

    from skill_mcp.embeddings import EmbeddingModel
    from skill_mcp.index import SkillIndex
    from skill_mcp.store import SkillStore

    store = SkillStore(db_path, readonly=True)
    skill_count = store.count()
    print(f"  Store has {skill_count:,} skills")

    emb = EmbeddingModel(model_name="all-MiniLM-L6-v2", backend="sentence-transformers")
    print(f"  Embedding dimension: {emb.dimension}")

    index = SkillIndex(emb.dimension)
    index.embedding_info = {
        "backend": "sentence-transformers",
        "model": "all-MiniLM-L6-v2",
    }
    index.build(store, emb, batch_size=256)
    store.close()

    st_dir = work_dir / "st-index"
    index.save(st_dir)
    print(f"  Built index: {len(index.skill_ids):,} skills")

    # ── Step 4: Upload sentence-transformers index ───────────────────
    print("\n[4/5] Uploading sentence-transformers index...")
    api.upload_file(
        path_or_fileobj=str(st_dir / "index.faiss"),
        path_in_repo="indices/sentence-transformers/all-MiniLM-L6-v2/index.faiss",
        repo_id=REPO,
        repo_type="dataset",
        commit_message="add sentence-transformers/all-MiniLM-L6-v2 index",
    )
    api.upload_file(
        path_or_fileobj=str(st_dir / "skill_ids.json"),
        path_in_repo="indices/sentence-transformers/all-MiniLM-L6-v2/skill_ids.json",
        repo_id=REPO,
        repo_type="dataset",
        commit_message="add sentence-transformers/all-MiniLM-L6-v2 index metadata",
    )
    print("  Done.")

    # ── Step 5: Delete old flat index files ──────────────────────────
    print("\n[5/5] Deleting old indices/index.faiss and indices/skill_ids.json...")
    try:
        api.delete_file("indices/index.faiss", repo_id=REPO, repo_type="dataset",
                        commit_message="remove old flat index (moved to indices/openai/)")
        api.delete_file("indices/skill_ids.json", repo_id=REPO, repo_type="dataset",
                        commit_message="remove old flat index metadata (moved to indices/openai/)")
        print("  Deleted.")
    except Exception as e:
        print(f"  Warning: could not delete old files: {e}")

    # Cleanup
    shutil.rmtree(work_dir, ignore_errors=True)

    print("\n✓ Done! HuggingFace index layout:")
    print("  indices/openai/text-embedding-3-large/          (existing)")
    print("  indices/sentence-transformers/all-MiniLM-L6-v2/ (new)")


if __name__ == "__main__":
    main()
