import threading

import pytest

from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.reports import ReportBuilder, shared_report_revision
from fgo_local_exporter.settings import LocalConfig


@pytest.mark.parametrize(
    "name",
    [
        "features/report/calculator.py",
        "features/capture_import/parser.py",
        "infrastructure/report_ui/template.html",
        "infrastructure/native_support_ui/typography.py",
        "infrastructure/native_support_ui/asset_hashes.json",
        "contracts/report.py",
    ],
)
def test_shared_module_changes_require_restart(tmp_path, name):
    config = make_config(tmp_path, name)
    source = config.engine_source
    root = source / "fgo_stat_core"
    builder = ReportBuilder(config)
    before = shared_report_revision(source)
    (root / name).write_text("synthetic version B", encoding="utf-8")
    assert shared_report_revision(source) != before
    with pytest.raises(ExportError, match="REPORT_ENGINE_RESTART_REQUIRED"):
        builder.render(b"synthetic", {"friend": False, "support": False}, threading.Event())


def make_config(tmp_path, name):
    source = tmp_path / "src"
    root = source / "fgo_stat_core"
    for filename in (
        "infrastructure/report_ui/builder.py",
        "infrastructure/native_support_render.py",
        "infrastructure/native_support_adapter.py",
        "infrastructure/report_master.py",
        "infrastructure/report_assets.py",
        "infrastructure/report_fonts.py",
        name,
    ):
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic version A", encoding="utf-8")
    for folder in ("data", "atlas"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "SOURCE_MANIFEST.json").write_text('{"files":[]}')
    return LocalConfig(
        engine_source=source,
        data_dir=tmp_path / "data",
        atlas_dir=tmp_path / "atlas",
        asset_dir=tmp_path / "assets",
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.invalid",
        "https://public.invalid/path",
        "https://name:password@public.invalid",
        "https://127.0.0.1:55313",
    ],
)
def test_rejects_remote_or_ambiguous_origins(origin):
    with pytest.raises(ExportError, match="LOCAL_CONFIG_INVALID"):
        LocalConfig(origin=origin)


def test_resource_manifest_update_also_invalidates_cached_calculations(tmp_path):
    config = make_config(tmp_path, "features/report/calculator.py")
    builder = ReportBuilder(config)
    before = builder.revision()
    (config.data_dir / "SOURCE_MANIFEST.json").write_text('{"files":[],"revision":"B"}')
    assert builder.revision() != before
    with pytest.raises(ExportError, match="REPORT_ENGINE_RESTART_REQUIRED"):
        builder.render(b"synthetic", {"friend": False, "support": False}, threading.Event())
