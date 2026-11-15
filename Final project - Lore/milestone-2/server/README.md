# Legacy Box local server

Runs real models on your own computer so the prototype can understand your photos, videos, recordings and documents. Nothing is sent to the internet after the models are downloaded once.

| Job | Model | Size |
|---|---|---|
| Describe photos and video frames, read writing in pictures, pull names/years/places, write answers and stories | `Qwen/Qwen2-VL-7B-Instruct` in 4-bit if downloaded (see below), otherwise `Qwen/Qwen2-VL-2B-Instruct` | ~5.5 GB / ~4.5 GB |
| Speech-to-text for audio and video (Chinese, English and more) | `openai/whisper-small` | ~1 GB |
| Embeddings for search and "which story" questions (multilingual) | `paraphrase-multilingual-MiniLM-L12-v2` | ~0.5 GB |

Tested on Windows 11, Python 3.11, RTX 4060 Laptop (8 GB). The three models together use about 6 GB of GPU memory. Without a GPU it still runs, but slowly.

## First-time setup (Windows, PowerShell, from the `ee542` folder)

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
- Known limits of the 2B model: picture descriptions can be vague or wrong ("two people" when there are none), and story drafts sometimes add details that aren't in the memories. The bigger 7B model below does better.

## Bigger vision model (free, optional)

**Why Lore needs it.** The vision model is the agent's eyes: it is the tool Lore uses to recognize what is in a photo or video frame (people, place, event, objects, writing) and what the picture seems meant to show, such as *a birthday party to celebrate Rose's 80th*. Lore asks questions from that understanding (*"Was this a birthday party? Am I right?"*), so the better it sees, the smarter and fewer the questions, and the fewer the wrong guesses an older user has to correct. With the 2B model, descriptions were often vague or wrong (it invented people on a drawn cake), and its own questions were too poor to use. The 7B model is a big step up in recognition and reasoning and still costs nothing: no paid API, and photos never leave the family's computer, which matters for private family memories.

The 7B model understands pictures better and writes better notes and questions. It is free and runs on your own GPU, compressed to 4-bit so it fits in 8 GB next to Whisper and MiniLM. The server uses it automatically when its folder is complete; otherwise it uses the 2B model. If the 7B model fails to load, the server falls back to 2B by itself.

Download it once (5.5 GB, from ModelScope, which works where huggingface.co is blocked):

```powershell
server\.venv\Scripts\python.exe -m pip install bitsandbytes modelscope
server\.venv\Scripts\modelscope.exe download --model unsloth/Qwen2-VL-7B-Instruct-bnb-4bit --local_dir $HOME\.cache\lore-models\Qwen2-VL-7B-Instruct-bnb-4bit
```

- Other folder: set `$env:LEGACY_BIG_VLM_PATH`. A full-size copy also works; it is compressed while loading.
- Turn it off: `$env:LEGACY_BIG_VLM = "off"`.
- The *Models* panel on page 2 shows which one is running.

## Swapping models

Set environment variables before starting:

```powershell
$env:LEGACY_VLM = "Qwen/Qwen2-VL-2B-Instruct"   # vision + language (used when the 7B model is not downloaded)
$env:LEGACY_ASR = "openai/whisper-small"         # e.g. openai/whisper-medium for better accuracy
$env:LEGACY_EMB = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
$env:LEGACY_SKIP_VISION_SLM = "1"                # skip a model entirely
```
