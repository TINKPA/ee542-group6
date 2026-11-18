"""Model loading and media analysis for the Legacy Box local server.

Models (all optional; the server reports which are ready on /health):
  - embedding : sentence-transformers multilingual MiniLM  (search, "goes with" questions)
  - speech    : Whisper small via transformers              (audio + video transcripts)
  - vision_slm: Qwen2-VL-2B-Instruct                        (photo/frame description, text in images,
                                                             fact extraction, answers and stories)
Swap any of them with the LEGACY_EMB / LEGACY_ASR / LEGACY_VLM environment variables.
"""
import json
import logging
import os
import re
import threading

import numpy as np
from PIL import Image, ImageOps

log = logging.getLogger("legacy.models")

EMB_NAME = os.getenv("LEGACY_EMB", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
ASR_NAME = os.getenv("LEGACY_ASR", "openai/whisper-small")
VLM_NAME = os.getenv("LEGACY_VLM", "Qwen/Qwen2-VL-2B-Instruct")
# bigger, smarter vision model (free, runs locally); used instead of the 2B one when downloaded
BIG_VLM = os.getenv("LEGACY_BIG_VLM_PATH",
                    os.path.join(os.path.expanduser("~"), ".cache", "lore-models", "Qwen2-VL-7B-Instruct-bnb-4bit"))

def _cached(name):
    home = os.getenv("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    return os.path.isdir(os.path.join(os.getenv("HF_HUB_CACHE") or os.path.join(home, "hub"), "models--" + name.replace("/", "--")))


# Once every model is downloaded, load from the local copy only: no internet needed, no hang when offline.
if all(_cached(n) for n in (EMB_NAME, ASR_NAME, VLM_NAME)) and not os.getenv("LEGACY_ALLOW_DOWNLOAD"):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

STATUS = {"embedding": "waiting", "speech": "waiting", "vision_slm": "waiting"}
NAMES = {"embedding": EMB_NAME, "speech": ASR_NAME, "vision_slm": VLM_NAME}

_gpu = threading.Lock()
_emb = _asr = _vlm = _proc = None


class NotReady(RuntimeError):
    pass


def device():
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "unavailable (PyTorch not installed)"


def ready(key):
    return STATUS.get(key) == "ready"


# ---------------------------------------------------------------- loading
def _small_on_cpu():
    """The 7B model needs almost the whole 8 GB GPU, so Whisper and MiniLM move to the CPU."""
    v = os.getenv("LEGACY_SMALL_ON_CPU", "auto").lower()
    return v in ("1", "yes", "on") or (v == "auto" and not os.getenv("LEGACY_SKIP_VISION_SLM") and _big_ready())


def _load_emb():
    global _emb
    from sentence_transformers import SentenceTransformer
    _emb = SentenceTransformer(EMB_NAME, device="cpu" if _small_on_cpu() else device())


def _load_asr():
    global _asr
    import torch
    from transformers import pipeline
    cuda = torch.cuda.is_available() and not _small_on_cpu()
    _asr = pipeline("automatic-speech-recognition", model=ASR_NAME,
                    torch_dtype=torch.float16 if cuda else torch.float32,
                    device="cuda:0" if cuda else "cpu")


def _big_ready():
    """Opt-in (LEGACY_BIG_VLM=on): the 7B model, if its folder is complete. Off by default: on an 8 GB
    laptop GPU the 4-bit 7B was 6-10x slower than the 2B and read less writing in pictures (tested 2026-11-14)."""
    if os.getenv("LEGACY_BIG_VLM", "").lower() not in ("1", "on", "yes"):
        return False
    try:
        idx = os.path.join(BIG_VLM, "model.safetensors.index.json")
        if os.path.isfile(idx):
            with open(idx, encoding="utf-8") as f:
                shards = set(json.load(f)["weight_map"].values())
        else:
            shards = {"model.safetensors"}
        return all(os.path.isfile(os.path.join(BIG_VLM, s)) for s in shards) and \
            os.path.isfile(os.path.join(BIG_VLM, "config.json"))
    except Exception:
        return False


def _load_vlm():
    global _vlm, _proc
    import torch
    from transformers import AutoProcessor, Qwen2VLForConditionalGeneration
    cuda = torch.cuda.is_available()
    if cuda and _big_ready():
        # 7B squeezed to 4-bit so it fits next to Whisper and MiniLM on an 8 GB GPU
        try:
            with open(os.path.join(BIG_VLM, "config.json"), encoding="utf-8") as f:
                prequant = "quantization_config" in json.load(f)
            kw = {}
            if not prequant:  # full-size copy: compress while loading
                from transformers import BitsAndBytesConfig
                kw["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16)
            _vlm = Qwen2VLForConditionalGeneration.from_pretrained(
                BIG_VLM, torch_dtype=torch.float16, device_map="cuda", **kw)
            _proc = AutoProcessor.from_pretrained(BIG_VLM, min_pixels=128 * 28 * 28, max_pixels=512 * 28 * 28)
            NAMES["vision_slm"] = "Qwen/Qwen2-VL-7B-Instruct (4-bit)"
            log.info("vision model: 7B 4-bit, GPU memory %.1f GB", torch.cuda.memory_allocated() / 1e9)
            return
        except Exception as e:
            log.warning("7B model did not load (%s); using the 2B model", e)
            _vlm = _proc = None
            import gc
            gc.collect()
            torch.cuda.empty_cache()
    _vlm = Qwen2VLForConditionalGeneration.from_pretrained(
        VLM_NAME, torch_dtype=torch.float16 if cuda else torch.float32,
        device_map="cuda" if cuda else "cpu")
    # cap image tokens so an 8 GB GPU is enough
    _proc = AutoProcessor.from_pretrained(VLM_NAME, min_pixels=128 * 28 * 28, max_pixels=640 * 28 * 28)


def load_all():
    for key, fn in (("embedding", _load_emb), ("speech", _load_asr), ("vision_slm", _load_vlm)):
        if os.getenv(f"LEGACY_SKIP_{key.upper()}"):
            STATUS[key] = "off"
            continue
        STATUS[key] = "loading"
        try:
            fn()
            STATUS[key] = "ready"
            log.info("%s ready (%s)", key, NAMES[key])
        except Exception as e:  # keep the server usable without this model
            log.exception("could not load %s", key)
            STATUS[key] = f"error: {type(e).__name__}: {str(e)[:200]}"


# ---------------------------------------------------------------- embedding
def embed(texts):
    if not ready("embedding"):
        raise NotReady("embedding model is not ready")
    with _gpu:
        v = _emb.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True)
    return v.astype(np.float32)


# ---------------------------------------------------------------- speech
def load_audio(path, sr=16000, max_seconds=600):
    """Decode any audio/video file to mono float32 at 16 kHz with PyAV (no ffmpeg install needed)."""
    import av
    with av.open(str(path)) as c:
        if not c.streams.audio:
            return None
        res = av.AudioResampler(format="s16", layout="mono", rate=sr)
        chunks, n = [], 0
        try:
            for frame in c.decode(c.streams.audio[0]):
                for f in res.resample(frame):
                    a = f.to_ndarray().reshape(-1)
                    chunks.append(a)
                    n += len(a)
                if n > sr * max_seconds:
                    break
            for f in res.resample(None) or []:
                chunks.append(f.to_ndarray().reshape(-1))
        except Exception:
            # a recording that is still in progress ends mid-frame; keep what decoded
            if not chunks:
                raise
    if not chunks:
        return None
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def media_duration(path):
    import av
    try:
        with av.open(str(path)) as c:
            return float(c.duration / av.time_base) if c.duration else None
    except Exception:
        return None


def transcribe(audio, hint_names=()):
    """hint_names: people already in the box; Whisper spells them correctly more often when primed."""
    if not ready("speech"):
        raise NotReady("speech model is not ready")
    if audio is None or len(audio) < 1600:
        return ""
    with _gpu:
        if hint_names:
            try:
                ids = _asr.tokenizer.get_prompt_ids("People: " + ", ".join(hint_names) + ".", return_tensors="pt").to(_asr.device)
                out = _asr({"raw": audio, "sampling_rate": 16000}, chunk_length_s=30, batch_size=8, generate_kwargs={"prompt_ids": ids})
                text = (out.get("text") or "").strip()
                # drop the echoed prompt if the model returns it
                text = re.sub(r"\s*People:[^.]*\.\s*", " ", text).strip()
                if text:
                    return text
            except Exception:
                log.exception("prompted transcription failed; retrying without names")
        out = _asr({"raw": audio, "sampling_rate": 16000}, chunk_length_s=30, batch_size=8)
    return (out.get("text") or "").strip()


# ---------------------------------------------------------------- vision + SLM
def video_frame(path):
    import av
    with av.open(str(path)) as c:
        if not c.streams.video:
            return None
        vs = c.streams.video[0]
        dur = float(c.duration / av.time_base) if c.duration else 3.0
        try:
            c.seek(int((dur / 3) / float(vs.time_base)), stream=vs)
        except Exception:
            pass
        for frame in c.decode(vs):
            return frame.to_image()
    return None


def open_image(path):
    try:
        import pillow_heif  # noqa: F401  (HEIC photos from phones)
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    img = Image.open(path)
    exif_date = None
    try:
        ex = img.getexif()
        exif_date = ex.get_ifd(0x8769).get(36867) or ex.get(306)
    except Exception:
        pass
    img = ImageOps.exif_transpose(img).convert("RGB")
    return img, exif_date


def generate(prompt, image=None, max_new_tokens=320):
    if not ready("vision_slm"):
        raise NotReady("vision / language model is not ready")
    content = ([{"type": "image"}] if image is not None else []) + [{"type": "text", "text": prompt}]
    text = _proc.apply_chat_template([{"role": "user", "content": content}], tokenize=False, add_generation_prompt=True)
    kw = {"text": [text], "return_tensors": "pt"}
    if image is not None:
        kw["images"] = [image]
    with _gpu:
        inputs = _proc(**kw).to(_vlm.device)
        out = _vlm.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False, repetition_penalty=1.05)
        out = out[:, inputs["input_ids"].shape[1]:]
        return _proc.batch_decode(out, skip_special_tokens=True)[0].strip()


DESCRIBE = (
    "This picture comes from a family's personal memory collection. Look carefully and answer in exactly this format, one line each:\n"
    "Event: <what is happening, such as a birthday party, wedding, holiday dinner, graduation, trip, everyday moment>\n"
    "Setting: <where it is: indoors or outdoors and what kind of place>\n"
    "People: <number of people visible>\n"
    "Main person: <the person this picture is mostly about: where they are in the picture, age group, clothing, what they are doing. None if no people>\n"
    "Others: <the other people, each described briefly by position, age group and action, separated by semicolons. None if no one else>\n"
    "Objects: <important objects, such as a cake, car, flowers, a sign>\n"
    "Mood: <one or two words>\n"
    "Purpose: <in one sentence, what this picture seems meant to show or help remember>\n"
    "Decade: <best guess of the decade it was taken, such as 1980s, or Unknown>\n"
    "Description: <two plain sentences describing the scene. Do not invent names.>"
)
OCR = "Read all the writing in this image. Reply with only the exact text, line by line. If there is no writing, reply NONE."
NO_TEXT = re.compile(r"^\W*(none|no (visible |readable )?(text|writing)|there is no (visible )?(text|writing)).*$", re.I | re.S)


def read_text_in_image(img):
    t = generate(OCR, image=img, max_new_tokens=160).strip().strip('"')
    if re.fullmatch(r"[\s\d(),.\-<>/a-z_]*\d[\s\d(),.\-<>/a-z_]*", t) and not re.search(r"[A-Za-z]{3,}", t):
        return ""   # box coordinates, not writing
    return "" if not t or NO_TEXT.match(t) else t


SCENE_FIELDS = ("Event", "Setting", "People", "Main person", "Others", "Objects", "Mood", "Purpose", "Decade", "Description")


def _field(raw, name):
    names = "|".join(re.escape(n) for n in SCENE_FIELDS)
    m = re.search(rf"{re.escape(name)}\s*:\s*(.+?)(?=[\n;]\s*(?:{names})\s*:|\Z)", raw, re.S | re.I)
    v = m.group(1).strip().strip(";").strip("<>").strip() if m else ""
    return "" if re.fullmatch(r"(none|n/?a|unknown|no one( else)?( visible)?|nobody|no (important |notable )?objects?|-)?\.?", v, re.I) else v


def describe_image(img):
    text = read_text_in_image(img)
    raw = generate(DESCRIBE, image=img, max_new_tokens=360)
    decade = re.search(r"(19[0-9]0|20[0-2]0)s", _field(raw, "Decade"))
    people = re.search(r"\d+", _field(raw, "People"))
    scene = {k: _field(raw, k) for k in ("Event", "Setting", "Main person", "Others", "Objects", "Mood", "Purpose")}
    # small vision models tend to invent people; a plain yes/no question is more reliable
    has_people = generate("Is there at least one real person visible in this picture? Answer only yes or no.", image=img, max_new_tokens=3).lower().startswith("y")
    if not has_people:
        scene["Main person"] = scene["Others"] = ""
        scene["Objects"] = ", ".join(o for o in re.split(r",\s*", scene.get("Objects", "")) if not re.search(r"people|person|family|members|guests|children|man|woman", o, re.I))
        people = None
    desc = _field(raw, "Description")
    if not desc or ":" in desc[:30]:
        desc = ". ".join(x.rstrip(".") for x in (scene.get("Event"), scene.get("Setting"), scene.get("Main person")) if x) + "."
    return {"description": desc, "text": text, "has_people": has_people,
            "decade": int(decade.group(1)) if decade else None,
            "people_count": (int(people.group()) if people else None) if has_people else 0, "scene": scene}


TITLE = (
    "Give this item from a family memory collection a short, simple title of 2 to 6 words, "
    "like 'Grandma's 80th birthday' or 'Fishing at the lake'. Use the same language as the content. "
    "Use a person's name only if it is listed under Names; never use other names from what was said. Reply with the title only.\n\n{info}"
)


def make_title(info):
    t = generate(TITLE.format(info=info[:1500]), max_new_tokens=24).strip().splitlines()[0]
    t = re.sub(r"^(title\s*:\s*)", "", t, flags=re.I).strip(" \"'*.#")
    return t[:60]


ASK = (
    "You are Lore, helping an older adult keep the story behind a family memory. Read what you know about this item. "
    "Write 2 short, warm questions that only the family can answer and that would make this memory richer. "
    "Good topics: the occasion, who took the picture, why it was kept, the place, how they felt, what happened next. "
    "Never ask for a year or a date. Never ask about something listed under Already known. "
    "Each question has exactly 3 likely answers of 1 to 4 words each, all different. "
    'Reply with JSON only, no other words: [{{"question": "...", "why": "one sentence about what you noticed", '
    '"topic": "occasion or place or photographer or reason or feeling or next or other", "options": ["...", "...", "..."]}}]\n\n'
    "Item: {title} ({kind})\n{notes}\n\nAlready known: {known}"
)
TOPICS = {"occasion", "place", "photographer", "reason", "feeling", "next", "other"}


def smart_questions(title, kind, notes, known):
    """Questions the model writes from its own understanding of the item, each with 3 likely answers."""
    raw = generate(ASK.format(title=title, kind=kind, notes=notes[:2000], known=known or "nothing yet"), max_new_tokens=360)
    start = raw.find("[")
    items = []
    if start >= 0:
        body = raw[start:raw.rfind("]") + 1] if "]" in raw[start:] else raw[start:]
        for tail in ("", "]", "}]", '"]}]', '"}]'):
            try:
                items = json.loads(body + tail)
                break
            except Exception:
                continue
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question", "")).strip()
        opts = [str(o).strip().strip(".") for o in it.get("options") or [] if str(o).strip()]
        opts = list(dict.fromkeys(opts))
        if not q.endswith("?") or len(q) > 120 or len(opts) != 3 or any(len(o) > 40 for o in opts):
            continue
        if re.search(r"\b(year|date|when was|what time)\b", q, re.I):
            continue   # dates are handled by the life-stage question
        topic = str(it.get("topic", "other")).strip().lower()
        out.append({"question": q, "why": str(it.get("why", "")).strip()[:220], "topic": topic if topic in TOPICS else "other", "options": opts})
    return out[:2]


ANALYSIS_FIELDS = ("What happened", "Who", "When", "Where", "Why it matters", "Links", "Still unclear")
ANALYZE = (
    "You are Lore, an agent that organizes {owner}'s family memories. Study this new item carefully and write your analysis "
    "in exactly this format, one line each:\n"
    "What happened: <three or four specific sentences>\n"
    "Who: <each person: their name if it is known, otherwise how they look; and the evidence>\n"
    "When: <date or period and the evidence, or Unclear>\n"
    "Where: <place and the evidence, or Unclear>\n"
    "Why it matters: <why this might be meaningful to the family>\n"
    "Links: <which earlier memories below it relates to and why, or None>\n"
    "Still unclear: <the most important things only the family can tell you>\n"
    "Use only the evidence in the new item. Earlier memories are only for the Links line: never take people or facts from them. "
    "Say 'probably' for anything you are guessing. Do not invent names. Do not use bold, bullets or numbering.\n\n"
    "New item: {title} ({kind})\n{content}\n\nEarlier memories (for Links only):\n{earlier}"
)


def analyze(owner, title, kind, content, earlier):
    raw = generate(ANALYZE.format(owner=owner, title=title, kind=kind, content=content[:2500],
                                  earlier="\n".join(f"- {t}: {f}" for t, f in earlier) or "- none"), max_new_tokens=420)
    # tolerate markdown anyway: **bold labels**, bullets, numbering
    raw = re.sub(r"[*#_]+", "", raw)
    raw = re.sub(r"(?m)^\s*(?:[-•]|\d+[.)])\s*", "", raw)
    names = "|".join(re.escape(n) for n in ANALYSIS_FIELDS)
    out = {}
    for f in ANALYSIS_FIELDS:
        m = re.search(rf"{re.escape(f)}\s*:\s*(.+?)(?=[\n;]\s*(?:{names})\s*:|\Z)", raw, re.S | re.I)
        v = m.group(1).strip().strip("<>").strip() if m else ""
        out[f] = "" if re.fullmatch(r"(none|n/?a|unclear|unknown)?\.?", v, re.I) else v
    if not any(out.values()):
        log.warning("analysis reply could not be read: %r", raw[:300])
    return out


FACTS = (
    "Read this item from {owner}'s personal memory collection and reply with JSON only, no other words:\n"
    '{{"names": [first names of people mentioned], "year": four-digit year it happened or null, '
    '"places": [places mentioned], "summary": "two or three specific sentences, speaking to {owner} as you: what happened, who was there (describe people by appearance if their names are unknown), where and when"}}\n\n'
    "Title: {title}\nContent:\n{content}"
)


def extract_facts(title, content, owner):
    raw = generate(FACTS.format(owner=owner, title=title, content=content[:2500]), max_new_tokens=380)
    data = {}
    start = raw.find("{")
    if start >= 0:
        body = raw[start:raw.rfind("}") + 1] if "}" in raw[start:] else raw[start:]
        for tail in ("", "}", '"}', '"]}', "]}"):     # repair a reply that was cut off
            try:
                data = json.loads(body + tail)
                break
            except Exception:
                continue
    low = (title + " " + content).lower()
    def ok(s, words):
        s = s.strip() if isinstance(s, str) else ""
        return s and s.lower() not in ("i", "me", "we", "my", "you") and s.lower() in low and len(s.split()) <= words and (not s[0].isascii() or s[0].isupper())
    titles = r"^(grandpa|grandma|granddad|grandmother|grandfather|nana|papa|mama|aunt|auntie|uncle|cousin|mr|mrs|ms|miss|dr)\.?\s+"
    names = [re.sub(titles, "", n.strip(), flags=re.I) for n in data.get("names") or [] if ok(n, 2)]
    places = [p.strip() for p in data.get("places") or [] if ok(p, 4)]
    year = data.get("year")
    try:
        year = int(year) if year and str(int(year)) in low and 1900 <= int(year) <= 2035 else None
    except Exception:
        year = None
    summary = data.get("summary") if isinstance(data.get("summary"), str) else ""
    return {"names": list(dict.fromkeys(names))[:8], "places": places[:5], "year": year, "summary": summary.strip()}
