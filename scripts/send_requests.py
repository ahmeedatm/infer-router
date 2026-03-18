import argparse
import json
import random
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


def send_requests(count, url=f"{BASE_URL}/data", scenario="default"):
    print(f"Sending {count} requests to {url} [scenario={scenario}]...")

    for i in range(count):
        data = {
            "sensor_id": f"sensor-{random.randint(1, 100)}",
            "timestamp": time.time(),
            "features": [random.random() for _ in range(3)],
            "scenario": scenario,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    print(f"[{i+1}/{count}] Sent successfully")
                else:
                    print(f"[{i+1}/{count}] Failed: {response.status}")
        except urllib.error.URLError as e:
            print(f"[{i+1}/{count}] Connection error: {e}")

    print("Done!")


def send_feedback(model, accuracy, base_url=BASE_URL):
    url = f"{base_url}/feedback"
    data = {"model": model, "accuracy": accuracy}
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as response:
            body = json.loads(response.read())
            print(f"Feedback accepted: {body}")
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode()}")
    except urllib.error.URLError as e:
        print(f"Connection error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send dummy inference requests or accuracy feedback.")
    parser.add_argument("--count", type=int, default=10, help="Number of inference requests to send")
    parser.add_argument("--url", type=str, default=f"{BASE_URL}/data", help="Target URL for inference requests")
    parser.add_argument("--scenario", type=str, default="default", help="Tag requests with a scenario name")
    parser.add_argument("--feedback", action="store_true", help="Send a feedback update instead of inference requests")
    parser.add_argument("--model", type=str, default="Fast-Model", help="Model name for feedback (Fast-Model or Accurate-Model)")
    parser.add_argument("--accuracy", type=float, default=0.9, help="Accuracy value for feedback (0.0–1.0)")

    args = parser.parse_args()

    if args.feedback:
        send_feedback(args.model, args.accuracy)
    else:
        send_requests(args.count, args.url, args.scenario)
