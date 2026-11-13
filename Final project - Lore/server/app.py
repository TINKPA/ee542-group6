"""Legacy Box local server.

Serves the prototype page at http://127.0.0.1:8000 and implements the back-end contract from
Legacy_Box_UI_UX_Requirements.md section 7 with real local models (see models.py).
Run:  python server/app.py      (after installing server/requirements.txt, see server/README.md)
"""
import json
import logging
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse

import db
import models as M

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("legacy")

ROOT = Path(__file__).resolve().parent
PAGE = ROOT.parent / "legacy-box-demo.html"
UPLOADS = Path(os.getenv("LEGACY_DATA") or ROOT / "data") / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Legacy Box local server")
MEM = db.load_all()   # memory id -> record (includes "vec"); persisted in data/legacy.db
QCACHE = {}   # question id -> question (with server-side option effects)
OWNER = os.getenv("LEGACY_OWNER", "Me")
TEXT_EXT = {".txt", ".md", ".csv", ".srt", ".vtt", ".json"}
KIND_WORD = {"photo": "photo", "video": "video", "voice": "recording", "doc": "document", "note": "note"}


@app.on_event("startup")
def _warm():
    threading.Thread(target=M.load_all, daemon=True).start()


@app.get("/")
def page():
    head = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style></head><body>')
    return HTMLResponse(head + PAGE.read_text(encoding="utf-8") + "</body></html>")


@app.get("/health")
def health():
    return {"ok": True, "owner": OWNER, "device": M.device(),
            "models": {k: {"name": M.NAMES[k], "status": M.STATUS[k]} for k in M.STATUS}}


# ---------------------------------------------------------------- helpers
def safe_id(s):
    s = re.sub(r"[^A-Za-z0-9_-]", "", str(s or ""))[:40]
    return s or uuid.uuid4().hex[:10]


def fmt_dur(s):
    return f"{int(s // 60)}:{int(round(s % 60)):02d}" if s else "unknown length"


def excerpt(t, n=160):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def read_text_file(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def read_document(path):
    ext = Path(path).suffix.lower()
    if ext in TEXT_EXT:
        return read_text_file(path)
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages[:30])
    if ext == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    return ""


def reembed(m):
    if M.ready("embedding"):
        m["vec"] = M.embed([m["embed_text"] + " " + " ".join(m.get("people", []))])[0]
        db.save(m)


def public(m):
    return {k: m.get(k) for k in ("id", "title", "original_title", "text", "fact", "year", "people", "observations", "log", "analysis")}


GENERIC_NAME = re.compile(r"^(img|image|dsc|dscn|dscf|dcim|pxl|vid|video|mov|mvimg|photo|pic|picture|scan|scanned|document|doc|untitled|"
                          r"new recording|recording|audio|voice|memo|screenshot|screen shot|whatsapp|wechat|weixin|mmexport|wx camera|"
                          r"camera|snapshot|file|talk|note|download|signal|telegram|qq|\u5fae\u4fe1|\u56fe\u7247|\u5f55\u97f3|\u89c6\u9891)(\b|\d|\s|$)", re.I)


def needs_name(title):
    """True for camera, phone and app file names that say nothing about the memory."""
    t = (title or "").strip()
    if not t or GENERIC_NAME.match(t):
        return True
    if re.fullmatch(r"[0-9a-fA-F\- ]{10,}", t):            # uuid or hash
        return True
    letters = sum(ch.isalpha() for ch in t)
    digits = sum(ch.isdigit() for ch in t)
    return digits >= letters


