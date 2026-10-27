"""Customer-support RAG pipeline (carried over from Experiment 6) with a swappable LLM provider.

Retrieval (MiniLM embeddings + FAISS) is independent of generation. The provider is picked
with the LLM_PROVIDER env var: "groq" (cloud API, default) or "mock" (offline, for tests).
"""
import logging
import os
from pathlib import Path
from typing import List, TypedDict

import requests
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph

load_dotenv()
logger = logging.getLogger("rag_pipeline")

PROJECT_DIR = Path(__file__).parent
KNOWLEDGE_FILE = PROJECT_DIR / "knowledge_base.txt"
SECTION_SEPARATOR = "=====PAGE====="

GROQ_ENDPOINT = os.getenv("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
REQUEST_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT", "30"))
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
NO_ANSWER_TOKEN = "INSUFFICIENT_CONTEXT"
MAX_RETRIES = 1

SAFE_FALLBACK_REPLY = (
    "Sorry, I could not find a reliable answer to that in our FAQ. "
    "Please reach out to the support team via the Help section. "
    "Never share your password, one-time code, or full card details."
)

QUERY_EXPANSIONS = {
    "order_cancellation": "cancel order before dispatch",
    "returns_refunds": "return eligibility refund process",
    "order_tracking": "order dispatch tracking shipment status",
    "account_access": "account sign in password reset",
    "billing_payments": "billing payment transaction charged twice",
    "technical_support": "website technical troubleshooting",
    "general_support": "customer support help contact",
}

INTENT_KEYWORDS = [
    ("order_cancellation", ["cancel"]),
    ("returns_refunds", ["refund", "return", "exchange"]),
    ("order_tracking", ["track", "shipment", "delivery", "order status", "shipping"]),
    ("account_access", ["password", "sign in", "log in", "login", "account", "verification"]),
    ("billing_payments", ["charged", "payment", "billing", "invoice", "card"]),
    ("technical_support", ["website", "error", "loading", "browser", "technical"]),
]


class LLMServiceError(Exception):
    """Raised when the LLM provider fails. The message is safe to log (no secrets)."""


# ------------------------------------------------------------------ LLM providers
def call_groq(prompt: str) -> str:
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise LLMServiceError("GROQ_API_KEY is not configured")
    try:
        resp = requests.post(
            GROQ_ENDPOINT,
            headers={"Authorization": f"Bearer {groq_key}"},
            json={
                "model": GROQ_MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 1000,
            },
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.RequestException as err:
        raise LLMServiceError(f"network error: {type(err).__name__}") from None
    if resp.status_code != 200:
        # only the status code: the body may echo request details
        raise LLMServiceError(f"provider returned HTTP {resp.status_code}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise LLMServiceError("unexpected provider response format") from None
    return (content or "").strip()


def call_mock(prompt: str) -> str:
    """Offline stand-in: echoes the first retrieved passage, or the no-answer token."""
    context_part = prompt.split("FAQ CONTEXT:")[1].split("CUSTOMER QUESTION:")[0].strip()
    question_part = prompt.split("CUSTOMER QUESTION:")[1].split("ANSWER:")[0].lower()
    if "insurance" in question_part or not context_part:
        return NO_ANSWER_TOKEN
    return "[mock provider] " + context_part[:200]


PROVIDERS = {"groq": call_groq, "mock": call_mock}


def active_provider() -> str:
    return os.getenv("LLM_PROVIDER", "groq").strip().lower()


def run_llm(prompt: str) -> str:
    provider = active_provider()
    if provider not in PROVIDERS:
        raise LLMServiceError(f"unknown LLM_PROVIDER '{provider}'")
    return PROVIDERS[provider](prompt)


# ---------------------------------------------------------------- knowledge base
def read_knowledge_base(path: Path = KNOWLEDGE_FILE) -> List[Document]:
    raw_text = path.read_text(encoding="utf-8")
    documents = []
    for section in raw_text.split(SECTION_SEPARATOR):
        lines = section.strip().split("\n")
        if len(lines) < 3:
            continue
        title, source_line, *body = lines
        documents.append(Document(
            page_content=f"{title}\n" + "\n".join(body),
            metadata={"topic": title.strip(), "source": source_line.removeprefix("Source:").strip()},
        ))
    if not documents:
        raise RuntimeError(f"no documents found in {path.name}")
    return documents


class ChatState(TypedDict, total=False):
    question: str
    intent: str
    query: str
    context: str
    sources: List[str]
    draft: str
    attempts: int
    reply: str
    used_fallback: bool


class SupportAssistant:
    """Loads embeddings, the FAISS index and the LangGraph workflow once; reused per request."""

    def __init__(self, top_k: int = 3):
        splitter = RecursiveCharacterTextSplitter(chunk_size=450, chunk_overlap=60)
        chunks = splitter.split_documents(read_knowledge_base())
        embedder = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        self.index = FAISS.from_documents(chunks, embedder)
        self.retriever = self.index.as_retriever(search_type="similarity", search_kwargs={"k": top_k})
        self.chunk_count = len(chunks)
        self.workflow = self._compile_workflow()
        logger.info("RAG ready: %d chunks indexed", self.chunk_count)

    # --- graph nodes
    @staticmethod
    def detect_intent(state: ChatState):
        text = state["question"].lower()
        intent = next((name for name, words in INTENT_KEYWORDS if any(w in text for w in words)),
                      "general_support")
        return {"intent": intent, "query": state["question"], "attempts": state.get("attempts", 0)}

    def fetch_context(self, state: ChatState):
        hits = self.retriever.invoke(state["query"])
        return {"context": "\n\n".join(h.page_content for h in hits),
                "sources": [h.metadata.get("source", "unknown") for h in hits]}

    @staticmethod
    def write_draft(state: ChatState):
        prompt = f"""You are a polite customer-support assistant.
Answer the CUSTOMER QUESTION using only the FAQ CONTEXT.
Never make up order status, refund approvals, timelines, or company policies.
If the context does not contain the answer, output exactly:
{NO_ANSWER_TOKEN}
Never ask for passwords, one-time codes, or full payment-card details.
Keep the answer short and clear.

FAQ CONTEXT:
{state.get("context", "")}

CUSTOMER QUESTION:
{state["question"]}

ANSWER:"""
        return {"draft": run_llm(prompt)}

    @staticmethod
    def check_draft(state: ChatState):
        draft = state.get("draft", "").strip()
        return {"reply": "" if (not draft or NO_ANSWER_TOKEN in draft) else draft}

    @staticmethod
    def choose_next(state: ChatState):
        if state.get("reply"):
            return "done"
        return "retry" if state.get("attempts", 0) < MAX_RETRIES else "give_up"

    @staticmethod
    def broaden_query(state: ChatState):
        extra = QUERY_EXPANSIONS.get(state.get("intent"), "customer support")
        return {"query": f"{state['question']} {extra}", "attempts": state.get("attempts", 0) + 1}

    @staticmethod
    def use_fallback(state: ChatState):
        return {"reply": SAFE_FALLBACK_REPLY, "used_fallback": True}

    def _compile_workflow(self):
        graph = StateGraph(ChatState)
        graph.add_node("detect_intent", self.detect_intent)
        graph.add_node("fetch_context", self.fetch_context)
        graph.add_node("write_draft", self.write_draft)
        graph.add_node("check_draft", self.check_draft)
        graph.add_node("broaden_query", self.broaden_query)
        graph.add_node("use_fallback", self.use_fallback)
        graph.add_edge(START, "detect_intent")
        graph.add_edge("detect_intent", "fetch_context")
        graph.add_edge("fetch_context", "write_draft")
        graph.add_edge("write_draft", "check_draft")
        graph.add_conditional_edges("check_draft", self.choose_next,
                                    {"done": END, "retry": "broaden_query", "give_up": "use_fallback"})
        graph.add_edge("broaden_query", "fetch_context")
        graph.add_edge("use_fallback", END)
        return graph.compile()

    def answer(self, question: str) -> dict:
        """Run the workflow. Raises LLMServiceError if the LLM provider fails."""
        final = self.workflow.invoke({"question": question, "attempts": 0})
        fell_back = bool(final.get("used_fallback", False))
        return {
            "answer": final["reply"],
            "intent": final.get("intent"),
            # the fallback reply is not based on retrieved passages, so no sources are cited
            "sources": [] if fell_back else sorted(set(final.get("sources", []))),
            "retry_count": final.get("attempts", 0),
            "is_fallback": fell_back,
        }
