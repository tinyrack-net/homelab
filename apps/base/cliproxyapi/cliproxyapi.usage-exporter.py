#!/usr/bin/env python3
import http.server
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.parse


ERROR_MAX_BACKOFF_SECONDS = 60
ERROR_INITIAL_BACKOFF_SECONDS = 5
AUTH_BACKOFF_SECONDS = 300
CONNECT_TIMEOUT_SECONDS = 10
USAGE_CHANNEL = "usage"

LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300)
TTFT_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60)
OUTPUT_TPS_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000)


def normalize_label(value, default="unknown"):
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def as_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def escape_label(value):
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def format_labels(labels):
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{escape_label(value)}"' for key, value in sorted(labels.items()))
    return "{" + rendered + "}"


def format_number(value):
    if isinstance(value, int):
        return str(value)
    return format(float(value), ".17g")


def encode_resp_command(*parts):
    encoded = [f"*{len(parts)}\r\n".encode("ascii")]
    for part in parts:
        value = str(part).encode("utf-8")
        encoded.append(f"${len(value)}\r\n".encode("ascii"))
        encoded.append(value)
        encoded.append(b"\r\n")
    return b"".join(encoded)


def read_resp_line(reader):
    line = reader.readline()
    if not line:
        raise ConnectionError("connection closed")
    if not line.endswith(b"\r\n"):
        raise ValueError("invalid RESP line")
    return line[:-2]


def read_resp_value(reader):
    prefix = reader.read(1)
    if not prefix:
        raise ConnectionError("connection closed")

    if prefix == b"+":
        return read_resp_line(reader).decode("utf-8", errors="replace")

    if prefix == b"-":
        message = read_resp_line(reader).decode("utf-8", errors="replace")
        raise ConnectionError(message)

    if prefix == b":":
        return int(read_resp_line(reader))

    if prefix == b"$":
        length = int(read_resp_line(reader))
        if length < 0:
            return None
        payload = reader.read(length)
        if len(payload) != length:
            raise ConnectionError("truncated RESP bulk string")
        if reader.read(2) != b"\r\n":
            raise ValueError("invalid RESP bulk string terminator")
        return payload

    if prefix == b"*":
        length = int(read_resp_line(reader))
        if length < 0:
            return None
        return [read_resp_value(reader) for _ in range(length)]

    raise ValueError("unsupported RESP type")


class MetricsRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {}
        self._gauges = {}
        self._histograms = {}

    def inc_counter(self, name, labels=None, amount=1):
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def set_gauge(self, name, value, labels=None):
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            self._gauges[key] = value

    def observe_histogram(self, name, value, buckets, labels=None):
        key = (name, tuple(sorted((labels or {}).items())))
        with self._lock:
            histogram = self._histograms.setdefault(
                key,
                {
                    "buckets": {bucket: 0 for bucket in buckets},
                    "count": 0,
                    "sum": 0.0,
                },
            )
            for bucket in buckets:
                if value <= bucket:
                    histogram["buckets"][bucket] += 1
            histogram["count"] += 1
            histogram["sum"] += value

    def render(self):
        with self._lock:
            counters = sorted(self._counters.items(), key=lambda item: (item[0][0], item[0][1]))
            gauges = sorted(self._gauges.items(), key=lambda item: (item[0][0], item[0][1]))
            histograms = sorted(self._histograms.items(), key=lambda item: (item[0][0], item[0][1]))

        lines = []
        last_name = None
        for (name, labels), value in counters:
            if name != last_name:
                lines.append(f"# TYPE {name} counter")
                last_name = name
            lines.append(f"{name}{format_labels(dict(labels))} {format_number(value)}")
        last_name = None
        for (name, labels), value in gauges:
            if name != last_name:
                lines.append(f"# TYPE {name} gauge")
                last_name = name
            lines.append(f"{name}{format_labels(dict(labels))} {format_number(value)}")
        last_name = None
        for (name, labels), histogram in histograms:
            label_map = dict(labels)
            if name != last_name:
                lines.append(f"# TYPE {name} histogram")
                last_name = name
            for bucket, count in sorted(histogram["buckets"].items()):
                bucket_labels = dict(label_map)
                bucket_labels["le"] = str(bucket)
                lines.append(f"{name}_bucket{format_labels(bucket_labels)} {format_number(count)}")
            bucket_labels = dict(label_map)
            bucket_labels["le"] = "+Inf"
            lines.append(
                f"{name}_bucket{format_labels(bucket_labels)} {format_number(histogram['count'])}"
            )
            lines.append(
                f"{name}_sum{format_labels(label_map)} {format_number(histogram['sum'])}"
            )
            lines.append(
                f"{name}_count{format_labels(label_map)} {format_number(histogram['count'])}"
            )
        return "\n".join(lines) + "\n"


