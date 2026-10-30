"""EE542 Lab 9 Part 3 I: website for collecting documents and chatting with them.

  streamlit run web_app.py --server.port 8501

Sidebar: upload one or many PDF / TXT / MD / HTML files, press "Process" to
extract -> store in MySQL -> chunk -> embed -> add to the FAISS index; the
documents already in the collection are listed with their page and chunk
counts. Main area: ask questions; every answer shows the ranked context it was
built from (cosine similarity, file, page, chunk text) and the first values of
each chunk's embedding vector, so the RAG steps are visible.
"""
import numpy as np
import streamlit as st

import rag_core as rc

st.set_page_config(page_title="EE542 Lab 9 · Chat with your documents", page_icon="📄", layout="wide")


@st.cache_resource(show_spinner=False)
def vectorstore(collection: str, embedder: str, version: int):
    # `version` changes after each upload so the cached index is reloaded.
    if embedder == "hist":
        if version and rc.load_vectorstore(collection) is not None:
            return rc.build_hist_store(collection, log=lambda s: None)   # new uploads: re-fit
        return rc.load_store(collection, "hist") if rc.load_vectorstore(collection) else None
    return rc.load_vectorstore(collection)


def reset_chat():
    st.session_state.history = []
    st.session_state.chain = None


if "history" not in st.session_state:
    reset_chat()
    st.session_state.version = 0

# ---------------------------------------------------------------- sidebar: collect
with st.sidebar:
    st.header("Your documents")
    collection = st.text_input("Collection", value="default",
                               help="Separate knowledge bases live in separate collections.")
    embedder = st.radio("Embedding", ["openai", "hist"], horizontal=True,
                        format_func={"openai": "OpenAI (Part 3)", "hist": "Word2Vec histogram (Part 5)"}.get)
    if (st.session_state.get("collection"), st.session_state.get("embedder")) != (collection, embedder):
        st.session_state.collection, st.session_state.embedder = collection, embedder
        reset_chat()
    files = st.file_uploader("Upload PDFs or text files, then press Process",
                             type=["pdf", "txt", "md", "html", "htm"], accept_multiple_files=True)
    if st.button("Process", type="primary", disabled=not files, use_container_width=True):
        log = []
        with st.status("Processing…", expanded=True) as status:
            def say(msg):
                log.append(msg)
                st.write(msg)
            rc.ingest([(f.name, f.getvalue()) for f in files], collection, log=say)
            status.update(label="Done", state="complete")
        st.session_state.version += 1
        reset_chat()

    stats = rc.collection_stats(collection)
    if stats:
        st.caption(f"{len(stats)} documents · {sum(s['chunks'] for s in stats):,} chunks · "
                   f"embeddings: {rc.EMBED_MODEL} · chat: {rc.CHAT_MODEL}")
        st.dataframe([{"file": s["filename"], "pages": s["pages"], "chars": s["chars"],
                       "chunks": s["chunks"]} for s in stats],
                     hide_index=True, use_container_width=True)
    else:
        st.info("No documents yet in this collection.")
    if st.button("Clear conversation", use_container_width=True):
        reset_chat()

# ---------------------------------------------------------------- main: chat
st.title("Chat with your documents")
vs = vectorstore(collection, embedder, st.session_state.version)
if vs is None:
    st.write("Upload documents in the sidebar to start.")
    st.stop()
if st.session_state.chain is None:
    st.session_state.chain = rc.get_conversation_chain(rc.chat_llm(), vs)


def show_context(ctx):
    with st.expander(f"Retrieved context ({len(ctx)} chunks, ranked by cosine similarity)"):
        for rank, (doc, sim, vec) in enumerate(ctx, 1):
            st.markdown(f"**{rank}. {doc.metadata['source']} p.{doc.metadata['page']}** · "
                        f"similarity `{sim:.3f}` · chunk #{doc.metadata.get('chunk_index')} · "
                        f"{len(doc.page_content)} chars")
            st.text(doc.page_content)
            if vec is not None:
                nz = np.flatnonzero(vec)
                if len(nz) < len(vec) / 2:     # sparse histogram: show its largest bins
                    top = nz[np.argsort(-vec[nz])][:8]
                    st.caption(f"histogram embedding ({len(vec)} bins, {len(nz)} non-zero, ‖v‖="
                               f"{np.linalg.norm(vec):.3f}); largest bins: "
                               + ", ".join(f"[{b}] {vec[b]:.3f}" for b in top))
                else:
                    st.caption(f"embedding ({len(vec)} dims, ‖v‖={np.linalg.norm(vec):.3f}): "
                               + ", ".join(f"{x:+.4f}" for x in vec[:8]) + ", …")


for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["q"])
    with st.chat_message("assistant"):
        st.write(turn["a"])
        show_context(turn["ctx"])

q = st.chat_input("Ask a question about your documents")
if q:
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        with st.spinner("Searching and answering…"):
            out = st.session_state.chain.invoke({"question": q})
            # The chain retrieves with the (possibly rewritten) standalone question;
            # show exactly the chunks it used, scored against the user's question.
            scored = {d.id: s for d, s in rc.ranked_context(vs, q, k=max(rc.TOP_K, 20))}
            ctx = [(d, scored.get(d.id, float("nan")), rc.vector_of(vs, d)) for d in out["source_documents"]]
        st.write(out["answer"])
        show_context(ctx)
    st.session_state.history.append({"q": q, "a": out["answer"], "ctx": ctx})
