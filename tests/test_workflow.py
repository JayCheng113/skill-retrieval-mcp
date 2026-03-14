"""End-to-end workflow tests simulating real user journeys.

Tests the full lifecycle: init → import → build-index → search → status,
plus edge cases discovered via thought experiments.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from skill_mcp.cli import main
from skill_mcp.config import Config, load_config, save_config
from skill_mcp.embeddings import EmbeddingModel
from skill_mcp.importers.directory import DirectoryImporter
from skill_mcp.index import SkillIndex
from skill_mcp.schema import Skill, SkillSource
from skill_mcp.store import SkillStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "skill-mcp-test"


@pytest.fixture
def skills_dir(tmp_path):
    """Create a directory with sample SKILL.md files."""
    base = tmp_path / "skills"
    for name, desc in [
        ("debug-memory", "Debug memory leaks in applications"),
        ("write-tests", "Write comprehensive unit tests"),
        ("deploy-docker", "Deploy applications with Docker"),
    ]:
        d = base / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f'---\nname: "{name}"\ndescription: "{desc}"\ntags: ["testing"]\n---\n\n## Instructions\n\nDetailed instructions for {name}.\n'
        )
    return base


@pytest.fixture
def populated_data_dir(data_dir, skills_dir, runner):
    """A fully initialized data dir with skills imported and index built."""
    result = runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
    assert result.exit_code == 0
    result = runner.invoke(
        main,
        [
            "--data-dir",
            str(data_dir),
            "import",
            "--source",
            "directory",
            "--no-index",
            "--path",
            str(skills_dir),
        ],
    )
    assert result.exit_code == 0
    result = runner.invoke(
        main,
        ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
    )
    assert result.exit_code == 0
    return data_dir


# ---------------------------------------------------------------------------
# E2E Workflow
# ---------------------------------------------------------------------------


class TestFullWorkflow:
    """Simulate the complete user journey from init to search."""

    def test_init_creates_config_and_db(self, runner, data_dir):
        result = runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        assert result.exit_code == 0
        assert (data_dir / "config.yaml").exists()
        assert (data_dir / "skills.db").exists()
        assert "Initialization complete" in result.output

    def test_init_idempotent(self, runner, data_dir):
        """Running init twice should not fail or overwrite existing DB."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        assert result.exit_code == 0
        assert "already exists" in result.output

    def test_import_directory(self, runner, data_dir, skills_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        assert result.exit_code == 0
        assert "3 added" in result.output
        assert "Store now has 3 skills" in result.output

    def test_import_auto_indexes_when_index_exists(self, runner, populated_data_dir, tmp_path):
        """After import, if index exists, auto-update it incrementally."""
        new_skill_dir = tmp_path / "extra"
        new_skill_dir.mkdir()
        d = new_skill_dir / "new-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            '---\nname: "new-skill"\ndescription: "A new skill"\n---\n\nInstructions.\n'
        )
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--path",
                str(new_skill_dir),
            ],
        )
        assert result.exit_code == 0
        assert "index updated" in result.output.lower()
        assert "1 new skills indexed" in result.output.lower()

    def test_build_index_mock(self, runner, data_dir, skills_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "Index built: 3 skills" in result.output
        assert (data_dir / "index" / "index.faiss").exists()
        assert (data_dir / "index" / "skill_ids.json").exists()

    def test_build_index_up_to_date(self, runner, populated_data_dir):
        """build-index with no changes should report up to date."""
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "up to date" in result.output

    def test_build_index_force_overwrites(self, runner, populated_data_dir):
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "build-index", "--backend", "mock", "--force"],
        )
        assert result.exit_code == 0
        assert "Index built" in result.output

    def test_build_index_empty_store(self, runner, data_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "No skills in store" in result.output

    def test_search_with_index(self, runner, populated_data_dir):
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "search", "debug memory", "--k", "2"],
        )
        assert result.exit_code == 0
        # Should show scored results
        assert "[" in result.output  # score brackets

    def test_search_no_db(self, runner, data_dir):
        """Search without init should give helpful error."""
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "search", "test"],
        )
        assert result.exit_code == 0
        assert "init" in result.output.lower()

    def test_search_no_index_falls_back_to_keyword(self, runner, data_dir, skills_dir):
        """Search without index should fall back to keyword search."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "search", "debug"],
        )
        assert result.exit_code == 0
        assert "Falling back to keyword search" in result.output

    def test_status_full(self, runner, populated_data_dir):
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert result.exit_code == 0
        assert "Data directory" in result.output
        assert "Skills: 3" in result.output
        assert "Index: 3 skills" in result.output

    def test_status_warns_stale_index_with_no_index(self, runner, populated_data_dir, tmp_path):
        """Status should warn when index count != store count (--no-index skips auto-update)."""
        new_skill_dir = tmp_path / "extra2"
        d = new_skill_dir / "another"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "another"\ndescription: "Another skill"\n---\n\nInstructions.\n'
        )
        runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(new_skill_dir),
            ],
        )
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert result.exit_code == 0
        assert "WARNING" in result.output

    def test_status_no_warning_after_auto_index(self, runner, populated_data_dir, tmp_path):
        """Status should not warn when auto-index kept the index in sync."""
        new_skill_dir = tmp_path / "extra3"
        d = new_skill_dir / "synced"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "synced"\ndescription: "A synced skill"\n---\n\nInstructions.\n'
        )
        runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--path",
                str(new_skill_dir),
            ],
        )
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert result.exit_code == 0
        assert "WARNING" not in result.output

    def test_status_no_init(self, runner, data_dir):
        result = runner.invoke(main, ["--data-dir", str(data_dir), "status"])
        assert result.exit_code == 0
        assert "not found" in result.output

    def test_dedup_command(self, runner, data_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "dedup"])
        assert result.exit_code == 0
        assert "No duplicates" in result.output or "Removed" in result.output


# ---------------------------------------------------------------------------
# Global --data-dir consistency
# ---------------------------------------------------------------------------


class TestDataDirOverride:
    """Ensure global --data-dir works uniformly across all commands."""

    def test_global_data_dir_init(self, runner, data_dir):
        result = runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        assert result.exit_code == 0
        assert (data_dir / "config.yaml").exists()

    def test_global_data_dir_import(self, runner, data_dir, skills_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        assert result.exit_code == 0
        # Verify skills went to the custom data dir
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 3
        store.close()

    def test_global_data_dir_status(self, runner, data_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "status"])
        assert result.exit_code == 0
        assert str(data_dir) in result.output

    def test_envvar_override(self, runner, data_dir):
        result = runner.invoke(
            main,
            ["init", "--no-register"],
            env={"SKILL_MCP_DATA_DIR": str(data_dir)},
        )
        assert result.exit_code == 0
        assert (data_dir / "config.yaml").exists()


# ---------------------------------------------------------------------------
# Config round-trip
# ---------------------------------------------------------------------------


class TestConfig:
    def test_load_save_roundtrip(self, tmp_path):
        config = Config(data_dir=str(tmp_path))
        save_config(config)
        loaded = load_config(config.config_path)
        assert loaded.data_dir == str(tmp_path)
        assert loaded.embedding.backend == "sentence-transformers"
        assert loaded.embedding.model == "all-MiniLM-L6-v2"

    def test_load_missing_file_returns_defaults(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.data_dir == "~/.skill-mcp"
        assert config.embedding.backend == "sentence-transformers"

    def test_build_index_persists_embedding_config(self, runner, data_dir, skills_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "build-index",
                "--backend",
                "mock",
                "--model",
                "test-model",
            ],
        )
        config = load_config(data_dir / "config.yaml")
        assert config.embedding.backend == "mock"
        assert config.embedding.model == "test-model"


# ---------------------------------------------------------------------------
# Importers
# ---------------------------------------------------------------------------


class TestDirectoryImporter:
    def test_basic_import(self, skills_dir):
        store = SkillStore()
        importer = DirectoryImporter()
        stats = importer.import_skills(skills_dir, store)
        assert stats.added == 3
        assert store.count() == 3
        store.close()

    def test_no_skill_files(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        store = SkillStore()
        importer = DirectoryImporter()
        stats = importer.import_skills(empty_dir, store)
        assert stats.added == 0
        store.close()

    def test_malformed_frontmatter_skipped(self, tmp_path):
        d = tmp_path / "bad"
        d.mkdir()
        # No frontmatter
        (d / "SKILL.md").write_text("Just some text without frontmatter.")
        store = SkillStore()
        importer = DirectoryImporter()
        stats = importer.import_skills(tmp_path, store)
        assert stats.added == 0
        store.close()

    def test_category_from_parent_dir(self, tmp_path):
        d = tmp_path / "my-category" / "my-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "test"\ndescription: "test"\n---\n\nInstructions.\n'
        )
        store = SkillStore()
        importer = DirectoryImporter()
        importer.import_skills(tmp_path, store)
        skills = store.get_all()
        assert skills[0].category == "my-skill"  # parent dir name of SKILL.md
        store.close()

    def test_nested_skill_dirs(self, tmp_path):
        for depth in ["a/b/s1", "a/s2", "s3"]:
            d = tmp_path / depth
            d.mkdir(parents=True)
            name = depth.split("/")[-1]
            (d / "SKILL.md").write_text(
                f'---\nname: "{name}"\ndescription: "test"\n---\n\nInstructions for {name}.\n'
            )
        store = SkillStore()
        importer = DirectoryImporter()
        stats = importer.import_skills(tmp_path, store)
        assert stats.added == 3
        store.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class TestSkill:
    def test_deterministic_id(self):
        s1 = Skill(
            name="test", description="d", instructions="content", source=SkillSource.COMMUNITY
        )
        s2 = Skill(
            name="test", description="d", instructions="content", source=SkillSource.COMMUNITY
        )
        assert s1.id == s2.id
        assert s1.content_hash == s2.content_hash

    def test_different_content_different_hash(self):
        s1 = Skill(
            name="test", description="d", instructions="content A", source=SkillSource.COMMUNITY
        )
        s2 = Skill(
            name="test", description="d", instructions="content B", source=SkillSource.COMMUNITY
        )
        assert s1.content_hash != s2.content_hash

    def test_to_embedding_text_truncation(self):
        long_instructions = "x" * 1000
        s = Skill(
            name="test",
            description="desc",
            instructions=long_instructions,
            source=SkillSource.COMMUNITY,
        )
        text = s.to_embedding_text()
        assert len(text) < 600  # name + desc + 500 chars max

    def test_serialization_roundtrip(self):
        s = Skill(
            name="test",
            description="desc",
            instructions="content",
            source=SkillSource.COMMUNITY,
            category="cat",
            tags=["a", "b"],
        )
        d = s.to_dict()
        s2 = Skill.from_dict(d)
        assert s2.name == s.name
        assert s2.id == s.id
        assert s2.tags == ["a", "b"]
        assert s2.source == SkillSource.COMMUNITY


# ---------------------------------------------------------------------------
# Store edge cases
# ---------------------------------------------------------------------------


class TestStoreEdgeCases:
    def test_delete_skill(self):
        store = SkillStore()
        s = Skill(name="test", description="d", instructions="c", source=SkillSource.COMMUNITY)
        store.add_skill(s)
        assert store.count() == 1
        assert store.delete_skill(s.id)
        assert store.count() == 0
        store.close()

    def test_delete_nonexistent(self):
        store = SkillStore()
        assert not store.delete_skill("nonexistent")
        store.close()

    def test_get_by_category(self):
        store = SkillStore()
        s1 = Skill(
            name="s1",
            description="d",
            instructions="c",
            source=SkillSource.COMMUNITY,
            category="cat-a",
        )
        s2 = Skill(
            name="s2",
            description="d",
            instructions="c2",
            source=SkillSource.COMMUNITY,
            category="cat-b",
        )
        store.add_skill(s1)
        store.add_skill(s2)
        results = store.get_by_category("cat-a")
        assert len(results) == 1
        assert results[0].name == "s1"
        store.close()

    def test_iter_all(self):
        store = SkillStore()
        for i in range(5):
            store.add_skill(
                Skill(
                    name=f"s{i}",
                    description="d",
                    instructions=f"content {i}",
                    source=SkillSource.COMMUNITY,
                )
            )
        items = list(store.iter_all())
        assert len(items) == 5
        store.close()

    def test_batch_import_stats(self):
        store = SkillStore()
        skills = [
            Skill(
                name=f"s{i}",
                description="d",
                instructions=f"content {i}",
                source=SkillSource.COMMUNITY,
            )
            for i in range(3)
        ]
        stats = store.add_skills(skills)
        assert stats.total == 3
        assert stats.added == 3
        assert stats.replaced == 0
        assert stats.skipped_duplicate == 0
        store.close()

    def test_context_manager(self):
        with SkillStore() as store:
            store.add_skill(
                Skill(name="test", description="d", instructions="c", source=SkillSource.COMMUNITY)
            )
            assert store.count() == 1

    def test_merge_from(self, tmp_path):
        """merge_from should add skills from another DB, respecting dedup."""
        # Create source DB
        source_path = tmp_path / "source.db"
        source = SkillStore(source_path)
        for i in range(3):
            source.add_skill(
                Skill(
                    name=f"src-{i}",
                    description="d",
                    instructions=f"src content {i}",
                    source=SkillSource.LANGSKILLS,
                )
            )
        source.close()

        # Create target DB with one overlapping skill
        target_path = tmp_path / "target.db"
        target = SkillStore(target_path)
        target.add_skill(
            Skill(
                name="existing",
                description="d",
                instructions="unique content",
                source=SkillSource.COMMUNITY,
            )
        )
        stats = target.merge_from(source_path)
        assert stats.added == 3
        assert target.count() == 4  # 1 existing + 3 merged
        target.close()

    def test_merge_from_dedup(self, tmp_path):
        """merge_from should skip duplicates based on content_hash."""
        source_path = tmp_path / "source.db"
        source = SkillStore(source_path)
        source.add_skill(
            Skill(
                name="shared",
                description="d",
                instructions="same content",
                source=SkillSource.LANGSKILLS,
            )
        )
        source.close()

        target_path = tmp_path / "target.db"
        target = SkillStore(target_path)
        target.add_skill(
            Skill(
                name="shared",
                description="d",
                instructions="same content",
                source=SkillSource.COMMUNITY,  # higher priority
            )
        )
        stats = target.merge_from(source_path)
        assert stats.skipped_duplicate == 1
        assert target.count() == 1  # no duplicates
        target.close()


# ---------------------------------------------------------------------------
# Index metadata roundtrip
# ---------------------------------------------------------------------------


class TestIndexMetadata:
    def test_embedding_info_saved(self, tmp_path):
        store = SkillStore()
        store.add_skill(
            Skill(name="test", description="d", instructions="c", source=SkillSource.COMMUNITY)
        )
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.embedding_info = {"backend": "mock", "model": "test-model"}
        index.build(store, emb)
        index.save(tmp_path / "idx")

        loaded = SkillIndex.load(tmp_path / "idx")
        assert loaded.embedding_info["backend"] == "mock"
        assert loaded.embedding_info["model"] == "test-model"
        store.close()

    def test_empty_embedding_info_on_old_index(self, tmp_path):
        """Indexes built before embedding_info should load with empty dict."""
        store = SkillStore()
        store.add_skill(
            Skill(name="test", description="d", instructions="c", source=SkillSource.COMMUNITY)
        )
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)
        index.save(tmp_path / "idx")

        # Simulate old format: remove embedding key from metadata
        meta_path = tmp_path / "idx" / "skill_ids.json"
        with open(meta_path) as f:
            meta = json.load(f)
        meta.pop("embedding", None)
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        loaded = SkillIndex.load(tmp_path / "idx")
        assert loaded.embedding_info == {}
        store.close()

    def test_incremental_update_adds_new(self):
        """update() should encode only new skills."""
        store = SkillStore()
        s1 = Skill(
            name="s1", description="d", instructions="content 1", source=SkillSource.COMMUNITY
        )
        store.add_skill(s1)

        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)
        assert index.index.ntotal == 1

        # Add a second skill
        s2 = Skill(
            name="s2", description="d", instructions="content 2", source=SkillSource.COMMUNITY
        )
        store.add_skill(s2)

        added = index.update(store, emb)
        assert added == 1
        assert index.index.ntotal == 2
        assert s2.id in index.skill_ids
        store.close()

    def test_incremental_update_noop(self):
        """update() with no new skills returns 0."""
        store = SkillStore()
        store.add_skill(
            Skill(name="s1", description="d", instructions="c1", source=SkillSource.COMMUNITY)
        )

        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)

        assert index.update(store, emb) == 0
        store.close()

    def test_incremental_update_detects_deletion(self):
        """update() returns -1 when skills were deleted (needs full rebuild)."""
        store = SkillStore()
        s1 = Skill(name="s1", description="d", instructions="c1", source=SkillSource.COMMUNITY)
        s2 = Skill(name="s2", description="d", instructions="c2", source=SkillSource.COMMUNITY)
        store.add_skill(s1)
        store.add_skill(s2)

        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)
        assert index.index.ntotal == 2

        # Delete one skill from store
        store.delete_skill(s2.id)
        assert index.update(store, emb) == -1
        store.close()

    def test_build_index_incremental_via_cli(self, runner, populated_data_dir, tmp_path):
        """build-index after import --no-index should incrementally add new skills."""
        # populated_data_dir has 3 skills + index
        new_skill_dir = tmp_path / "extra"
        d = new_skill_dir / "new-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "brand-new"\ndescription: "A new skill"\n---\n\nNew instructions.\n'
        )
        runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(new_skill_dir),
            ],
        )
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "Incremental" in result.output
        assert "added 1" in result.output

    def test_build_index_model_change_requires_force(self, runner, populated_data_dir):
        """build-index with different model should require --force."""
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "build-index",
                "--backend",
                "mock",
                "--model",
                "different-model",
            ],
        )
        assert result.exit_code == 0
        assert "--force" in result.output


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDedup:
    def test_cross_source_dedup_keeps_higher_priority(self):
        from skill_mcp.dedup import deduplicate_skills

        skills = [
            Skill(
                name="s1",
                description="d",
                instructions="same content",
                source=SkillSource.LANGSKILLS,
            ),
            Skill(
                name="s2",
                description="d",
                instructions="same content",
                source=SkillSource.ANTHROPIC,
            ),
        ]
        result = deduplicate_skills(skills)
        assert len(result) == 1
        assert result[0].source == SkillSource.ANTHROPIC

    def test_no_duplicates_preserved(self):
        from skill_mcp.dedup import deduplicate_skills

        skills = [
            Skill(
                name="s1", description="d", instructions="content A", source=SkillSource.COMMUNITY
            ),
            Skill(
                name="s2", description="d", instructions="content B", source=SkillSource.COMMUNITY
            ),
        ]
        result = deduplicate_skills(skills)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Server handlers
# ---------------------------------------------------------------------------


class TestServerHandlers:
    def _setup(self):
        import skill_mcp.server as srv

        store = SkillStore()
        skills = [
            Skill(
                name="debug-memory",
                description="Debug memory leaks",
                instructions="Use profiler tools",
                source=SkillSource.COMMUNITY,
                category="debugging",
            ),
            Skill(
                name="write-tests",
                description="Write unit tests",
                instructions="Use pytest framework",
                source=SkillSource.COMMUNITY,
                category="testing",
            ),
        ]
        store.add_skills(skills)
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)
        srv._store = store
        srv._index = index
        srv._embedding = emb
        return srv, store, skills

    def test_search_returns_no_instructions(self):
        """Search results should not include full instructions (privacy/efficiency)."""
        srv, store, _ = self._setup()
        result = srv._handle_search_skills({"query": "debug", "k": 5})
        data = json.loads(result[0].text)
        for r in data:
            assert "instructions" not in r

    def test_get_skill_returns_instructions(self):
        srv, store, skills = self._setup()
        result = srv._handle_get_skill({"skill_id": skills[0].id})
        data = json.loads(result[0].text)
        assert "instructions" in data
        assert data["instructions"] == "Use profiler tools"

    def test_keyword_search_no_index_needed(self):
        """Keyword search should work even without vector index."""
        srv, store, _ = self._setup()
        srv._index = None
        srv._embedding = None
        result = srv._handle_keyword_search({"query": "debug"})
        data = json.loads(result[0].text)
        assert len(data) >= 1

    def test_search_without_store(self):
        """search_skills with no index should return helpful error."""
        srv, store, _ = self._setup()
        srv._index = None
        result = srv._handle_search_skills({"query": "test"})
        data = json.loads(result[0].text)
        assert "error" in data


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------


class TestEmbeddingModel:
    def test_mock_deterministic(self):
        emb = EmbeddingModel(backend="mock")
        v1 = emb.encode_single("hello")
        v2 = emb.encode_single("hello")
        assert (v1 == v2).all()

    def test_mock_different_texts(self):
        emb = EmbeddingModel(backend="mock")
        v1 = emb.encode_single("hello")
        v2 = emb.encode_single("world")
        assert not (v1 == v2).all()

    def test_mock_dimension(self):
        emb = EmbeddingModel(backend="mock")
        assert emb.dimension == 128

    def test_mock_batch_encode(self):
        emb = EmbeddingModel(backend="mock")
        vecs = emb.encode(["hello", "world", "test"])
        assert vecs.shape == (3, 128)

    def test_unsupported_backend(self):
        with pytest.raises(ValueError, match="Unsupported"):
            EmbeddingModel(backend="nonexistent")


# ---------------------------------------------------------------------------
# Pull command (HuggingFace download)
# ---------------------------------------------------------------------------


def _create_fake_hf_db(path: Path) -> Path:
    """Create a small valid skills.db to simulate HF download."""
    db_path = path / "fake_hf.db"
    store = SkillStore(db_path)
    for i in range(5):
        store.add_skill(
            Skill(
                name=f"hf-skill-{i}",
                description=f"HF skill {i}",
                instructions=f"Instructions for HF skill {i}",
                source=SkillSource.LANGSKILLS,
                category="testing",
            )
        )
    store.close()
    return db_path


class TestPull:
    def _mock_download(self, fake_db, monkeypatch):
        """Patch download_skills_db to return a fake cached DB path."""
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)

    def test_pull_fresh_store(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull into empty store should copy directly and report count."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0
        assert "5" in result.output
        assert "Next step" in result.output

    def test_pull_merges_by_default(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull into existing store should merge, not overwrite."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        # Init and add a custom skill
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        store = SkillStore(data_dir / "skills.db")
        store.add_skill(
            Skill(
                name="my-custom",
                description="My skill",
                instructions="Custom instructions unique content",
                source=SkillSource.COMMUNITY,
            )
        )
        store.close()

        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0
        assert "Merged" in result.output

        # Custom skill should still be there
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 6  # 1 custom + 5 from HF
        store.close()

    def test_pull_replace_overwrites(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull --replace should discard existing skills."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        # Add a custom skill
        store = SkillStore(data_dir / "skills.db")
        store.add_skill(
            Skill(
                name="my-custom",
                description="My skill",
                instructions="Custom instructions unique",
                source=SkillSource.COMMUNITY,
            )
        )
        store.close()

        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull", "--replace"])
        assert result.exit_code == 0
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 5  # only HF skills
        store.close()

    def test_pull_auto_inits_data_dir(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull on a non-existent data dir should auto-create it."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0
        assert data_dir.exists()
        assert (data_dir / "skills.db").exists()

    def test_pull_merge_dedup(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull should not create duplicates when run twice."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0
        assert "0 new" in result.output or "unchanged" in result.output
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 5
        store.close()

    def test_pull_empty_db_uses_fast_path(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull after init (empty DB) should use copy, not slow merge."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0
        # Should show "Loaded" (copy path), not "Merged" (merge path)
        assert "Loaded" in result.output
        assert "Merged" not in result.output

    def test_pull_merge_warns_stale_index(self, runner, populated_data_dir, tmp_path, monkeypatch):
        """Pull with existing index should prompt to update."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "pull"])
        assert result.exit_code == 0
        assert "build-index" in result.output

    def test_pull_replace_clears_stale_index(
        self, runner, populated_data_dir, tmp_path, monkeypatch
    ):
        """Pull --replace should remove the old index."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "pull", "--replace"])
        assert result.exit_code == 0
        assert not (populated_data_dir / "index" / "index.faiss").exists()


class TestSkillSourceCompat:
    """Ensure SKILLNET source from HF dataset is handled correctly."""

    def test_skillnet_source_in_store(self):
        store = SkillStore()
        s = Skill(
            name="skillnet-test",
            description="From SkillNet",
            instructions="SkillNet content",
            source=SkillSource.SKILLNET,
            category="development",
        )
        store.add_skill(s)
        retrieved = store.get_skill(s.id)
        assert retrieved.source == SkillSource.SKILLNET
        store.close()

    def test_skillnet_dedup_priority(self):
        """SKILLNET should have lowest priority in dedup."""
        from skill_mcp.dedup import deduplicate_skills

        skills = [
            Skill(
                name="s1", description="d", instructions="same content", source=SkillSource.SKILLNET
            ),
            Skill(
                name="s2",
                description="d",
                instructions="same content",
                source=SkillSource.LANGSKILLS,
            ),
        ]
        result = deduplicate_skills(skills)
        assert len(result) == 1
        assert result[0].source == SkillSource.LANGSKILLS  # LANGSKILLS > SKILLNET


# ---------------------------------------------------------------------------
# Cross-feature lifecycle tests
# ---------------------------------------------------------------------------


class TestCrossFeatureLifecycle:
    """Tests that simulate real user workflows spanning multiple commands."""

    def test_pull_import_build_search(self, runner, data_dir, tmp_path, monkeypatch):
        """Full lifecycle: pull HF data → import custom → build-index → search."""
        # 1. Pull HF skills
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0

        # 2. Import custom skills
        custom_dir = tmp_path / "custom"
        d = custom_dir / "my-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "my-custom-skill"\ndescription: "Custom debugging skill"\n'
            'tags: ["custom"]\n---\n\n## Instructions\n\nCustom skill instructions.\n'
        )
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(custom_dir),
            ],
        )
        assert result.exit_code == 0
        assert "1 added" in result.output

        # 3. Build index (should cover all 6 skills)
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "6 skills" in result.output

        # 4. Search should work
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "search", "custom debugging", "--k", "3"],
        )
        assert result.exit_code == 0
        # Should return scored results
        assert "[" in result.output

    def test_pull_build_import_incremental(self, runner, data_dir, tmp_path, monkeypatch):
        """Pull → build-index → import more → incremental build."""
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)
        runner.invoke(main, ["--data-dir", str(data_dir), "pull"])

        # Build index on 5 HF skills
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "5 skills" in result.output

        # Import one more custom skill
        custom_dir = tmp_path / "extra"
        d = custom_dir / "extra-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "extra"\ndescription: "Extra skill"\n---\n\nExtra instructions.\n'
        )
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(custom_dir),
            ],
        )

        # Incremental build should add only 1
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "Incremental" in result.output
        assert "added 1" in result.output

    def test_import_build_delete_rebuild(self, runner, data_dir, tmp_path):
        """Import → build-index → delete skill → build-index detects deletion and rebuilds."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])

        # Add 3 distinct skills
        store = SkillStore(data_dir / "skills.db")
        s1 = Skill(
            name="s1", description="d", instructions="content alpha", source=SkillSource.COMMUNITY
        )
        s2 = Skill(
            name="s2", description="d", instructions="content beta", source=SkillSource.COMMUNITY
        )
        s3 = Skill(
            name="s3", description="d", instructions="content gamma", source=SkillSource.COMMUNITY
        )
        store.add_skill(s1)
        store.add_skill(s2)
        store.add_skill(s3)
        store.close()

        # Build index on 3 skills
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "3 skills" in result.output

        # Delete one skill (simulates what dedup does)
        store = SkillStore(data_dir / "skills.db")
        store.delete_skill(s1.id)
        store.close()

        # build-index should detect deletion and rebuild
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "Rebuilding" in result.output or "Index built" in result.output

    def test_pull_replace_clears_index_then_rebuild(self, runner, data_dir, tmp_path, monkeypatch):
        """pull --replace → verify index cleared → build-index starts fresh."""
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)
        runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert (data_dir / "index" / "index.faiss").exists()

        # Pull --replace should clear index
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull", "--replace"])
        assert result.exit_code == 0
        assert not (data_dir / "index" / "index.faiss").exists()

        # build-index should do full build, not incremental
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "Index built" in result.output

    def test_build_index_force_changes_model(self, runner, data_dir, skills_dir):
        """build-index with model A → --force with model B → search uses new model."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )

        # Build with model A
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock", "--model", "model-a"],
        )

        # Force rebuild with model B
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "build-index",
                "--backend",
                "mock",
                "--model",
                "model-b",
                "--force",
            ],
        )
        assert result.exit_code == 0
        assert "Index built" in result.output

        # Verify config updated to model B
        config = load_config(data_dir / "config.yaml")
        assert config.embedding.model == "model-b"

        # Verify index metadata has model B
        meta_path = data_dir / "index" / "skill_ids.json"
        with open(meta_path) as f:
            meta = json.load(f)
        assert meta["embedding"]["model"] == "model-b"

    def test_search_k_greater_than_total(self, runner, populated_data_dir):
        """Search with k > total skills should return all skills without error."""
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "search", "test", "--k", "100"],
        )
        assert result.exit_code == 0
        # Should return 3 results (all skills in populated_data_dir)

    def test_status_after_full_lifecycle(self, runner, data_dir, skills_dir, tmp_path, monkeypatch):
        """Status should reflect correct counts after pull + import + build."""
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)

        runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )

        result = runner.invoke(main, ["--data-dir", str(data_dir), "status"])
        assert result.exit_code == 0
        assert "Skills: 8" in result.output  # 5 HF + 3 custom
        assert "Index: 8 skills" in result.output

    def test_double_import_same_skills(self, runner, data_dir, skills_dir):
        """Importing same directory twice should not create duplicates."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        assert result.exit_code == 0
        assert "3 duplicates" in result.output
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 3
        store.close()

    def test_pull_then_pull_merge_is_idempotent(self, runner, data_dir, tmp_path, monkeypatch):
        """Pulling twice with merge should not change skill count."""
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)
        runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        store = SkillStore(data_dir / "skills.db", readonly=True)
        count_after_first = store.count()
        store.close()

        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull"])
        assert result.exit_code == 0
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == count_after_first
        store.close()


