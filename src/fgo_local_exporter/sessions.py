"""有界的访客会话；原文件经匿名管道处理，统计与报告仅留在内存。"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

from fgo_local_exporter import __version__
from fgo_local_exporter.errors import ExportError
from fgo_local_exporter.login_session import LoginSession
from fgo_local_exporter.protocol import SERVERS

__all__ = ["LocalStore"]
_BUSY = {
    "generating",
    "waiting_scan",
    "waiting_confirm",
    "game_handoff",
    "game_initialization",
    "fetching_statistics",
    "filtering_statistics",
}
_DATA_TTL = 600
_QR_SWITCHABLE = {"generating", "waiting_scan", "waiting_confirm"}


class _Budget:
    def __init__(self, limit):
        self.limit, self.sizes = (limit, {})
        self.lock = threading.Lock()

    def set(self, key, size):
        with self.lock:
            if sum(self.sizes.values()) - self.sizes.get(key, 0) + size > self.limit:
                raise ExportError("LOCAL_BUSY")
            if size:
                self.sizes[key] = size
            else:
                self.sizes.pop(key, None)


class LocalSession(LoginSession):
    def __init__(self, store, identifier):
        super().__init__(store.profile)
        self.store = store
        self.identifier = identifier
        self.deadline = time.monotonic() + 1800
        self.profile = store.profile
        self.phase = "ready"
        self.source = ""
        self.document = None
        self.details = None
        self.details_bytes = 0
        self.details_revision = ""
        self.report_version = ""
        self.report_phase, self.report_error = ("idle", "")
        self.report_progress = {}
        self.report_cancel = threading.Event()
        self.failure_phase = ""

    def clear(self):
        with self.lock:
            super().clear()
            self.report_cancel.set()
            self.document = None
            self.details = None
            self.details_bytes = 0
            self.details_revision = ""
            self.report_version = ""
            self.report_phase, self.report_error = ("idle", "")
            self.report_progress = {}
            self.source = ""
            self.failure_phase = ""
            self.store.budget.set(self.identifier, 0)

    def memory_size(self):
        return (
            len(self.export)
            + self.details_bytes
            + (self.document.byte_size if self.document else 0)
        )

    def gacha_history(self):
        builder = self.store.builder
        if builder is None:
            raise ExportError("REPORT_NOT_CONFIGURED")
        revision = builder.revision()
        with self.lock:
            self.state()
            if not self.export or self.phase != "complete":
                raise ExportError("STATISTICS_NOT_READY")
            if self.details is not None and self.details_revision == revision:
                return self.details, self.generation
            raw, generation = self.export, self.generation
        if not self.store.details_slots.acquire(blocking=False):
            raise ExportError("LOCAL_BUSY")
        try:
            details = builder.gacha_history(raw)
            with self.lock:
                self.state()
                if generation != self.generation or not self.export:
                    raise ExportError("STATISTICS_NOT_READY")
                if builder is not self.store.builder or revision != builder.revision():
                    raise ExportError("REPORT_ENGINE_RESTART_REQUIRED")
                count = details.byte_size
                self.store.budget.set(
                    self.identifier, self.memory_size() - self.details_bytes + count
                )
                self.details, self.details_bytes = details, count
                self.details_revision = revision
                return details, generation
        finally:
            self.store.details_slots.release()

    def detail_image(self, generation, gacha_id):
        details, current = self.gacha_history()
        if generation != current:
            raise ExportError("STATISTICS_NOT_READY")
        if not self.store.image_slots.acquire(blocking=False):
            raise ExportError("LOCAL_BUSY")
        try:
            builder = self.store.builder
            if builder is None or self.details_revision != builder.revision():
                raise ExportError("REPORT_ENGINE_RESTART_REQUIRED")
            image = builder.gacha_image(details, gacha_id)
            with self.lock:
                self.state()
                if (
                    generation != self.generation
                    or not self.export
                    or builder is not self.store.builder
                ):
                    raise ExportError("STATISTICS_NOT_READY")
            return image
        finally:
            self.store.image_slots.release()

    def state(self):
        with self.lock:
            value = super().state()
            value.pop("saved_export", None)
            value.pop("can_open_export_directory", None)
            value.pop("can_prepare", None)
            value.update(
                {
                    "app_version": __version__,
                    "source": self.source,
                    "can_import": self.phase not in _BUSY,
                    "can_switch_server": self.source == "qr" and self.phase in _QR_SWITCHABLE,
                    "qr_available": self.profile is not None,
                    "qr_error": "" if self.profile is not None else self.store.profile_error,
                    "report_available": self.store.builder is not None,
                    "report_phase": self.report_phase,
                    "report_error": self.report_error,
                    "report_warning": self.document.image_warning if self.document else "",
                    "report_progress": dict(self.report_progress),
                    "report_version": self.report_version,
                    "report_revision": self.document.revision if self.document else "",
                    "engine_revision": self.store.builder.revision() if self.store.builder else "",
                }
            )
            if self.source == "file" and self.phase == "filtering_statistics":
                value["message"] = "正在校验文件并提取统计白名单…"
            elif self.phase == "complete":
                value["message"] = "统计已就绪，请核对角色档案，再下载文件或查看统计报告。"
            return value

    def start(self, server):
        if server not in SERVERS:
            raise ExportError("SERVER_SELECTION_REQUIRED")
        if self.profile is None:
            raise ExportError(self.store.profile_error or "LOCAL_PROFILE_REQUIRED")
        if not self.store.qr_slots.acquire(blocking=False):
            raise ExportError("LOCAL_BUSY")
        try:
            with self.lock:
                super().start(server)
                self.source = "qr"
        except BaseException:
            self.store.qr_slots.release()
            raise

    def _run(self, generation, cancel, server):
        try:
            super()._run(generation, cancel, server)
            with self.lock:
                if self.generation == generation and self.phase == "complete":
                    try:
                        self.store.budget.set(self.identifier, self.memory_size())
                    except ExportError:
                        self.clear()
                        self.phase, self.error = ("error", "LOCAL_BUSY")
        finally:
            self.store.qr_slots.release()

    def select_server(self, server, generation):
        """切换区服只取消旧二维码，新二维码由用户手动申请。"""
        if server not in SERVERS:
            raise ExportError("SERVER_SELECTION_REQUIRED")
        if type(generation) is not int or generation < 0:
            raise ExportError("REQUEST_INVALID")
        with self.lock:
            if generation != self.generation or not self.state()["can_switch_server"]:
                raise ExportError("OPERATION_NOT_READY")
            if server != self.server:
                self.clear()
                self.server = server

    def import_file(self, raw, server):
        if server not in SERVERS:
            raise ExportError("SERVER_SELECTION_REQUIRED")
        if not raw or len(raw) > 16 * 1024 * 1024:
            raise ExportError("INPUT_TOO_LARGE")
        if not self.store.import_slots.acquire(blocking=False):
            raise ExportError("LOCAL_BUSY")
        try:
            with self.lock:
                if self.phase in _BUSY:
                    raise ExportError("OPERATION_NOT_READY")
                self.clear()
                self.cancel = threading.Event()
                self.source, self.server = ("file", server)
                self.phase = "filtering_statistics"
                generation, cancel = (self.generation, self.cancel)
            threading.Thread(
                target=self._import, args=(raw, generation, cancel), daemon=True
            ).start()
        except BaseException:
            self.store.import_slots.release()
            raise

    def _import(self, raw, generation, cancel):
        process = None
        try:
            if self.store.importer is not None:
                body, preview = self.store.importer(raw)
                raw = None
                self._complete_import(body, preview, generation, cancel)
                return
            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            process = subprocess.Popen(
                [sys.executable, "--import-worker"]
                if getattr(sys, "frozen", False)
                else [sys.executable, "-m", "fgo_local_exporter.import_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                output, _ = process.communicate(raw, timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise ExportError("IMPORT_TIMEOUT") from None
            finally:
                raw = None
            if process.returncode or len(output) > 32 * 1024 * 1024 + 32773:
                raise ExportError("IMPORT_INVALID")
            if output.startswith(b"E"):
                code = output[1:].decode("ascii")
                if not code.replace("_", "").isalnum() or len(code) > 80:
                    code = "IMPORT_INVALID"
                raise ExportError(code)
            if not output.startswith(b"O") or len(output) < 5:
                raise ExportError("IMPORT_INVALID")
            length = int.from_bytes(output[1:5], "big")
            if not 0 < length <= 32768:
                raise ExportError("IMPORT_INVALID")
            preview = json.loads(output[5 : 5 + length])
            body = output[5 + length :]
            if not body:
                raise ExportError("IMPORT_INVALID")
            self._complete_import(body, preview, generation, cancel)
        except Exception as error:
            with self.lock:
                if not cancel.is_set() and generation == self.generation:
                    self.phase = "error"
                    self.error = error.code if isinstance(error, ExportError) else "IMPORT_INVALID"
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            self.store.import_slots.release()

    def _complete_import(self, body, preview, generation, cancel):
        with self.lock:
            if cancel.is_set() or generation != self.generation:
                return
            self.store.budget.set(self.identifier, len(body))
            self.export, self.preview = (body, preview)
            self.preview["sha256"] = hashlib.sha256(body).hexdigest()
            self.phase, self.error = ("complete", "")
            self.expires = time.monotonic() + _DATA_TTL

    def build_report(self, options):
        if self.store.builder is None:
            raise ExportError("REPORT_NOT_CONFIGURED")
        if not self.store.report_queue.acquire(blocking=False):
            raise ExportError("LOCAL_BUSY")
        try:
            with self.lock:
                self.state()
                if not self.export or self.phase != "complete":
                    raise ExportError("STATISTICS_NOT_READY")
                if self.report_phase in {"queued", "building"}:
                    raise ExportError("OPERATION_NOT_READY")
                self.report_cancel.set()
                self.report_cancel = threading.Event()
                self.report_version = ""
                self.document = None
                self.store.budget.set(self.identifier, self.memory_size())
                self.report_phase, self.report_error = ("queued", "")
                self.report_progress = {}
                args = (self.export, options, self.generation, self.report_cancel)
            threading.Thread(target=self._report, args=args, daemon=True).start()
        except BaseException:
            self.store.report_queue.release()
            raise

    def _report(self, raw, options, generation, cancel):
        acquired = False
        try:
            acquired = self.store.report_slot.acquire(timeout=15)
            if not acquired:
                raise ExportError("REPORT_QUEUE_TIMEOUT")
            with self.lock:
                self.state()
                if cancel.is_set() or generation != self.generation:
                    return
                self.report_phase = "building"

            def progress(stage, completed, total):
                with self.lock:
                    if cancel.is_set() or generation != self.generation:
                        raise ExportError("CANCELLED")
                    self.report_progress = {"stage": stage, "completed": completed, "total": total}

            document = self.store.builder.render(raw, options, cancel, progress=progress)
            with self.lock:
                self.state()
                if cancel.is_set() or generation != self.generation:
                    return
                self.store.budget.set(
                    self.identifier, len(self.export) + self.details_bytes + document.byte_size
                )
                self.document = document
                self.report_version = secrets.token_hex(12)
                self.report_phase = "ready"
        except Exception as error:
            with self.lock:
                if not cancel.is_set() and generation == self.generation:
                    self.report_phase = "error"
                    self.report_error = (
                        error.code if isinstance(error, ExportError) else "REPORT_BUILD_FAILED"
                    )
        finally:
            if acquired:
                self.store.report_slot.release()
            self.store.report_queue.release()


class LocalStore:
    def __init__(self, config, profile=None, builder=None, importer=None):
        self.config, self.profile, self.builder = (config, profile, builder)
        self.profile_error = "" if profile is not None else "LOCAL_PROFILE_REQUIRED"
        self.importer = importer
        self.lock = threading.Lock()
        self.sessions = {}
        self.budget = _Budget(config.memory_bytes)
        self.qr_slots = threading.BoundedSemaphore(4)
        self.import_slots = threading.BoundedSemaphore(2)
        self.report_slot = threading.BoundedSemaphore(1)
        self.details_slots = threading.BoundedSemaphore(2)
        self.image_slots = threading.BoundedSemaphore(2)
        self.report_queue = threading.BoundedSemaphore(3)
        self.stop = threading.Event()

    def get(self, identifier):
        with self.lock:
            session = self.sessions.get(identifier)
        if session is None:
            return None
        if time.monotonic() >= session.deadline:
            self.remove(identifier)
            return None
        session.state()
        return session

    def create(self):
        self.prune()
        with self.lock:
            if len(self.sessions) >= self.config.max_sessions:
                raise ExportError("LOCAL_BUSY")
            identifier = secrets.token_urlsafe(32)
            session = LocalSession(self, identifier)
            self.sessions[identifier] = session
            return session

    def remove(self, identifier):
        with self.lock:
            session = self.sessions.pop(identifier, None)
        if session:
            session.clear()

    def prune(self):
        with self.lock:
            sessions = tuple(self.sessions.values())
        for session in sessions:
            if time.monotonic() >= session.deadline:
                self.remove(session.identifier)
            else:
                session.state()

    def start_cleanup(self):

        def cleanup():
            while not self.stop.wait(10):
                self.prune()

        threading.Thread(target=cleanup, daemon=True).start()

    def close(self):
        self.stop.set()
        with self.lock:
            identifiers = tuple(self.sessions)
        for identifier in identifiers:
            self.remove(identifier)
