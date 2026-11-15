# Lore development log

This log records how the Lore final-project prototype was built: what changed in each round, why, how it was tested, and what is still open. Newest entries are at the bottom.

Lore helps older adults and their families turn photos, recordings, videos and writing into a memory collection. An agent organizes the material and asks simple pick-one questions. The answers build a map of who people are and which memories belong together, and the family can ask for something more personal, such as a story for the grandchildren.

## 2026-11-02 · Proposal discussion with Prof. Cho

Feedback that shaped the work below:

- **Competitors and money.** Find companies that do part of this and are already making money. Legacy Box (they digitize a box of old media and send it back) is the closest. Lore adds what comes after digitizing.
- **Who buys it.** Older people often can't do the input themselves. Middle-aged children may buy it for their parents. Selling Lore as an add-on to a digitizing company may be easier than starting alone.
- **Technical progress.** Build on the RAG + LLM work from the labs, and add image processing, video processing and embeddings. Make input easy for family members and for company staff digitizing a box.
- **Timing.** Baby boomers born 1945–1965 will all be retired by about 2030, and they are the largest generation.

## 2026-11-05 · v1: first clickable prototype

- Turned the handwritten sketch (Capture → Ask/Connect → Q&A/RAG) into `Legacy_Box_UI_UX_Requirements.md` and a three-page clickable demo with sample data: Rose's memories.
- Simulated OCR, agent and keyword search in the page so the flow could be tried before any back end existed.

**Team clarifications applied the same day:**

- **Page 1** is the user's data input.
- **Page 2** is the agent: it does most of the work and asks **pick-one questions (3 options + Skip)**.
- **Page 3** is the personalization page. Relationships come **only from answers to the agent**, not from upload time.
- **Q&A** is where a user states specific requests (audience, tone, naming, privacy) or asks questions.

**Map and questions:**

- Replaced a messy force-directed relationship map with a fixed layout: people, then You, then story boxes.
- Every agent question now starts with **what the agent understood** from the item, with each point marked sure, guess or not sure, and one sentence on why it is asking.
- Added an adapter (`LegacyAPI`) and an endpoint contract so the mock could later be replaced by real models.

## 2026-11-06 · v2: real local models

- **Local server** (`server/`, FastAPI): runs on the user's own computer, and files never leave it.
- **Three models:**
  - `Qwen2-VL-2B-Instruct` describes photos and video frames, reads writing in pictures, pulls out names, years and places, and writes answers and stories.
  - `whisper-small` does speech-to-text for audio and video.
  - `paraphrase-multilingual-MiniLM-L12-v2` makes embeddings for search and "which story" questions.
- **Hardware:** all three run together in about 6.5 GB on an RTX 4060 Laptop GPU.
- **Fixes from testing:**
  - Whisper heard "Walter" as "water", so names already in the collection are now passed to Whisper as hints.
  - Names heard in speech are marked as guesses, and the agent asks "Who is X?" when unsure.
  - The image description and the reading of text in the image are now two separate model calls, because one combined call missed the text.
  - "Grandpa Walter" is merged with "Walter".
- **Page 3:** answers are written by the local model from memories found by embedding search.

## 2026-11-09 · v3: MVP for the second presentation

- **Smallest embedding database:** one SQLite file (`server/data/legacy.db`). Each memory's 384-number vector is stored as a BLOB, and search is exact cosine with NumPy. Answers, the map layout and requests are saved too, so everything survives a restart.
- **Own data only:** with the server running, the page starts empty, with no sample people, and uses only what the user adds.
- **Database view on page 2:** a table of what is stored, including each memory's vector.
- **"Vector search only" vs "vector search + your answers":** the same question run two ways against the same database. This shows the product idea: anyone can copy digitizing and vector search, but only the family knows who people are and which memories belong together.
- **Editable relationship map:**
  - Drag nodes, pan and zoom.
  - Drag a node's **+** onto another node to connect them, then choose what the link means.
  - Remove links and add people or themes.
  - **Arrange for me** groups memories using the user's answers plus embedding similarity (`/similarity`).
- **Motion on the map:**
  - Nodes burst out from You when the page opens and float gently.
  - Dots travel along the links.
  - Dragging a node pulls its neighbors like elastic.
  - Hovering highlights a node's links and fades the rest.
  - Turned off for users who choose reduced motion.
- **Colors:** went through several rounds. The final palette is warm and taken from old family prints and albums: brick red, amber and wine, with olive and lake teal as small accents. All text meets at least 7:1 contrast for older eyes, and color is never the only signal.
- **Renamed** the product on the page from "Legacy Box" to **Lore**, since Legacy Box is another company's name.
- **Bugs found and fixed:**
  - When served locally, all three pages showed at once.
  - Dragging moved a node about eight times too far.
  - Name hints did not work on recordings longer than 30 seconds.
  - The label halo smeared the letters inside map nodes.

## 2026-11-09 · v4: talking to Lore, naming files, deeper analysis

- **One-button input, later one input box:**
  - The start page has only a **Lore** button (it opens the app) and one input box.
  - Type and press Enter, or press the microphone, talk, and press it again.
  - Files can be dropped anywhere, including whole folders, or chosen with the paperclip.
