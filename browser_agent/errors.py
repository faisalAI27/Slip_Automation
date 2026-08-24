"""Controlled, privacy-safe browser-layer errors."""


class BrowserAgentError(RuntimeError):
    """Base class for expected Phase 4 failures."""


class BrowserConfigurationError(BrowserAgentError):
    pass


class BrowserLaunchError(BrowserAgentError):
    pass


class BrowserTimeoutError(BrowserAgentError):
    pass


class NavigationError(BrowserAgentError):
    pass


class UnsafeNavigationError(BrowserAgentError):
    pass


class UnsafeSearchQueryError(BrowserAgentError):
    pass


class SearchExecutionError(BrowserAgentError):
    pass


class PageInspectionError(BrowserAgentError):
    pass


class NonActionablePlanError(BrowserAgentError):
    pass


class InteractionSafetyError(BrowserAgentError):
    pass


class ElementUnavailableError(BrowserAgentError):
    pass


class DownloadCaptureError(BrowserAgentError):
    pass


class DownloadValidationError(BrowserAgentError):
    pass
