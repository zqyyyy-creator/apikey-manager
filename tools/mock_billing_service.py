from __future__ import annotations

"""Local-only mock billing service for MaaS CustomLogger chain testing.

Do not deploy this file. It exists only to verify:
ds-api-gateway -> MaaS API -> external billing service.
"""

import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


INPUT_RATE = Decimal("0.000001")
OUTPUT_RATE = Decimal("0.000002")
CACHE_RATE = Decimal("0.0000002")


class MockBillingHandler(BaseHTTPRequestHandler):
    server_version = "MaasMockBilling/0.1"

    def do_GET(self) -> None:
        if self.path in {"/", "/health"}:
            self._send_json({"status": "ok", "service": "maas-mock-billing"})
            return
        self._send_json({"error": {"message": "not found"}}, status=404)

    def do_POST(self) -> None:
        if self.path != "/api/v1/cost/calculate":
            self._send_json({"error": {"message": "not found"}}, status=404)
            return

        content_length = int(self.headers.get("content-length", "0") or "0")
        raw_body = self.rfile.read(content_length) if content_length else b"{}"

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json({"error": {"message": "invalid JSON"}}, status=400)
            return

        model = str(payload.get("model") or "")
        input_tokens = self._int(payload.get("input_tokens"))
        output_tokens = self._int(payload.get("output_tokens"))
        cache_tokens = self._int(payload.get("cache_tokens"))

        input_cost = INPUT_RATE * Decimal(input_tokens)
        output_cost = OUTPUT_RATE * Decimal(output_tokens)
        cache_cost = CACHE_RATE * Decimal(cache_tokens)
        total = input_cost + output_cost + cache_cost

        print(
            "mock_billing_cost_calculated "
            f"model={model} input_tokens={input_tokens} "
            f"output_tokens={output_tokens} cache_tokens={cache_tokens} "
            f"cost={total}"
        )

        self._send_json(
            {
                "data": {
                    "cost": str(total),
                    "charge_detail": {
                        "input_cost": str(input_cost),
                        "output_cost": str(output_cost),
                        "cache_cost": str(cache_cost),
                    },
                }
            }
        )

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _int(self, value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8080), MockBillingHandler)
    print("Mock billing service running on http://127.0.0.1:8080")
    print("Cost endpoint: POST /api/v1/cost/calculate")
    server.serve_forever()


if __name__ == "__main__":
    main()