# ---------------------------------------------------------------------------
# Server handler edge cases
# ---------------------------------------------------------------------------


class TestServerHandlerEdgeCases:
    """Server handler edge cases that could crash in production."""

    def test_get_skill_nonexistent_id(self):
        """get_skill with invalid ID should return error, not crash."""
        import skill_mcp.server as srv

        store = SkillStore()
        srv._store = store
        result = srv._handle_get_skill({"skill_id": "nonexistent-id"})
        data = json.loads(result[0].text)
        assert "error" in data
        store.close()

    def test_get_skill_store_is_none(self):
        """get_skill when store is None should not crash."""
        import skill_mcp.server as srv

        srv._store = None
        srv._index = None
        srv._embedding = None
        try:
            result = srv._handle_get_skill({"skill_id": "any-id"})
            # If it handles gracefully, check for error message
            data = json.loads(result[0].text)
            assert "error" in data
        except AttributeError:
            pytest.fail("_handle_get_skill crashes when _store is None — needs null check")

    def test_keyword_search_store_is_none(self):
        """keyword_search when store is None should not crash."""
        import skill_mcp.server as srv

        srv._store = None
        try:
            result = srv._handle_keyword_search({"query": "test"})
            data = json.loads(result[0].text)
            assert "error" in data
        except AttributeError:
            pytest.fail("_handle_keyword_search crashes when _store is None — needs null check")

    def test_list_categories_store_is_none(self):
        """list_categories when store is None should not crash."""
        import skill_mcp.server as srv

        srv._store = None
        try:
            result = srv._handle_list_categories()
            json.loads(result[0].text)  # should not crash
        except AttributeError:
            pytest.fail("_handle_list_categories crashes when _store is None — needs null check")

    def test_list_categories_empty_store(self):
        """list_categories with empty store should return empty list."""
        import skill_mcp.server as srv

        store = SkillStore()
        srv._store = store
        result = srv._handle_list_categories()
        data = json.loads(result[0].text)
        assert data == []
        store.close()

    def test_search_k_zero(self):
        """search_skills with k=0 should return empty results."""
        import skill_mcp.server as srv

        store = SkillStore()
        store.add_skill(
            Skill(
                name="test",
                description="test",
                instructions="test content",
                source=SkillSource.COMMUNITY,
            )
        )
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)
        srv._store = store
        srv._index = index
        srv._embedding = emb
        result = srv._handle_search_skills({"query": "test", "k": 0})
        data = json.loads(result[0].text)
        assert isinstance(data, list)
        assert len(data) == 0
        store.close()

    def test_keyword_search_special_characters(self):
        """keyword_search with FTS5 special chars should not crash."""
        import skill_mcp.server as srv

        store = SkillStore()
        store.add_skill(
            Skill(
                name="c++ debugging",
                description="Debug C++ apps",
                instructions="Use gdb for debugging",
                source=SkillSource.COMMUNITY,
            )
        )
        srv._store = store
        # These contain FTS5 operators that could cause syntax errors
        for query in ["c++", "NOT AND OR", '"unclosed quote', "test*", "()"]:
            result = srv._handle_keyword_search({"query": query})
            data = json.loads(result[0].text)
            assert isinstance(data, list)  # should not crash
        store.close()


