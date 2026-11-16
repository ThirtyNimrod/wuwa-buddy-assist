"""CLI entrypoint for calibration, Phase 2 capture daemon, parsing, strategy, and UI serving."""

from __future__ import annotations

import argparse
import functools
import http.server
import logging
import socketserver
import sys
import threading
import time
from pathlib import Path

from src.capture.macro_controller import AbortCaptureError, MacroController, is_admin
from src.capture.notifier import notify_capture_complete, wait_for_game_exit
from src.capture.screen_grabber import run_calibration, run_multi_menu_calibration
from src.config import PROJECT_ROOT, load_config
from src.engine.strategist import run_strategist
from src.parsers.router import parse_captures

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wuwa_buddy_assist")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Static HTTP handler serving the project root without noisy stack traces."""

    def log_message(self, format: str, *args: object) -> None:
        logger.debug(format, *args)


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_ui(port: int = 8080, root: Path | None = None) -> None:
    """Serve the project directory so ui/index.html can fetch /data/*.json cleanly."""
    serve_root = root or PROJECT_ROOT
    handler = functools.partial(_QuietHandler, directory=str(serve_root))
    with _ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        url = f"http://127.0.0.1:{port}/ui/index.html"
        print(f"Serving wuwa-buddy-assist dashboard at: {url}")
        print("Press Ctrl+C to stop the server.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down UI server.")


def _run_with_abort_hotkey(controller: MacroController, abort_key: str, fn: object) -> None:
    """Attach the F12 abort hotkey for the duration of a capture run."""
    hook_registered = False
    try:
        import keyboard

        keyboard.add_hotkey(abort_key.lower(), controller.request_abort)
        hook_registered = True
    except Exception as exc:
        logger.debug("Unable to register abort hotkey %s: %s", abort_key, exc)

    try:
        fn()  # type: ignore[operator]
    finally:
        if hook_registered:
            try:
                import keyboard

                keyboard.remove_hotkey(abort_key.lower())
            except Exception:
                pass


def _run_capture_sequence(
    from_terminal: bool = False,
    scan_roster: bool = True,
    scan_bag: bool = False,
    navigate_bag: bool = False,
    countdown_sec: int = 3,
    roster_count: int | None = None,
    max_bag_echos: int | None = None,
    test_run: bool = False,
) -> None:
    """Execute automated capture sequence with countdown, F12 abort, Toast, and parser trigger."""
    cfg = load_config()
    if not is_admin():
        raise PermissionError(
            "Windows Administrator privileges are required for pydirectinput inside Wuthering Waves. "
            "Run run_capture_admin.bat / run_test_capture_admin.bat or open an Administrator PowerShell terminal."
        )

    effective_roster_count = roster_count if roster_count is not None else (1 if test_run else cfg.roster_count)
    effective_bag_count = max_bag_echos if max_bag_echos is not None else (6 if test_run else cfg.max_bag_echos)

    controller = MacroController(config=cfg)
    mode_label = "TEST RUN (1 Resonator + 6 Bag Echoes)" if test_run else "FULL SCAN"
    print(f"Starting {mode_label} in {countdown_sec}s... Ensure Wuthering Waves (1600x900 / 16:9 windowed) is ready.")
    print(f"Press {cfg.hotkey_abort} at any time to abort immediately.")
    for remaining in range(countdown_sec, 0, -1):
        print(f"  {remaining}...")
        time.sleep(1.0)

    def _execute() -> None:
        if scan_roster:
            res_info = controller.scan_roster_loop(
                roster_count=effective_roster_count,
                from_terminal=from_terminal,
            )
            print(f"[Capture] Roster scan complete: {res_info['characters_scanned']} characters.")
        if scan_bag:
            bag_info = controller.scan_backpack_loop(
                max_echos=effective_bag_count,
                navigate_from_game=navigate_bag,
            )
            print(f"[Capture] Backpack scan complete: {bag_info['echoes_scanned']} echoes.")

    try:
        _run_with_abort_hotkey(controller, cfg.hotkey_abort, _execute)
    except AbortCaptureError as exc:
        print(f"[ABORTED] {exc}")
        return

    notify_capture_complete()
    parse_result = parse_captures(config=cfg)
    print(f"[Parse] Mode={parse_result.get('mode')} Status={parse_result.get('status')}")
    if "agent_task_path" in parse_result:
        print(f"[Parse] Generated {parse_result['agent_task_path']}")

    if cfg.wait_for_game_exit and not test_run:
        print("Waiting for Wuthering Waves (Client-Win64-Shipping.exe) to exit before post-processing...")
        wait_for_game_exit()
        print("Game closed. Captures are ready in captures/latest/.")
    elif test_run:
        print("Test run finished (skipping WAIT_FOR_GAME_EXIT). Inspect captures/latest/ now.")


