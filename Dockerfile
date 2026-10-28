FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.hf

WORKDIR /app

# CPU-only torch keeps the image ~1GB smaller than the default CUDA build
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image so cold starts skip the download
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
# Model is already in the image; don't hit the Hugging Face Hub at runtime
ENV HF_HUB_OFFLINE=1

COPY . .

# SERVICE=api (default) runs FastAPI; SERVICE=ui runs Streamlit. Cloud Run sets $PORT.
ENV SERVICE=api PORT=8080
# exec makes the server PID 1 so it receives Cloud Run's SIGTERM on shutdown
CMD ["sh", "-c", "if [ \"$SERVICE\" = \"ui\" ]; then exec streamlit run streamlit_app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true; else exec uvicorn app:app --host 0.0.0.0 --port $PORT; fi"]
