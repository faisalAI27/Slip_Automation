"""URL, DNS, redirect, and display-redaction safety for Phase 4."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from browser_agent.errors import UnsafeNavigationError


AddressResolver = Callable[[str, int], Iterable[str]]


@dataclass(frozen=True, slots=True)
class ValidatedURL:
    url: str
    scheme: str
    hostname: str
    port: int
    domain: str

    @property
    def uses_https(self) -> bool:
        return self.scheme == "https"


def _default_resolver(hostname: str, port: int) -> set[str]:
    return {
        item[4][0]
        for item in socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    }


def _is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


def registrable_domain(hostname: str) -> str:
    """Return a conservative effective domain for informational redirect warnings."""

    host = hostname.rstrip(".").casefold()
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    multi_label_suffixes = {
        "co.uk",
        "org.uk",
        "com.au",
        "com.pk",
        "com.sg",
        "co.in",
        "co.nz",
        "co.za",
    }
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in multi_label_suffixes else suffix


def redact_url_for_display(value: str) -> str:
    """Remove query values, fragments, and user information from displayed URLs."""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return "[invalid URL]"
    hostname = parsed.hostname or ""
    if not hostname:
        return "[invalid URL]"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    default_port = (parsed.scheme.casefold() == "http" and port == 80) or (
        parsed.scheme.casefold() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    query_marker = "[redacted]" if parsed.query else ""
    return urlunsplit(
        (parsed.scheme.casefold(), netloc, parsed.path or "/", query_marker, "")
    )


def validate_public_url(
    value: str,
    *,
    resolver: AddressResolver = _default_resolver,
    resolve_dns: bool = True,
) -> ValidatedURL:
    candidate = value.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeNavigationError("The destination URL is invalid.") from exc

    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise UnsafeNavigationError("Only HTTP(S) destinations are permitted.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeNavigationError("The destination URL is not safe to navigate.")

    raw_hostname = parsed.hostname.rstrip(".")
    if not raw_hostname or "%" in raw_hostname:
        raise UnsafeNavigationError("The destination hostname is invalid.")
    try:
        hostname = raw_hostname.encode("idna").decode("ascii").casefold()
    except UnicodeError as exc:
        raise UnsafeNavigationError("The destination hostname is invalid.") from exc

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeNavigationError("Local-network navigation is not permitted.")

    destination_port = port or (443 if scheme == "https" else 80)
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None:
        addresses = {str(literal_address)}
    elif resolve_dns:
        try:
            addresses = set(resolver(hostname, destination_port))
        except OSError as exc:
            raise UnsafeNavigationError(
                "The destination hostname could not be verified."
            ) from exc
        if not addresses:
            raise UnsafeNavigationError(
                "The destination hostname did not resolve to a public address."
            )
    else:
        addresses = set()

    if addresses and any(not _is_public_address(address) for address in addresses):
        raise UnsafeNavigationError("Local or private-network navigation is not permitted.")

    hostname_for_url = hostname
    if literal_address is not None and literal_address.version == 6:
        hostname_for_url = f"[{hostname}]"
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    netloc = (
        hostname_for_url
        if port is None or default_port
        else f"{hostname_for_url}:{port}"
    )
    normalized = urlunsplit(
        (scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment)
    )
    return ValidatedURL(
        url=normalized,
        scheme=scheme,
        hostname=hostname,
        port=destination_port,
        domain=registrable_domain(hostname),
    )
