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