# ---------------------------------------------------------------- ingest
def analyze_file(m):
    path, kind, owner = m["path"], m["kind"], m.get("owner", "you")
    known = sorted({p for x in MEM.values() for p in x.get("people", [])} | set(m.get("known") or []) | {owner})
    obs, parts, logs = [], [], []
    description = transcript = shown_text = doc_text = ""
    decade = None
    scene = {}

    def add(label, value, conf):
        obs.append({"label": label, "value": value, "confidence": conf})

    try:
        if kind == "photo":
            img, exif = M.open_image(path)
            if exif:
                m["year"], m["date_sure"] = int(str(exif)[:4]), True
                add("Date taken (camera)", str(exif)[:10].replace(":", "-"), "sure")
            if M.ready("vision_slm"):
                d = M.describe_image(img)
                description, shown_text, decade, scene = d["description"], d["text"], d["decade"], d["scene"]
                add("I see", description, "guess")
                add("Writing on it", f"“{excerpt(shown_text)}”" if shown_text else "None found", "sure")
                logs.append("look")
            else:
                add("I see", "The vision model is still loading, so I could not look yet.", "unclear")

        elif kind == "video":
            dur = M.media_duration(path)
            m["duration"] = dur
            add("Video", f"{fmt_dur(dur)} long", "sure")
            frame = M.video_frame(path)
            if frame is not None and M.ready("vision_slm"):
                d = M.describe_image(frame)
                description, shown_text, decade, scene = d["description"], d["text"], d["decade"], d["scene"]
                add("I see", description, "guess")
                if shown_text:
                    add("Writing on screen", f"“{excerpt(shown_text)}”", "sure")
                logs.append("look")
            if M.ready("speech"):
                transcript = M.transcribe(M.load_audio(path), known)
                add("I heard", f"“{excerpt(transcript)}”" if transcript else "No clear speech", "sure" if transcript else "unclear")
                logs.append("listen")
            else:
                add("I heard", "The speech model is still loading.", "unclear")

        elif kind == "voice":
            audio = M.load_audio(path)
            # browser recordings often carry no duration in their header
            dur = M.media_duration(path) or (len(audio) / 16000 if audio is not None else None)
            m["duration"] = dur
            add("Recording", f"{fmt_dur(dur)} long", "sure")
            if M.ready("speech"):
                transcript = M.transcribe(audio, known)
                add("I heard", f"“{excerpt(transcript, 220)}”" if transcript else "No clear speech", "sure" if transcript else "unclear")
                logs.append("listen")
            else:
                add("I heard", "The speech model is still loading.", "unclear")

        elif kind == "doc":
            doc_text = read_document(path)
            if doc_text.strip():
                add("I read", f"“{excerpt(doc_text, 220)}”", "sure")
                logs.append("read")
            else:
                add("I read", "No text could be taken from this file (it may be a scanned image).", "unclear")
    except Exception as e:
        log.exception("analysis failed for %s", path)
        add("Problem", f"Could not analyze this file: {type(e).__name__}", "unclear")

    if scene:
        for label, key in (("Event", "Event"), ("Setting", "Setting"), ("Main person", "Main person"), ("Others in it", "Others"), ("Objects", "Objects"), ("Mood", "Mood")):
            if scene.get(key):
                add(label, scene[key], "guess")
    scene_text = "\n".join(f"{k}: {v}" for k, v in scene.items() if v)
    content = "\n".join(x for x in (description, scene_text, shown_text, transcript, doc_text) if x)
    people = list(m.get("people") or [])
    summary = ""
    if content and M.ready("vision_slm"):
        try:
            f = M.extract_facts(m["title"], content, owner)
            # names read from writing are reliable; names heard in speech or guessed from a picture are not
            written = (shown_text + " " + doc_text).lower()
            sure_names = [n for n in f["names"] if n.lower() in written]
            # names that were neither written nor spoken came from the picture description: drop them
            heard = [n for n in f["names"] if n not in sure_names and n.lower() in transcript.lower()]
            for n in sure_names + [n for n in heard if n in known]:
                if n not in people:
                    people.append(n)
            m["heard_names"] = [n for n in heard if n not in known and n != owner]
            if sure_names:
                add("Names", ", ".join(sure_names), "sure")
            if heard:
                add("Names I heard", ", ".join(heard), "guess")
            # real places come from writing or speech, not from the picture description
            said = (shown_text + " " + transcript + " " + doc_text).lower()
            places = [x for x in f["places"] if x.lower() in said]
            if places:
                add("Places", ", ".join(places), "sure")
            if f["year"] and not m.get("date_sure"):
                m["year"], m["date_sure"] = f["year"], True
                add("Year mentioned", str(f["year"]), "sure")
            summary = f["summary"]
        except Exception:
            log.exception("fact extraction failed")
    if not people and kind in ("photo", "video", "voice"):
        add("Who", "I can't tell who this is yet", "unclear")
    if decade and not m.get("date_sure"):
        m["decade_guess"] = decade
        add("Looks like", f"the {decade}s", "guess")

    m.update(people=people, observations=obs, description=description, transcript=transcript,
             shown_text=shown_text, doc_text=doc_text, log=logs)
    m["text"] = excerpt(transcript or shown_text or doc_text or description or m.get("text", ""), 600)
    m["scene"] = scene
    m["main_person"] = scene.get("Main person", "")
    if needs_name(m["title"]) and content and M.ready("vision_slm"):
        try:
            info = "\n".join(x for x in (f"Type: {KIND_WORD.get(kind, 'item')}", scene_text, f"Writing: {shown_text}" if shown_text else "",
                                          f"Said: {excerpt(transcript, 600)}" if transcript else "", f"Text: {excerpt(doc_text, 600)}" if doc_text else "",
                                          f"Names: {', '.join(people)}" if people else "", f"Year: {m['year']}" if m.get("year") else "", f"Summary: {summary}" if summary else "") if x)
            new = M.make_title(info)
            if new and not needs_name(new):
                m["original_title"], m["title"] = m["title"], new
                obs.insert(0, {"label": "Named by the agent", "value": f"\u201c{new}\u201d (the file was called \u201c{m.get('filename') or m['original_title']}\u201d)", "confidence": "guess"})
                logs.append("named")
        except Exception:
            log.exception("naming failed")
    m["fact"] = summary or m.get("fact") or f"You added the {KIND_WORD.get(kind, 'item')} \u201c{m['title']}\u201d."
    m["embed_text"] = " ".join([m["title"], content, summary])
    reembed(m)
    # deeper reasoning: what happened, who, when, where, why it matters, links to earlier memories, open questions
    if content and M.ready("vision_slm"):
        try:
            near = sorted((o for o in MEM.values() if o["id"] != m["id"] and "vec" in o and "vec" in m), key=lambda o: -float(o["vec"] @ m["vec"]))[:3]
            near = [o for o in near if float(o["vec"] @ m["vec"]) > 0.25]
            m["analysis"] = M.analyze(owner, m["title"], KIND_WORD.get(kind, "item"), content + (f"\nSummary: {m['fact']}" if m.get("fact") else ""),
                                      [(o["title"], o.get("fact", "")) for o in near])
            an = m["analysis"]
            # never leave the notes blank: fall back to what is already known for certain
            if not an.get("What happened") and (m.get("fact") or description):
                an["What happened"] = m.get("fact") or description
            if not an.get("Who") and m.get("people"):
                an["Who"] = ", ".join(m["people"]) + " (named in the memory)"
            if not an.get("Who") and scene.get("Main person"):
                an["Who"] = "Probably: " + scene["Main person"]
            if not an.get("When") and m.get("year"):
                an["When"] = str(m["year"]) + (" (stated in the memory)" if m.get("date_sure") else " (estimated)")
            if not an.get("Where") and scene.get("Setting"):
                an["Where"] = "Probably: " + scene["Setting"]
            # links backed by evidence from the database: shared people, year, words, and vector similarity
            stop = {"the", "and", "with", "for", "that", "this", "was", "were", "her", "his", "their", "they", "you", "your", "from", "at", "in", "on", "of", "a", "to"}
            words = lambda x: {w for w in re.findall(r"[a-z]{4,}", (x.get("embed_text", "") + " " + x.get("title", "")).lower()) if w not in stop}
            links = []
            for o in near:
                why = []
                shared = sorted(set(m.get("people", [])) & set(o.get("people", [])))
                if shared:
                    why.append("both mention " + ", ".join(shared))
                if m.get("year") and m.get("year") == o.get("year"):
                    why.append(f"both from {m['year']}")
                common = sorted(words(m) & words(o), key=len, reverse=True)[:3]
                if common:
                    why.append("shared words: " + ", ".join(common))
                links.append(f"“{o['title']}” ({'; '.join(why) or 'similar content'}; similarity {float(o['vec'] @ m['vec']):.2f})")
            if links:
                an["Links"] = " | ".join(links) + ((" — " + an["Links"]) if an.get("Links") else "")
            gaps = []
            if not m.get("people") and kind in ("photo", "video", "voice"):
                gaps.append("who is in it" if kind != "voice" else "whose voice it is")
            gaps += [f"who “{n}” is" for n in m.get("heard_names", [])]
            if not m.get("date_sure"):
                gaps.append("when it happened")
            for p in m.get("people", []):
                gaps.append(f"how {p} is related to you")
            if gaps:
                an["Still unclear"] = "; ".join(dict.fromkeys(gaps))[:400]
            m["embed_text"] += " " + " ".join(v for v in an.values() if v)
            logs.append("analyzed")
            reembed(m)
        except Exception:
            log.exception("analysis failed")
    return m


