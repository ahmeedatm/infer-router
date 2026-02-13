import argparse
import json
import random
import time
import urllib.request
import urllib.error

def send_requests(count, url="http://localhost:8000/data"):
    print(f"🚀 Sending {count} requests to {url}...")
    
    for i in range(count):
        data = {
            "sensor_id": f"sensor-{random.randint(1, 100)}",
            "timestamp": time.time(),
            "features": [random.random() for _ in range(3)]
        }
        
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    print(f"[{i+1}/{count}] ✅ Sent successfully")
                else:
                    print(f"[{i+1}/{count}] ❌ Failed: {response.status}")
        except urllib.error.URLError as e:
            print(f"[{i+1}/{count}] ❌ Connection error: {e}")
            
    print("Done!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send dummy inference requests.")
    parser.add_argument("--count", type=int, default=10, help="Number of requests to send")
    parser.add_argument("--url", type=str, default="http://localhost:8000/data", help="Target URL")
    
    args = parser.parse_args()
    send_requests(args.count, args.url)
