"""EE542 Lab 9 Part 3: the RAG pipeline (collect -> chunk -> embed -> store ->
retrieve -> answer), shared by the CLI driver (driver.py) and the upload
website (web_app.py).

Handout functions and where they live:
  II.1 PDF text extraction, stored in database tables -> extract_document(), store_document()
  II.2 chunks of 500 with LangChain CharacterTextSplitter -> get_text_chunks()
  II.3 OpenAI embeddings into a vector database        -> get_vectorstore() / add_to_vectorstore()
  II.4 conversation chain with ConversationBufferMemory -> get_conversation_chain()

Storage:
  MySQL (same server/database as the Part 1 chat app):
    rag_documents  one row per file (name, sha256, kind, pages, chars)
    rag_pages      the extracted text of every page
    rag_chunks     every chunk, with its document, page, position and FAISS id
  FAISS (index/<collection>/): the embedding vectors, saved to disk.

Config (env or ../groupchat/.env):
  OPENAI_API_KEY, RAG_EMBED_MODEL (text-embedding-3-small),
  RAG_CHAT_MODEL (gpt-4o-mini), RAG_DATABASE_URL, RAG_INDEX_DIR.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from langchain_classic.chains import ConversationalRetrievalChain
from langchain_classic.memory import ConversationBufferMemory
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import CharacterTextSplitter
from sqlalchemy import (Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text,
                        UniqueConstraint, create_engine, delete, func, insert, select)

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / "groupchat" / ".env")
key_file = Path(os.getenv("OPENAI_KEY_FILE", "~/.config/ee542/openai_key")).expanduser()
if not os.getenv("OPENAI_API_KEY") and key_file.exists():
    os.environ["OPENAI_API_KEY"] = key_file.read_text().strip()

EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("RAG_CHAT_MODEL", "gpt-4o-mini")
DATABASE_URL = os.getenv("RAG_DATABASE_URL", "mysql+pymysql://chatuser:chatpass@127.0.0.1:3306/groupchat")
INDEX_DIR = Path(os.getenv("RAG_INDEX_DIR", HERE / "index"))
TOP_K = int(os.getenv("RAG_TOP_K", "6"))
SUPPORTED = {".pdf", ".txt", ".md", ".html", ".htm"}

# ---------------------------------------------------------------- database tables
meta = MetaData()
documents = Table(
    "rag_documents", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("collection", String(64), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("kind", String(8), nullable=False),
    Column("pages", Integer, nullable=False),
    Column("chars", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("collection", "sha256", name="uq_collection_sha"),
    mysql_charset="utf8mb4",
)
pages = Table(
    "rag_pages", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_id", Integer, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False),
    Column("page", Integer, nullable=False),
    Column("text", Text(16_000_000), nullable=False),     # MEDIUMTEXT
    mysql_charset="utf8mb4",
)
chunks_t = Table(
    "rag_chunks", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("document_id", Integer, ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False),
    Column("page", Integer, nullable=False),
    Column("chunk_index", Integer, nullable=False),     # position within the document
    Column("content", Text, nullable=False),
    Column("chars", Integer, nullable=False),
    Column("faiss_id", String(64), nullable=True),      # docstore id inside the FAISS index
    mysql_charset="utf8mb4",
)

_engine = None


def db():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        meta.create_all(_engine)
    return _engine


# ---------------------------------------------------------------- 1. collect
@dataclass
class Extracted:
    filename: str
    kind: str
    sha256: str
    pages: list[str]          # one string per page (html/txt: one "page")


def extract_document(path: str | Path, data: bytes | None = None, filename: str | None = None) -> Extracted:
    """Extract text per page. `data` lets the website pass an upload without saving it first."""
    path = Path(path)
    filename = filename or path.name
    data = data if data is not None else path.read_bytes()
    kind = Path(filename).suffix.lower().lstrip(".")
    if kind == "pdf":
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        texts = [(p.extract_text() or "") for p in reader.pages]
    elif kind in ("html", "htm"):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(data, "html.parser")
        # Drop page furniture (scripts, styles, nav, the feedback form), then
        # unwrap inline tags so "save it in <code>ads_setup</code>, then" stays
        # one line; block elements still end a line, which the splitter uses.
        for tag in soup(["script", "style", "nav", "form", "iframe", "noscript", "header", "footer", "aside"]):
            tag.decompose()
        # Keep only the page's main content when it marks one (government and
        # university sites do), so menus, banners and footers are not indexed.
        soup = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup
        for tag in soup.find_all(["a", "span", "code", "b", "i", "em", "strong", "sup", "sub", "tt", "kbd", "font"]):
            tag.unwrap()
        soup.smooth()
        texts = [soup.get_text("\n")]
    else:
        texts = [data.decode("utf-8", errors="replace")]
    # Collapse runs of blank lines; keep single newlines, which the splitter uses.
    # A line longer than the chunk size (a regulation paragraph can run for
    # thousands of characters) is broken after its sentences, so the
    # newline-only CharacterTextSplitter can still keep chunks near 500.
    def lines(t):
        for line in t.splitlines():
            line = line.strip()
            if len(line) > 450:
                yield from (s for s in re.split(r"(?<=[.;:])\s+(?=[A-Z(])", line) if s)
            elif line:
                yield line
    clean = ["\n".join(lines(t)) for t in texts]
    return Extracted(filename, kind, hashlib.sha256(data).hexdigest(), clean)


def iter_folder(folder: str | Path):
    """Handout II.1: iterate over the documents in a folder."""
    for p in sorted(Path(folder).iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            yield p


def store_document(ex: Extracted, collection: str = "default") -> tuple[int, bool]:
    """Insert the document and its pages. Returns (document_id, is_new);
    a file already in the collection (same sha256) is not stored twice."""
    with db().begin() as c:
        row = c.execute(select(documents.c.id).where(documents.c.collection == collection,
                                                     documents.c.sha256 == ex.sha256)).first()
        if row:
            return row.id, False
        doc_id = c.execute(insert(documents).values(
            collection=collection, filename=ex.filename, sha256=ex.sha256, kind=ex.kind,
            pages=len(ex.pages), chars=sum(map(len, ex.pages)),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None))).inserted_primary_key[0]
        c.execute(insert(pages), [{"document_id": doc_id, "page": i + 1, "text": t}
                                  for i, t in enumerate(ex.pages)])
        return doc_id, True


# ---------------------------------------------------------------- 2. chunk
def make_splitter() -> CharacterTextSplitter:
    # separator="\n": PDF text comes out one visual line per "\n", so splitting
    #   there never cuts a word or a line in half.
    # chunk_size=500 characters (the handout's size), measured with len().
    # chunk_overlap=100: the last ~100 characters of a chunk are repeated at the
    #   start of the next, so a sentence that straddles a boundary is still whole
    #   in at least one chunk.
    # Note: CharacterTextSplitter only splits AT the separator, so one line
    #   longer than 500 characters stays one (oversized) chunk; it warns.
    return CharacterTextSplitter(separator="\n", chunk_size=500, chunk_overlap=100,
                                 length_function=len, strip_whitespace=True)


def get_text_chunks(ex: Extracted, doc_id: int | None = None) -> list[Document]:
    """Handout II.2. Splits page by page so every chunk keeps its page number."""
    splitter = make_splitter()
    out = []
    for page_no, text in enumerate(ex.pages, start=1):
        if not text:
            continue
        for piece in splitter.split_text(text):
            out.append(Document(page_content=piece, metadata={
                "source": ex.filename, "page": page_no, "document_id": doc_id,
                "chunk_index": len(out)}))
    return out


# ---------------------------------------------------------------- 3. embed + store
def embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBED_MODEL)


def get_vectorstore(chunks: list[Document]) -> FAISS:
    """Handout II.3: embed the chunks with OpenAI and put them in a FAISS index."""
    return FAISS.from_documents(chunks, embeddings())


def index_path(collection: str) -> Path:
    return INDEX_DIR / collection


def load_vectorstore(collection: str = "default") -> FAISS | None:
    p = index_path(collection)
    if not (p / "index.faiss").exists():
        return None
    return FAISS.load_local(str(p), embeddings(), allow_dangerous_deserialization=True)  # our own file


def add_to_vectorstore(vs: FAISS | None, chunks: list[Document], collection: str = "default") -> FAISS:
    """Embed new chunks, add them to the collection's index, save it, and record
    each chunk (with its FAISS id) in rag_chunks."""
    if not chunks:
        return vs
    if vs is None:
        vs = get_vectorstore(chunks)
        ids = list(vs.index_to_docstore_id.values())
    else:
        ids = vs.add_documents(chunks)
    vs.save_local(str(index_path(collection)))
    with db().begin() as c:
        c.execute(insert(chunks_t), [{
            "document_id": d.metadata["document_id"], "page": d.metadata["page"],
            "chunk_index": d.metadata["chunk_index"], "content": d.page_content,
            "chars": len(d.page_content), "faiss_id": fid} for d, fid in zip(chunks, ids)])
    return vs


def ingest(paths_or_uploads, collection: str = "default", log=print) -> FAISS | None:
    """Extract -> store -> chunk -> embed for each file. Items are paths, or
    (filename, bytes) tuples from the website. Already-ingested files are skipped."""
    vs = load_vectorstore(collection)
    for item in paths_or_uploads:
        ex = extract_document(item) if not isinstance(item, tuple) else \
            extract_document(item[0], data=item[1], filename=item[0])
        doc_id, new = store_document(ex, collection)
        if not new:
            log(f"skip  {ex.filename} (already in '{collection}', document {doc_id})")
            continue
        ch = get_text_chunks(ex, doc_id)
        vs = add_to_vectorstore(vs, ch, collection)
        big = sum(len(d.page_content) > 500 for d in ch)
        log(f"added {ex.filename}: {len(ex.pages)} pages, {sum(map(len, ex.pages)):,} chars, "
            f"{len(ch)} chunks" + (f" ({big} over 500 chars: single long lines)" if big else ""))
    return vs


# ---------------------------------------------------------------- 4. conversation chain
QA_PROMPT = PromptTemplate.from_template(
    "You are a helpful assistant that answers questions about the user's documents.\n"
    "Use the context excerpts below, retrieved from those documents, as your only source. "
    "Answer whenever the excerpts contain relevant information, even if it is partial: "
    "say what they do contain, and mention what is missing. Only if no excerpt is relevant, "
    "reply that the documents do not cover it; never fill gaps with outside knowledge.\n"
    "Cite the file and page for each fact in brackets, e.g. [cookbook.pdf p.12].\n\n"
    "Context:\n{context}\n\nQuestion: {question}\nAnswer:")
DOC_PROMPT = PromptTemplate.from_template("[{source} p.{page}]\n{page_content}")


def chat_llm(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(model=CHAT_MODEL, temperature=temperature)


def get_conversation_chain(llm, vectorstore: FAISS, qa_prompt: PromptTemplate | None = None,
                           history: list[tuple[str, str]] | None = None,
                           search_type: str = "similarity", search_kwargs: dict | None = None
                           ) -> ConversationalRetrievalChain:
    """Handout II.4. The memory keeps the whole dialogue; the chain first rewrites a
    follow-up question into a standalone one using that history, retrieves the
    TOP_K closest chunks for it, and answers from them only."""
    memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True,
                                      output_key="answer")
    # Prior turns (role, text) from a caller that keeps the conversation itself,
    # e.g. the group chat backend, which is stateless per request.
    for role, text in history or []:
        (memory.chat_memory.add_user_message if role == "user" else memory.chat_memory.add_ai_message)(text)
    return ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=vectorstore.as_retriever(search_type=search_type, search_kwargs=search_kwargs or {"k": TOP_K}),
        memory=memory,
        return_source_documents=True,
        combine_docs_chain_kwargs={"prompt": qa_prompt or QA_PROMPT, "document_prompt": DOC_PROMPT},
    )


# ---------------------------------------------------------------- inspection helpers
def ranked_context(vs: FAISS, question: str, k: int = TOP_K):
    """Summary steps e-f made visible: embed the question, rank chunks by
    similarity. OpenAI vectors are unit length, so FAISS's squared-L2 distance
    d maps to cosine similarity 1 - d/2."""
    hits = vs.similarity_search_with_score(question, k=k)
    return [(doc, 1.0 - float(d) / 2.0) for doc, d in hits]


def vector_of(vs: FAISS, doc: Document) -> np.ndarray | None:
    """The stored embedding of a retrieved chunk (looked up by its docstore id)."""
    pos = {v: k for k, v in vs.index_to_docstore_id.items()}.get(doc.id)
    return None if pos is None else vs.index.reconstruct(pos)


def collection_stats(collection: str = "default"):
    with db().connect() as c:
        rows = c.execute(
            select(documents.c.id, documents.c.filename, documents.c.kind, documents.c.pages,
                   documents.c.chars, func.count(chunks_t.c.id).label("chunks"))
            .select_from(documents.outerjoin(chunks_t, chunks_t.c.document_id == documents.c.id))
            .where(documents.c.collection == collection)
            .group_by(documents.c.id).order_by(documents.c.id)).all()
    return [dict(r._mapping) for r in rows]


def reset_collection(collection: str = "default"):
    """Drop a collection's rows and its FAISS index (for a clean rebuild)."""
    with db().begin() as c:
        ids = [r.id for r in c.execute(select(documents.c.id).where(documents.c.collection == collection))]
        if ids:
            c.execute(delete(chunks_t).where(chunks_t.c.document_id.in_(ids)))
            c.execute(delete(pages).where(pages.c.document_id.in_(ids)))
            c.execute(delete(documents).where(documents.c.id.in_(ids)))
    p = index_path(collection)
    for f in ("index.faiss", "index.pkl"):
        (p / f).unlink(missing_ok=True)


