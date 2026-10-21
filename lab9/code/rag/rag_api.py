"""EE542 Lab 9 Part 4: the knowledge-base service behind the group chat bot.

  uvicorn rag_api:app --port 8002          (run_api.sh)

  POST /ask  {"question": "...", "history": [["user", "..."], ["assistant", "..."]],
              "collection": "f1", "embedder": "openai" | "hist"}
       ->    {"answer": "...", "sources": [{"title", "agency", "url", "page", "similarity", "snippet"}]}
  GET  /health

The group chat backend (../groupchat/backend/app.py) calls /ask for every
message with a "?", passing the recent conversation, and posts the answer with
its source links. Keeping RAG in its own service lets the chat app stay on its
small dependency set and lets the knowledge base be rebuilt without touching it.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

import rag_core as rc
from f1.sources import url_for

F1_PROMPT = PromptTemplate.from_template(
    "You are F-1 Compass, an assistant for F-1 international students at the University of "
    "Southern California (USC). Answer the question using ONLY the excerpts below, which come "
    "from official sources: the F-1 regulation (8 CFR 214.2(f)), USCIS, SEVP / Study in the "
    "States, ICE, and the USC Office of International Services (OIS).\n"
    "Rules:\n"
    "- Be concrete: give the exact numbers, deadlines, forms and steps the excerpts state.\n"
    "- State the general rule first. Some excerpts are worked examples for one student with specific "
    "calendar dates; use those only as a labelled example after the general rule, never as the rule.\n"
    "- Say whether a rule is federal (regulation, USCIS, SEVP) or a USC OIS procedure when it matters.\n"
    "- Cite each fact as [Agency: Title], using the bracketed source label of its excerpt (drop the "
    "'.html'/'.pdf' and page).\n"
    "- If the question is about F-1 status, work, travel or immigration but the excerpts do not "
    "answer it, say so plainly and suggest asking a USC OIS advisor (DSO); never fill the gap from memory.\n"
    "- If the question has nothing to do with F-1 students, reply with exactly this sentence and "
    "nothing else: 'I can only help with F-1 student questions: status, OPT, CPT, employment and travel.'\n"
    "- For every F-1 answer, end with the line: 'Not legal advice; confirm with your DSO at USC OIS.'\n\n"
    "Excerpts:\n{context}\n\nQuestion: {question}\nAnswer:")

PROMPTS = {"f1": F1_PROMPT}
# Max-marginal-relevance retrieval for the F-1 base: several pages repeat each
# other (USC's STEM OPT page and its prior-degree twin) and one long news page
# has many near-identical worked examples, so plain top-k returned 3 chunks of
# the same example. MMR picks 8 of the 30 closest chunks, trading relevance
# (lambda 0.6) against similarity to the chunks already chosen.
RETRIEVAL = {"f1": ("mmr", {"k": 8, "fetch_k": 30, "lambda_mult": 0.6})}


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[tuple[str, str]] = Field(default_factory=list)
    collection: str = "f1"
    embedder: str = "openai"


app = FastAPI(title="EE542 Lab 9 RAG API")


@lru_cache(maxsize=8)
def store(collection: str, embedder: str):
    vs = rc.load_store(collection, embedder)
    if vs is None:
        raise HTTPException(404, f"no index for collection '{collection}' ({embedder})")
    return vs


@app.get("/health")
def health():
    return {"ok": True, "embed_model": rc.EMBED_MODEL, "chat_model": rc.CHAT_MODEL}


@app.post("/ask")
def ask(req: Ask):
    vs = store(req.collection, req.embedder)
    stype, skw = RETRIEVAL.get(req.collection, ("similarity", None))
    chain = rc.get_conversation_chain(rc.chat_llm(), vs, PROMPTS.get(req.collection), req.history[-10:],
                                      search_type=stype, search_kwargs=skw)
    out = chain.invoke({"question": req.question})
    scores = {d.id: s for d, s in rc.ranked_context(vs, req.question, k=max(rc.TOP_K, 20))}
    meta = url_for() if req.collection == "f1" else {}
    sources, seen = [], set()
    for d in out["source_documents"]:
        name = d.metadata["source"]
        m = meta.get(name, {})
        if name in seen:
            continue
        seen.add(name)
        sim = scores.get(d.id)
        sources.append({"title": m.get("title", name), "agency": m.get("agency", ""),
                        "url": m.get("url", ""), "page": d.metadata.get("page"),
                        "similarity": None if sim is None or math.isnan(sim) else round(sim, 3),
                        "snippet": d.page_content[:240]})
    # Citation labels come from file names; drop a leaked extension or page tag.
    answer = re.sub(r"\s+p\.\d+(?=[\],;])", "", out["answer"])
    answer = re.sub(r"\.(?:html|pdf|txt)(?=[\],;])", "", answer)
    return {"answer": answer, "sources": sources, "embedder": req.embedder}
