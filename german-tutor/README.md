# Deutsch sprechen — a voice-only German tutor

You hold a button, speak German out loud, and a tutor answers you in German
out loud. When you get grammar wrong it cuts in, says the correct sentence,
makes you repeat it, then carries on. There is nothing to read.

---

## 1. Get an OpenAI API key

1. Go to **https://platform.openai.com** and sign in (or make an account).
2. Click your profile icon (top right) → **Your profile** → **User API keys**,
   or go straight to https://platform.openai.com/api-keys.
3. Press **Create new secret key**, give it a name like `german-tutor`,
   and press Create.
4. **Copy the key now** — it starts with `sk-` and is only shown once. If you
   lose it, just delete it and make a new one.
5. Add money to the account: **Settings → Billing → Add payment method**, then
   add credit. $5 is plenty to get started. Without credit you will get an
   `insufficient_quota` error.

## 2. Put the key in the app

In the `german-tutor` folder there is a file called `.env`. Open it in any
text editor. It looks like this:

```
OPENAI_API_KEY=sk-paste-your-key-here
```

Replace `sk-paste-your-key-here` with your real key and save. No quotes, no
spaces around the `=`.

That file is ignored by git, so your key can never be committed by accident.

## 3. Install what it needs

Open a terminal in the `german-tutor` folder and run:

```
pip install -r requirements.txt
```

That installs five things: FastAPI and uvicorn (the little web server), httpx
(to call OpenAI), python-dotenv (to read your `.env`), and pydantic.

## 4. Run it

```
python main.py
```

Then open **http://localhost:8000** in Chrome or Edge.

Use `localhost` — not the `file://` path to index.html. Browsers only give
microphone access to real web pages, and `localhost` counts as one.

Press the big button once to connect. Your browser will ask for microphone
permission — say yes. The tutor greets you in German straight away.

To stop the server, press `Ctrl+C` in the terminal.

---

## How to use it

- **Hold** the big button while you speak. **Release** when you are done.
  The spacebar does the same thing if you would rather keep your hands still.
- The ring around the button tells you whose turn it is:
  - **grey** — your turn, hold and speak
  - **green** — it is hearing you
  - **amber** — it is thinking
  - **blue** — the tutor is speaking
- **You can talk over the tutor.** Hold the button while it is speaking and it
  will stop and listen. That is also how it interrupts *you* mid-sentence when
  you make a mistake.
- **A1 / A2 / B1** change the difficulty instantly. You do not need to reload
  the page or hang up — the change is sent down the live connection and the
  conversation keeps going.
- The **Situation** dropdown puts you in a roleplay (ordering food, the
  doctor, renting a flat…). Changing it also works mid-conversation.

### One design note worth knowing

You asked for push-to-talk *and* for the tutor to interrupt you mid-sentence.
Those pull in opposite directions: a strict walkie-talkie means the model
hears nothing until you let go, so it can never cut in.

So the button controls your **microphone**, not the model's turn. Holding it
opens the mic; releasing mutes it. While the mic is open the model listens
continuously and decides for itself when to jump in — which is what makes the
interrupting corrections work. You still control exactly when it can hear you.

If you would rather have strict walkie-talkie behaviour (it can only reply
after you release, and never interrupts), say so and I will switch it — it is
a few lines in `main.py`.

---

## Changing how the tutor teaches

Everything the tutor says and does lives in **`prompts.py`**. Nothing else
needs editing. Change the file, press `Ctrl+C`, run `python main.py` again.

- **`LEVELS`** — what A1, A2 and B1 actually mean to the tutor.
- **`SCENARIOS`** — the dropdown. To add your own, copy one block and give it
  a new key, a `label` for the menu, and a `situation` describing the
  roleplay. It appears in the dropdown automatically — no HTML to touch.
- **`TUTOR_PROMPT`** — the teaching rules. This is the heart of the app. If
  the tutor is too soft, too chatty, or corrects too much, this is the knob.
- **`MISTAKE_TAGS`** — the grammar categories used in the log.

## Your mistake log

Every correction is appended to **`mistakes.json`**:

```json
{
  "said": "Ich habe zu Hause gegangen",
  "correction": "Ich bin nach Hause gegangen",
  "tag": "auxiliary",
  "note": "gehen takes sein",
  "level": "A2",
  "scenario": "free",
  "at": "2026-08-29T13:15:14+00:00"
}
```

The file is append-only — nothing is ever edited or deleted, so it stays a
plain running record. Tags come from this list: `gender`, `case`,
`verb-form`, `word-order`, `auxiliary`, `preposition`, `adjective-ending`,
`vocabulary`.

The tutor never mentions the log out loud. Every save is also printed in your
terminal, so you can watch it working while you talk.

---

## What it costs

Realtime audio is billed per token, and audio turns into tokens at a fixed
rate: about **600 tokens per minute you speak** and **1,200 tokens per minute
the tutor speaks**.

At current prices for `gpt-realtime` ($32 per million audio-input tokens,
$64 per million audio-output tokens), a straightforward hour where you talk
40 minutes and the tutor talks 20 works out at roughly **$0.75 of listening
plus $1.50 of speaking**.

Real sessions cost more than that, because every turn re-sends the
conversation so far as input — so a long conversation gets more expensive per
minute as it goes. Measured real-world usage lands around **$0.06–$0.11 per
minute**, so:

| | per hour of conversation |
|---|---|
| **`gpt-realtime`** (default) | **roughly $4–$7** |
| **`gpt-realtime-mini`** | **roughly $1.50–$3** |

Two practical ways to spend less:

1. **Switch to the mini model.** Open `main.py`, find the line
   `MODEL = "gpt-realtime"` near the top, and change it to
   `"gpt-realtime-mini"`. It is noticeably cheaper and still good enough for
   beginner conversation practice. Try it first.
2. **Keep sessions to 20–30 minutes.** Reload the page to start fresh. The
   cost per minute climbs as the conversation history grows, so several short
   sessions cost less than one long one — and shorter sessions are better
   practice anyway.

Set a spending cap at **Settings → Billing → Limits** on the OpenAI dashboard
so there are no surprises.

---

## If something goes wrong

**"No OPENAI_API_KEY found"** — the `.env` file is missing, or the key was
pasted with quotes around it. It should read `OPENAI_API_KEY=sk-...`.

**A 401 error** — the key is wrong or was deleted. Make a new one.

**`insufficient_quota`** — the key works but the account has no credit. Add a
payment method and some credit.

**No microphone prompt** — you opened the HTML file directly instead of going
to `http://localhost:8000`. Also check Chrome's site permissions.

**You hear nothing** — check the machine's volume, and check the terminal for
errors. Open the browser console (F12) too; every connection problem is
printed there.

**"model not found"** — OpenAI renamed the model. Change `MODEL` at the top of
`main.py` to the current name from the Realtime docs.
