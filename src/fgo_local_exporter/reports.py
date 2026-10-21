"""装配独立统计引擎、报告模板和助战组件；完整图片由本机浏览器引擎生成。"""

import asyncio
import hashlib
import importlib.util
import json
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from fgo_local_exporter.errors import ExportError

__all__ = ["ReportBuilder", "ReportDocument", "shared_report_revision"]


def shared_report_revision(source):
    root = source / "fgo_stat_core"
    if not root.is_dir():
        spec = importlib.util.find_spec("fgo_stat_core")
        if spec is None or spec.origin is None:
            raise ExportError("REPORT_NOT_CONFIGURED")
        root = Path(spec.origin).parent
    files = {
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".html", ".json"}
    }
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


@dataclass(repr=False)
class ReportDocument:
    html: str
    assets: dict[str, bytes] = field(repr=False)
    data: dict = field(repr=False)
    revision: str

    @property
    def byte_size(self):
        return (
            len(self.html.encode())
            + sum(map(len, self.assets.values()))
            + len(json.dumps(self.data, ensure_ascii=False).encode())
        )


class ReportBuilder:
    """只调用共享报告模块，不包含独立的公式或报告模板副本。"""

    def __init__(self, config):
        self.config = config
        for name in ("engine_source", "data_dir", "atlas_dir", "asset_dir"):
            if getattr(config, name) is None:
                raise ExportError("REPORT_NOT_CONFIGURED")
        root = config.engine_source.resolve()
        if (root / "fgo_stat_core/infrastructure/report_ui/builder.py").is_file() and str(
            root
        ) not in sys.path:
            sys.path.insert(0, str(root))
        if importlib.util.find_spec("fgo_stat_core") is None:
            raise ExportError("REPORT_NOT_CONFIGURED")
        self._master = None
        self._revision = self.revision()

    def revision(self):
        digest = hashlib.sha256()
        digest.update(shared_report_revision(self.config.engine_source).encode())
        for directory in (self.config.data_dir, self.config.atlas_dir):
            digest.update((directory / "SOURCE_MANIFEST.json").read_bytes())
        return digest.hexdigest()[:16]

    def render(self, raw, options, cancelled):
        try:
            if self.revision() != self._revision:
                raise ExportError("REPORT_ENGINE_RESTART_REQUIRED")
            from fgo_stat_core.features.capture_import.parser import parse_capture
            from fgo_stat_core.features.report.calculator import build_report
            from fgo_stat_core.infrastructure.report_assets import (
                fetch_report_assets,
                plan_report_assets,
            )
            from fgo_stat_core.infrastructure.report_master import load_report_master
            from fgo_stat_core.infrastructure.report_ui.builder import build

            if cancelled.is_set():
                raise ExportError("CANCELLED")
            snapshot = parse_capture(raw, secrets.token_bytes(32), report_fields=True)
            if self._master is None:
                self._master = load_report_master(self.config.data_dir, self.config.atlas_dir)
            report = build_report(
                snapshot,
                self._master,
                generated_at=int(time.time()),
                show_friend_code=options["friend"],
                show_support=options["support"],
            )
            specs = plan_report_assets(
                report, self.config.data_dir, native_support=options["support"]
            )
            asyncio.run(fetch_report_assets(specs, self.config.asset_dir))
            support_html, native_assets = None, {}
            if options["support"] and self.config.native_ui_dir is not None:
                from fgo_stat_core.infrastructure.native_support_render import render_native_blocks

                support_html, native_assets = render_native_blocks(
                    report,
                    self.config.asset_dir,
                    self.config.native_ui_dir,
                    **({"header_font": self.config.header_font} if self.config.header_font else {}),
                    **(
                        {"regular_font": self.config.regular_font}
                        if self.config.regular_font
                        else {}
                    ),
                )
            data = report.model_dump(mode="json")
            source = build(data, asset_dir=self.config.asset_dir, support_html=support_html)
            # 只调整固定标题，角色名和计算结果保持统计引擎的输出。
            # fmt: off
            labels = {
                '<title>FGO 御主纪念册</title>':
                    '<title>FGO 抓包统计</title>',
                '<h1>御主纪念册</h1>':
                    '<h1>FGO 抓包统计</h1>',
                '<div class="memory-label">CHALDEA / MEMORY FILE</div>':
                    '<div class="memory-label">FGO / CN ACCOUNT STATS</div>',
                '<p class="subtitle">把每一次相遇，收进这一本纪念册。</p>':
                    '<p class="subtitle">基于当前账号数据生成的统计快照。</p>',
                '<span>CHALDEA ARCHIVE</span>':
                    '<span>FGO CN STATS</span>',
                '<span>MEMORY RECORD</span>':
                    '<span>ACCOUNT DATA</span>',
                '<h2>相遇，都留有回响。</h2>':
                    '<h2>账号数据概览</h2>',
                '<span>MEMORY PIECE / 01</span> THE JOURNEY CONTINUES':
                    '<span>ACCOUNT / 01</span> FGO CN STATISTICS',
                '<span class="photo-tab">MY CHALDEA</span>':
                    '<span class="photo-tab">角色信息</span>',
                '<span>MY FAVORITE</span>':
                    '<span>角色展示</span>',
                '<div class="hero-empty">✦<br>待写入的回忆</div>':
                    '<div class="hero-empty">✦<br>未提供单推从者</div>',
            }
            # fmt: on

            for old, new in labels.items():
                source = source.replace(old, new)
            # 仅通过本机会话接口提供当前报告白名单内的图片。
            source = source.replace(
                'src="' + self.config.asset_dir.resolve().as_uri() + "/", 'src="assets/'
            )
            assets = {}
            for name in set(re.findall(r'(?:src|href)="assets/([a-z0-9-]+\.png)"', source)):
                path = self.config.asset_dir / name
                if path.is_symlink() or path.resolve().parent != self.config.asset_dir.resolve():
                    raise ExportError("REPORT_RESOURCE_INVALID")
                if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
                    raise ExportError("REPORT_IMAGE_MISSING")
                payload = path.read_bytes()
                key = hashlib.sha256(payload).hexdigest()[:24] + ".png"
                assets[key] = payload
                source = source.replace('"assets/' + name + '"', '"ASSET_BASE/' + key + '"')
            for name, payload in native_assets.items():
                key = hashlib.sha256(payload).hexdigest()[:24] + ".png"
                assets[key] = payload
                source = source.replace('"' + name + '"', '"ASSET_BASE/' + key + '"')
            if re.search(
                r"""(?:src|href)=["'](?:file:|https?:|//|report-native:|assets/)""", source
            ):
                raise ExportError("REPORT_RESOURCE_INVALID")
            if len(assets) > 256 or sum(map(len, assets.values())) > 48 * 1024 * 1024:
                raise ExportError("REPORT_RESOURCE_LIMIT")
            if cancelled.is_set():
                raise ExportError("CANCELLED")
            return ReportDocument(source, assets, data, self._revision)
        except ExportError:
            raise
        except Exception as error:
            code = getattr(error, "code", "REPORT_BUILD_FAILED")
            allowed = {
                "REPORT_IMAGE_MISSING",
                "REPORT_DATA_INVALID",
                "MASTER_DATA_INVALID",
                "REPORT_NATIVE_FONT_MISSING",
                "REPORT_FONT_CONFIG_INVALID",
                "REPORT_ASSET_CACHE_INVALID",
                "REPORT_ASSET_LIMIT",
                "REPORT_ASSET_PATH_INVALID",
            }
            raise ExportError(code if code in allowed else "REPORT_BUILD_FAILED") from None