def listen_hotkeys() -> None:
    """Listen for F8 (Calibrate), F9 (Roster Scan), F10 (Backpack Scan), and F12 (Abort)."""
    try:
        import keyboard
    except ImportError as exc:
        raise RuntimeError(
            "Hotkey listener requires the 'keyboard' package (`pip install keyboard`)."
        ) from exc

    cfg = load_config()
    if not is_admin():
        logger.warning(
            "Not running as Administrator. pydirectinput clicks (F9/F10) will be ignored by "
            "Wuthering Waves unless started from an Administrator shell or run_capture_admin.bat."
        )

    controller = MacroController(config=cfg)
    scan_lock = threading.Lock()

    logger.info("Listening for hotkeys:")
    logger.info("  %s -> Visual Calibration Preview", cfg.hotkey_calibrate)
    logger.info("  %s -> Roster Scan (from Resonators screen)", cfg.hotkey_scan_roster)
    logger.info("  %s -> Backpack Scan (from Backpack Echoes screen)", cfg.hotkey_scan_bag)
    logger.info("  %s -> Instant Abort", cfg.hotkey_abort)

    def _on_calibrate() -> None:
        out = run_calibration(
            monitor_index=cfg.game_monitor,
            expected_aspect_ratio=cfg.aspect_ratio,
        )
        print(f"[Calibrate] Saved calibration preview to: {out}")

    def _on_scan_roster() -> None:
        if not scan_lock.acquire(blocking=False):
            print("[Hotkey] A capture scan is already running.")
            return
        try:
            res = controller.scan_roster_loop(from_terminal=False)
            print(f"[F9] Roster scan complete ({res['characters_scanned']} chars).")
            notify_capture_complete()
            parse_captures(config=cfg)
        except AbortCaptureError as exc:
            print(f"[ABORTED] {exc}")
        except Exception as exc:
            logger.error("Roster scan failed: %s", exc)
        finally:
            scan_lock.release()

    def _on_scan_bag() -> None:
        if not scan_lock.acquire(blocking=False):
            print("[Hotkey] A capture scan is already running.")
            return
        try:
            res = controller.scan_backpack_loop(navigate_from_game=False)
            print(f"[F10] Backpack scan complete ({res['echoes_scanned']} echoes).")
            notify_capture_complete()
            parse_captures(config=cfg)
        except AbortCaptureError as exc:
            print(f"[ABORTED] {exc}")
        except Exception as exc:
            logger.error("Backpack scan failed: %s", exc)
        finally:
            scan_lock.release()

    def _on_abort() -> None:
        controller.request_abort()
        print(f"[{cfg.hotkey_abort}] Abort requested! Stopping capture...")

    keyboard.add_hotkey(cfg.hotkey_calibrate.lower(), _on_calibrate)
    keyboard.add_hotkey(
        cfg.hotkey_scan_roster.lower(),
        lambda: threading.Thread(target=_on_scan_roster, daemon=True).start(),
    )
    keyboard.add_hotkey(
        cfg.hotkey_scan_bag.lower(),
        lambda: threading.Thread(target=_on_scan_bag, daemon=True).start(),
    )
    keyboard.add_hotkey(cfg.hotkey_abort.lower(), _on_abort)

    print("Hotkey listener active. Press Ctrl+C in this terminal to exit.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped hotkey listener.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wuwa-buddy-assist",
        description="Non-intrusive Wuthering Waves build companion, capture daemon, parser, and strategist.",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Grab screen (or synthetic canvas with --synthetic, or file with --image) and save calibration_preview.png.",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use a synthetic 1600x900 16:9 canvas instead of live screen capture during --calibrate.",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Optional screenshot path to overlay anchors onto during --calibrate.",
    )
    parser.add_argument(
        "--menu",
        default=None,
        help="Optional menu filter for --calibrate (e.g., terminal, overview, weapon, forte, echo_wheel, echo_customization).",
    )
    parser.add_argument(
        "--calibrate-menus",
        action="store_true",
        help="Generate per-menu calibration overlays in captures/calibration/ from captured screenshots.",
    )
    parser.add_argument(
        "--terminal-image",
        type=Path,
        default=None,
        help="Optional Terminal menu screenshot path to use for 01_terminal.png during --calibrate-menus.",
    )
    parser.add_argument(
        "--scan-from-terminal",
        action="store_true",
        help="Focus 16:9 Wuthering Waves window (e.g. 1600x900) at Terminal menu, click Resonators, and capture.",
    )
    parser.add_argument(
        "--include-bag",
        action="store_true",
        help="When used with --scan-from-terminal, also navigate to Backpack Echoes after scanning the roster.",
    )
    parser.add_argument(
        "--test-run",
        action="store_true",
        help="Fast test run: scan 1 Resonator + 6 Backpack Echoes and skip waiting for game exit.",
    )
    parser.add_argument(
        "--roster-count",
        type=int,
        default=None,
        help="Override ROSTER_COUNT from .env during capture.",
    )
    parser.add_argument(
        "--max-bag-echos",
        type=int,
        default=None,
        help="Override MAX_BAG_ECHOS from .env during capture.",
    )
    parser.add_argument(
        "--scan-roster",
        action="store_true",
        help="Run Roster screenshot scan directly from the Resonators (C) screen.",
    )
    parser.add_argument(
        "--scan-bag",
        action="store_true",
        help="Run Backpack Echoes screenshot scan directly from the Backpack Echoes (B) screen.",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Run the Phase 3 parser router on captures/latest/.",
    )
    parser.add_argument(
        "--mode",
        choices=("agent", "offline", "online"),
        default=None,
        help="Override APP_MODE from .env when running --parse.",
    )
    parser.add_argument(
        "--strategize",
        action="store_true",
        help="Run Phase 4 Strategist Engine on data/roster.json + data/echo_bag.json.",
    )
    parser.add_argument(
        "--serve-ui",
        action="store_true",
        help="Start local HTTP server for ui/index.html.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for --serve-ui (default: 8080).",
    )
    parser.add_argument(
        "--listen-hotkeys",
        action="store_true",
        help="Start global hotkey listener (F8 calibrate, F9 roster, F10 bag, F12 abort).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()

    ran_action = False

    if args.calibrate:
        ran_action = True
        output_path = run_calibration(
            monitor_index=cfg.game_monitor,
            use_synthetic=args.synthetic,
            expected_aspect_ratio=cfg.aspect_ratio,
            source_image_path=args.image,
            menu_filter=args.menu,
        )
        print(f"[Calibrate] Saved calibration overlay to {output_path}")

    if args.calibrate_menus:
        ran_action = True
        sources = {"terminal": args.terminal_image} if args.terminal_image else None
        outputs = run_multi_menu_calibration(menu_sources=sources)
        for menu_name, out_path in outputs.items():
            print(f"[Calibrate:{menu_name}] {out_path}")

    if args.scan_from_terminal:
        ran_action = True
        _run_capture_sequence(
            from_terminal=True,
            scan_roster=True,
            scan_bag=args.include_bag,
            navigate_bag=args.include_bag,
            roster_count=args.roster_count,
            max_bag_echos=args.max_bag_echos,
            test_run=args.test_run,
        )

    if args.scan_roster:
        ran_action = True
        _run_capture_sequence(
            from_terminal=False,
            scan_roster=True,
            scan_bag=False,
            navigate_bag=False,
            roster_count=args.roster_count,
            max_bag_echos=args.max_bag_echos,
            test_run=args.test_run,
        )

    if args.scan_bag:
        ran_action = True
        _run_capture_sequence(
            from_terminal=False,
            scan_roster=False,
            scan_bag=True,
            navigate_bag=False,
            roster_count=args.roster_count,
            max_bag_echos=args.max_bag_echos,
            test_run=args.test_run,
        )

    if args.parse:
        ran_action = True
        result = parse_captures(mode=args.mode, config=cfg)
        print(f"[Parse] Mode={result.get('mode')} Status={result.get('status')}")
        if "agent_task_path" in result:
            print(f"[Parse] Generated {result['agent_task_path']}")

    if args.strategize:
        ran_action = True
        recs = run_strategist()
        print(
            f"[Strategist] UL {recs.union_level} | Alerts={len(recs.alerts)} | "
            f"Swaps={len(recs.swap_recommendations)} | Cleanup={recs.echo_cleanup.candidate_count}"
        )
        print(f"[Strategist] Waveplate Focus: {recs.waveplate_plan.primary_focus}")

    if args.serve_ui:
        ran_action = True
        serve_ui(port=args.port)

    if args.listen_hotkeys:
        ran_action = True
        listen_hotkeys()

    if not ran_action:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