# ---------------------------------------------------------------------------
# Store additional edge cases
# ---------------------------------------------------------------------------


class TestStoreAdditionalEdgeCases:
    def test_merge_from_empty_source(self, tmp_path):
        """merge_from with empty source DB should be a no-op."""
        empty_path = tmp_path / "empty.db"
        SkillStore(empty_path).close()

        target = SkillStore(tmp_path / "target.db")
        target.add_skill(
            Skill(
                name="existing",
                description="d",
                instructions="c",
                source=SkillSource.COMMUNITY,
            )
        )
        stats = target.merge_from(empty_path)
        assert stats.total == 0
        assert stats.added == 0
        assert target.count() == 1
        target.close()

    def test_merge_from_higher_priority_replaces(self, tmp_path):
        """merge_from should replace when source has higher priority."""
        # Source has ANTHROPIC (priority 4)
        source_path = tmp_path / "source.db"
        source = SkillStore(source_path)
        source.add_skill(
            Skill(
                name="upgraded",
                description="d",
                instructions="same content for both",
                source=SkillSource.ANTHROPIC,
            )
        )
        source.close()

        # Target has LANGSKILLS (priority 2)
        target_path = tmp_path / "target.db"
        target = SkillStore(target_path)
        target.add_skill(
            Skill(
                name="original",
                description="d",
                instructions="same content for both",
                source=SkillSource.LANGSKILLS,
            )
        )
        stats = target.merge_from(source_path)
        assert stats.replaced == 1
        assert target.count() == 1  # replaced, not added
        # The remaining skill should be ANTHROPIC source
        skill = list(target.iter_all())[0]
        assert skill.source == SkillSource.ANTHROPIC
        target.close()

    def test_keyword_search_empty_store(self):
        """keyword_search on empty store should return empty list."""
        store = SkillStore()
        results = store.search_keyword("anything")
        assert results == []
        store.close()

    def test_add_skill_same_id_ignored(self):
        """Adding skill with same ID (INSERT OR IGNORE) should not duplicate."""
        store = SkillStore()
        s1 = Skill(
            name="test", description="d", instructions="content", source=SkillSource.COMMUNITY
        )
        store.add_skill(s1)
        # Same skill again should be ignored
        result = store.add_skill(s1)
        assert not result  # should return False (duplicate)
        assert store.count() == 1
        store.close()

    def test_categories_empty_store(self):
        """categories() and category_counts() on empty store."""
        store = SkillStore()
        assert store.categories() == []
        assert store.category_counts() == []
        store.close()

    def test_skill_with_empty_instructions(self):
        """Skill with empty instructions should still work."""
        store = SkillStore()
        s = Skill(name="empty", description="d", instructions="", source=SkillSource.COMMUNITY)
        store.add_skill(s)
        retrieved = store.get_skill(s.id)
        assert retrieved is not None
        assert retrieved.instructions == ""
        store.close()


