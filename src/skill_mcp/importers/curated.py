"""CuratedImporter: imports SKILL.md trees from vetted upstream repositories.

Every repository here was checked for a redistributable licence before being
listed. The manifest is the authoritative record of that check: an unlisted
repository is rejected rather than imported under an assumed licence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from skill_mcp.importers.frontmatter import split_frontmatter
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import ImportStats, SkillStore


@dataclass(frozen=True)
class CuratedRepo:
    """A vetted upstream repository and the licence its content ships under."""

    slug: str
    spdx: str
    source: SkillSource

    @property
    def url(self) -> str:
        return f"https://github.com/{self.slug}"


CURATED_REPOS: dict[str, CuratedRepo] = {
    repo.slug: repo
    for repo in (
        # Apache-2.0 is declared per skill in skills/<name>/LICENSE.txt, not at repo root.
        CuratedRepo("anthropics/skills", "Apache-2.0", SkillSource.ANTHROPIC),
        CuratedRepo("google/skills", "Apache-2.0", SkillSource.COMMUNITY),
        CuratedRepo("K-Dense-AI/scientific-agent-skills", "MIT", SkillSource.COMMUNITY),
        CuratedRepo("mattpocock/skills", "MIT", SkillSource.COMMUNITY),
        CuratedRepo("addyosmani/agent-skills", "MIT", SkillSource.COMMUNITY),
        CuratedRepo("obra/superpowers", "MIT", SkillSource.COMMUNITY),
        CuratedRepo("kepano/obsidian-skills", "MIT", SkillSource.COMMUNITY),
    )
}


class UnvettedRepositoryError(Exception):
    """Raised when a directory does not correspond to a vetted repository."""


class CuratedImporter:
    """Import SKILL.md files from a tree of vetted upstream repository clones.

    ``source_path`` holds one directory per repository, laid out as
    ``<owner>/<repo>`` so it matches the manifest slug::

        git clone https://github.com/obra/superpowers <root>/obra/superpowers
    """

    def import_skills(self, source_path: Path, store: SkillStore) -> ImportStats:
        skills: list[Skill] = []
        for repo in self._present_repos(source_path):
            root = source_path / repo.slug
            for skill_file in sorted(root.rglob("SKILL.md")):
                skill = self._parse_skill_file(skill_file, root, repo)
                if skill is not None:
                    skills.append(skill)
        return store.add_skills(skills)

    def _present_repos(self, source_path: Path) -> list[CuratedRepo]:
        """Resolve on-disk ``<owner>/<repo>`` directories against the manifest.

        Unvetted directories abort the import: silently skipping them would let
        unlicensed content reach the corpus on the next careless clone.
        """
        found: list[CuratedRepo] = []
        unvetted: list[str] = []
        for owner_dir in sorted(p for p in source_path.iterdir() if p.is_dir()):
            for repo_dir in sorted(p for p in owner_dir.iterdir() if p.is_dir()):
                slug = f"{owner_dir.name}/{repo_dir.name}"
                repo = CURATED_REPOS.get(slug)
                if repo is None:
                    unvetted.append(slug)
                else:
                    found.append(repo)
        if unvetted:
            raise UnvettedRepositoryError(
                "refusing to import from repositories with no vetted licence: "
                + ", ".join(sorted(unvetted))
            )
        return found

    def _parse_skill_file(self, path: Path, root: Path, repo: CuratedRepo) -> Skill | None:
        text = path.read_text(encoding="utf-8")
        frontmatter, body = split_frontmatter(text)
        if frontmatter is None:
            return None

        meta = yaml.safe_load(frontmatter)
        if not isinstance(meta, dict):
            return None

        relative = path.relative_to(root)
        description = meta.get("description") or ""
        if not isinstance(description, str):
            description = str(description)

        metadata: dict[str, object] = {
            "repo": repo.slug,
            "repo_url": repo.url,
            "license": repo.spdx,
            "path": relative.as_posix(),
            "url": f"{repo.url}/blob/main/{relative.as_posix()}",
        }
        # Upstream sometimes states a narrower licence per skill (K-Dense ships
        # BSD-3-Clause files under an MIT repo). Keep it verbatim beside the
        # vetted repo licence rather than trying to reconcile the two.
        declared = meta.get("license")
        if isinstance(declared, str) and declared.strip():
            metadata["declared_license"] = declared.strip()

        return Skill(
            name=str(meta.get("name") or path.parent.name),
            description=description.strip(),
            instructions=body.strip(),
            source=repo.source,
            source_id=f"{repo.slug}:{relative.as_posix()}",
            category=self._detect_category(relative),
            tags=self._normalise_tags(meta.get("tags")),
            metadata=metadata,
        )

    @staticmethod
    def _detect_category(relative: Path) -> str:
        """Use the grouping directory upstream chose, if it used one.

        Every vetted repo roots its skills at ``skills/``, so that component
        carries no meaning. What remains is either ``<name>/SKILL.md`` (no
        grouping) or ``<group>/<name>/SKILL.md``.
        """
        parts = relative.parts
        if parts and parts[0] == "skills":
            parts = parts[1:]
        return parts[-3] if len(parts) >= 3 else ""

    @staticmethod
    def _normalise_tags(raw: object) -> list[str]:
        if isinstance(raw, str):
            return [t.strip() for t in raw.split(",") if t.strip()]
        if isinstance(raw, list):
            return [str(t).strip() for t in raw if str(t).strip()]
        return []