@app.post("/memories")
async def add_memory(request: Request):
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        up = form.get("file")
        if up is None:
            raise HTTPException(400, "missing file")
        meta = json.loads(form.get("meta") or "{}")
        mid = safe_id(meta.get("id"))
        name = re.sub(r"[^\w.\- ]", "_", up.filename or "file")[-80:]
        path = UPLOADS / f"{mid}_{name}"
        with open(path, "wb") as out:
            shutil.copyfileobj(up.file, out)
        m = {"id": mid, "kind": meta.get("kind", "doc"), "title": meta.get("title") or name, "year": meta.get("year"),
             "date_sure": bool(meta.get("dateSure")), "file_year": meta.get("fileYear") or datetime.now().year,
             "people": meta.get("people") or [], "owner": meta.get("owner", "you"), "known": meta.get("known") or [], "thumb": meta.get("thumb"),
             "path": str(path), "filename": up.filename}
        m = await run_in_threadpool(analyze_file, m)
    else:
        b = await request.json()
        mid = safe_id(b.get("id"))
        m = {"id": mid, "kind": b.get("kind", "note"), "title": b.get("title", ""), "text": b.get("text", ""),
             "fact": b.get("fact", ""), "year": b.get("year"), "people": b.get("people") or [], "date_sure": True}
        m["embed_text"] = " ".join([m["title"], m["text"], m["fact"], " ".join(b.get("tags") or [])])
        try:
            await run_in_threadpool(reembed, m)
        except M.NotReady:
            pass
    MEM[mid] = m
    db.save(m)
    return public(m)