# ---------------------------------------------------------------------------
# Index edge cases
# ---------------------------------------------------------------------------


class TestIndexEdgeCases:
    def test_search_empty_index(self):
        """Search on empty index should return empty list."""
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        qv = emb.encode_single("test query")
        results = index.search(qv, k=5)
        assert results == []

    def test_search_k_larger_than_ntotal(self):
        """Search with k > ntotal should return all available results."""
        store = SkillStore()
        store.add_skill(
            Skill(name="s1", description="d", instructions="c1", source=SkillSource.COMMUNITY)
        )
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)

        qv = emb.encode_single("test")
        results = index.search(qv, k=100)
        assert len(results) == 1  # only 1 skill in index
        store.close()

    def test_build_empty_store(self):
        """build() with empty store should create valid but empty index."""
        store = SkillStore()
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)
        assert index.index.ntotal == 0
        assert index.skill_ids == []
        store.close()

    def test_save_load_roundtrip(self, tmp_path):
        """Save → load should preserve all state."""
        store = SkillStore()
        s1 = Skill(name="s1", description="d1", instructions="c1", source=SkillSource.COMMUNITY)
        s2 = Skill(name="s2", description="d2", instructions="c2", source=SkillSource.COMMUNITY)
        store.add_skill(s1)
        store.add_skill(s2)
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.embedding_info = {"backend": "mock", "model": "test"}
        index.build(store, emb)

        idx_dir = tmp_path / "idx"
        index.save(idx_dir)
        loaded = SkillIndex.load(idx_dir)

        assert loaded.index.ntotal == 2
        assert set(loaded.skill_ids) == {s1.id, s2.id}
        assert loaded.embedding_info == {"backend": "mock", "model": "test"}
        assert loaded._dimension == 128

        # Search should work on loaded index
        qv = emb.encode_single("test")
        results = loaded.search(qv, k=5)
        assert len(results) == 2
        store.close()

    def test_update_then_search_finds_new_skill(self):
        """After incremental update, search should find the new skill."""
        store = SkillStore()
        s1 = Skill(
            name="python-debug",
            description="Debug Python apps",
            instructions="Use pdb for Python debugging",
            source=SkillSource.COMMUNITY,
        )
        store.add_skill(s1)
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)

        s2 = Skill(
            name="rust-debug",
            description="Debug Rust apps",
            instructions="Use rust-gdb for Rust debugging",
            source=SkillSource.COMMUNITY,
        )
        store.add_skill(s2)
        index.update(store, emb)

        qv = emb.encode_single("Rust debugging")
        results = index.search(qv, k=2)
        assert len(results) == 2
        result_ids = {r[0] for r in results}
        assert s2.id in result_ids
        store.close()