# ---------------------------------------------------------------- Part 5: histogram embedder
# Re-embed the collection's chunks (already in rag_chunks) with the Word2Vec
# cluster histogram instead of OpenAI, into a second FAISS index
# index/<collection>__hist/, so the same conversation chain can run on either.
HIST_DEFAULT = dict(n_dim=100, k=800, stopwords=True, soft=True, bin_idf=True, sqrt=True)


def hist_index_path(collection: str) -> Path:
    return INDEX_DIR / f"{collection}__hist"


def build_hist_store(collection: str = "default", log=print, **cfg_overrides) -> FAISS:
    from hist_embed import HistConfig, HistEmbedder
    with db().connect() as c:
        rows = c.execute(select(chunks_t.c.content, chunks_t.c.page, chunks_t.c.chunk_index,
                                chunks_t.c.document_id, documents.c.filename)
                         .join(documents, documents.c.id == chunks_t.c.document_id)
                         .where(documents.c.collection == collection).order_by(chunks_t.c.id)).all()
    if not rows:
        raise SystemExit(f"collection '{collection}' has no chunks; ingest documents first")
    texts = [r.content for r in rows]
    cfg = HistConfig(**{**HIST_DEFAULT, **cfg_overrides})
    emb = HistEmbedder.fit(texts, cfg, log=log)
    metas = [{"source": r.filename, "page": r.page, "chunk_index": r.chunk_index,
              "document_id": r.document_id} for r in rows]
    vs = FAISS.from_embeddings(list(zip(texts, emb.embed_documents(texts))), emb, metadatas=metas)
    p = hist_index_path(collection)
    vs.save_local(str(p))
    emb.save(p / "embedder.pkl")
    log(f"histogram index: {vs.index.ntotal} vectors x {vs.index.d} dims -> {p}")
    return vs


def load_hist_store(collection: str = "default") -> FAISS | None:
    from hist_embed import HistEmbedder
    p = hist_index_path(collection)
    if not (p / "index.faiss").exists():
        return None
    return FAISS.load_local(str(p), HistEmbedder.load(p / "embedder.pkl"),
                            allow_dangerous_deserialization=True)  # our own files


def load_store(collection: str, embedder: str = "openai") -> FAISS | None:
    if embedder == "hist":
        return load_hist_store(collection) or build_hist_store(collection)
    return load_vectorstore(collection)
