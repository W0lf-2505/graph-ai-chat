# 🧠 Graph-Powered AI Chatbot (FastAPI + Neo4j + Ollama)

This project is a **knowledge graph chatbot** that answers questions using **your own Neo4j data**, not LLM memory.

It combines:

* 🗄️ Neo4j (Graph Database)
* ⚡ FastAPI (Backend API)
* 🤖 Ollama (Local LLM)
* 🌐 Simple Chat UI (HTML)

---

# 🚀 What This Does

Instead of:

```
LLM → guess answer ❌
```

This system does:

```
User → LLM → Cypher → Neo4j → Data → LLM → Answer ✅
```

👉 Result:

* No hallucination
* Explainable answers
* Uses your data as source of truth

---

## 🧠 Trainer (Build Your Knowledge Graph)

The Trainer lets you **ingest new knowledge into the graph** from a topic (e.g., a company) and watch progress in real time.

### ✨ What it does

```text
Topic → Wikipedia text → chunking → LLM extracts triples → Neo4j stores graph
```

* Fetches content (e.g., Wikipedia)
* Splits into chunks
* Uses local LLM (Ollama) to extract triples
* Stores relationships in Neo4j
* Streams live progress via WebSocket

---

## 🌐 Open the Trainer UI

```text
http://127.0.0.1:8000/trainer
```

---

## ▶️ How to use

1. Enter a topic (e.g., `OpenAI`, `Stripe`, `Zoom Video Communications`)
2. Click **Train**
3. Watch live logs as data is processed

Example:

```text
Fetching data for OpenAI...
12 chunks created
Processing chunk 1/12
Processing chunk 2/12
...
Training complete ✅
```

---

## 🔌 API Endpoints

### Start Training

```http
POST /train?topic=OpenAI
```

**Response**

```json
{
  "job_id": "uuid",
  "message": "Training started"
}
```

### Stream Progress (WebSocket)

```text
ws://localhost:8000/ws/train/{job_id}
```

---

## 🧪 Recommended Topics (fast training)

Start with smaller pages to reduce chunk count:

* OpenAI
* Stripe
* Notion Labs
* Zoom Video Communications

> Tip: Limit chunks during dev:

```python
chunks = chunk_text(text)[:10]
```

---

## ⚠️ Important Notes

* **Do not use `--reload` during training** (it restarts the server and kills jobs)
* WebSocket must connect **before or at the start** of training to receive logs
* In-memory jobs are **not persisted** (lost on restart)

---

## 🛠️ Troubleshooting

**No logs, only ping/pong**

* Ensure WebSocket is connected before training starts
* Check `send_progress` is `await`ed

**“No WS FOUND”**

* `job_id` mismatch or race condition

**Slow training**

* Use a smaller model (`phi3`) or limit chunks

---

## 🚀 Next Improvements

* Progress bar (% complete)
* Cancel training job
* Persist jobs (Redis/DB)
* De-duplicate triples
* Live graph visualization

---

## 💡 Design Principle

```text
Graph = source of truth
LLM = extractor (training) + formatter (answers)
```

---

# 🏗️ Architecture

```
Frontend (HTML Chat)
        ↓
FastAPI (/chat)
        ↓
LLM (Ollama → Cypher generation)
        ↓
Neo4j (Graph query)
        ↓
LLM (formats answer)
        ↓
User
```

---

# 📦 Tech Stack

* FastAPI – API server
* Neo4j – Graph database
* Ollama – Local LLM (mistral / llama3)
* Requests – HTTP calls
* Jinja2 – HTML templating

---

# ⚙️ Setup

## 1. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 2. Setup `.env`

```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=password

OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=deepseek-coder:6.7b
OLLAMA_ANSWER_MODEL=mistral
```

---

## 3. Run Neo4j

Make sure Neo4j is running locally:

```
bolt://localhost:7687
```

---

## 4. Run Ollama

```bash
ollama pull mistral
ollama run mistral
```

---

## 5. Start FastAPI

```bash
uvicorn app:app --reload
```

---

## 6. Open UI

```
http://127.0.0.1:8000/
```

---

# 🧪 Example Questions

Try these:

### Basic

* Who is the CEO of Tesla?
* Where is Tesla located?

### Graph Queries

* What is Tesla connected to?
* Show all relationships of Tesla

### Multi-hop

* What is connected to Tesla within 2 steps?

---

# 🔁 Self-Correcting Query System

This project includes a **retry loop**:

```
LLM → bad query → Neo4j error → LLM fixes → retry
```

Example:

1. Wrong query (uses Person label ❌)
2. Error: label does not exist
3. LLM regenerates query using Entity ✅

---

# ⚠️ Important Design Decisions

## 1. Generic Schema

All nodes are stored as:

```
(:Entity {name: "Tesla"})
```

👉 No strict labels (Person, Company)

---

## 2. Simple Cypher Only

LLM is restricted to:

```
MATCH → WHERE → RETURN
```

❌ No:

* filter()
* relationships()
* complex queries

---

## 3. Grounded Answers

LLM is forced to:

* use ONLY graph data
* never hallucinate
* return "No data found" if empty

---

# 🔧 Key Functions

## Generate Cypher

```python
generate_cypher(question)
```

## Extract + Clean Query

```python
extract_cypher(text)
```

## Execute Query

```python
run_query(cypher)
```

## Retry Loop

```python
ask_graph(question)
```

---

# 🛠️ Common Issues

## ❌ "Bot: undefined"

Frontend didn’t receive `answer` → backend error

---

## ❌ "label does not exist"

Graph uses `Entity`, not `Person`/`Company`

---

## ❌ "Invalid input 'To'"

LLM returned explanation instead of Cypher

---

## ❌ Hallucinated answers

Fix prompt → enforce strict data usage

---

# 🔥 Improvements (Next Steps)

* Add schema auto-detection
* Switch to structured JSON outputs
* Add graph visualization (D3.js)
* Add chat memory
* Add authentication

---

# 💡 Key Insight

```
Graph = truth
LLM = reasoning layer
```

---

# 🚀 Final Result

You now have a:

✅ Graph-based AI assistant
✅ No hallucination system
✅ Self-healing query engine
✅ Local + zero API cost

---

# 👨‍💻 Author Notes

This project is designed as a **foundation for AI-first backend systems**.

You can extend it into:

* enterprise copilots
* internal knowledge assistants
* decision engines