# ---------------------------------------------------------------- search
def ensure_vecs():
    """Memories added before the embedding model finished loading get their vectors now."""
    if M.ready("embedding"):
        for m in MEM.values():
            if "vec" not in m and m.get("embed_text"):
                reembed(m)


def _search(query, k=4, ids=None, min_score=0.2):
    ensure_vecs()
    pool =[m for m in MEM.values() if "vec" in m and (ids is None or m["id"] in ids)]
    if not pool:
        return []
    q = M.embed([query])[0]
    scores = np.stack([m["vec"] for m in pool]) @ q
    order = np.argsort(-scores)
    return [{"memoryId": pool[i]["id"], "score": float(scores[i])} for i in order[:k] if scores[i] >= min_score]


@app.post("/embed")
async def embed(b: dict):
    try:
        return {"vectors": (await run_in_threadpool(M.embed, b.get("texts") or [])).tolist()}
    except M.NotReady as e:
        raise HTTPException(503, str(e))


@app.post("/search")
async def search(b: dict):
    try:
        ids = set(b["memoryIds"]) if b.get("memoryIds") else None
        return {"hits": await run_in_threadpool(_search, b.get("query", ""), int(b.get("k", 4)), ids)}
    except M.NotReady as e:
        raise HTTPException(503, str(e))


