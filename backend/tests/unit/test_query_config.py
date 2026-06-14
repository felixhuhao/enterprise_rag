"""Unit tests for QueryConfig: defaults, dict extraction, toggle behavior."""

from app.rag.query.config import QueryConfig, get_query_config, normalize_retrieval_flavor


class TestQueryConfigDefaults:
    def test_all_features_on_by_default(self):
        cfg = QueryConfig()
        assert cfg.retrieval_flavor == "balanced"
        assert cfg.strict_evidence is False
        assert cfg.use_entity_confirm is True
        assert cfg.use_hyde is True
        assert cfg.use_query_expansion is True
        assert cfg.use_table_expand is True
        assert cfg.use_context_expand is True
        assert cfg.use_rerank is True
        assert cfg.use_rewrite is True
        assert cfg.context_expand_window == 1
        assert cfg.context_expand_same_section is True
        assert cfg.context_expand_max_chars == 2400
        assert cfg.query_expansion_count == 3

    def test_toggle_off_individually(self):
        """每个 toggle 可以独立关闭。"""
        cfg = QueryConfig(use_hyde=False, use_rerank=False)
        assert cfg.use_hyde is False
        assert cfg.use_rerank is False
        assert cfg.use_entity_confirm is True  # 其他不受影响


class TestGetQueryConfig:
    def test_none_returns_default(self):
        cfg = get_query_config({})
        assert isinstance(cfg, QueryConfig)
        assert cfg.use_hyde is True

    def test_instance_passthrough(self):
        custom = QueryConfig(use_hyde=False, search_limit=5)
        cfg = get_query_config({"configurable": {"query_config": custom}})
        assert cfg.use_hyde is False
        assert cfg.search_limit == 5

    def test_dict_filtered(self):
        cfg = get_query_config({"configurable": {"query_config": {
            "use_hyde": False,
            "retrieval_flavor": "exact",
            "strict_evidence": True,
            "invalid_key": 123,
            "search_limit": 3,
        }}})
        assert cfg.use_hyde is False
        assert cfg.retrieval_flavor == "exact"
        assert cfg.strict_evidence is True
        assert cfg.search_limit == 3
        assert not hasattr(cfg, "invalid_key")

    def test_empty_configurable(self):
        cfg = get_query_config({"configurable": {}})
        assert isinstance(cfg, QueryConfig)
        assert cfg.use_rerank is True

    def test_step1_minimal_config(self):
        """可以通过 dict 传入 Step1 最小配置。"""
        cfg = get_query_config({"configurable": {"query_config": {
            "use_entity_confirm": False,
            "use_hyde": False,
            "use_table_expand": False,
            "use_rerank": False,
        }}})
        assert cfg.use_entity_confirm is False
        assert cfg.use_rewrite is True  # 默认不改
        assert cfg.use_hyde is False


class TestQueryConfigClamp:
    """Extreme values should be clamped to safe ranges."""

    def test_search_limit_too_high(self):
        assert QueryConfig(search_limit=99999).search_limit == 50

    def test_search_limit_too_low(self):
        assert QueryConfig(search_limit=0).search_limit == 1

    def test_hyde_limit_clamped(self):
        assert QueryConfig(hyde_limit=1000).hyde_limit == 50

    def test_weights_clamped_to_0_1(self):
        cfg = QueryConfig(dense_weight=2.0, sparse_weight=-0.5)
        assert cfg.dense_weight == 1.0
        assert cfg.sparse_weight == 0.0

    def test_rerank_min_top_k_cannot_exceed_max(self):
        cfg = QueryConfig(rerank_min_top_k=20, rerank_max_top_k=5)
        assert cfg.rerank_min_top_k == 5

    def test_rerank_batch_size_clamped(self):
        assert QueryConfig(rerank_batch_size=0).rerank_batch_size == 1
        assert QueryConfig(rerank_batch_size=100).rerank_batch_size == 20

    def test_thresholds_clamped(self):
        cfg = QueryConfig(entity_filter_min_score=-1.0, rerank_cliff_threshold=5.0)
        assert cfg.entity_filter_min_score == 0.0
        assert cfg.rerank_cliff_threshold == 1.0

    def test_content_preview_length_clamped(self):
        assert QueryConfig(content_preview_length=5).content_preview_length == 50
        assert QueryConfig(content_preview_length=50000).content_preview_length == 2000

    def test_context_expand_values_clamped(self):
        assert QueryConfig(context_expand_window=-1).context_expand_window == 0
        assert QueryConfig(context_expand_window=100).context_expand_window == 5
        assert QueryConfig(context_expand_max_chars=100).context_expand_max_chars == 500
        assert QueryConfig(context_expand_max_chars=50000).context_expand_max_chars == 8000

    def test_query_expansion_count_clamped(self):
        assert QueryConfig(query_expansion_count=1).query_expansion_count == 2
        assert QueryConfig(query_expansion_count=99).query_expansion_count == 4

    def test_defaults_unchanged(self):
        """Default values should all be within range (no clamping needed)."""
        cfg = QueryConfig()
        assert cfg.search_limit == 10
        assert cfg.dense_weight == 0.8
        assert cfg.rerank_max_top_k == 10

    def test_invalid_retrieval_flavor_falls_back(self):
        assert QueryConfig(retrieval_flavor="unknown").retrieval_flavor == "balanced"


def test_normalize_retrieval_flavor_valid_inputs():
    assert normalize_retrieval_flavor("balanced") == "balanced"
    assert normalize_retrieval_flavor("exact") == "exact"
    assert normalize_retrieval_flavor("recall") == "recall"
    assert normalize_retrieval_flavor("discovery") == "discovery"


def test_normalize_retrieval_flavor_invalid_falls_back_to_balanced():
    assert normalize_retrieval_flavor("strict_evidence") == "balanced"
    assert normalize_retrieval_flavor("unknown") == "balanced"
    assert normalize_retrieval_flavor("") == "balanced"
    assert normalize_retrieval_flavor(None) == "balanced"  # type: ignore[arg-type]
    assert normalize_retrieval_flavor("Balanced") == "balanced"


class TestRuntimeSettingsClamp:
    """Runtime settings bypass __init__ — clamp() must be called explicitly."""

    def test_runtime_oversize_clamped(self):
        """get_default_query_config() must clamp values from runtime_settings."""
        from unittest.mock import patch, MagicMock
        import app.core.runtime_settings as rs_mod
        from app.rag.query.config import get_default_query_config

        mock_rs = MagicMock()
        mock_rs.get_all_cached.return_value = {
            "query.search_limit": "10000",
            "query.rerank_batch_size": "0",
            "query.dense_weight": "5.0",
            "query.content_preview_length": "99999",
        }
        original = rs_mod.runtime_settings
        rs_mod.runtime_settings = mock_rs
        try:
            cfg = get_default_query_config()
        finally:
            rs_mod.runtime_settings = original
        assert cfg.search_limit == 50
        assert cfg.rerank_batch_size == 1
        assert cfg.dense_weight == 1.0
        assert cfg.content_preview_length == 2000
