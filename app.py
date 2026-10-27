"""FastAPI service that serves the customer-support RAG pipeline."""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import rag_pipeline
from rag_pipeline import LLMServiceError, SupportAssistant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("api")

QUESTION_LIMIT = 1000
resources = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The embedding model, FAISS index and graph are expensive: build them once at startup.
    started = time.perf_counter()
    resources["assistant"] = SupportAssistant()
    logger.info("startup finished in %.0f ms (provider=%s)",
                (time.perf_counter() - started) * 1000, rag_pipeline.active_provider())
    yield
    resources.clear()


app = FastAPI(
    title="Support Assistant API",
    description="Customer-support RAG (LangGraph + FAISS) with a Groq-hosted LLM.",
    version="1.1",
    lifespan=lifespan,
)


class QuestionIn(BaseModel):
    question: str = Field(..., examples=["How can I track my shipment?"])

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        if len(value) > QUESTION_LIMIT:
            raise ValueError(f"question must be at most {QUESTION_LIMIT} characters")
        return value


class AnswerOut(BaseModel):
    request_id: str
    answer: str
    intent: str | None
    sources: list[str]
    retry_count: int
    is_fallback: bool
    latency_ms: float


class FieldProblem(BaseModel):
    field: str
    message: str


class InvalidInputOut(BaseModel):
    detail: list[FieldProblem]


class ServiceErrorOut(BaseModel):
    detail: str
    request_id: str


ASK_ERROR_RESPONSES = {
    422: {"model": InvalidInputOut, "description": "Empty, too long, missing or malformed question"},
    500: {"model": ServiceErrorOut, "description": "Unexpected server error"},
    503: {"model": ServiceErrorOut, "description": "LLM provider unavailable (bad key, quota, network, model)"},
}


def elapsed_ms(since: float) -> float:
    return (time.perf_counter() - since) * 1000


@app.exception_handler(RequestValidationError)
async def on_validation_error(_: Request, exc: RequestValidationError):
    # Return only field + message; the submitted input is never echoed back.
    problems = [{"field": ".".join(part for part in err["loc"][1:] if isinstance(part, str)) or "body",
                 "message": err["msg"].removeprefix("Value error, ")} for err in exc.errors()]
    logger.warning("rejected request: invalid input (%d problem(s))", len(problems))
    return JSONResponse(status_code=422, content={"detail": problems})


@app.get("/health", summary="Liveness check")
def health():
    """Reports that the process is up and the RAG pipeline is loaded (does not call the LLM)."""
    assistant = resources.get("assistant")
    return {
        "status": "ok",
        "rag_loaded": assistant is not None,
        "indexed_chunks": assistant.chunk_count if assistant else 0,
        "provider": rag_pipeline.active_provider(),
    }


@app.post("/ask", response_model=AnswerOut, responses=ASK_ERROR_RESPONSES, summary="Ask a support question")
def ask(payload: QuestionIn):
    """Answers from the FAQ knowledge base, or returns a safe fallback when it has no answer."""
    request_id = uuid.uuid4().hex[:8]
    started = time.perf_counter()
    try:
        assistant = resources.get("assistant")
        if assistant is None:
            raise LLMServiceError("pipeline not loaded")
        outcome = assistant.answer(payload.question)
    except LLMServiceError as err:
        logger.error("req=%s status=failure reason=%s latency_ms=%.0f", request_id, err, elapsed_ms(started))
        return JSONResponse(status_code=503, content={
            "detail": "The answer service is temporarily unavailable. Please try again later.",
            "request_id": request_id})
    except Exception:
        logger.exception("req=%s status=failure reason=unexpected latency_ms=%.0f", request_id, elapsed_ms(started))
        return JSONResponse(status_code=500, content={
            "detail": "Internal server error.", "request_id": request_id})
    latency = elapsed_ms(started)
    logger.info("req=%s status=success intent=%s fallback=%s question_chars=%d latency_ms=%.0f",
                request_id, outcome["intent"], outcome["is_fallback"], len(payload.question), latency)
    return AnswerOut(request_id=request_id, latency_ms=round(latency, 1), **outcome)
