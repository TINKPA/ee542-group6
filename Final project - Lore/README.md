# Lore

Lore turns a family's photos, recordings, videos and writing into a memory collection you can search and personalize. An AI agent organizes the material and asks simple pick-one questions. Your answers build a map of who people are and which memories belong together.

**Live demo: [createurownlore.netlify.app](https://createurownlore.netlify.app/)**

The live demo is the web page on its own, so it runs in demo mode with sample data and simulated AI. To use the real models on your own files, set up the local server below.

This is an MVP. Everything runs on your own computer, and your files are not sent to the internet. The only download is the AI models, once, the first time you start it.

## What you need

- Windows with PowerShell (the commands below are for Windows)
- Python 3.11
- An NVIDIA GPU with about 8 GB of memory (it also runs without one, but slowly)
- About 15 GB of free disk space for the Python packages and models

## Setup (first time only)

Run these in PowerShell.

1. Download the code:

   ```powershell
   git clone https://github.com/TINKPA/ee542-group6.git
   cd "ee542-group6/Final project - Lore"
   ```

2. Create a Python environment:

   ```powershell
   py -3.11 -m venv server\.venv
   ```

3. Install PyTorch:

   ```powershell
   server\.venv\Scripts\python.exe -m pip install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124
   ```

4. Install the other packages:

   ```powershell
   server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
   ```

## Start Lore

From the `Final project - Lore` folder:

```powershell
server\.venv\Scripts\python.exe server\app.py
```

Keep this window open while you use Lore. Then open **http://127.0.0.1:8000** in your browser.

The first start downloads about 6 GB of models, so it takes a while. On page 2, wait until the **Models** panel shows every model as **Ready** before adding files. Files added earlier are only partly analyzed.

## How to use it

### Start page

The start page has only two things: the **Lore** button and one input box.

- Type a memory and press **Enter**.
- Or press the microphone, talk, and press it again when you finish. Subtitles at the bottom show what Lore hears.
- Lore saves it and replies with a short question to help you tell more.
- Press **Lore** to go to the questions and the map. Press **Lore** at the top of those pages to come back.

You can still add other material:

- Drag files or a whole folder anywhere on the page (up to 30 files at a time).
- Or click the paperclip in the input box to choose files.
- Supported: photos, videos, audio, text files, PDF and Word `.docx` files.

Lore transcribes speech, reads writing in pictures, and describes each photo and video in detail: the event, the setting, the main person and the others in it. It finds names, places and years, and writes a few specific sentences about each memory.

Files with meaningless names, such as `IMG_20190704_183255.jpg` or `WhatsApp Image…`, get a short, simple name from what is in them, such as "Grandma's 80th birthday". Files that already have a clear name keep it, and the original file name is always shown.

### Questions

- Answer the agent's questions. Each card shows what the agent understood and why it is asking. Tap one answer, or **Skip**. If the person isn't listed, choose **Someone else…** and type the name.
- **See how Lore is thinking** opens Lore's detailed notes on each memory (what happened, who, when, where, why it matters, links and open questions), the agent skills, and the memory database with each memory's vector.
- The search box compares two results for the same question: vector search alone, and vector search plus your answers. To see the difference, first answer "Who is X to you?", then search for something like `my friend`.

### People & stories

**Relationship map**

- Drag a node to move it. Drag the background to move around the map.
- Hover over a node, or click it, to show its **+**. Drag the **+** onto another node to connect them, then choose what the link means.
- Click a line to see or remove it.
- Use **Add person** or **Add theme** for new nodes.
- **Arrange for me** lets the agent group memories by your answers and their content. **Tidy columns** gives a plain layout.

**Talk to the agent**

- Ask a question, such as `Where did we go in the summer?`. The answer shows the saved memories it came from.
- Make a request, such as `Write a short story about the lake for my family`, `Call Walter Grandpa`, or `Keep the letter from camp private`.

Everything you add, answer and arrange is saved and is still there after a restart.

## Start over or remove your data

Your data is in `server/data/`, which is never uploaded to GitHub.

- To clear the memories, close the server and delete `server/data/legacy.db`.
- To remove the copies of your files, also delete what is in `server/data/uploads/`.

## Troubleshooting

| Problem | What to do |
|---|---|
| The page won't open | Make sure the server window is still open, then start it again. |
| A model shows **Not available** | Check the error in the server window. It is usually a failed download or not enough GPU memory. Close other programs that use the GPU and restart. |
| A file was only partly understood | The models were still loading. Wait for **Ready**, then add the file again. |

## Known limits

- This is an early MVP and has only been tested lightly.
- The small AI model can describe pictures wrongly, and story drafts can include details that aren't in the memories. Check them against the saved records shown with each answer.
- Speech recognition can mishear names. The agent asks when it isn't sure.
- Scanned PDFs with no text layer can't be read yet.

## For developers

- `legacy-box-demo.html`: the whole web page
- `server/app.py`: the API and the agent's questions
- `server/models.py`: speech, vision, language and embedding models
- `server/db.py`: the SQLite embedding database
- `server/README.md`: model details and how to swap models
- `Legacy_Box_UI_UX_Requirements.md`: product requirements and the API contract

To open the page without the server, double-click `legacy-box-demo.html`. It runs a demo with sample data and simulated AI.