# ---------------------------------------------------------------------------
# Retriever edge cases
# ---------------------------------------------------------------------------


class TestRetriever:
    def test_retrieve_stale_index_skill_deleted(self):
        """If a skill was deleted from store but still in index, retriever should skip it."""
        from skill_mcp.retriever import retrieve

        store = SkillStore()
        s1 = Skill(name="s1", description="d", instructions="c1", source=SkillSource.COMMUNITY)
        s2 = Skill(name="s2", description="d", instructions="c2", source=SkillSource.COMMUNITY)
        store.add_skill(s1)
        store.add_skill(s2)

        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)

        # Delete s1 from store (but not from index)
        store.delete_skill(s1.id)

        results = retrieve("test query", store, index, emb, k=5)
        # s1 should be silently skipped
        result_ids = {r.skill.id for r in results}
        assert s1.id not in result_ids
        assert s2.id in result_ids
        store.close()

    def test_retrieve_returns_metadata(self):
        """retrieve should include retrieval metadata."""
        from skill_mcp.retriever import retrieve

        store = SkillStore()
        store.add_skill(
            Skill(name="s1", description="d", instructions="c1", source=SkillSource.COMMUNITY)
        )
        emb = EmbeddingModel(backend="mock")
        index = SkillIndex(emb.dimension)
        index.build(store, emb)

        results = retrieve("test", store, index, emb)
        assert len(results) >= 1
        assert results[0].retrieval_metadata["method"] == "vector"
        store.close()