- **Lore replies:** after each memory, the local model says a short thank-you out loud and asks one follow-up question based on what is still unclear.
- **Live subtitles:** while the user talks, the recording so far goes to `/transcribe` every 2.5 seconds, and the text appears at the bottom of the screen. The audio stays on the user's computer: we did not use the browser's built-in speech recognition, because Chrome sends that audio to Google.
- **Agent names files:**
  - Camera, phone and app names get a short name from their content, for example `IMG_20190704_183255.jpg` → "Rose's 80th Birthday Party" and `New Recording 3.wav` → "Ann's Cherry Pie at the State Fair". Names renamed this way include `IMG_…`, `DSC…`, `WhatsApp Image…`, `New Recording…`, hashes, mostly-digit names and `微信图片…`.
  - Clear names are kept, and the original file name is always shown.
- **Detailed reading of each picture or video frame:** event, setting, main person, other people, objects and mood. The agent then asks "Who is the main person in …?" instead of a generic question.
- **Agent notes on every memory:** what happened, who (with evidence), when, where, why it matters, links to earlier memories, and what is still unclear.
  - Links are backed by evidence from the database: shared people, same year, shared words, and vector similarity. For example: *"fair note": both mention Walter, both from 1972, shared words ribbon, cherry, Walter, similarity 0.84*.
  - "Still unclear" lists real gaps, such as *how Walter is related to you*.
- **Simpler pages:**
  - Questions shows one card at a time. The skills, notes, database and search comparison are behind "See how Lore is thinking".
  - People & stories shows the map and a conversation, and everything else is behind one link.
- **Small-model problems found and handled:**
  - **Invented people:** the 2B vision model claimed "Rose, 80, white shirt and blue jeans" and "20–30 people" on a drawn cake with nobody in it. A separate yes/no "is there a person?" check now removes invented people.
  - **Names and places:** names now count only if written in the picture or spoken in the audio, and places only from writing or speech, so "indoor" no longer counts as a place.
  - **Silence:** Whisper made up words ("I, Maya") from a test tone, and the reply then called the speaker "Maya". Replies no longer use the speaker's name.
  - **Cut-off replies:** model replies cut off mid-JSON lost the extracted names. Cut-off replies are now repaired.
  - **Mixed-up memories:** the notes sometimes mixed people from earlier memories into a new one. Earlier memories are now used for links only.

## 2026-11-14 · v5: smarter agent questions, bigger free model

- **The agent says what a picture is for:** the vision model now also answers "what does this picture seem meant to show or help remember?" (for example *to celebrate Rose's 80th birthday*). Questions start from that: *"Was this a birthday party? It looks like a birthday party to me, and it seems meant to celebrate Rose's 80th birthday. Am I right?"*
- **No more "Around 2026":** the year the file was saved is never offered, because that is when it was copied, not when it happened.
  - If the file name has a year: *"Is … really from 1998?"* (Yes / Earlier / Later).
  - Otherwise: *"When in your life was …?"* (When I was young / When I was raising a family / In recent years).
- **New easy, valuable questions, always three taps:**
  - Photos and videos: *Why is this one special to you?*, *Who took this picture?*
  - Recordings: *Who would you like to hear this story one day?*, *How do you feel when you remember this?*
  - Letters and documents: *Who wrote this?*, *Why does this matter to you?*
  - Answers go into the memory's notes ("From you") and its search text, and "Was this a birthday party?" also links the memory to a theme on the map.
  - The web demo asks the same questions.
- **Bigger free model:** Qwen2-VL-7B, compressed to 4-bit, runs on the same 8 GB laptop GPU. No paid API. The server uses it when it is downloaded and falls back to the 2B model otherwise. huggingface.co was unreachable, so it came from ModelScope.
- **Offline start:** once all models are downloaded, the server starts without the internet.

## How it was tested

- Each round was tested on a separate copy of the server (`LEGACY_PORT=8010`, `LEGACY_DATA` in a temporary folder), so real data was never touched.
- The test files were all generated:
  - typed text
  - drawn pictures
  - Windows text-to-speech recordings
  - short videos built from those
- Browser flows were scripted in the browser: adding files, answering questions, dragging and connecting on the map, reloading the page, and recording with a simulated microphone.

## Still open

- **Not tried on real material:** no real family photos and no real human voice have been tested yet. Real photos may be easier for the vision model than drawings, but this is unchecked.
- **The 2B vision/language model is the weak point:**
  - descriptions can be wrong
  - notes can include guesses ("the family's history of science fairs")
  - story drafts can add details that aren't in the memories

  A larger model would help but needs more GPU memory.
- **Speed:** each photo takes several model passes, so adding photos is noticeably slower.
- **Money:** the business case still needs real numbers (what Legacy Box and similar companies earn, with sources). None are included here.
- **Open questions from the sketch:** the A·V·I·L input categories and the "C" after Ask are still unconfirmed.

## Files

| File | What it is |
|---|---|
| `legacy-box-demo.html` | The whole web page. Works alone as a demo with sample data, or with the server |
| `server/app.py` | API, agent questions, naming, notes, database endpoints |
| `server/models.py` | Vision, speech, language and embedding models |
| `server/db.py` | SQLite embedding database |
| `server/README.md` | Model details, timings, how to swap models |
| `README.md` | How to set up and use Lore |
| `Legacy_Box_UI_UX_Requirements.md` | Product requirements and API contract |
