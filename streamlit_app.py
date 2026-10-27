"""Streamlit frontend for the Support Assistant API (start the FastAPI server first)."""
import os

import requests
import streamlit as st

BACKEND_URL = os.getenv("API_URL", "http://127.0.0.1:8001").rstrip("/")
SAMPLE_QUESTIONS = [
    "How can I track my shipment?",
    "I forgot my password and cannot log in. What should I do?",
    "I was charged twice for one order. What should I do?",
    "Do you sell home insurance?",
]


def backend_is_up() -> bool:
    try:
        return requests.get(f"{BACKEND_URL}/health", timeout=3).json().get("status") == "ok"
    except (requests.RequestException, ValueError):
        return False


def fill_question(text: str):
    st.session_state["question_box"] = text


st.set_page_config(page_title="Support Assistant", page_icon="🎧")
st.title("🎧 Support Assistant")
st.caption("FAQ-grounded answers · LangGraph + FAISS retrieval · Groq LLM · FastAPI backend")

st.sidebar.markdown(f"**Backend:** {'🟢 online' if backend_is_up() else '🔴 offline'}")
st.sidebar.code(BACKEND_URL)
st.sidebar.markdown("**Try a sample question**")
for sample in SAMPLE_QUESTIONS:
    st.sidebar.button(sample, on_click=fill_question, args=(sample,), use_container_width=True)

user_question = st.text_area("Ask a support question", key="question_box", max_chars=1100, height=100)
if st.button("Get answer", type="primary"):
    try:
        with st.spinner("Searching the FAQ..."):
            resp = requests.post(f"{BACKEND_URL}/ask", json={"question": user_question}, timeout=90)
        body = resp.json()
    except requests.RequestException:
        st.error("Could not reach the API. Is the FastAPI server running?")
    except ValueError:
        st.error(f"The API returned an unexpected response (HTTP {resp.status_code}).")
    else:
        if resp.status_code == 200:
            (st.warning if body["is_fallback"] else st.success)(body["answer"])
            col_latency, col_intent, col_retries = st.columns([1, 1.6, 0.7])
            col_latency.metric("Latency", f"{body['latency_ms']:.0f} ms")
            col_intent.metric("Intent", body["intent"] or "-")
            col_retries.metric("Retries", body["retry_count"])
            if body["sources"]:
                with st.expander("Sources"):
                    for link in body["sources"]:
                        st.write(link)
            st.caption(f"request id: {body['request_id']}")
        elif resp.status_code == 422:
            st.error("Invalid input: " + "; ".join(p["message"] for p in body.get("detail", [])))
        else:
            st.error(f"{body.get('detail', 'Request failed.')} (request id: {body.get('request_id', 'n/a')})")