# ---------------------------------------------------------------------------
# CLI edge cases
# ---------------------------------------------------------------------------


class TestCLIEdgeCases:
    def test_import_nonexistent_path(self, runner, data_dir):
        """Import from nonexistent path should fail gracefully."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                "/nonexistent/path",
            ],
        )
        assert result.exit_code != 0

    def test_search_empty_store_with_index(self, runner, data_dir):
        """Edge: what if someone manually deleted all skills but index remains?"""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "search", "test"],
        )
        assert result.exit_code == 0
        # Should show "no index" message since we never built one

    def test_dedup_removes_via_cli(self, runner, data_dir):
        """dedup command removes duplicates inserted via raw SQL (bypassing store dedup)."""
        import sqlite3

        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])

        # Insert duplicates via raw SQL to bypass _add_skill_detail dedup
        store = SkillStore(data_dir / "skills.db")
        s1 = Skill(
            name="s1", description="d", instructions="shared content", source=SkillSource.LANGSKILLS
        )
        s2 = Skill(
            name="s2", description="d", instructions="shared content", source=SkillSource.ANTHROPIC
        )
        s3 = Skill(
            name="s3", description="d", instructions="unique content", source=SkillSource.COMMUNITY
        )
        # Add s2 first (higher priority), then force s1 in via raw SQL
        store.add_skill(s2)
        store.add_skill(s3)
        conn = sqlite3.connect(str(data_dir / "skills.db"))
        conn.execute(
            "INSERT INTO skills (id, name, description, instructions, source, source_id, category, tags, metadata, content_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                s1.id,
                s1.name,
                s1.description,
                s1.instructions,
                s1.source.value,
                s1.source_id,
                s1.category,
                "[]",
                "{}",
                s1.content_hash,
                s1.created_at.isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        store.close()

        # Now store has 3 skills, 2 with same content_hash
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 3
        store.close()

        result = runner.invoke(main, ["--data-dir", str(data_dir), "dedup"])
        assert result.exit_code == 0
        assert "Removed 1" in result.output

    def test_pull_replace_no_existing_db(self, runner, data_dir, tmp_path, monkeypatch):
        """pull --replace when no DB exists yet should work fine."""
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)
        result = runner.invoke(main, ["--data-dir", str(data_dir), "pull", "--replace"])
        assert result.exit_code == 0
        store = SkillStore(data_dir / "skills.db", readonly=True)
        assert store.count() == 5
        store.close()

    def test_status_index_stale_after_import(self, runner, data_dir, skills_dir, tmp_path):
        """Status should show WARNING when index count != store count."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )

        # Add one more skill
        extra_dir = tmp_path / "extra"
        d = extra_dir / "new"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "new"\ndescription: "New"\n---\n\nNew instructions.\n'
        )
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(extra_dir),
            ],
        )

        result = runner.invoke(main, ["--data-dir", str(data_dir), "status"])
        assert result.exit_code == 0
        assert "WARNING" in result.output
        assert "3" in result.output  # index has 3
        assert "4" in result.output  # store has 4


