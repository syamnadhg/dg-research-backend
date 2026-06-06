from facade import config


def test_web_config_has_required_client_keys():
    cfg = config.web_config()
    for k in ("apiKey", "authDomain", "projectId", "appId"):
        assert cfg[k], f"missing {k}"
    assert cfg["projectId"] == config.PROJECT_ID


def test_origins():
    # CLI/skill use reliable IPv4; the browser sign-in uses localhost so
    # Firebase recognizes the authorized domain.
    assert config.bridge_origin().startswith("http://127.0.0.1:")
    assert config.login_origin().startswith("http://localhost:")
    assert str(config.BRIDGE_PORT) in config.bridge_origin()


def test_store_namespace_is_isolated_from_device_keystore():
    # Load-bearing: must NOT collide with research-automate's "super-research".
    assert config.STORE_SERVICE == "super-agent"
    assert config.STORE_DIR_NAME == ".super-agent"
