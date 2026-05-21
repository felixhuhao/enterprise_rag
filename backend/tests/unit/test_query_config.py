"""Unit tests for QueryConfig: defaults, dict extraction, toggle behavior."""

from app.rag.query.config import QueryConfig, get_query_config


class TestQueryConfigDefaults:
    def test_all_features_on_by_default(self):
        cfg = QueryConfig()
        assert cfg.use_entity_confirm is True
        assert cfg.use_hyde is True
        assert cfg.use_table_expand is True
        assert cfg.use_rerank is True
        assert cfg.use_rewrite is True

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
            "invalid_key": 123,
            "search_limit": 3,
        }}})
        assert cfg.use_hyde is False
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
