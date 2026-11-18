# How to use Lore

A step-by-step guide for setting up and using Lore (milestone 2). Lore is a personal memory agent for older adults and their families. You talk to it, type, or drop in photos, recordings, videos and documents. An AI agent looks at everything, asks a few simple pick-one questions, and builds a map of who people are and which memories belong together.

Everything runs on your own computer. Your photos, voice and answers are never sent to the internet. The only download is the AI models, once.

---

## 1. Two ways to run Lore

| | Demo mode | Live mode (real AI) |
|---|---|---|
| How to open | Double-click `legacy-box-demo.html`, or open the Netlify link | Start the server, then open **http://127.0.0.1:8000** |
| Setup | None | About 30 minutes the first time (section 2) |
| AI | Simulated, with Rose's sample family | Real models on your computer: vision, speech and embeddings |
| Understands your own photos | No | Yes: reads writing, recognizes the event, names the file, asks about it |
| Good for | Showing the idea anywhere | Trying it with your own memories |

**How to tell which mode you're in:** live mode only works when the page comes from `http://127.0.0.1:8000` *and* the server window is open. If the server is closed, the page quietly falls back to demo mode and can no longer see your pictures.

---

## 2. Setup (first time only)

### What you need

- Windows 10 or 11 with PowerShell
- Python 3.11 ([python.org](https://www.python.org/downloads/))
- An NVIDIA GPU with about 8 GB of memory. It also runs without a GPU, but slowly.
- About 15 GB of free disk space
- Chrome or Edge, for talking to Lore with the microphone

### Steps

Open PowerShell and run these one at a time.

1. **Get the code.** Milestone 2 is in the group repository:

   ```powershell
   git clone -b feat/final-project-lore https://github.com/TINKPA/ee542-group6.git
   cd "ee542-group6\Final project - Lore\milestone-2"
   ```

   Or unzip `Lore.zip` and `cd` into the `Lore` folder.

2. **Create a Python environment:**

   ```powershell
   py -3.11 -m venv server\.venv
   ```

3. **Install PyTorch with GPU support:**

   ```powershell
   server\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
   ```

4. **Install the other packages:**

   ```powershell
   server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
   ```

---

## 3. Start Lore

From the same folder:

```powershell
server\.venv\Scripts\python.exe server\app.py
```

1. **Keep this window open** the whole time you use Lore. Closing it stops the AI.
2. Open **http://127.0.0.1:8000** in Chrome or Edge.
3. **The first start downloads about 6 GB of models** into your Hugging Face cache, so it can take 10–30 minutes. Later starts take under a minute and work without the internet.
4. Before adding files, go to **Open Lore → See how Lore is thinking** and wait until all three models show **Ready**. Files added while a model is still loading are only partly understood.

Optional settings, typed in the same PowerShell window before starting:

| Setting | What it does |
|---|---|
| `$env:LEGACY_OWNER = "Rose"` | The owner's name, used in questions and on the map (default "Me") |
| `$env:LEGACY_PORT = "8010"` | Use a different port |
| `$env:LEGACY_DATA = "D:\lore-data"` | Keep the database and uploaded files in another folder |

---

## 4. The first page: put memories in

The first page is deliberately almost empty: a small golden sound-wave icon, the words **Tap to talk**, and three small links.

### Talk

1. Tap the sound-wave icon. The first time, the browser asks to use the microphone: choose **Allow**.
2. The bars turn red and move: Lore is listening. Talk as long as you like (up to 10 minutes).
3. **Subtitles** at the bottom of the screen show what Lore hears while you talk.
4. Tap the icon again when you're done.
5. Lore saves the recording, writes out what you said, and **answers out loud** with a short follow-up question, for example about a name or place it wasn't sure of. Tap again to answer.

### Type

Tap **Type instead**, write a memory, and press **Enter**. Lore gives it a name from its content and replies the same way.

### Add photos, videos, recordings and documents

- **Drag files or whole folders anywhere on the page.** The page shows a dashed frame while you drag.
- Or tap **Add photos or files** to choose them.
- Supported: photos (JPG, PNG, HEIC), videos, audio (WAV, MP3, M4A, WebM), text files, PDF and Word `.docx`.

For each file, Lore:

- **Looks at it:** the vision model describes the event, setting, people, objects and mood, and what the picture **seems meant to show** (for example *"to celebrate Rose's 80th birthday"*).
- **Reads the writing** in pictures: cards, letters, the backs of photos.
- **Listens:** recordings and videos are turned into text.
- **Names it:** meaningless names like `IMG_20190704_183255.jpg` or `New Recording 3.wav` get a clear name from the content ("Happy 80th Birthday, Rose!"). Files that already have a clear name keep it, and the original name is always shown.
- **Saves it** in the memory database with a vector for search.

**Open Lore →** goes to the agent.

---

## 5. Questions: the agent asks, you tap

The agent shows **one question at a time**. Each card says what Lore understood and why it's asking. Tap one of three answers, or **Skip**. Nobody has to type.

Kinds of questions you'll see:

| About | Example |
|---|---|
| Who is in it | "Who is in your photo 'Happy 80th Birthday, Rose!'?" |
| Who someone is to you | "Who is Walter to you?" → husband / brother / father |
| A name it misheard | "Who is 'NNI'?" → Ann / Rose / Keep as written |
| What was happening | "Was this a birthday party? It looks like a birthday party to me, and it seems meant to celebrate Rose's 80th birthday. Am I right?" |
| When | "Is it really from 1998?" or "When in your life was it?" → when I was young / raising a family / in recent years. Lore never offers the year the file was copied. |
| The story behind it | "Why is this one special to you?", "Who took this picture?", "Who would you like to hear this story one day?", "How do you feel when you remember this?", "Who wrote this?" |
| Which story it belongs to | "Which story does it belong to?" → goes with "fair note" / its own story |

If the right person isn't listed, choose **Someone else…** and type the name.

**Every answer is remembered.** It becomes a link on the map, is added to the memory's notes ("From you"), and makes search and stories more personal.

### See how Lore is thinking

At the bottom of the page, this opens:

- **Lore's notes on each memory:** what happened, who (with evidence), when, where, why it matters, links to other memories (shared people, year, words, similarity) and what is still unclear.
- **Agent skills:** what each model did in the last run.
- **Models:** each model's status (Loading / Ready).
- **Memory database:** every memory with its vector.
- **Search comparison:** the same search with vectors only, and with vectors plus your answers. Try answering "Who is X to you?" first, then search `my friend`.

---

## 6. People & stories: make it personal

### The relationship map

The map shows only what you told Lore: people, memories, themes, and the links between them.

- **Move:** drag a node. Connected nodes follow. Drag the background to move around.
- **Connect:** hover over or click a node to show its **+**, drag the **+** onto another node, then pick what the link means.
- **Remove a link:** click the line.
- **Add:** **Add person** or **Add theme**.
- **Arrange for me:** the agent groups memories by your answers and their content. **Tidy columns** gives a plain layout.

### Talk to the agent

Type in the box under the map.

- **Ask a question:** `Where did we spend our summers?` The answer lists the saved memories it came from, so you can always check the original.
- **Ask for something:** `Write the lake stories for my grandkids in simple words`. If something is unclear, Lore asks a pick-one question (for example the children's age) instead of making you type more.
- **Set a lasting request:** `Call Walter Grandpa` or `Keep the letter from camp private`. It applies to every answer after that.

AI-written text is clearly marked, separate from the real memories.

Everything you add, answer and arrange is saved and still there after a restart.

---

## 7. Stop, start over, or remove your data

- **Stop:** close the server window, or press `Ctrl+C` in it.
- **Your data** is in `server/data/` (`legacy.db` and `uploads/`). It is never uploaded to GitHub.
- **Start over:** stop the server, then delete `server/data/legacy.db`. To also remove the copies of your files, delete what's in `server/data/uploads/`.

---

## 8. Optional: the bigger vision model

A 7B vision model (Qwen2-VL-7B, compressed to 4-bit) can be switched on, but **we don't recommend it on an 8 GB laptop GPU**. In our test it was 6–10 times slower and read less writing in pictures than the default 2B model. It's worth trying on a GPU with 12 GB or more. Download steps and settings are in `server/README.md` under "Bigger vision model". The model files are not in this repository.

---

## 9. Troubleshooting

| Problem | What to do |
|---|---|
| The page shows Rose's sample family and doesn't understand my photos | It's in demo mode. Start the server and open **http://127.0.0.1:8000** (not the file or the Netlify link). |
| The page won't open | Check that the server window is still open, then start it again. |
| "I can't hear you yet" | Allow the microphone in the browser (the icon at the left of the address bar), then tap again. Use Chrome or Edge. |
| A model shows **Not available** | Read the error in the server window. Usually a failed download or not enough GPU memory. Close programs that use the GPU (video editors, games) and restart. |
| The first start hangs on downloading | huggingface.co may be blocked on your network. Try another network or a VPN, then restart. |
| A file was only partly understood | The models were still loading. Wait for **Ready**, then add it again. |
| Everything is very slow | Check that the GPU is used: under **See how Lore is thinking**, the Models panel should say "Running on CUDA". Close other GPU-heavy programs. |

## 10. Known limits

- An early MVP, tested with generated photos, recordings and documents, not yet with real family material.
- The vision model can describe pictures wrongly, and story drafts can include details that aren't in the memories. Check them against the saved records shown with each answer.
- Speech recognition can mishear names; the agent asks when it isn't sure.
- Scanned PDFs without a text layer can't be read yet.
