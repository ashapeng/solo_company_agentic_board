from server.harness.config import HarnessConfig, load_config, save_config


def test_hardening_disagreement_threshold_default_is_four():
    """Spec §9.2.2 + supplement choice 1: default disagreement_threshold = 4."""
    cfg = HarnessConfig()
    assert cfg.hardening["disagreement_threshold"] == 4


def test_hardening_auto_promote_summarizer_model_default_is_none():
    """Supplement choice 2: None falls back to atomizer_model at use site."""
    cfg = HarnessConfig()
    assert cfg.hardening["auto_promote_summarizer_model"] is None


def test_hardening_auto_promote_max_pairs_default_is_two():
    """Supplement choice 3: cap at 2 pairs per session (cost ceiling)."""
    cfg = HarnessConfig()
    assert cfg.hardening["auto_promote_max_pairs"] == 2


def test_hardening_auto_promote_enabled_default_is_false():
    """Supplement choice 5: dark-launch — disabled until calibrated."""
    cfg = HarnessConfig()
    assert cfg.hardening["auto_promote_enabled"] is False


def test_hardening_p5b_keys_round_trip_via_json(tmp_path):
    """Save + reload preserves all four P5b keys."""
    cfg = HarnessConfig()
    cfg.hardening["disagreement_threshold"] = 6
    cfg.hardening["auto_promote_summarizer_model"] = "qwen/qwen3.6-max-preview"
    cfg.hardening["auto_promote_max_pairs"] = 3
    cfg.hardening["auto_promote_enabled"] = True
    path = tmp_path / "harness_config.json"
    save_config(cfg, path=path)
    reloaded = load_config(path=path)
    assert reloaded.hardening["disagreement_threshold"] == 6
    assert reloaded.hardening["auto_promote_summarizer_model"] == "qwen/qwen3.6-max-preview"
    assert reloaded.hardening["auto_promote_max_pairs"] == 3
    assert reloaded.hardening["auto_promote_enabled"] is True
