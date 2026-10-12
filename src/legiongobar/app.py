from __future__ import annotations

import argparse
import json
import sys
import tempfile
import hashlib
from pathlib import Path

from .storage import Store
from .backend import Backend
from .i18n import normalize_language


def build_parser():
    parser = argparse.ArgumentParser(description="Independent Python Legion Go desktop frontend")
    parser.add_argument("--demo", action="store_true", help="Preview only; no device writes or real profile switching")
    parser.add_argument("--diagnose", action="store_true", help="Read-only JSON capability probe; no GUI")
    parser.add_argument("--diagnostic-output", type=Path, help="Save read-only diagnostic JSON without requiring a console")
    parser.add_argument("--data-dir", type=Path, help="Override local settings directory")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="Capture a preview and exit (forces --demo)")
    parser.add_argument("--tab", default="Quick")
    parser.add_argument("--smoke", action="store_true", help="Render all pages offscreen and exit (forces --demo)")
    parser.add_argument("--windowed", "--debug-window", action="store_true", help="Use the standard window frame for debugging")
    parser.add_argument("--lang", type=normalize_language,
                        choices=("auto", "zh_CN", "en_US"), help="Interface language: auto, zh-CN or en-US")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.screenshot or args.smoke:
        args.demo = True
    temporary = tempfile.TemporaryDirectory(prefix="LegionGoBar-preview-", ignore_cleanup_errors=True) if args.demo and not args.data_dir else None
    store = Store(args.data_dir or (Path(temporary.name) if temporary else None))
    backend = Backend(store, args.demo)
    if args.diagnose or args.diagnostic_output:
        try:
            result = json.dumps(backend.discover(), ensure_ascii=False, indent=2)
            if args.diagnostic_output:
                args.diagnostic_output.parent.mkdir(parents=True, exist_ok=True)
                args.diagnostic_output.write_text(result, encoding="utf-8")
            else:
                print(result)
            return 0
        finally:
            backend.close()
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from .ui.window import Window
    app = QApplication(sys.argv[:1])
    from .ui.theme import configure_font
    configure_font(app)
    app.setApplicationName("LegionGoBar")
    server = None
    if not args.demo:
        from PySide6.QtNetwork import QLocalServer, QLocalSocket
        name = "LegionGoBar-" + hashlib.sha256(str(store.directory.resolve()).encode()).hexdigest()[:16]
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(300):
            socket.write(b"show")
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            return 0
        server = QLocalServer()
        if not server.listen(name):
            QLocalServer.removeServer(name)
            if not server.listen(name):
                raise RuntimeError(server.errorString())
    from .i18n import I18n
    language = I18n(args.lang or store.get("Language", "auto"), app)
    window = Window(backend, store, no_tray=args.no_tray or args.smoke or bool(args.screenshot),
                    windowed=args.windowed, i18n=language)
    window.show()
    if server:
        def connected():
            connection = server.nextPendingConnection()
            connection.readyRead.connect(lambda: (connection.readAll(), window.reveal()))
            connection.disconnected.connect(connection.deleteLater)
            window.reveal()
        server.newConnection.connect(connected)
    from .ui.hotkey import Hotkey
    hotkey = Hotkey(app, window.reveal) if not args.demo else None
    errors = []

    def capture():
        try:
            if args.smoke:
                for key in window.tab_ids:
                    window.select(key)
                    app.processEvents()
                print(json.dumps({"tabs": window.tab_ids, "rendered_controls": len(window.renderer.rendered), "reference_controls": len(window.reference["controls"])}))
            else:
                window.select(args.tab)
                app.processEvents()
                if app.focusWidget():
                    app.focusWidget().clearFocus()
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(args.screenshot)):
                    raise OSError("Could not save screenshot")
        except Exception as exc:
            errors.append(str(exc))
            print(str(exc), file=sys.stderr)
        finally:
            window.quit()

    if args.screenshot or args.smoke:
        QTimer.singleShot(1500, capture)
    code = app.exec()
    window.pool.waitForDone()
    if hotkey:
        hotkey.close()
    backend.close()
    if server:
        server.close()
    if temporary:
        temporary.cleanup()
    return 1 if errors else code
