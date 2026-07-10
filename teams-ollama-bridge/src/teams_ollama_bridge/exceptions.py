"""Benutzerdefinierte Ausnahmen für teams-ollama-bridge."""

from __future__ import annotations


class BridgeError(Exception):
    """Basisklasse für Anwendungsfehler."""

    def __init__(self, message: str, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type or self.__class__.__name__
        self.user_message = message


class ConfigurationError(BridgeError):
    """Konfigurationsfehler beim Start."""


class InvalidJsonError(BridgeError):
    """Ungültiges JSON in einer Inputdatei."""


class InvalidInputSchemaError(BridgeError):
    """Input-JSON entspricht nicht dem erwarteten Schema."""


class EmptyMessageError(BridgeError):
    """Nachricht ist nach Bereinigung leer."""


class MessageTooLongError(BridgeError):
    """Nachricht überschreitet die maximale Länge."""


class DuplicateRequestError(BridgeError):
    """Request wurde bereits erfolgreich verarbeitet."""


class RequestContentMismatchError(BridgeError):
    """Gleiche requestId mit abweichendem Dateiinhalt."""


class OutputFileExistsError(BridgeError):
    """Outputdatei existiert bereits."""


class OllamaConnectionError(BridgeError):
    """Ollama ist nicht erreichbar."""


class OllamaTimeoutError(BridgeError):
    """Ollama-Anfrage hat das Zeitlimit überschritten."""


class OllamaResponseError(BridgeError):
    """Ungültige oder leere Ollama-Antwort."""


class FileNotStableError(BridgeError):
    """Datei ist noch nicht vollständig synchronisiert."""


class FilePermissionError(BridgeError):
    """Fehlende Berechtigung für Dateioperationen."""


class SQLiteError(BridgeError):
    """Fehler bei SQLite-Operationen."""


class TemporaryProcessingError(BridgeError):
    """Vorübergehender Fehler, der einen Retry rechtfertigt."""


class PermanentProcessingError(BridgeError):
    """Dauerhafter Fehler ohne weiteren Retry."""


class InstanceAlreadyRunningError(BridgeError):
    """Eine andere Instanz läuft bereits."""


class AttachmentPathError(BridgeError):
    """Unsicherer oder ungültiger Attachment-Pfad."""


class AttachmentNotSyncedError(TemporaryProcessingError):
    """Attachment-Datei ist noch nicht lokal synchronisiert."""


class AttachmentTooLargeError(BridgeError):
    """Attachment überschreitet die maximale Größe."""


class UnsupportedAttachmentTypeError(BridgeError):
    """Dateityp ist nicht erlaubt oder nicht unterstützt."""


class EncryptedPdfError(BridgeError):
    """PDF ist verschlüsselt und kann nicht gelesen werden."""


class AttachmentExtractionError(BridgeError):
    """Fehler bei der Textextraktion aus einem Attachment."""


class MCPUnavailableError(BridgeError):
    """CPD-AutoPlan MCP-Server ist nicht erreichbar."""


class MCPAuthenticationError(BridgeError):
    """MCP-Bearer-Token ist ungültig oder veraltet."""


class MCPConsentRequiredError(BridgeError):
    """CPD-Agent-Consent (Allow agent) fehlt."""


class MCPToolError(BridgeError):
    """MCP-Tool-Aufruf ist fehlgeschlagen."""


class MCPProtocolError(BridgeError):
    """MCP-Protokoll- oder Transportfehler."""


class MCPToolNotAllowedError(BridgeError):
    """Tool ist durch die Sicherheitsrichtlinie blockiert."""

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Das Tool '{tool_name}' ist aus Sicherheitsgründen nicht erlaubt.",
            error_type="MCPToolNotAllowedError",
        )
        self.tool_name = tool_name


class MCPResultTooLargeError(BridgeError):
    """MCP-Toolergebnis überschreitet das Größenlimit."""