# ---------------------------------------------------------------- agent questions
def questions_for(m, ids, people, owner):
    qs = []
    kw = KIND_WORD.get(m["kind"], "item")
    title = m["title"]
    import difflib
    known = [p for p in dict.fromkeys(people + [p for x in MEM.values() for p in x.get("people", [])]) if p != owner]
    for n in m.get("heard_names") or []:
        close = sorted(known, key=lambda k: -difflib.SequenceMatcher(None, n.lower(), k.lower()).ratio())[:2]
        qs.append({"id": f"s-name-{m['id']}-{safe_id(n)}", "prio": 0, "memoryIds": [m["id"]],
                   "basis": f"In this {kw} I heard a name that sounds like “{n}”, but speech is easy to mishear.",
                   "text": f"Who is “{n}”?",
                   "options": [{"label": p, "relationship": {"type": "identity", "from": f"p:{p}", "to": f"m:{m['id']}", "label": f"mentioned in this {kw}"},
                                "effect": {"person": p, "replace": n}} for p in close]
                              + [{"label": f"Keep \u201c{n}\u201d as written", "relationship": None, "effect": {"person": n, "replace": n}}]
                              + ([{"label": "Not a person's name", "relationship": None, "effect": {"drop": n}}] if len(close) < 2 else [])
                              + ([{"label": "Someone else\u2026", "custom": True, "relationship": None, "effect": {"replace": n}}] if len(close) < 1 else [])})
    if not m.get("people") and not m.get("heard_names") and m["kind"] in ("photo", "video", "voice"):
        voice = m["kind"] == "voice"
        pick = ([owner] + [p for p in people if p != owner])[:2]
        if voice and m.get("transcript"):
            basis = f"I heard someone say “{excerpt(m['transcript'], 90)}”, but I don't know whose voice it is."
        elif m.get("main_person"):
            ev = (m.get("scene") or {}).get("Event")
            basis = f"{'This looks like ' + ev[0].lower() + ev[1:].rstrip('.') + '. ' if ev else ''}The main person is {m['main_person'][0].lower() + m['main_person'][1:].rstrip('.')}. I don't know who they are."
        elif m.get("description"):
            basis = f"I see {m['description'][0].lower() + m['description'][1:]} But I can't tell who {'it is' if m['kind'] != 'voice' else 'is speaking'}."
        else:
            basis = f"I found no names in this {kw}, so I need your help."
        qs.append({"id": f"s-who-{m['id']}", "prio": 0, "memoryIds": [m["id"]], "basis": basis,
                   "text": f"Whose voice is in \u201c{title}\u201d?" if voice else (f"Who is the main person in \u201c{title}\u201d?" if m.get("main_person") else f"Who is in your {kw} \u201c{title}\u201d?"),
                   "options": [{"label": "Me" if p == owner else p,
                                "relationship": {"type": "identity", "from": f"p:{p}", "to": f"m:{m['id']}",
                                                 "label": "voice in recording" if voice else ("main person" if m.get("main_person") else f"in this {kw}")},
                                "effect": {"person": p}} for p in pick]
                              + ([{"label": "A group of people", "relationship": None, "effect": {}}] if len(pick) < 2 else [])
                              + [{"label": "Someone else\u2026", "custom": True, "relationship": None, "effect": {}}]})
    if not m.get("date_sure") and m["kind"] != "note":
        fy = int(m.get("file_year") or datetime.now().year)
        if m.get("decade_guess"):
            g = m["decade_guess"]
            opts = [(f"The {g}s", g + 5), (f"The {g - 10}s", g - 5), (f"Around {fy}", fy)]
            basis = f"From the way it looks, I'd guess the {g}s, but the file was saved in {fy}."
        elif m.get("year") and m["year"] != fy:
            y = m["year"]
            opts = [(str(y), y), (f"Around {fy}", fy), (f"Earlier, the {(y - 10) // 10 * 10}s", (y - 10) // 10 * 10 + 5)]
            basis = f"The file name says {y}, but it was saved on this computer in {fy}."
        else:
            d1 = (fy - 15) // 10 * 10
            opts = [(f"Around {fy}", fy), (f"The {d1}s", d1 + 5), (f"The {d1 - 20}s", d1 - 15)]
            basis = f"The file was saved in {fy}, but that is often when it was copied or scanned, not when it happened."
        qs.append({"id": f"s-when-{m['id']}", "prio": 1, "memoryIds": [m["id"]], "basis": basis,
                   "text": f"When is “{title}” from?",
                   "options": [{"label": l, "relationship": None, "effect": {"year": y, "label": l}} for l, y in opts]})
    if "vec" in m:
        others = [o for o in MEM.values() if o["id"] != m["id"] and o["id"] in ids and "vec" in o]
        near = sorted(others, key=lambda o: -float(o["vec"] @ m["vec"]))[:2]
        near = [o for o in near if float(o["vec"] @ m["vec"]) > 0.25]
        if near:
            opts = [{"label": f"Goes with “{o['title']}”", "effect": {},
                     "relationship": {"type": "same_story", "from": f"m:{m['id']}", "to": f"m:{o['id']}", "label": "same story"}} for o in near]
            if len(opts) < 2:
                opts.append({"label": "Related, but separate", "relationship": None, "effect": {}})
            opts.append({"label": "Its own story", "relationship": None, "effect": {}})
            qs.append({"id": f"s-story-{m['id']}", "prio": 2, "memoryIds": [m["id"], near[0]["id"]],
                       "basis": f"What I found in it is closest to “{near[0]['title']}”.",
                       "text": f"Which story does “{title}” belong to?", "options": opts})
    return qs


@app.post("/agent/run")
def agent_run(b: dict):
    ids = set(b.get("memoryIds") or MEM.keys())
    answered = set(b.get("answered") or [])
    owner = b.get("owner", "you")
    people = b.get("people") or []
    ensure_vecs()
    files = [m for m in MEM.values() if m["id"] in ids and "path" in m]
    qs = []
    for m in files:
        for q in questions_for(m, ids, people, owner):
            if q["id"] not in answered:
                QCACHE[q["id"]] = q
                qs.append(q)
    looked = sum("look" in (m.get("log") or []) for m in files)
    heard = sum("listen" in (m.get("log") or []) for m in files)
    read = sum("read" in (m.get("log") or []) for m in files)
    names = sorted({p for m in files for p in m.get("people", []) if p != owner})
    out_qs = [{k: v for k, v in q.items()} | {"options": [{k: v for k, v in o.items() if k != "effect"} for o in q["options"]]} for q in qs]
    return {"log": [
        {"skill": "Look at pictures (vision model)", "message": f"Described {looked} of your photos and videos." if looked else "No new pictures to look at."},
        {"skill": "Listen (speech model)", "message": f"Transcribed {heard} recordings or videos." if heard else "No new recordings."},
        {"skill": "Read documents", "message": f"Read {read} documents." if read else "No new documents."},
        {"skill": "Study each memory (language model)", "message": (lambda n: f"Wrote detailed notes on {n} memor{'ies' if n != 1 else 'y'}: what happened, who, when, where, why it matters, links and open questions." if n else "No new memories to study.")(sum("analyzed" in (m.get("log") or []) for m in files))},
        {"skill": "Name your files", "message": (lambda n: f"Gave {n} file{'s' if n != 1 else ''} a clear name from what is in them. Clear names were kept." if n else "Every file already had a clear name.")(sum("named" in (m.get("log") or []) for m in files))},
        {"skill": "Find people (language model)", "message": f"Found names in your files: {', '.join(names)}." if names else "Found no names in your files yet."},
    ], "questions": out_qs}


@app.post("/agent/answer")
def agent_answer(b: dict):
    q = QCACHE.get(b.get("questionId"))
    if not q:
        raise HTTPException(404, "unknown question; run the agent again")
    o = dict(q["options"][int(b.get("optionId"))])
    if o.get("custom"):
        name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:40]
        if not name:
            raise HTTPException(400, "a name is required")
        o["effect"] = {**(o.get("effect") or {}), "person": name}
        o["relationship"] = {"type": "identity", "from": f"p:{name}", "to": f"m:{q['memoryIds'][0]}",
                             "label": f"in this {KIND_WORD.get(MEM[q['memoryIds'][0]]['kind'], 'item')}"}
    m = MEM.get(q["memoryIds"][0])
    eff, upd = o.get("effect") or {}, {"memoryId": m["id"]} if m else None
    msg = f"Saved: {o['label']}."
    if m and "person" in eff:
        p = eff["person"]
        if eff.get("replace"):
            m["heard_names"] = [x for x in m.get("heard_names", []) if x != eff["replace"]]
            for key in ("text", "fact", "embed_text"):
                if m.get(key):
                    m[key] = re.sub(rf"\b{re.escape(eff['replace'])}\b", p, m[key], flags=re.I)
            upd["text"], upd["fact"] = m.get("text"), m.get("fact")
        if p not in m.setdefault("people", []):
            m["people"].append(p)
        upd.update(people=m["people"], observation=["Voice" if m["kind"] == "voice" else "Who", f"{'You' if o['label'] == 'Me' else p} (you told me)", "sure"])
        msg = f"{'Your voice is' if o['label'] == 'Me' else p + ' is'} in “{m['title']}”."
        reembed(m)
    if m and "drop" in eff:
        m["heard_names"] = [x for x in m.get("heard_names", []) if x != eff["drop"]]
        msg = f"\u201c{eff['drop']}\u201d is not a person's name."
    if m and "year" in eff:
        m["year"], m["date_sure"] = eff["year"], True
        upd.update(year=eff["year"], observation=["When", f"{eff['label']} (you told me)", "sure"])
        msg = f"“{m['title']}” is from {eff['label'].lower()}."
    if m and eff.get("replace"):
        msg = f"“{eff['replace']}” in “{m['title']}” is {p}." if p != eff["replace"] else f"Kept “{p}” as written."
    if o.get("relationship") and m and q["id"].startswith("s-story"):
        msg =f"“{m['title']}” {o['label'][0].lower() + o['label'][1:]}."
    QCACHE.pop(q["id"], None)
    if m:
        db.save(m)
    return {"relationships": [o["relationship"]] if o.get("relationship") else [], "message": msg, "updates": [upd] if upd else []}


# ---------------------------------------------------------------- database, saved state, personal search
@app.get("/state")
def get_state():
    keep = ("kind", "title", "thumb", "duration", "file_year", "date_sure", "filename")
    return {"memories": [public(m) | {k: m.get(k) for k in keep} | {"hasFile": "path" in m} for m in MEM.values()],
            "app": db.kv_get("app", {})}


@app.put("/state")
def put_state(b: dict):
    db.kv_set("app", b)
    return {"ok": True}


@app.get("/files/{mid}")
def get_file(mid: str):
    m = MEM.get(mid)
    if not m or "path" not in m or not Path(m["path"]).exists():
        raise HTTPException(404, "no file")
    return FileResponse(m["path"])


@app.get("/db")
def db_view():
    ensure_vecs()
    state = db.kv_get("app", {})
    return {"path": "server/data/legacy.db", "sizeKb": db.size_kb(), "count": len(MEM),
            "embedded": sum("vec" in m for m in MEM.values()),
            "dim": next((len(m["vec"]) for m in MEM.values() if "vec" in m), None), "model": M.NAMES["embedding"],
            "relationships": len(state.get("rels") or []),
            "rows": [{"id": m["id"], "kind": m.get("kind"), "title": m.get("title"), "people": m.get("people", []),
                      "year": m.get("year"), "text": excerpt(m.get("text", ""), 90),
                      "vector": [round(float(x), 3) for x in m["vec"][:5]] if "vec" in m else None}
                     for m in MEM.values()]}


@app.post("/similarity")
def similarity(b: dict):
    """Cosine similarity between memories; the agent uses it to arrange the relationship map."""
    ensure_vecs()
    ids = b.get("ids") or []
    vecs = [MEM[i]["vec"] if i in MEM and "vec" in MEM[i] else None for i in ids]
    return {"matrix": [[0.0 if a is None or c is None else round(float(a @ c), 4) for c in vecs] for a in vecs]}


@app.post("/people")
def set_people(b: dict):
    """A person connected to a memory by hand on the map; search uses it right away."""
    m = MEM.get(b.get("memoryId"))
    if not m:
        raise HTTPException(404, "unknown memory")
    m["people"] = [str(p)[:40] for p in b.get("people") or []]
    reembed(m)
    db.save(m)
    return {"ok": True}


ROLE_WORDS = {"family member": ["family", "\u5bb6\u4eba"], "friend": ["\u670b\u53cb"], "classmate": ["\u540c\u5b66"]}


@app.post("/compare")
def compare(b: dict):
    """Same question, same database: vector search alone vs. vector search plus the user's own answers."""
    query, rels, k = b.get("query", ""), b.get("relationships") or [], int(b.get("k", 5))
    try:
        ensure_vecs()
        plain = _search(query, k=len(MEM) or 1, min_score=-1)
    except M.NotReady as e:
        raise HTTPException(503, str(e))
    low, boosted, used = query.lower(), set(), []
    for r in rels:
        if r.get("type") != "role":
            continue
        name, label = r["from"][2:], r.get("label", "")
        if label.lower() in low or any(w in low for w in ROLE_WORDS.get(label, [])) or name.lower() in low:
            boosted.add(name)
            used.append(f"{name} is your {label}")
    expanded = (query + " " + " ".join(sorted(boosted))).strip()
    links = {}
    for r in rels:
        if r.get("type") == "same_story":
            x, y = r["from"][2:], r["to"][2:]
            links.setdefault(x, set()).add(y)
            links.setdefault(y, set()).add(x)
    base = {h["memoryId"]: h["score"] for h in _search(expanded, k=len(MEM) or 1, min_score=-1)}
    scored, why = {}, {}
    for mid, sim in base.items():
        scored[mid], why[mid] = sim, []
        hit = boosted & set(MEM[mid].get("people", []))
        if hit:
            scored[mid] += 0.25
            why[mid].append("features " + ", ".join(sorted(hit)))
    if scored:
        top = max(scored, key=scored.get)
        for n in links.get(top, []):
            if n in scored:
                scored[n] += 0.15
                why[n].append(f"you linked it to \u201c{MEM[top]['title']}\u201d")
    row = lambda mid, score, w=(): {"memoryId": mid, "title": MEM[mid]["title"], "score": round(float(score), 3), "why": list(w)}
    return {"plain": [row(h["memoryId"], h["score"]) for h in plain[:k]],
            "personal": [row(mid, v, why[mid]) for mid, v in sorted(scored.items(), key=lambda x: -x[1])[:k]],
            "used": used}


@app.post("/transcribe")
async def transcribe_live(request: Request):
    """Live subtitles: transcribe the recording so far. Long talks send only the last 25 seconds to the model."""
    form = await request.form()
    up = form.get("file")
    if up is None:
        raise HTTPException(400, "missing file")
    if not M.ready("speech"):
        return {"text": "", "ready": False}
    tmp = UPLOADS / f"live_{uuid.uuid4().hex}.webm"
    with open(tmp, "wb") as out:
        shutil.copyfileobj(up.file, out)

    def run():
        audio = M.load_audio(tmp)
        if audio is None:
            return "", False
        cut = len(audio) > 16000 * 30
        known = sorted({p for x in MEM.values() for p in x.get("people", [])})
        return M.transcribe(audio[-16000 * 25:] if cut else audio, known), cut
    try:
        text, cut = await run_in_threadpool(run)
    except Exception:
        log.exception("live transcription failed")
        text, cut = "", False
    finally:
        tmp.unlink(missing_ok=True)
    return {"text": text, "partial": cut}


@app.post("/followup")
def followup(b: dict):
    """The agent's short spoken reply after someone finishes talking on page 1."""
    m = MEM.get(b.get("memoryId"))
    said = (m or {}).get("transcript") or (m or {}).get("doc_text")
    if not m or not said:
        return {"heard": False, "text": "I could not hear any words that time. Please press the button and try again."}
    if not M.ready("vision_slm"):
        return {"text": "Thank you. I saved that. Press the button whenever you want to tell me more."}
    unclear = (m.get("analysis") or {}).get("Still unclear", "")
    prompt = ("Someone just shared a personal memory with you. They said:\n"
              f"{excerpt(said, 1200)}\n\n" + (f"What is still unclear to you: {unclear}\n\n" if unclear else "") +
              "Reply in the same language they used, in at most 30 words: thank them warmly, then ask one simple question "
              "that helps them say more about this memory. Use only what they said. Do not call the speaker by any name, and do not invent names or facts.")
    return {"text": M.generate(prompt, max_new_tokens=80).strip().strip('"')}


# ---------------------------------------------------------------- answers and stories (RAG + SLM)
@app.post("/interact")
def interact(b: dict):
    if not M.ready("vision_slm"):
        raise HTTPException(503, "language model is not ready")
    owner = b.get("owner", "you")
    ms = [MEM[i] for i in (b.get("memoryIds") or []) if i in MEM]
    ctx = "\n".join(f"[{i + 1}] {m['title']}{' (' + str(m['year']) + ')' if m.get('year') else ''}: {m.get('fact', '')} "
                    f"Details: {excerpt(m.get('text', ''), 500)}" for i, m in enumerate(ms))
    reqs = "\n".join(f"- {r.get('kind')}: {r.get('text')}" for r in b.get("requirements") or []) or "- none"
    rels = "\n".join(f"- {s}" for s in b.get("relationships") or []) or "- none"
    rules = (f"You are Legacy Box, a gentle memory assistant for {owner}. Use ONLY the memories listed. "
             f"Never invent names, dates or events. Speak to {owner} as \"you\" unless a request says otherwise.\n"
             f"What {owner} told you about people:\n{rels}\n{owner}'s requests (follow them):\n{reqs}\n\nMemories:\n{ctx}\n\n")
    if b.get("mode") == "story":
        n = max(1, min(int(b.get("length") or 3), 8))
        prompt = rules + (f"Write a short story for {owner}'s family based on these memories, in {n} short paragraphs, "
                          f"in time order. Start with a line 'Title: <title>'. Then the paragraphs, separated by blank lines. "
                          f"Request from {owner}: {b.get('text', '')}")
        raw = M.generate(prompt, max_new_tokens=140 * n + 60)
        t = re.search(r"Title\s*:\s*(.+)", raw)
        title = t.group(1).strip().strip('"*') if t else (ms[0]["title"] if ms else "Your story")
        body = raw[t.end():] if t else raw
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n", body) if p.strip()]
        return {"story": {"title": title, "paragraphs": paras[: n + 2], "memoryIds": [m["id"] for m in ms]}}
    prompt = rules + (f"Question from {owner}: {b.get('text', '')}\n"
                      f"Answer in one to three plain sentences using only the memories. If they don't answer it, say you couldn't find it.")
    return {"answer": {"text": M.generate(prompt, max_new_tokens=160)}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("LEGACY_PORT", "8000")))
