import re
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from http.client import HTTPException, HTTPSConnection, IncompleteRead
from http.cookies import CookieError, SimpleCookie
from threading import Lock
from time import time_ns
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from .const import MODEL

MAX_RESPONSE_BYTES = 65536


class WattBoxError(Exception):
    pass


class CannotConnect(WattBoxError):
    pass


class InvalidAuth(WattBoxError):
    pass


class InvalidResponse(WattBoxError):
    pass


class UnsupportedModel(WattBoxError):
    pass


def validate_host(host: str) -> str:
    host = host.strip().lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
        raise ValueError("Enter an IPv4 address or hostname without a scheme or port")
    return host


@dataclass(frozen=True)
class OutletReading:
    name: str
    is_on: bool | None


@dataclass(frozen=True)
class PowerReading:
    serial: str
    model: str
    voltage: float
    current: float
    power: int
    outlets: tuple[OutletReading, ...]


def parse_reading(body: bytes) -> PowerReading:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise InvalidResponse("XML declarations are not supported")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as err:
        raise InvalidResponse("Incomplete or invalid status XML") from err
    if root.tag != "request":
        raise InvalidResponse("Expected WattBox status XML")
    model = (root.findtext("hardware_version") or "").strip()
    if model != MODEL:
        raise UnsupportedModel("Only WB-300VB-IP-5 is supported")
    serial = (root.findtext("serial_number") or "").strip()
    if not serial:
        raise InvalidResponse("Missing device serial number")
    values = []
    for tag in ("voltage_value", "current_value", "power_value"):
        value = (root.findtext(tag) or "").strip()
        if not re.fullmatch(r"[0-9]{1,9}", value):
            raise InvalidResponse(f"Missing or invalid {tag}")
        values.append(int(value))
    names = (root.findtext("outlet_name") or "").split(",")
    states = (root.findtext("outlet_status") or "").split(",")
    outlets = tuple(
        OutletReading(
            name=(names[index].strip() if len(names) == 5 else "")
            or f"Outlet {index + 1}",
            is_on={"0": False, "1": True}.get(states[index].strip())
            if len(states) == 5
            else None,
        )
        for index in range(5)
    )
    return PowerReading(
        serial, model, values[0] / 10, values[1] / 10, values[2], outlets
    )


def _is_login(body: bytes) -> bool:
    return b"login.htm" in body or b"form_login" in body


class _CSRFParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "input" and attributes.get("id") == "csrftoken":
            self.token = attributes.get("value")


def parse_csrf_token(body: bytes) -> str:
    parser = _CSRFParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    if not parser.token:
        if _is_login(body):
            raise InvalidAuth("Status page requires a new session")
        raise InvalidResponse("Status page did not provide an outlet-control token")
    return parser.token


class WattBoxClient:
    def __init__(
        self, host: str, username: str, password: str, verify_ssl: bool = False
    ) -> None:
        self.host = validate_host(host)
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._context: ssl.SSLContext | None = None
        self._cookies: SimpleCookie = SimpleCookie()
        self._lock = Lock()

    def _request(self, method: str, path: str, data: str | None = None) -> bytes:
        # Run only in an executor: TLS setup and http.client both block.
        if self._context is None:
            self._context = ssl.create_default_context()
            if not self._verify_ssl:
                self._context.check_hostname = False
                self._context.verify_mode = ssl.CERT_NONE
        connection = HTTPSConnection(
            self.host, port=443, timeout=10, context=self._context
        )
        headers = {"Connection": "close"}
        if self._cookies:
            headers["Cookie"] = "; ".join(
                f"{key}={value.coded_value}" for key, value in self._cookies.items()
            )
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            if response.status in (401, 403):
                raise InvalidAuth("Authentication rejected")
            if response.status != 200:
                raise CannotConnect(
                    f"Device returned HTTP {response.status} for {method} {path.split('?', 1)[0]}"
                )
            for key, value in response.getheaders():
                if key.lower() == "set-cookie":
                    self._cookies.load(value)
            # This firmware closes chunked responses without a terminating chunk.
            # Preserve partial bytes, but accept measurements only after full XML
            # validation. Never treat a partial document as a successful poll.
            try:
                body = response.read(MAX_RESPONSE_BYTES + 1)
            except IncompleteRead as err:
                body = err.partial
            if len(body) > MAX_RESPONSE_BYTES:
                raise InvalidResponse("Status response too large")
            return body
        except (OSError, HTTPException, CookieError) as err:
            raise CannotConnect("Unable to read the WattBox HTTPS interface") from err
        finally:
            connection.close()

    def _login(self) -> None:
        self._cookies.clear()
        body = self._request(
            "POST",
            "/login.cgi",
            urlencode(
                {
                    "user_login": "1",
                    "account": self._username,
                    "password": self._password,
                }
            ),
        )
        if _is_login(body):
            raise InvalidAuth("Login rejected")
        if b"index.htm" not in body:
            raise InvalidResponse("Unexpected login response")

    def _fetch(self) -> PowerReading:
        body = self._request("GET", "/wattbox_info.xml")
        if _is_login(body):
            self._login()
            body = self._request("GET", "/wattbox_info.xml")
            if _is_login(body):
                raise InvalidAuth("Session was not accepted after login")
        return parse_reading(body)

    def fetch(self) -> PowerReading:
        with self._lock:
            return self._fetch()

    def set_outlet(self, outlet: int, on: bool, expected_serial: str) -> PowerReading:
        if type(outlet) is not int or not 1 <= outlet <= 5 or type(on) is not bool:
            raise ValueError("Expected outlet 1–5 and an on/off boolean")
        with self._lock:
            reading = self._fetch()
            if reading.serial != expected_serial:
                raise InvalidResponse("The address belongs to a different WattBox")
            state = reading.outlets[outlet - 1].is_on
            if state is None:
                raise InvalidResponse("Outlet state is unavailable")
            if state == on:
                return reading
            page = self._request("GET", "/Status.htm")
            params = urlencode(
                {
                    "outlet": outlet,
                    "command": int(on),
                    "time": time_ns() // 1_000_000,
                    "csrftoken": parse_csrf_token(page),
                }
            )
            # Match the web UI's session token; never replay an ambiguous command.
            body = self._request("GET", f"/control.cgi?{params}")
            if _is_login(body):
                raise InvalidAuth("Outlet command requires a new session")
            reading = self._fetch()
            if reading.serial != expected_serial:
                raise InvalidResponse("The address belongs to a different WattBox")
            if reading.outlets[outlet - 1].is_on != on:
                raise InvalidResponse("Outlet did not report the requested state")
            return reading
