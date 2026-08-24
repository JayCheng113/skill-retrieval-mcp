"""Defend the `[:500]` in `Skill.to_embedding_text()`.

That constant reads arbitrary and invites being raised, so `schema.py` carries a
comment claiming it was swept and won. This is the sweep. Without it the comment
is an assertion nobody can check.

The sweep re-embeds the whole corpus per arm rather than going through the
shipped index, because the recipe is what changes and the index is built from
it. Retrieval is reproduced in numpy — normalized vectors, inner product, top-5
— which is what `SkillIndex` does with a flat IP index. The first arm is the
shipped configuration, so if its row does not match the numbers in
`retrieval_eval.py` the instrument is wrong and nothing below it means anything.

Two things get measured together because they are easy to confuse:

  MiniLM arms   raise the slice on the shipped model. Everything they add lands
                outside the 256 word-piece window, so the added text is
                unreachable rather than merely truncated.
  bge-small     is a 384-dimensional model like MiniLM but with a 512 window,
                run with the query prefix its model card asks for so that "bge
                is worse" cannot be blamed on using it wrong.

The bge arms download about 130 MB on first run. Results are recorded in the
"embedding text overflows the model window" section of `dev.md`.

    pip install -e ".[local]"
    skill-mcp pull
    python tests/eval/embedding_recipe_sweep.py
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

from skill_mcp.schema import Skill
from skill_mcp.store import SkillStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retrieval_eval import IN_DOMAIN, OUT_OF_DOMAIN  # noqa: E402

BGE_PREFIX = "Represent this sentence for searching relevant passages: "


def recipe(skill: Skill, instr_chars: int) -> str:
    parts = [skill.name, skill.description]
    if skill.instructions:
        parts.append(skill.instructions[:instr_chars])
    return "\n".join(parts)


def encode(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    vecs = np.asarray(model.encode(texts, batch_size=64, show_progress_bar=False), dtype=np.float32)
    return vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-10)


def overflow(model: SentenceTransformer, texts: list[str]) -> tuple[int, int, int]:
    """How many texts exceed the window, and by how many word-pieces."""
    lost = [
        n - model.max_seq_length
        for n in (len(model.tokenizer(t, add_special_tokens=True)["input_ids"]) for t in texts)
        if n > model.max_seq_length
    ]
    if not lost:
        return 0, 0, 0
    return len(lost), int(statistics.median(lost)), max(lost)


def run_arm(label, model_name, window, instr_chars, skills, query_prefix=""):
    model = SentenceTransformer(model_name)
    model.max_seq_length = window
    texts = [recipe(s, instr_chars) for s in skills]
    names = [s.name for s in skills]
    docs = encode(model, texts)

    sims = encode(model, [query_prefix + q for q, _ in IN_DOMAIN]) @ docs.T
    hits1 = hits3 = hits5 = 0
    rr = 0.0
    top1 = []
    for i, (_query, expected) in enumerate(IN_DOMAIN):
        order = np.argsort(-sims[i])[:5]
        top1.append(float(sims[i][order[0]]))
        rank = next((r + 1 for r, j in enumerate(order) if names[j] in expected), None)
        if rank:
            rr += 1 / rank
            hits1 += rank <= 1
            hits3 += rank <= 3
            hits5 += rank <= 5

    ood = encode(model, [query_prefix + q for q in OUT_OF_DOMAIN]) @ docs.T
    ood_top1 = [float(row.max()) for row in ood]

    n = len(IN_DOMAIN)
    n_over, med_over, max_over = overflow(model, texts)
    return {
        "label": label,
        "overflow": f"{n_over}/{med_over}/{max_over}",
        "chars": statistics.median(len(t) for t in texts),
        "r1": hits1 / n,
        "r3": hits3 / n,
        "r5": hits5 / n,
        "mrr": rr / n,
        "ind_med": statistics.median(top1),
        "ood_max": max(ood_top1),
        "ood_med": statistics.median(ood_top1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("SKILL_MCP_DATA_DIR", "~/.skill-mcp")).expanduser(),
    )
    args = parser.parse_args()

    db = args.data_dir / "skills.db"
    if not db.exists():
        sys.exit(
            f"nothing to sweep: {db} does not exist.\n"
            f"Build a corpus first:  skill-mcp --data-dir {args.data_dir} pull"
        )

    skills = SkillStore(db, readonly=True).get_all()
    # The baseline arm is a fiction unless it is literally the shipped recipe.
    if recipe(skills[0], 500) != skills[0].to_embedding_text():
        sys.exit("recipe() has drifted from Skill.to_embedding_text(); the baseline arm is stale")
    print(f"corpus: {len(skills)} skills\n")

    mini, bge = "all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"
    arms = [
        run_arm("MiniLM @256  instr[:500]  (ships)", mini, 256, 500, skills),
        run_arm("MiniLM @256  instr[:1000]", mini, 256, 1000, skills),
        run_arm("MiniLM @256  instr[:2000]", mini, 256, 2000, skills),
        run_arm("MiniLM @256  instr full", mini, 256, 10**9, skills),
        run_arm("bge-sm @512  instr[:500]  +prefix", bge, 512, 500, skills, BGE_PREFIX),
        run_arm("bge-sm @512  instr[:2000] +prefix", bge, 512, 2000, skills, BGE_PREFIX),
        run_arm("bge-sm @512  instr full   +prefix", bge, 512, 10**9, skills, BGE_PREFIX),
    ]

    header = (
        f"{'arm':<36} {'overflow n/med/max':<20} {'medchar':>8} {'R@1':>6} {'R@3':>6} "
        f"{'R@5':>6} {'MRR':>6} {'ind_med':>8} {'ood_max':>8} {'ood_med':>8}"
    )
    print(header)
    print("-" * len(header))
    for a in arms:
        print(
            f"{a['label']:<36} {a['overflow']:<20} {a['chars']:>8.0f} {a['r1']:>6.1%} "
            f"{a['r3']:>6.1%} {a['r5']:>6.1%} {a['mrr']:>6.3f} {a['ind_med']:>8.3f} "
            f"{a['ood_max']:>8.3f} {a['ood_med']:>8.3f}"
        )


if __name__ == "__main__":
    main()