# ---------------------------------------------------------------------------
# Auto-index after import
# ---------------------------------------------------------------------------


class TestAutoIndex:
    """Test automatic index update after import."""

    def test_auto_index_no_index_exists(self, runner, data_dir, skills_dir):
        """Import without existing index should prompt to build manually."""
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--path",
                str(skills_dir),
            ],
        )
        assert result.exit_code == 0
        assert "3 added" in result.output
        assert "no index found" in result.output.lower()
        assert "build-index" in result.output.lower()

    def test_auto_index_incremental(self, runner, populated_data_dir, tmp_path):
        """Import with existing index should auto-update incrementally."""
        new_dir = tmp_path / "new"
        d = new_dir / "auto-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "auto-skill"\ndescription: "Auto-indexed skill"\n---\n\nInstructions.\n'
        )
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--path",
                str(new_dir),
            ],
        )
        assert result.exit_code == 0
        assert "index updated" in result.output.lower()
        assert "1 new skills indexed" in result.output

        # Verify index is actually in sync
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert "WARNING" not in result.output
        assert "4 skills" in result.output  # 3 original + 1 new

    def test_auto_index_no_new_skills(self, runner, populated_data_dir, skills_dir):
        """Re-importing same skills should report index up to date."""
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--path",
                str(skills_dir),
            ],
        )
        assert result.exit_code == 0
        assert "0 added" in result.output or "3 duplicates" in result.output

    def test_no_index_flag_skips_auto_index(self, runner, populated_data_dir, tmp_path):
        """--no-index should skip auto-indexing and leave index stale."""
        new_dir = tmp_path / "skip"
        d = new_dir / "skipped-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "skipped"\ndescription: "Skipped skill"\n---\n\nInstructions.\n'
        )
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(populated_data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(new_dir),
            ],
        )
        assert result.exit_code == 0
        assert "index updated" not in result.output.lower()
        assert "skipped" in result.output.lower() or "build-index" in result.output.lower()

        # Index should be stale
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert "WARNING" in result.output

    def test_auto_index_multiple_imports(self, runner, populated_data_dir, tmp_path):
        """Multiple imports should each incrementally update the index."""
        for i in range(3):
            skill_dir = tmp_path / f"batch{i}"
            d = skill_dir / f"skill-{i}"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f'---\nname: "batch-{i}"\ndescription: "Batch skill {i}"\n---\n\nInstructions {i}.\n'
            )
            result = runner.invoke(
                main,
                [
                    "--data-dir",
                    str(populated_data_dir),
                    "import",
                    "--source",
                    "directory",
                    "--path",
                    str(skill_dir),
                ],
            )
            assert result.exit_code == 0
            assert "1 new skills indexed" in result.output

        # Final status: 3 original + 3 new = 6
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert "6 skills" in result.output
        assert "WARNING" not in result.output

    def test_auto_index_embedding_mismatch(self, runner, data_dir, skills_dir, tmp_path):
        """Auto-index should skip if index embedding doesn't match config."""
        # Init, import, build with mock
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--no-index",
                "--path",
                str(skills_dir),
            ],
        )
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )

        # Change config backend to something different
        from skill_mcp.config import load_config, save_config

        config = load_config(data_dir / "config.yaml")
        config.embedding.backend = "openai"
        config.embedding.model = "text-embedding-3-large"
        save_config(config)

        # Import new skill — should detect mismatch
        new_dir = tmp_path / "mismatch"
        d = new_dir / "mismatch-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "mismatch"\ndescription: "Mismatch test"\n---\n\nInstructions.\n'
        )
        result = runner.invoke(
            main,
            [
                "--data-dir",
                str(data_dir),
                "import",
                "--source",
                "directory",
                "--path",
                str(new_dir),
            ],
        )
        assert result.exit_code == 0
        assert "skipping auto-index" in result.output.lower()
        assert "build-index --force" in result.output.lower()


