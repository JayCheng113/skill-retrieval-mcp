"""End-to-end workflow tests simulating real user journeys.

Tests the full lifecycle: init → import → build-index → search → status,
plus edge cases discovered via thought experiments.
"""

from __future__ import annotations

import json
import os
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
        ["--data-dir", str(data_dir), "import", "--source", "directory", "--path", str(skills_dir)],
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
            ["--data-dir", str(data_dir), "import", "--source", "directory", "--path", str(skills_dir)],
        )
        assert result.exit_code == 0
        assert "3 added" in result.output
        assert "Store now has 3 skills" in result.output

    def test_import_warns_stale_index(self, runner, populated_data_dir, tmp_path):
        """After import, if index exists, warn user to rebuild."""
        new_skill_dir = tmp_path / "extra"
        new_skill_dir.mkdir()
        d = new_skill_dir / "new-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            '---\nname: "new-skill"\ndescription: "A new skill"\n---\n\nInstructions.\n'
        )
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "import", "--source", "directory", "--path", str(new_skill_dir)],
        )
        assert result.exit_code == 0
        assert "stale" in result.output.lower() or "rebuild" in result.output.lower()

    def test_build_index_mock(self, runner, data_dir, skills_dir):
        runner.invoke(main, ["--data-dir", str(data_dir), "init", "--no-register"])
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "import", "--source", "directory", "--path", str(skills_dir)],
        )
        result = runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "Index built with 3 skills" in result.output
        assert (data_dir / "index" / "index.faiss").exists()
        assert (data_dir / "index" / "skill_ids.json").exists()

    def test_build_index_refuses_overwrite(self, runner, populated_data_dir):
        result = runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "build-index", "--backend", "mock"],
        )
        assert result.exit_code == 0
        assert "--force" in result.output

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
            ["--data-dir", str(data_dir), "import", "--source", "directory", "--path", str(skills_dir)],
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

    def test_status_warns_stale_index(self, runner, populated_data_dir, tmp_path):
        """Status should warn when index count != store count."""
        new_skill_dir = tmp_path / "extra2"
        d = new_skill_dir / "another"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            '---\nname: "another"\ndescription: "Another skill"\n---\n\nInstructions.\n'
        )
        runner.invoke(
            main,
            ["--data-dir", str(populated_data_dir), "import", "--source", "directory", "--path", str(new_skill_dir)],
        )
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "status"])
        assert result.exit_code == 0
        assert "WARNING" in result.output

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
            ["--data-dir", str(data_dir), "import", "--source", "directory", "--path", str(skills_dir)],
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
            main, ["init", "--no-register"],
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
            ["--data-dir", str(data_dir), "import", "--source", "directory", "--path", str(skills_dir)],
        )
        runner.invoke(
            main,
            ["--data-dir", str(data_dir), "build-index", "--backend", "mock", "--model", "test-model"],
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
        s1 = Skill(name="test", description="d", instructions="content", source=SkillSource.COMMUNITY)
        s2 = Skill(name="test", description="d", instructions="content", source=SkillSource.COMMUNITY)
        assert s1.id == s2.id
        assert s1.content_hash == s2.content_hash

    def test_different_content_different_hash(self):
        s1 = Skill(name="test", description="d", instructions="content A", source=SkillSource.COMMUNITY)
        s2 = Skill(name="test", description="d", instructions="content B", source=SkillSource.COMMUNITY)
        assert s1.content_hash != s2.content_hash

    def test_to_embedding_text_truncation(self):
        long_instructions = "x" * 1000
        s = Skill(name="test", description="desc", instructions=long_instructions, source=SkillSource.COMMUNITY)
        text = s.to_embedding_text()
        assert len(text) < 600  # name + desc + 500 chars max

    def test_serialization_roundtrip(self):
        s = Skill(
            name="test", description="desc", instructions="content",
            source=SkillSource.COMMUNITY, category="cat", tags=["a", "b"],
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
        s1 = Skill(name="s1", description="d", instructions="c", source=SkillSource.COMMUNITY, category="cat-a")
        s2 = Skill(name="s2", description="d", instructions="c2", source=SkillSource.COMMUNITY, category="cat-b")
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
                Skill(name=f"s{i}", description="d", instructions=f"content {i}", source=SkillSource.COMMUNITY)
            )
        items = list(store.iter_all())
        assert len(items) == 5
        store.close()

    def test_batch_import_stats(self):
        store = SkillStore()
        skills = [
            Skill(name=f"s{i}", description="d", instructions=f"content {i}", source=SkillSource.COMMUNITY)
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
            source.add_skill(Skill(
                name=f"src-{i}", description="d", instructions=f"src content {i}",
                source=SkillSource.LANGSKILLS,
            ))
        source.close()

        # Create target DB with one overlapping skill
        target_path = tmp_path / "target.db"
        target = SkillStore(target_path)
        target.add_skill(Skill(
            name="existing", description="d", instructions="unique content",
            source=SkillSource.COMMUNITY,
        ))
        stats = target.merge_from(source_path)
        assert stats.added == 3
        assert target.count() == 4  # 1 existing + 3 merged
        target.close()

    def test_merge_from_dedup(self, tmp_path):
        """merge_from should skip duplicates based on content_hash."""
        source_path = tmp_path / "source.db"
        source = SkillStore(source_path)
        source.add_skill(Skill(
            name="shared", description="d", instructions="same content",
            source=SkillSource.LANGSKILLS,
        ))
        source.close()

        target_path = tmp_path / "target.db"
        target = SkillStore(target_path)
        target.add_skill(Skill(
            name="shared", description="d", instructions="same content",
            source=SkillSource.COMMUNITY,  # higher priority
        ))
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
        store.add_skill(Skill(name="test", description="d", instructions="c", source=SkillSource.COMMUNITY))
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
        store.add_skill(Skill(name="test", description="d", instructions="c", source=SkillSource.COMMUNITY))
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


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDedup:
    def test_cross_source_dedup_keeps_higher_priority(self):
        from skill_mcp.dedup import deduplicate_skills

        skills = [
            Skill(name="s1", description="d", instructions="same content", source=SkillSource.LANGSKILLS),
            Skill(name="s2", description="d", instructions="same content", source=SkillSource.ANTHROPIC),
        ]
        result = deduplicate_skills(skills)
        assert len(result) == 1
        assert result[0].source == SkillSource.ANTHROPIC

    def test_no_duplicates_preserved(self):
        from skill_mcp.dedup import deduplicate_skills

        skills = [
            Skill(name="s1", description="d", instructions="content A", source=SkillSource.COMMUNITY),
            Skill(name="s2", description="d", instructions="content B", source=SkillSource.COMMUNITY),
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
            Skill(name="debug-memory", description="Debug memory leaks", instructions="Use profiler tools", source=SkillSource.COMMUNITY, category="debugging"),
            Skill(name="write-tests", description="Write unit tests", instructions="Use pytest framework", source=SkillSource.COMMUNITY, category="testing"),
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
        store.add_skill(Skill(
            name="my-custom",
            description="My skill",
            instructions="Custom instructions unique content",
            source=SkillSource.COMMUNITY,
        ))
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
        store.add_skill(Skill(
            name="my-custom",
            description="My skill",
            instructions="Custom instructions unique",
            source=SkillSource.COMMUNITY,
        ))
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
        """Pull with existing index should warn about staleness."""
        fake_db = _create_fake_hf_db(tmp_path)
        self._mock_download(fake_db, monkeypatch)
        result = runner.invoke(main, ["--data-dir", str(populated_data_dir), "pull"])
        assert result.exit_code == 0
        assert "stale" in result.output.lower()

    def test_pull_replace_clears_stale_index(self, runner, populated_data_dir, tmp_path, monkeypatch):
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
            Skill(name="s1", description="d", instructions="same content", source=SkillSource.SKILLNET),
            Skill(name="s2", description="d", instructions="same content", source=SkillSource.LANGSKILLS),
        ]
        result = deduplicate_skills(skills)
        assert len(result) == 1
        assert result[0].source == SkillSource.LANGSKILLS  # LANGSKILLS > SKILLNET
