#!/usr/bin/env python3
"""Runnable sample client for the wfeval Gateway. See docs/integration-guide.md.

Three things, pick what you need:

  python sample_client.py validate <bpmn-file>
      Calls POST /v1/validate (the sync pre-deploy gate) and prints the result.

  python sample_client.py evaluate <bpmn-file> [--wait]
      Calls POST /v1/evaluations, then either prints the poll_url (default)
      or polls until it finishes (--wait).

  python sample_client.py serve-webhook [--port 8099]
      Starts a minimal HTTP server that receives the Gateway's webhook
      callback, verifies its HMAC signature, and prints the report. Point
      --callback-url at this when calling `evaluate`.

Needs only `httpx` (already a dependency of this repo) -- no project import,
so this file can be copied out and run standalone against any wfeval
Gateway deployment, not just this repo's dev server.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import http.server
import json
import os
import sys
import time
from pathlib import Path

import httpx

DEFAULT_GATEWAY_URL = os.environ.get("WFEVAL_GATEWAY_URL", "http://localhost:8000")
SIGNATURE_HEADER = "X-Wfeval-Signature"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("WFEVAL_API_KEY")
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def _artifact_body(path: str) -> dict[str, str]:
    content = Path(path).read_text()
    fmt = "dmn" if path.endswith(".dmn") else "bpmn"
    return {"format": fmt, "content": content}


def cmd_validate(args: argparse.Namespace) -> None:
    request = {
        "request_id": f"sample-{int(time.time())}",
        "platform": "uipath_maestro",
        "artifact": _artifact_body(args.artifact),
        "prompt": args.prompt,
    }
    resp = httpx.post(f"{args.gateway_url}/v1/validate", json=request, headers=_headers(), timeout=10.0)
    resp.raise_for_status()
    report = resp.json()
    print(json.dumps(report, indent=2))

    gates = report.get("validation", {}).get("gates", {})
    if all(gates.values()):
        print(f"\nverdict={report['verdict']} -- all gates passed", file=sys.stderr)
    else:
        failed = [g for g, ok in gates.items() if not ok]
        print(f"\nverdict={report['verdict']} -- failed gates: {failed}", file=sys.stderr)
        sys.exit(1)


def cmd_evaluate(args: argparse.Namespace) -> None:
    request = {
        "request_id": f"sample-{int(time.time())}",
        "platform": "uipath_maestro",
        "artifact": _artifact_body(args.artifact),
        "prompt": args.prompt,
    }
    if args.callback_url:
        request["callback_url"] = args.callback_url

    resp = httpx.post(f"{args.gateway_url}/v1/evaluations", json=request, headers=_headers(), timeout=10.0)
    resp.raise_for_status()
    accepted = resp.json()
    print(json.dumps(accepted, indent=2))

    if not args.wait:
        print(f"\nPoll {args.gateway_url}{accepted['poll_url']} for the result.", file=sys.stderr)
        return

    poll_url = f"{args.gateway_url}{accepted['poll_url']}"
    print(f"\nPolling {poll_url} ...", file=sys.stderr)
    while True:
        poll_resp = httpx.get(poll_url, headers=_headers(), timeout=10.0)
        if poll_resp.status_code == 202:
            time.sleep(args.poll_interval)
            continue
        poll_resp.raise_for_status()
        print(json.dumps(poll_resp.json(), indent=2))
        return


def cmd_serve_webhook(args: argparse.Namespace) -> None:
    secret = args.secret or os.environ.get("WFEVAL_WEBHOOK_SECRET")
    if not secret:
        print("Need --secret or WFEVAL_WEBHOOK_SECRET -- ask the Gateway's operator "
              "for the value they configured as GATEWAY_WEBHOOK_SECRET.", file=sys.stderr)
        sys.exit(1)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            signature = self.headers.get(SIGNATURE_HEADER, "")
            expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

            if not hmac.compare_digest(expected, signature):
                print(f"REJECTED: signature mismatch (got {signature!r})", file=sys.stderr)
                self.send_response(401)
                self.end_headers()
                return

            print("Verified webhook delivery:")
            print(json.dumps(json.loads(body), indent=2))
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt: str, *fmt_args: object) -> None:
            pass  # quiet -- we print what matters ourselves, above

    server = http.server.HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Listening on http://0.0.0.0:{args.port} -- point callback_url here.", file=sys.stderr)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_validate = subparsers.add_parser("validate")
    p_validate.add_argument("artifact")
    p_validate.add_argument("--prompt", default=None)
    p_validate.set_defaults(func=cmd_validate)

    p_evaluate = subparsers.add_parser("evaluate")
    p_evaluate.add_argument("artifact")
    p_evaluate.add_argument("--prompt", default=None)
    p_evaluate.add_argument("--callback-url", default=None)
    p_evaluate.add_argument("--wait", action="store_true")
    p_evaluate.add_argument("--poll-interval", type=float, default=3.0)
    p_evaluate.set_defaults(func=cmd_evaluate)

    p_webhook = subparsers.add_parser("serve-webhook")
    p_webhook.add_argument("--port", type=int, default=8099)
    p_webhook.add_argument("--secret", default=None)
    p_webhook.set_defaults(func=cmd_serve_webhook)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
