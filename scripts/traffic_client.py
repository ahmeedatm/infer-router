"""Traffic generator for Infer Router.

Sends images from data/images/ to the router's /new_pod_run_model endpoint.
Runs a Flask server on port 5002 to receive model callback results.
Results are saved as CSV files in data/responses/.

Usage:
    python3 scripts/traffic_client.py --count 20 --rate 0.1 --scenario default
"""
from __future__ import annotations

import argparse
import base64
import csv
import logging
import os
import threading
import time

import requests
from flask import Flask, jsonify, request

IMAGE_DIRECTORY = "data/images"
RESPONSES_DIRECTORY = "data/responses"
ROUTER_URL = "http://localhost:8000/new_pod_run_model"
CALLBACK_PORT = 5002

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

os.makedirs(RESPONSES_DIRECTORY, exist_ok=True)


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _send_request(image_path: str, scenario: str) -> dict | None:
    try:
        image_b64 = _encode_image(image_path)
        payload = {"image": image_b64, "scenario": scenario}
        resp = requests.post(ROUTER_URL, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error("Request failed for %s: %s", image_path, exc)
        return None


def _load_images_sorted_by_size(directory: str) -> list[str]:
    files = [
        f for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
    ]
    return sorted(files, key=lambda f: os.path.getsize(os.path.join(directory, f)))


def _run_traffic(count: int, rate: float, scenario: str) -> None:
    image_files = _load_images_sorted_by_size(IMAGE_DIRECTORY)
    if not image_files:
        logger.error("No images found in %s", IMAGE_DIRECTORY)
        return

    sent = 0
    for image_file in image_files:
        if sent >= count:
            break
        image_path = os.path.join(IMAGE_DIRECTORY, image_file)
        response = _send_request(image_path, scenario)
        if response:
            logger.info("Queued %s → %s", image_file, response)
        else:
            logger.warning("No response for %s", image_file)
        sent += 1
        if sent < count:
            time.sleep(rate)

    logger.info("Sent %d/%d requests.", sent, count)


def _make_flask_app(app_name: str) -> Flask:
    flask_app = Flask(app_name)
    csv_folder = os.path.join(RESPONSES_DIRECTORY, app_name)
    os.makedirs(csv_folder, exist_ok=True)

    @flask_app.route("/save_result", methods=["POST"])
    def save_result():
        try:
            data = request.get_json()
            model_id = data.get("id", "unknown")
            csv_file = os.path.join(csv_folder, f"{model_id}.csv")
            file_exists = os.path.exists(csv_file)
            with open(csv_file, "a", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                if not file_exists:
                    writer.writerow(["model_name", "id_request", "request_size(byte)", "accuracy", "results"])
                writer.writerow([
                    data.get("id"),
                    data.get("id"),
                    data.get("image_size"),
                    data.get("accuracy"),
                    data.get("results"),
                ])
            return jsonify({"status": "success"}), 200
        except Exception as exc:
            logger.error("[%s] save_result error: %s", app_name, exc)
            return jsonify({"status": "failed", "error": str(exc)}), 500

    return flask_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Infer Router traffic generator")
    parser.add_argument("--count", type=int, default=20, help="Number of requests to send")
    parser.add_argument("--rate", type=float, default=0.1, help="Seconds between requests")
    parser.add_argument("--scenario", type=str, default="default", help="Scenario label")
    args = parser.parse_args()

    app_name = f"traffic_{args.scenario}"
    flask_app = _make_flask_app(app_name)

    server_thread = threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=CALLBACK_PORT, debug=False, use_reloader=False),
        daemon=True,
    )
    server_thread.start()
    logger.info("Callback server listening on port %d", CALLBACK_PORT)
    time.sleep(1)

    try:
        _run_traffic(count=args.count, rate=args.rate, scenario=args.scenario)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")

    logger.info("Done. Results saved to %s/%s/", RESPONSES_DIRECTORY, app_name)


if __name__ == "__main__":
    main()
