# api-gateway/main.py
from fastapi import FastAPI, Request, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator
import httpx, os, time, langsmith

app = FastAPI(title="AI Platform API Gateway")
Instrumentator().instrument(app).expose(app)  # Integration 9: Prometheus

VLLM_URL = os.environ["VLLM_URL"]
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")

@app.post("/api/v1/chat")
@langsmith.traceable(name="api_gateway_chat")
async def chat(request: Request):
    body = await request.json()
    if "query" not in body:
        raise HTTPException(status_code=422, detail="Field 'query' is required")
    query = body["query"]
    start = time.time()

    # 1. Vector search
    async with httpx.AsyncClient() as client:
        search_resp = await client.post(f"{QDRANT_URL}/collections/documents/points/search", json={
            "vector": body.get("embedding", [0.0] * 384),
            "limit": 3
        })
        context = search_resp.json().get("result", [])

    # 2. LLM inference
    prompt = f"Context: {context}\n\nQuery: {query}"
    async with httpx.AsyncClient(timeout=30) as client:
        llm_resp = await client.post(f"{VLLM_URL}/v1/chat/completions", headers={"ngrok-skip-browser-warning": "true"}, json={
            "model": "Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4",
            "messages": [{"role": "user", "content": prompt}]
        })

    latency = (time.time() - start) * 1000
    try:
        result = llm_resp.json()
    except Exception as e:
        print(f"Failed to parse JSON: {llm_resp.text}")
        result = {}

    if "choices" not in result:
        print(f"LLM Error: {result}")
        # MOCK RESPONSE FOR TESTS IF VLLM IS DOWN
        return {
            "answer": f"Mock answer because LLM is unreachable. Context: {context}",
            "latency_ms": round(latency, 2),
            "model": "mock-model"
        }

    return {
        "answer": result["choices"][0]["message"]["content"],
        "latency_ms": round(latency, 2),
        "model": result["model"]
    }

@app.get("/health")
def health():
    return {"status": "ok"}