class ExporterState:
    def __init__(self):
        self.stop_event = threading.Event()
        self.metrics = MetricsRegistry()
        self.management_url = os.environ.get(
            "CLIPROXYAPI_MANAGEMENT_URL", "http://127.0.0.1:8317"
        ).rstrip("/")
        self.management_password = os.environ.get("MANAGEMENT_PASSWORD", "").strip()
        self.listen_port = int(os.environ.get("EXPORTER_PORT", "9101"))
        parsed = urllib.parse.urlparse(self.management_url)
        if parsed.hostname is None:
            raise ValueError("CLIPROXYAPI_MANAGEMENT_URL has no hostname")
        self.management_host = parsed.hostname
        self.management_port = parsed.port or 8317
        self.connection = None
        self.connection_lock = threading.Lock()
        self.connected = False
        self.failure_count = 0

    def set_connection(self, connection):
        with self.connection_lock:
            self.connection = connection

    def close_connection(self):
        with self.connection_lock:
            connection = self.connection
            self.connection = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def send_command(self, writer, *parts):
        writer.write(encode_resp_command(*parts))
        writer.flush()

    def handle_payload(self, payload):
        if not payload:
            return False
        try:
            record = json.loads(payload)
        except (TypeError, ValueError):
            return False
        if not isinstance(record, dict):
            return False
        if record.get("support_refresh") is True:
            return False
        self.observe_record(record)
        return True

    def observe_record(self, record):
        if not isinstance(record, dict):
            return

        provider = normalize_label(record.get("provider"))
        model = normalize_label(record.get("model"))
        alias = normalize_label(record.get("alias"), model)
        auth_type = normalize_label(record.get("auth_type"))
        endpoint = normalize_label(record.get("endpoint"))
        failed = "true" if bool(record.get("failed")) else "false"
        stream = "true" if bool(record.get("stream")) else "false"

        request_labels = {
            "provider": provider,
            "model": model,
            "alias": alias,
            "auth_type": auth_type,
            "endpoint": endpoint,
            "failed": failed,
            "stream": stream,
        }
        self.metrics.inc_counter("cliproxyapi_usage_requests_total", request_labels)

        token_labels = {
            "provider": provider,
            "model": model,
            "alias": alias,
            "auth_type": auth_type,
            "endpoint": endpoint,
        }
        tokens = record.get("tokens")
        if not isinstance(tokens, dict):
            tokens = {}
        token_fields = {
            "input": "input_tokens",
            "output": "output_tokens",
            "reasoning": "reasoning_tokens",
            "cached": "cached_tokens",
            "cache_read": "cache_read_tokens",
            "cache_creation": "cache_creation_tokens",
            "total": "total_tokens",
        }
        for direction, field in token_fields.items():
            amount = as_int(tokens.get(field))
            if amount > 0:
                labels = dict(token_labels)
                labels["direction"] = direction
                self.metrics.inc_counter("cliproxyapi_usage_tokens_total", labels, amount)

        latency_seconds = as_int(record.get("latency_ms")) / 1000.0
        if latency_seconds > 0:
            self.metrics.observe_histogram(
                "cliproxyapi_usage_request_latency_seconds",
                latency_seconds,
                LATENCY_BUCKETS,
                token_labels,
            )

        ttft_seconds = as_int(record.get("ttft_ms")) / 1000.0
        if ttft_seconds > 0:
            self.metrics.observe_histogram(
                "cliproxyapi_usage_ttft_seconds",
                ttft_seconds,
                TTFT_BUCKETS,
                token_labels,
            )

        # Keep timing bases separate so missing TTFT never changes the meaning
        # of the generation-speed average. Each successful request has weight 1.
        output_tokens = as_int(tokens.get("output_tokens"))
        if (
            failed == "false"
            and record.get("generate") is not False
            and output_tokens > 0
            and latency_seconds > 0
        ):
            tps_labels = {"provider": provider, "model": model, "alias": alias}
            self.metrics.observe_histogram(
                "cliproxyapi_usage_output_tokens_per_second",
                output_tokens / latency_seconds,
                OUTPUT_TPS_BUCKETS,
                {**tps_labels, "timing": "end_to_end"},
            )
            if stream == "true" and 0 < ttft_seconds < latency_seconds:
                self.metrics.observe_histogram(
                    "cliproxyapi_usage_output_tokens_per_second",
                    output_tokens / (latency_seconds - ttft_seconds),
                    OUTPUT_TPS_BUCKETS,
                    {**tps_labels, "timing": "generation"},
                )

    def run_subscription_cycle(self):
        if not self.management_password:
            print("MANAGEMENT_PASSWORD is not set", file=sys.stderr, flush=True)
            self.metrics.inc_counter(
                "cliproxyapi_usage_collector_polls_total", {"result": "auth_error"}
            )
            return AUTH_BACKOFF_SECONDS

        connection = None
        try:
            connection = socket.create_connection(
                (self.management_host, self.management_port),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
            connection.settimeout(None)
            self.set_connection(connection)
            reader = connection.makefile("rb")
            writer = connection.makefile("wb")

            self.send_command(writer, "AUTH", self.management_password)
            try:
                auth_response = read_resp_value(reader)
            except ConnectionError as error:
                raise PermissionError("management authentication failed") from error
            if auth_response != "OK":
                raise PermissionError("management authentication failed")

            self.send_command(writer, "SUBSCRIBE", USAGE_CHANNEL)
            subscribe_response = read_resp_value(reader)
            if (
                not isinstance(subscribe_response, list)
                or len(subscribe_response) < 2
                or subscribe_response[0] != b"subscribe"
                or subscribe_response[1] != USAGE_CHANNEL.encode("utf-8")
            ):
                raise ValueError("usage subscription was not acknowledged")

            self.failure_count = 0
            self.connected = True
            self.metrics.inc_counter(
                "cliproxyapi_usage_collector_polls_total", {"result": "success"}
            )
            self.metrics.set_gauge(
                "cliproxyapi_usage_collector_last_success_timestamp_seconds", time.time()
            )

            while not self.stop_event.is_set():
                message = read_resp_value(reader)
                if not isinstance(message, list) or len(message) < 3:
                    continue
                if message[0] != b"message" or message[1] != USAGE_CHANNEL.encode("utf-8"):
                    continue
                if self.handle_payload(message[2]):
                    self.metrics.inc_counter(
                        "cliproxyapi_usage_collector_records_total"
                    )
                    self.metrics.set_gauge(
                        "cliproxyapi_usage_collector_last_success_timestamp_seconds",
                        time.time(),
                    )

            return 0
        except PermissionError as error:
            self.metrics.inc_counter(
                "cliproxyapi_usage_collector_polls_total", {"result": "auth_error"}
            )
            print(f"usage subscription authentication failed: {error}", file=sys.stderr, flush=True)
            return AUTH_BACKOFF_SECONDS
        except Exception as error:
            self.metrics.inc_counter(
                "cliproxyapi_usage_collector_polls_total", {"result": "error"}
            )
            if not self.stop_event.is_set():
                print(
                    f"usage subscription failed: {type(error).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
            self.failure_count += 1
            exponent = min(self.failure_count - 1, 4)
            return min(
                ERROR_MAX_BACKOFF_SECONDS,
                ERROR_INITIAL_BACKOFF_SECONDS * (2 ** exponent),
            )
        finally:
            self.connected = False
            self.close_connection()

    def subscription_loop(self):
        while not self.stop_event.is_set():
            backoff = self.run_subscription_cycle()
            if backoff <= 0:
                break
            self.stop_event.wait(backoff)


def make_handler(state):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                if state.connected:
                    state.metrics.set_gauge(
                        "cliproxyapi_usage_collector_last_success_timestamp_seconds",
                        time.time(),
                    )
                payload = state.metrics.render().encode("utf-8")
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
                )
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if self.path == "/healthz":
                payload = b"ok\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_error(404)

        def log_message(self, format, *args):
            return

    return Handler


def main():
    state = ExporterState()
    shutdown_event = threading.Event()

    def stop(_signum, _frame):
        state.stop_event.set()
        state.close_connection()
        shutdown_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    subscription_thread = threading.Thread(
        target=state.subscription_loop, name="usage-subscriber", daemon=True
    )
    subscription_thread.start()

    server = http.server.ThreadingHTTPServer(("0.0.0.0", state.listen_port), make_handler(state))
    server.daemon_threads = True

    def serve():
        server.serve_forever(poll_interval=0.5)

    server_thread = threading.Thread(target=serve, name="metrics-server", daemon=True)
    server_thread.start()

    shutdown_event.wait()
    server.shutdown()
    server.server_close()
    subscription_thread.join(timeout=5)


if __name__ == "__main__":
    main()
