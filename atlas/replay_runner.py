"""Fixed checkout-v1 adapter. No uploaded code, shell commands, URLs or production credentials."""

import http.client
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def run(fixture, options):
    calls = []
    origin = time.monotonic()
    delay = options.get("dependency_delay_ms", 0) / 1000
    inventory = options.get("inventory_status") or fixture["inventory_status"]
    payment = options.get("payment_status") or fixture["payment_status"]

    class Dependency(BaseHTTPRequestHandler):
        def do_POST(self):
            began = time.monotonic()
            time.sleep(delay)
            status = inventory if self.path == "/inventory/reserve" else payment
            calls.append(
                {
                    "service": "inventory" if self.path.startswith("/inventory") else "payments",
                    "path": self.path,
                    "status": status,
                    "start_ms": round((began - origin) * 1000),
                    "duration_ms": round((time.monotonic() - began) * 1000),
                }
            )
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    dependency = ThreadingHTTPServer(("127.0.0.1", 0), Dependency)
    dependency.daemon_threads = True

    class Checkout(BaseHTTPRequestHandler):
        def do_POST(self):
            status = 201
            for path in ("/inventory/reserve", "/payments/charge"):
                connection = http.client.HTTPConnection("127.0.0.1", dependency.server_port, timeout=2)
                try:
                    connection.request(
                        "POST",
                        path,
                        body=json.dumps({"quantity": fixture["quantity"]}),
                        headers={"Content-Type": "application/json"},
                    )
                    response = connection.getresponse()
                    if not 200 <= response.status < 300:
                        status = 409 if path.startswith("/inventory") else 502
                        break
                except (TimeoutError, OSError):
                    status = 504
                    break
                finally:
                    connection.close()
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    checkout = ThreadingHTTPServer(("127.0.0.1", 0), Checkout)
    checkout.daemon_threads = True
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (dependency, checkout)]
    for thread in threads:
        thread.start()
    start = time.monotonic()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", checkout.server_port, timeout=5)
        try:
            connection.request("POST", "/checkout", body="{}", headers={"Content-Type": "application/json"})
            status = connection.getresponse().status
        finally:
            connection.close()
        return {
            "adapter": "checkout-v1",
            "observed_status": status,
            "expected_status": options["expected_status"],
            "passed": status == options["expected_status"],
            "captured_status": fixture["captured_checkout_status"],
            "matches_capture": status == fixture["captured_checkout_status"],
            "elapsed_ms": round((time.monotonic() - start) * 1000),
            "calls": calls,
            "scope": "bundled checkout adapter with recorded status fixtures; not arbitrary service replay",
        }
    finally:
        for server in (checkout, dependency):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


if __name__ == "__main__":
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    data = json.loads(sys.stdin.read(32768))
    print(json.dumps(run(data["fixture"], data["options"])))
