from app.models.schema import VideoParams


def test_localai_webui_subtitle_fields_exist():
    expected = ['subtitle_animation', 'subtitle_display_mode']
    missing = [name for name in expected if name not in VideoParams.model_fields]
    assert not missing, f"missing VideoParams fields: {missing}"


def test_localai_webui_subtitle_fields_assignable():
    params = VideoParams.model_construct()
    samples = {"subtitle_display_mode": "sentence", "subtitle_animation": "none"}
    for name in ['subtitle_animation', 'subtitle_display_mode']:
        value = samples[name]
        setattr(params, name, value)
        assert getattr(params, name) == value
