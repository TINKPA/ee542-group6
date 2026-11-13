# Legacy Box local server

Runs real models on your own computer so the prototype can understand your photos, videos, recordings and documents. Nothing is sent to the internet after the models are downloaded once.

| Job | Model | Size |
|---|---|---|
| Describe photos and video frames, read writing in pictures, pull names/years/places, write answers and stories | `Qwen/Qwen2-VL-2B-Instruct` | ~4.5 GB |
| Speech-to-text for audio and video (Chinese, English and more) | `openai/whisper-small` | ~1 GB |
| Embeddings for search and "which story" questions (multilingual) | `paraphrase-multilingual-MiniLM-L12-v2` | ~0.5 GB |

Tested on Windows 11, Python 3.11, RTX 4060 Laptop (8 GB). The three models together use about 6 GB of GPU memory. Without a GPU it still runs, but slowly.

## First-time setup (Windows, PowerShell, from the `Final project - Lore` folder)

```powershell
py -3.11 -m venv server\.venv
server\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
```

## Run

```powershell
server\.venv\Scripts\python.exe server\app.py
```

Then open **http://127.0.0.1:8000**. The page finds the server by itself. On page 2 the *Models* panel shows each model as *Loading…* and then *Ready*. The first start downloads the models (~6 GB) into your Hugging Face cache, so it takes a while. Later starts take under a minute.

Wait until all three models are ready before adding your own files. Files added while a model is still loading are only partly analyzed.

## How it fits the prototype

- The page calls the endpoints in `Legacy_Box_UI_UX_Requirements.md` §7: `/memories`, `/search`, `/agent/run`, `/agent/answer`, `/interact`, `/embed`, plus `/health`.
- Your files are saved in `server/data/uploads/`. Delete that folder to remove them.
- Rose's sample memories keep their scripted questions. Your own files get questions from the server, based on what the models found (who is in it, when it is from, which story it goes with).
- Page 3 answers and story drafts are written by the language model from the memories that the embedding search retrieves. Requests (audience, tone, naming, privacy) are passed to it.

## What to expect (measured on the RTX 4060)

- Photo: about 5 seconds. It describes the picture, reads the writing on it, and pulls out names, places and years.
- Recording or video: about 2–5 seconds for 15 seconds of audio. Names already in the box are given to Whisper as hints, so they are spelled right more often. Names heard in speech are marked as guesses, and the agent asks "Who is 'X'?" when it isn't sure.
- Answers on page 3: about 1 second.
- Known limits of the 2B model: picture descriptions can be vague or wrong ("two people" when there are none), and story drafts sometimes add details that aren't in the memories. A larger model (e.g. `Qwen/Qwen2-VL-7B-Instruct`, which needs more GPU memory or 4-bit loading) would do better.

## Swapping models

Set environment variables before starting:

```powershell
$env:LEGACY_VLM = "Qwen/Qwen2-VL-2B-Instruct"   # vision + language
$env:LEGACY_ASR = "openai/whisper-small"         # e.g. openai/whisper-medium for better accuracy
$env:LEGACY_EMB = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
$env:LEGACY_SKIP_VISION_SLM = "1"                # skip a model entirely
```
