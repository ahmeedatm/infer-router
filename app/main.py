from fastapi import FastAPI
import uvicorn
from pydantic import BaseModel
from contextlib import asynccontextmanager
from redis.asyncio import Redis
import asyncio
import time
import json

async def process_inference(redis_client):
    print("🤖 InferRouter démarré...")
    # Seuil de basculement (Threshold)
    QUEUE_THRESHOLD = 5 
    
    while True:
        result = await redis_client.brpop("inference_queue")
        if result:
            _, data_json = result
            data = json.loads(data_json)
            
            # --- LOGIQUE DE ROUTAGE (Cœur du sujet) ---
            # On vérifie la longueur actuelle de la file
            queue_length = await redis_client.llen("inference_queue")
            
            if queue_length > QUEUE_THRESHOLD:
                # Mode Dégradé : on privilégie la latence
                model_used = "Fast-Model"
                processing_time = 0.5
            else:
                # Mode Nominal : on privilégie la précision
                model_used = "Accurate-Model"
                processing_time = 2.0
            
            # Simulation de l'inférence
            await asyncio.sleep(processing_time)
            
            # Calcul de la latence
            end_time = time.time()
            latency = end_time - data["timestamp"]

            # Sauvegarde avec l'info du modèle utilisé
            data_history = {
                'sensor_id': data["sensor_id"],
                'model': model_used,
                'latency': latency,
                'queue_at_start': queue_length
            }
            await redis_client.lpush("inference_results", json.dumps(data_history))
            
            print(f"✅ [{model_used}] Latence: {latency:.2f}s | File: {queue_length}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = Redis(host="redis", port=6379)
    worker_task = asyncio.create_task(process_inference(app.state.redis))    
    yield
    worker_task.cancel()
    await app.state.redis.close()

app = FastAPI(
    title="Infer Router API",
    description="Router inference API",
    version="1.0.0",
    lifespan=lifespan
)

class InferenceRequest(BaseModel):
    sensor_id: str
    timestamp: float
    features: list[float]

@app.get("/")
async def root():
    return {"message": "Welcome to Infer Router API"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/results")
async def get_results():
    results_json = await app.state.redis.lrange("inference_results", 0, 9)
    results = [json.loads(r) for r in results_json]
    
    return {"latest_results": results}

@app.post("/data")
async def receive_data(data: InferenceRequest):
    data_json = data.model_dump_json()
    await app.state.redis.lpush("inference_queue", data_json)
    return {"status": "queued"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)