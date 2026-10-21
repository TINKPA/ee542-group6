#!/usr/bin/env python3
"""EE542 Lab 9 Part 3 III: the driver.

  python driver.py --docs ../_origin/embedding_data          # ingest the folder, then chat
  python driver.py --collection ads                          # chat with what is already indexed
  python driver.py --docs DIR --rebuild --show-context       # start over; print ranked chunks

It ingests every PDF / text / HTML file in --docs (extract -> MySQL -> chunk ->
OpenAI embeddings -> FAISS; files already ingested are skipped), builds the
conversation chain, then loops: read a question, answer it from the documents,
print the answer and its sources, ask again. Type 'exit' to quit.
"""
import argparse
import sys
import textwrap

import rag_core as rc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", help="folder of documents to ingest first")
    ap.add_argument("--collection", default="default")
    ap.add_argument("--rebuild", action="store_true", help="drop the collection before ingesting")
    ap.add_argument("--embedder", choices=["openai", "hist"], default="openai",
                    help="openai = Part 3 embeddings; hist = Part 5 Word2Vec cluster histogram")
    ap.add_argument("--show-context", action="store_true",
                    help="also print the ranked chunks (similarity) used for each answer")
    ap.add_argument("-q", "--question", action="append",
                    help="ask these questions non-interactively, then exit (repeatable)")
    a = ap.parse_args()

    if a.rebuild:
        rc.reset_collection(a.collection)
        print(f"collection '{a.collection}' cleared")
    vs = rc.ingest(rc.iter_folder(a.docs), a.collection) if a.docs else rc.load_vectorstore(a.collection)
    if a.embedder == "hist" and vs is not None:
        # (re)build when documents were just ingested, else reuse the saved index
        vs = rc.build_hist_store(a.collection) if (a.docs or a.rebuild) else rc.load_store(a.collection, "hist")
    if vs is None:
        sys.exit(f"collection '{a.collection}' is empty: pass --docs <folder> first")
    stats = rc.collection_stats(a.collection)
    print(f"\n'{a.collection}': {len(stats)} documents, {sum(s['chunks'] for s in stats)} chunks, "
          f"{vs.index.ntotal} vectors x {vs.index.d} dims "
          f"({rc.EMBED_MODEL if a.embedder == 'openai' else 'Word2Vec cluster histogram'}); chat model {rc.CHAT_MODEL}")

    chain = rc.get_conversation_chain(rc.chat_llm(), vs)
    questions = iter(a.question) if a.question else None
    while True:
        try:
            q = next(questions) if questions else input("\nYou: ").strip()
        except (StopIteration, EOFError, KeyboardInterrupt):
            break
        if questions:
            print(f"\nYou: {q}")
        if q.lower() == "exit":
            break
        if not q:
            continue
        if a.show_context:
            print("  ranked context (cosine similarity to the question):")
            for doc, sim in rc.ranked_context(vs, q):
                snippet = doc.page_content[:90].replace("\n", " ")
                print(f"   {sim:.3f}  [{doc.metadata['source']} p.{doc.metadata['page']}] {snippet}...")
        out = chain.invoke({"question": q})
        print("\nBot: " + textwrap.fill(out["answer"], 100, subsequent_indent="     "))
        srcs = dict.fromkeys(f"{d.metadata['source']} p.{d.metadata['page']}" for d in out["source_documents"])
        print("     sources: " + "; ".join(srcs))
    print("bye")


if __name__ == "__main__":
    main()