# ---------------------------------------------------------------------------
# Schema edge cases
# ---------------------------------------------------------------------------


class TestSchemaEdgeCases:
    def test_from_dict_missing_optional_fields(self):
        """from_dict with only required fields should fill defaults."""
        data = {
            "name": "test",
            "description": "d",
            "instructions": "content",
            "source": "community",
        }
        skill = Skill.from_dict(data)
        assert skill.name == "test"
        assert skill.tags == []
        assert skill.category == ""
        assert skill.source_id == ""

    def test_same_content_different_source_same_hash(self):
        """Same instructions from different sources should have same content_hash."""
        s1 = Skill(
            name="a", description="d", instructions="identical", source=SkillSource.LANGSKILLS
        )
        s2 = Skill(
            name="b", description="d", instructions="identical", source=SkillSource.ANTHROPIC
        )
        assert s1.content_hash == s2.content_hash
        # But different IDs since source differs
        assert s1.id != s2.id

    def test_embedding_text_with_empty_instructions(self):
        """to_embedding_text should work with empty instructions."""
        s = Skill(name="test", description="desc", instructions="", source=SkillSource.COMMUNITY)
        text = s.to_embedding_text()
        assert "test" in text
        assert "desc" in text


# ---------------------------------------------------------------------------
# Config edge cases
# ---------------------------------------------------------------------------


class TestConfigEdgeCases:
    def test_partial_yaml(self, tmp_path):
        """Config YAML with only some fields should fill defaults for the rest."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("data_dir: /custom/path\n")
        config = load_config(config_path)
        assert config.data_dir == "/custom/path"
        assert config.embedding.backend == "sentence-transformers"
        assert config.embedding.model == "all-MiniLM-L6-v2"

    def test_empty_yaml(self, tmp_path):
        """Empty YAML file should return defaults."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")
        config = load_config(config_path)
        assert config.data_dir == "~/.skill-mcp"

    def test_config_preserves_custom_embedding(self, tmp_path):
        """Config round-trip should preserve custom embedding settings."""
        from skill_mcp.config import save_config

        config = Config(data_dir=str(tmp_path))
        config.embedding.backend = "openai"
        config.embedding.model = "text-embedding-3-large"
        save_config(config)

        loaded = load_config(config.config_path)
        assert loaded.embedding.backend == "openai"
        assert loaded.embedding.model == "text-embedding-3-large"


# ---------------------------------------------------------------------------
# FTS edge cases
# ---------------------------------------------------------------------------


class TestFTSEdgeCases:
    def test_fts_search_after_pull_copy(self, runner, data_dir, tmp_path, monkeypatch):
        """After pull (copy path), FTS should work for keyword_search."""
        fake_db = _create_fake_hf_db(tmp_path)
        monkeypatch.setattr("skill_mcp.hub.download_skills_db", lambda: fake_db)
        runner.invoke(main, ["--data-dir", str(data_dir), "pull"])

        # keyword search should work
        store = SkillStore(data_dir / "skills.db", readonly=True)
        results = store.search_keyword("HF skill")
        assert len(results) > 0
        store.close()

    def test_fts_search_after_delete(self):
        """FTS should stay in sync after deleting a skill."""
        store = SkillStore()
        s1 = Skill(
            name="unique-findable",
            description="d",
            instructions="special searchable content xyz123",
            source=SkillSource.COMMUNITY,
        )
        store.add_skill(s1)

        results = store.search_keyword("xyz123")
        assert len(results) == 1

        store.delete_skill(s1.id)
        results = store.search_keyword("xyz123")
        assert len(results) == 0
        store.close()

    def test_fts_with_special_characters(self):
        """FTS should handle special characters in queries."""
        store = SkillStore()
        store.add_skill(
            Skill(
                name="c-sharp-testing",
                description="Test C# apps",
                instructions="Use NUnit for C# testing",
                source=SkillSource.COMMUNITY,
            )
        )
        # These should not crash
        for q in ["C#", "c++", "node.js", "test*", "(debug)"]:
            results = store.search_keyword(q)
            assert isinstance(results, list)
        store.close()
