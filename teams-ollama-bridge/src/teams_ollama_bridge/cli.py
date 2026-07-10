"""Kommandozeilenschnittstelle."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from teams_ollama_bridge.agent_loop import build_mcp_client, build_tool_policy
from teams_ollama_bridge.attachment_service import AttachmentService
from teams_ollama_bridge.config import Settings, load_settings
from teams_ollama_bridge.exceptions import (
    BridgeError,
    ConfigurationError,
    InstanceAlreadyRunningError,
    MCPAuthenticationError,
    MCPProtocolError,
    MCPUnavailableError,
)
from teams_ollama_bridge.file_service import is_file_stable, load_input_request, output_path_for
from teams_ollama_bridge.logging_config import get_logger, setup_logging
from teams_ollama_bridge.models import ProcessorMode
from teams_ollama_bridge.repository import RequestRepository
from teams_ollama_bridge.utils import discover_onedrive_paths, truncate_for_log
from teams_ollama_bridge.worker import create_worker

logger = get_logger(__name__)


def _init_logging(settings: Settings) -> None:
    setup_logging(
        settings.log_level,
        settings.log_file_path,
        settings.log_max_bytes,
        settings.log_backup_count,
    )


def cmd_run(_args: argparse.Namespace) -> int:
    try:
        worker = create_worker()
        worker.run()
        return 0
    except InstanceAlreadyRunningError as exc:
        print(f"Fehler: {exc.user_message}", file=sys.stderr)
        return 1
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1


def cmd_once(_args: argparse.Namespace) -> int:
    try:
        worker = create_worker()
        count = worker.process_pending_files()
        print(f"{count} Datei(en) verarbeitet.")
        worker.release_lock()
        return 0
    except InstanceAlreadyRunningError as exc:
        print(f"Fehler: {exc.user_message}", file=sys.stderr)
        return 1
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1


def cmd_check(_args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        _init_logging(settings)
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1

    print("=== teams-ollama-bridge check ===\n")
    ok = True

    print(f"Processor-Modus: {settings.processor_mode.value}")
    print(f"Umgebung: {settings.app_env}")

    directories = {
        "Input": settings.input_dir,
        "Output": settings.output_dir,
        "Archiv": settings.processed_input_dir,
        "Fehler": settings.failed_input_dir,
    }
    for label, directory in directories.items():
        exists = directory.exists() if directory else False
        writable = False
        if exists and directory:
            writable = _check_writable(directory)
        status = "OK" if exists and writable else "FEHLER"
        if status == "FEHLER":
            ok = False
        print(f"  {label}: {directory} [{status}]")

    if settings.output_dir:
        test_file = settings.output_dir / ".write_test"
        try:
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            print("  Schreibrechte Output: OK")
        except OSError:
            print("  Schreibrechte Output: FEHLER")
            ok = False

    try:
        repo = RequestRepository(settings.database_path)
        _ = repo.list_pending_and_failed()
        print(f"  SQLite: {settings.database_path} [OK]")
    except BridgeError:
        print(f"  SQLite: {settings.database_path} [FEHLER]")
        ok = False

    if settings.processor_mode == ProcessorMode.OLLAMA:
        url = f"{settings.ollama_base_url.rstrip('/')}/api/tags"
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url)
            if response.status_code == 200:
                print(f"  Ollama: {settings.ollama_base_url} [OK]")
                print(f"  Modell: {settings.ollama_model}")
            else:
                print(f"  Ollama: HTTP {response.status_code} [FEHLER]")
                ok = False
        except httpx.HTTPError:
            print(f"  Ollama: nicht erreichbar unter {settings.ollama_base_url} [FEHLER]")
            ok = False
    else:
        print("  Ollama: nicht geprüft (Mock-Modus aktiv)")

    print()
    if ok:
        print("Zusammenfassung: Alle Prüfungen bestanden.")
        return 0
    print("Zusammenfassung: Es wurden Probleme gefunden.")
    return 1


def _check_writable(directory: Path) -> bool:
    test_file = directory / ".perm_test"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        return True
    except OSError:
        return False


def cmd_process_file(args: argparse.Namespace) -> int:
    path = Path(args.file_path)
    if not path.exists():
        print(f"Datei nicht gefunden: {path}", file=sys.stderr)
        return 1
    try:
        worker = create_worker()
        success = worker.process_single_file(path)
        worker.release_lock()
        return 0 if success else 1
    except (InstanceAlreadyRunningError, ConfigurationError) as exc:
        print(f"Fehler: {exc.user_message}", file=sys.stderr)
        return 1


def cmd_list_pending(_args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        _init_logging(settings)
        repo = RequestRepository(settings.database_path)
        records = repo.list_pending_and_failed()
        if not records:
            print("Keine offenen oder fehlgeschlagenen Requests.")
            return 0
        print(f"{'Request-ID':<40} {'Status':<12} {'Retries':<8} Datei")
        print("-" * 90)
        for record in records:
            filename = record.input_filename or "-"
            print(
                f"{truncate_for_log(record.request_id, 40):<40} "
                f"{record.status.value:<12} "
                f"{record.retry_count:<8} "
                f"{truncate_for_log(filename, 30)}"
            )
        return 0
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1


def cmd_retry_failed(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        _init_logging(settings)
        repo = RequestRepository(settings.database_path)
        failed = repo.list_failed()
        if not failed:
            print("Keine fehlgeschlagenen Requests vorhanden.")
            return 0

        if not args.yes:
            print(f"{len(failed)} fehlgeschlagene Request(s) gefunden.")
            answer = input("Erneut versuchen? [j/N]: ").strip().lower()
            if answer not in ("j", "ja", "y", "yes"):
                print("Abgebrochen.")
                return 0

        reset_count = 0
        input_dir = settings.input_dir
        failed_dir = settings.failed_input_dir
        if input_dir is None or failed_dir is None:
            print("Verzeichnispfade sind nicht konfiguriert.", file=sys.stderr)
            return 1

        for record in failed:
            input_path = None
            error_path = None
            if record.input_filename:
                input_path = input_dir / record.input_filename
                error_path = failed_dir / record.input_filename
            file_exists = (
                (input_path and input_path.exists())
                or (error_path and error_path.exists())
            )
            if not file_exists:
                print(
                    f"  Überspringe {record.request_id}: Inputdatei nicht gefunden."
                )
                continue
            if repo.reset_failed_to_discovered(record.request_id):
                reset_count += 1
                print(f"  {record.request_id} -> discovered")

        print(f"{reset_count} Request(s) zurückgesetzt.")
        return 0
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1


def cmd_show_request(args: argparse.Namespace) -> int:
    """Status eines Requests anzeigen und Output-Datei suchen."""
    try:
        settings = load_settings()
        _init_logging(settings)
        repo = RequestRepository(settings.database_path)
        record = repo.get(args.request_id)
        if record is None:
            print(f"Request '{args.request_id}' nicht in SQLite gefunden.")
            return 1

        print(f"=== Request: {record.request_id} ===\n")
        print(f"Status:              {record.status.value}")
        print(f"Input-Datei:         {record.input_filename or '-'}")
        print(f"Output-Dateiname:    {record.output_filename or '-'}")
        print(f"Modell:              {record.model or '-'}")
        print(f"Dauer:               {record.processing_duration_ms or '-'} ms")
        print(f"Erstellt:            {record.created_at or '-'}")
        print(f"Abgeschlossen:       {record.completed_at or '-'}")
        if record.error_message:
            print(f"Fehler:              {record.error_message}")

        output_name = record.output_filename or f"response_{args.request_id}.json"
        if settings.output_dir:
            expected = output_path_for(settings.output_dir, args.request_id)
            print("\nErwarteter Output-Pfad:")
            print(f"  {expected}")
            print(f"  Vorhanden: {'Ja' if expected.exists() else 'Nein'}")
            if expected.exists():
                print(f"  Größe: {expected.stat().st_size} Bytes")

        if settings.teams_llm_root and settings.teams_llm_root.exists():
            print(f"\nSuche '{output_name}' unter {settings.teams_llm_root} ...")
            matches = list(settings.teams_llm_root.rglob(output_name))
            if matches:
                print("Gefunden:")
                for match in matches:
                    print(f"  {match}")
            else:
                print("  Nicht gefunden.")
                print(
                    "\nHinweis: Wenn der Worker 'Outputdatei erstellt' meldet, die Datei "
                    "aber fehlt, hat Flow 2 sie möglicherweise bereits verschoben "
                    "(ggf. in einen anderen Ordner als processed\\input) oder im "
                    "Fehlerzweig verarbeitet."
                )
        return 0
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1


def cmd_inspect_attachments(args: argparse.Namespace) -> int:
    """Attachments einer Request-JSON inspizieren ohne Verarbeitung."""
    path = Path(args.file_path)
    if not path.exists():
        print(f"Datei nicht gefunden: {path}", file=sys.stderr)
        return 1
    try:
        settings = load_settings()
        _init_logging(settings)
        request = load_input_request(path)
        print(f"Request: {request.request_id}")
        print(f"Attachments: {len(request.attachments)}\n")

        if not request.attachments:
            print("Keine Attachments vorhanden.")
            return 0

        service = AttachmentService(settings)
        for index, info in enumerate(request.attachments, start=1):
            print(f"{index}. {info.name or '(ohne Name)'}")
            print(f"   localPath: {info.local_path or '-'}")
            print(f"   status: {info.status or '-'}")
            if info.error:
                print(f"   error: {info.error}")
            if info.local_path and info.local_path.strip():
                try:
                    resolved = service._resolver.resolve_local_path(info.local_path)
                    print(f"   aufgelöst: {resolved.name}")
                    print(f"   vorhanden: {'Ja' if resolved.exists() else 'Nein'}")
                    if resolved.exists():
                        print(f"   Größe: {resolved.stat().st_size} Bytes")
                        stable = is_file_stable(resolved, settings.file_stable_seconds)
                        print(f"   stabil: {'Ja' if stable else 'Nein'}")
                except Exception as exc:
                    print(f"   Pfadfehler: {exc}")

        print("\nTestextraktion:")
        batch = service.process_request(request, treat_missing_as_failed=True)
        for item in batch.processed:
            chars = item.extracted_characters or 0
            print(f"  - {item.name}: {item.status.value}, {chars} Zeichen")
            if item.error:
                print(f"    Fehler: {item.error}")
        return 0
    except Exception as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


def cmd_discover_onedrive(_args: argparse.Namespace) -> int:
    print("=== OneDrive-Pfad-Erkennung ===\n")
    paths = discover_onedrive_paths()
    if not paths:
        print("Keine OneDrive-Pfade über Umgebungsvariablen gefunden.")
        print("\nBekannte Variablen: OneDriveCommercial, OneDrive, OneDriveConsumer")
        return 1

    for path in paths:
        print(f"  {path}")
        teams_llm = path / "TeamsLLM"
        marker = " (existiert)" if teams_llm.exists() else ""
        print(f"    -> {teams_llm}{marker}")

    print(
        "\nHinweis: Setzen Sie TEAMS_LLM_ROOT in der .env-Datei manuell, "
        "z.B. auf einen der obigen Pfade mit \\TeamsLLM."
    )
    return 0


def cmd_mcp_check(_args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        _init_logging(settings)
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1

    print("=== MCP-Verbindungstest (CPD-AutoPlan) ===\n")
    print(f"MCP aktiviert: {settings.mcp_enabled}")
    print(f"MCP Server URL: {settings.mcp_server_url}")
    print(f"MCP Token gesetzt: {'ja' if settings.mcp_token else 'nein'}")

    if not settings.mcp_enabled:
        print("\nHinweis: MCP_ENABLED=false — aktivieren Sie MCP in der .env für den Betrieb.")
        return 0

    policy = build_tool_policy(settings)
    print(f"\nErlaubte Tools (Policy): {', '.join(sorted(policy.allowed_tools))}")
    print(f"Blockierte Tools (Policy): {len(policy.blocked_tools)} Einträge")

    try:
        client = build_mcp_client(settings, policy)
        tools = client.list_tools()
    except MCPAuthenticationError as exc:
        print(f"\nFehler: {exc.user_message}", file=sys.stderr)
        return 1
    except MCPUnavailableError as exc:
        print(f"\nFehler: {exc.user_message}", file=sys.stderr)
        return 1
    except MCPProtocolError as exc:
        print(f"\nProtokollfehler: {exc.user_message}", file=sys.stderr)
        return 1
    except BridgeError as exc:
        print(f"\nFehler: {exc.user_message}", file=sys.stderr)
        return 1

    print(f"\nGefundene MCP-Tools: {len(tools)}")
    for tool in sorted(tools, key=lambda item: item.name):
        allowed = "erlaubt" if policy.is_allowed(tool.name) else "blockiert"
        print(f"  - {tool.name} ({allowed})")

    return 0


def cmd_mcp_call_test(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
        _init_logging(settings)
    except ConfigurationError as exc:
        print(f"Konfigurationsfehler: {exc.user_message}", file=sys.stderr)
        return 1

    if not settings.mcp_allow_manual_tool_test:
        print(
            "Fehler: MCP_ALLOW_MANUAL_TOOL_TEST ist nicht aktiviert.",
            file=sys.stderr,
        )
        return 1
    if not settings.mcp_enabled or not settings.mcp_token:
        print("Fehler: MCP_ENABLED und MCP_TOKEN müssen gesetzt sein.", file=sys.stderr)
        return 1

    import json

    policy = build_tool_policy(settings)
    try:
        arguments = json.loads(args.args_json)
    except json.JSONDecodeError as exc:
        print(f"Ungültiges JSON für --args: {exc}", file=sys.stderr)
        return 1
    if not isinstance(arguments, dict):
        print("--args muss ein JSON-Objekt sein.", file=sys.stderr)
        return 1

    try:
        client = build_mcp_client(settings, policy)
        result = client.call_tool(args.tool_name, arguments)
    except BridgeError as exc:
        print(f"Fehler: {exc.user_message}", file=sys.stderr)
        return 1

    preview = result.text[:500]
    if len(result.text) > 500:
        preview += "..."
    print(f"Tool: {args.tool_name}")
    print(f"Status: ok={result.ok}, gekürzt={result.truncated}")
    print(preview)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="teams-ollama-bridge",
        description="Dateibasierte Brücke zwischen Microsoft Teams und Ollama.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run", help="Dauerhafte Ordnerüberwachung starten")
    subparsers.add_parser("once", help="Alle ausstehenden Dateien einmal verarbeiten")
    subparsers.add_parser("check", help="Konfiguration und Umgebung prüfen")

    process_parser = subparsers.add_parser(
        "process-file", help="Eine einzelne Datei verarbeiten"
    )
    process_parser.add_argument("file_path", help="Pfad zur Input-JSON-Datei")

    subparsers.add_parser(
        "list-pending", help="Offene und fehlgeschlagene Requests auflisten"
    )

    retry_parser = subparsers.add_parser(
        "retry-failed", help="Fehlgeschlagene Requests erneut versuchen"
    )
    retry_parser.add_argument(
        "-y", "--yes", action="store_true", help="Sicherheitsabfrage überspringen"
    )

    show_parser = subparsers.add_parser(
        "show-request", help="Request-Status anzeigen und Output-Datei suchen"
    )
    show_parser.add_argument("request_id", help="requestId, z. B. test-001")

    inspect_parser = subparsers.add_parser(
        "inspect-attachments", help="Attachments einer Request-JSON debuggen"
    )
    inspect_parser.add_argument("file_path", help="Pfad zur Input-JSON-Datei")

    subparsers.add_parser(
        "discover-onedrive", help="Mögliche lokale OneDrive-Pfade anzeigen"
    )

    subparsers.add_parser(
        "mcp-check",
        help="MCP-Verbindung zu CPD-AutoPlan prüfen (nur tools/list)",
    )

    mcp_call_parser = subparsers.add_parser(
        "mcp-call-test",
        help="Einzelnes MCP-Tool testen (nur mit MCP_ALLOW_MANUAL_TOOL_TEST=true)",
    )
    mcp_call_parser.add_argument("tool_name", help="Name des MCP-Tools, z. B. get_state")
    mcp_call_parser.add_argument(
        "--args",
        dest="args_json",
        default="{}",
        help='Tool-Argumente als JSON, z. B. "{}"',
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    commands = {
        "run": cmd_run,
        "once": cmd_once,
        "check": cmd_check,
        "process-file": cmd_process_file,
        "list-pending": cmd_list_pending,
        "retry-failed": cmd_retry_failed,
        "show-request": cmd_show_request,
        "inspect-attachments": cmd_inspect_attachments,
        "discover-onedrive": cmd_discover_onedrive,
        "mcp-check": cmd_mcp_check,
        "mcp-call-test": cmd_mcp_call_test,
    }
    handler = commands[args.command]
    sys.exit(handler(args))


if __name__ == "__main__":
    main()
