"""Measure what the shipped corpus can and cannot answer.

Two query sets, and the second one is the point.

In-domain queries are phrased the way an agent would phrase a task and never
echo the skill's own name, because a query built from the name measures lexical
overlap rather than retrieval. Each carries a set of acceptable answers, not a
single one, since several skills in the corpus legitimately serve the same task.

Out-of-domain queries name real technical work the corpus provably does not
cover. Their top-1 scores are what tell us where "nothing fits" begins, and they
are the reason this file exists: they disproved the plan to filter results by a
score threshold. The best out-of-domain score sits above the median in-domain
score, so no cut-off separates them.

Expected-answer sets are pinned to skill names in the published corpus. A corpus
change is supposed to move these numbers; that is what an eval is for.

Run against a built store and index:

    pip install -e ".[local]"
    skill-mcp pull && skill-mcp build-index
    python tests/eval/retrieval_eval.py
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from pathlib import Path

from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.index import SkillIndex
from skill_mcp.retriever import retrieve
from skill_mcp.store import SkillStore

# (query, {acceptable skill names})
IN_DOMAIN = [
    (
        "expose a service running inside my kubernetes cluster to the internet",
        {"gke-service-networking", "gke-networking", "google-cloud-global-frontend-configuration"},
    ),
    (
        "automatically add more pods when cpu and memory usage climbs",
        {"gke-workload-scaling", "gke-cluster-autoscaler", "gke-compute-classes"},
    ),
    (
        "our kubernetes bill is too high, where is the money going",
        {"gke-cost-optimization", "gke-cost-analysis"},
    ),
    (
        "query a few terabytes of event data with sql and no servers",
        {"bigquery-basics", "bigquery-bigframes", "bigquery-ai-ml"},
    ),
    ("run my container image without provisioning any vms", {"cloud-run-basics"}),
    (
        "upload files to an object bucket and serve them",
        {"google-cloud-storage-basics", "google-cloud-storage-fuse"},
    ),
    (
        "page someone when the service burns through its error budget",
        {"google-cloud-slo-alert-configuration", "agent-platform-alert-configuration"},
    ),
    (
        "write a scheduled data pipeline as a dag on a managed service",
        {"managed-airflow-dag-authoring", "managed-airflow-migrations"},
    ),
    (
        "display a banner advertisement in my android app",
        {"google-mobile-ads-banner", "google-mobile-ads-get-started"},
    ),
    (
        "my tpu training job crashed with an out of memory error",
        {
            "gke-ai-troubleshooting-tpu-vbar-oom",
            "gke-ai-troubleshooting-handle-disruption-gpu-tpu",
        },
    ),
    (
        "figure out the least privilege permissions a service account needs",
        {"iam-helper-for-policy-simulator", "iam-helper-for-privileged-access-management"},
    ),
    (
        "fine tune a foundation model and deploy the adapter",
        {"agent-platform-tuning", "agent-platform-tuning-management"},
    ),
    (
        "search a corpus of documents and feed the hits to an llm",
        {
            "agent-platform-rag-engine-management",
            "google-cloud-solution-rag-enterprise-search-gke-sqldb",
        },
    ),
    (
        "trace where a table's data came from and what breaks if i change it",
        {"datalineage-bigquery-asset-impact-analysis", "datalineage-summary"},
    ),
    (
        "cluster cells from single cell rna sequencing counts",
        {"scanpy", "scvi-tools", "cellxgene-census"},
    ),
    ("find genes that change expression between two conditions", {"pydeseq2", "bulk-rnaseq"}),
    ("read alignments out of a bam file in python", {"pysam", "deeptools"}),
    (
        "compute chemical fingerprints and descriptors for a compound library",
        {"rdkit", "molfeat", "datamol", "medchem"},
    ),
    (
        "predict the binding pose of a small molecule against a protein",
        {"diffdock", "deepchem", "rowan"},
    ),
    (
        "build a phylogenetic tree from a set of sequences",
        {"phylogenetics", "etetoolkit", "scikit-bio"},
    ),
    (
        "run the same bioinformatics steps reproducibly over hundreds of samples",
        {"nextflow", "modal", "dask"},
    ),
    (
        "how many subjects do i need for this experiment to detect an effect",
        {"statistical-power", "experimental-design", "statistical-analysis"},
    ),
    (
        "make a publication quality figure for a paper",
        {"scientific-visualization", "matplotlib", "seaborn"},
    ),
    (
        "simulate a quantum circuit and measure the qubits",
        {"qiskit", "cirq", "pennylane", "qutip"},
    ),
    ("fit a bayesian model with mcmc sampling", {"pymc", "statsmodels"}),
    (
        "load a dicom study and pull out the pixel data",
        {"pydicom", "imaging-data-commons", "pacsomatic"},
    ),
    (
        "explain which features drove an individual model prediction",
        {"shap", "scikit-learn"},
    ),
    (
        "survey the recent papers on a topic and summarise the state of the art",
        {"literature-review", "paper-lookup", "research-lookup"},
    ),
    ("run a molecular dynamics simulation of a protein in water", {"molecular-dynamics"}),
    ("simulate a queueing system with discrete events", {"simpy"}),
    (
        "git says i have a conflict, walk me through resolving it",
        {
            "resolving-merge-conflicts",
            "git-workflow-and-versioning",
            "git-guardrails-claude-code",
        },
    ),
    (
        "turn this vague idea into a written specification",
        {"to-spec", "spec-driven-development", "idea-refine", "writing-plans"},
    ),
    (
        "add tracing and metrics so i can debug this in production",
        {
            "observability-and-instrumentation",
            "cloud-logging-configuration-basics",
            "gke-observability",
        },
    ),
    (
        "design the endpoints and error contract for a new rest api",
        {"api-and-interface-design", "domain-modeling"},
    ),
    (
        "check this code for injection holes and leaked secrets",
        {"security-and-hardening", "code-review-and-quality"},
    ),
    (
        "this bug is intermittent, help me narrow it down methodically",
        {"systematic-debugging", "diagnosing-bugs", "debugging-and-error-recovery"},
    ),
    ("write the failing test first, then make it pass", {"test-driven-development", "tdd"}),
    (
        "split this work across several agents running at the same time",
        {"dispatching-parallel-agents", "subagent-driven-development"},
    ),
    (
        "generate a slide deck from this outline",
        {"pptx", "pptx-posters", "scientific-slides"},
    ),
    ("build a server that exposes tools to an ai agent over mcp", {"mcp-builder"}),
    ("pull the text and tables out of a pdf", {"pdf", "markitdown", "liteparse"}),
    ("query my notes as if they were a database", {"obsidian-bases", "obsidian-cli"}),
    (
        "strip the navigation and ads off a web page to get clean markdown",
        {"defuddle", "obsidian-markdown"},
    ),
]

OUT_OF_DOMAIN = [
    "deploy a lambda function behind an api gateway on aws",
    "write an async tcp server in rust with tokio",
    "configure nginx as a reverse proxy terminating tls",
    "build a swiftui view with a navigation stack for ios",
    "tune postgresql autovacuum for a heavy write workload",
    "write an erc-20 token contract in solidity",
    "set up a kafka consumer group with exactly once semantics",
    "write a terraform module for an azure virtual network",
    "analyse a windows kernel crash dump in windbg",
    "implement the oauth2 pkce flow in a native mobile client",
    "write a unity c# script for third person character movement",
    "shard an elasticsearch index for full text search at scale",
    "migrate a wordpress site to a new host without downtime",
    "write a cobol batch job for mainframe payroll",
    "configure bgp peering on a cisco router",
]


def load(data_dir: Path):
    db, index_dir = data_dir / "skills.db", data_dir / "index"
    missing = [str(p) for p in (db, index_dir) if not p.exists()]
    if missing:
        sys.exit(
            f"nothing to evaluate: {', '.join(missing)} does not exist.\n"
            f"Build a corpus first:  skill-mcp --data-dir {data_dir} pull && "
            f"skill-mcp --data-dir {data_dir} build-index"
        )

    index = SkillIndex.load(index_dir)
    # The encoder is taken from the index, never from config: scoring a query
    # with a different model than built the vectors returns plausible-looking
    # numbers that mean nothing.
    info = index.embedding_info
    emb = EmbeddingModel(
        model_name=info.get("model", "all-MiniLM-L6-v2"),
        backend=info.get("backend", "sentence-transformers"),
    )
    return SkillStore(db, readonly=True), index, emb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("SKILL_MCP_DATA_DIR", "~/.skill-mcp")).expanduser(),
    )
    args = parser.parse_args()

    store, index, emb = load(args.data_dir)
    print(f"corpus: {store.count()} skills, encoder {index.embedding_info}")

    hits1 = hits3 = hits5 = 0
    rr_total = 0.0
    in_top1_scores = []
    misses = []

    print("=" * 78)
    print(f"IN-DOMAIN  ({len(IN_DOMAIN)} queries)")
    print("=" * 78)
    for query, expected in IN_DOMAIN:
        results = retrieve(query, store, index, emb, k=5)
        names = [r.skill.name for r in results]
        scores = [r.score for r in results]
        in_top1_scores.append(scores[0] if scores else 0.0)

        rank = next((i + 1 for i, n in enumerate(names) if n in expected), None)
        if rank:
            rr_total += 1 / rank
            hits1 += rank <= 1
            hits3 += rank <= 3
            hits5 += rank <= 5
        else:
            misses.append((query, names[:3], scores[:3], sorted(expected)))

        mark = {1: "1", 2: "3", 3: "3", 4: "5", 5: "5"}.get(rank, "-")
        print(f"  @{mark}  {scores[0]:.3f}  {query[:56]:<56} -> {names[0][:28]}")

    n = len(IN_DOMAIN)
    print()
    print(
        f"  Recall@1 {hits1}/{n} = {hits1 / n:.1%}   "
        f"Recall@3 {hits3}/{n} = {hits3 / n:.1%}   "
        f"Recall@5 {hits5}/{n} = {hits5 / n:.1%}   "
        f"MRR {rr_total / n:.3f}"
    )

    print()
    print("=" * 78)
    print(f"OUT-OF-DOMAIN  ({len(OUT_OF_DOMAIN)} queries the corpus cannot serve)")
    print("=" * 78)
    ood_top1 = []
    for query in OUT_OF_DOMAIN:
        results = retrieve(query, store, index, emb, k=3)
        top = results[0]
        ood_top1.append(top.score)
        print(f"     {top.score:.3f}  {query[:56]:<56} -> {top.skill.name[:28]}")

    print()
    print("=" * 78)
    print("SEPARATION")
    print("=" * 78)
    ind = sorted(in_top1_scores)
    ood = sorted(ood_top1)
    print(
        f"  in-domain  top1: min {ind[0]:.3f}  p25 {ind[len(ind) // 4]:.3f}  "
        f"median {statistics.median(ind):.3f}  max {ind[-1]:.3f}"
    )
    print(
        f"  out-domain top1: min {ood[0]:.3f}  median {statistics.median(ood):.3f}  "
        f"p75 {ood[len(ood) * 3 // 4]:.3f}  max {ood[-1]:.3f}"
    )
    print(
        f"  overlap: {sum(1 for s in ind if s <= ood[-1])} in-domain queries score "
        f"at or below the best out-of-domain score ({ood[-1]:.3f})"
    )

    for t in (0.30, 0.35, 0.40, 0.45, 0.50):
        keep = sum(1 for s in ind if s >= t)
        rejected = sum(1 for s in ood if s < t)
        print(
            f"  threshold {t:.2f}: keeps {keep}/{len(ind)} in-domain, "
            f"rejects {rejected}/{len(ood)} out-of-domain"
        )

    if misses:
        print()
        print("=" * 78)
        print(f"MISSES  ({len(misses)} in-domain queries with nothing expected in top 5)")
        print("=" * 78)
        for query, names, scores, expected in misses:
            print(f"  {query}")
            print(f"    got      {[f'{n} {s:.2f}' for n, s in zip(names, scores)]}")
            print(f"    expected {expected}")


if __name__ == "__main__":
    main()
