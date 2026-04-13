import os
import random
import requests
import time
import threading
import csv
import logging
import base64
from flask import Flask, request, jsonify

# Configuration
IMAGE_DIRECTORY = "data/images"
USER_REQUEST_RESPOSES = 'user_request_responses/'
service_port=5003
if not os.path.exists(USER_REQUEST_RESPOSES):
    os.makedirs(USER_REQUEST_RESPOSES)

logging.basicConfig(level=logging.DEBUG)

# --- Send request to YOLO model service ---
def send_request(image_path):
    try:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode('utf-8')

        payload = {
            "image": image_b64,
        }

        service_url = f"http://localhost:{service_port}/new_pod_run_model"
        headers = {"Content-Type": "application/json"}
        response = requests.post(service_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f" Request failed: {e}")
        return None

# --- Data sources ---
def data_sources(parameters):
   
    rate = int(parameters.get("rate"))
    total_requests = int(parameters.get("total_requests"))


    image_files = os.listdir(IMAGE_DIRECTORY)

    image_files_sorted = sorted(image_files,key=lambda x: os.path.getsize(os.path.join(IMAGE_DIRECTORY, x)))



    for image_file in image_files_sorted:
        image_path = os.path.join(IMAGE_DIRECTORY, image_file)
        response = send_request(image_path)
        if response:
            logging.info(f"GET Response: {response}")
        time.sleep(rate)

# --- Flask server for receiving results ---
def start_flask_server(port, app_name):
    app_instance = Flask(app_name)
    csv_folder = os.path.join(USER_REQUEST_RESPOSES, app_name)
    os.makedirs(csv_folder, exist_ok=True)

    @app_instance.route('/save_result', methods=['POST'])
    def save_result():
        try:
            data = request.get_json()
            model_name = data.get('id', 'unknown')
            csv_file = os.path.join(csv_folder, f"{model_name}.csv")
            if not os.path.exists(csv_file):
                with open(csv_file, 'w', newline='') as f:
                    writer = csv.writer(f, delimiter=';')
                    writer.writerow(['model_name', 'id_request', 'request_size(byte)', 'accuracy', 'results'])
            with open(csv_file, 'a', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow([data.get('id'), data.get('id'), data.get('image_size'), data.get('accuracy'), data.get('results')])
            return jsonify({"status": "success"}), 200
        except Exception as e:
            logging.error(f"[{app_name}] Error in save_result: {e}")
            return jsonify({"status": "failed", "error": str(e)}), 500

    app_instance.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# --- Main execution ---
if __name__ == "__main__":
    parameter_per_sources = [
        {"app_name": "src1_req", "algo": 4, "accuracy": 0.53, "latency": 479, "rate": 0.1, "total_requests": 20},
    ]

    server_threads = []
    client_threads = []

    port = 5002
    app_name = "app_name"

    # Start Flask server to receive results
    server_thread = threading.Thread(target=start_flask_server, args=(port, app_name))
    server_thread.start()
    server_threads.append(server_thread)
    time.sleep(1)

    for parameter in parameter_per_sources:
        
        # Start sending requests to YOLO service
        client_thread = threading.Thread(target=data_sources, args=(parameter,))
        client_thread.start()
        client_threads.append(client_thread)

    for t in client_threads:
        t.join()

    logging.info("All clients finished sending requests.")

