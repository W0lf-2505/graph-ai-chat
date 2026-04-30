from fastapi import FastAPI, Request
from pydantic import BaseModel
from neo4j import GraphDatabase
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
import os
from dotenv import load_dotenv
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import BackgroundTasks
import json
import httpx

load_dotenv()
import re
import asyncio
import uuid
import wikipedia


NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASS = os.getenv("NEO4J_PASS")

OLLAMA_URL = os.getenv("OLLAMA_URL")
MODEL = os.getenv("OLLAMA_MODEL")
ANSWER_MODEL = os.getenv("OLLAMA_ANSWER_MODEL", MODEL)

# ---------------- VALIDATION ----------------
missing = [k for k, v in {
    "NEO4J_URI": NEO4J_URI,
    "NEO4J_USER": NEO4J_USER,
    "NEO4J_PASS": NEO4J_PASS,
    "OLLAMA_URL": OLLAMA_URL,
    "OLLAMA_MODEL": MODEL
}.items() if not v]

print(f"Using model = {MODEL}")
print(f"Using answer model = {ANSWER_MODEL}")




driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
connections = {}
job_topics = {}

app = FastAPI()


if missing:
    raise RuntimeError(f"Missing env vars: {missing}")


def insert_triple(tx, s, r, o):
    query = f"""
    MERGE (a:Entity {{name: $s}})
    MERGE (b:Entity {{name: $o}})
    MERGE (a)-[:{r}]->(b)
    """
    tx.run(query, s=s, o=o)

def store_triples(triples):
    with driver.session() as session:
        for t in triples:
            relation = clean_relation(t["relation"])
            session.execute_write(insert_triple, t["subject"], relation, t["object"])

def clean_relation(rel):
    rel = rel.upper()
    
    # Replace invalid characters with underscore
    rel = re.sub(r'[^A-Z0-9_]', '_', rel)
    
    # Remove multiple underscores
    rel = re.sub(r'_+', '_', rel)
    
    # Remove leading/trailing underscores
    rel = rel.strip('_')
    
    # Fallback if empty
    if not rel:
        rel = "RELATED_TO"
    
    return rel

def get_text(topic):
    return wikipedia.page(topic).content

def chunk_text(text, size=1000):
    return [text[i:i+size] for i in range(0, len(text), size)]

async def extract_triples_ollama(chunk):
    prompt = f"""
Extract knowledge graph triples from the text.

Rules:
- Output ONLY valid JSON
Format:
[{{"subject": "X", "relation": "RELATION", "object": "Y"}}]

If no triples found, output: []
- Use UPPERCASE relations with underscores
- Keep entities concise
- Avoid duplicates

Text:
{chunk}
"""
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            OLLAMA_URL,
            json={"model": ANSWER_MODEL, "prompt": prompt, "stream": False}
        )
    return response.json()["response"]

def parse_triples(raw):
    try:
        # Try direct parse first
        triples = json.loads(raw)
        
    except:
        # Find JSON array anywhere in the response
        match = re.search(r'\[[\s\S]*?\]', raw)
        if not match:
            print(f"No JSON found in: {raw[:200]}")
            return []
        try:
            triples = json.loads(match.group(0))
        except Exception as e:
            print(f"JSON parse failed: {e}\nRaw: {raw[:200]}")
            return []

    cleaned = []
    for t in triples:
        if all(k in t for k in ("subject", "relation", "object")):
            cleaned.append({
                "subject": t["subject"].strip(),
                "relation": t["relation"].upper().strip(),
                "object":   t["object"].strip()
            })
    return cleaned

async def train_job(job_id, topic):
    try:
        await send_progress(job_id, f"Fetching data for {topic}...")
        try:
            page = wikipedia.page(topic, auto_suggest=False)
        except wikipedia.DisambiguationError as e:
            # Pick the first option that contains the topic name
            best = next((opt for opt in e.options if topic.lower() in opt.lower()), e.options[0])
            await send_progress(job_id, f"Disambiguation: using '{best}'")
            page = wikipedia.page(best, auto_suggest=False)
        except wikipedia.PageError:
            await send_progress(job_id, f"Error: Page '{topic}' not found on Wikipedia")
            return
        
        text = page.content
        chunks = chunk_text(text)
        total = len(chunks)

        await send_progress(job_id, f"{total} chunks created")

        for i, chunk in enumerate(chunks):
            pct = round(((i + 1) / total) * 100)
            await send_progress(job_id, f"Processing chunk {i+1}/{total} — {pct}%")

            raw = await extract_triples_ollama(chunk)  # now async
            triples = parse_triples(raw)

            if triples:
                store_triples(triples)

            await asyncio.sleep(0)  # yield to event loop

        await send_progress(job_id, "Training complete ✅")

    except Exception as e:
        await send_progress(job_id, f"Error: {str(e)}")
    finally:
        connections.pop(job_id, None)

async def send_progress(job_id, message):
    ws = connections.get(job_id)
    if ws:
        try:
            await ws.send_text(message)
        except:
            pass

def extract_cypher(text):
    text = text.strip()

    # Remove markdown / backticks
    text = text.replace("```cypher", "").replace("```", "").replace("`", "").strip()

    # Fix Mistral's markdown links: [ceo.name](http://...) → ceo.name
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Fix "Label as Alias" → just remove " as Alias" inside node patterns
    text = re.sub(r':(\w+)\s+as\s+(\w+)', r':\1', text, flags=re.IGNORECASE)

    # Find first MATCH or WITH
    match = re.search(r"(MATCH|WITH)[\s\S]+", text, re.IGNORECASE)

    if not match:
        return None

    query = match.group(0)

    # Stop at first invalid trailing sentence (optional cleanup)
    query = query.split("\n\n")[0]

    return query.strip()



# ---------------- REQUEST MODEL ----------------
class Query(BaseModel):
    question: str

def clean_cypher(text):
    return (
        text
        .replace("```cypher", "")
        .replace("```", "")
        .replace("`", "")   # 🔥 THIS FIX
        .strip()
    )

# ---------------- LLM: Generate Cypher ----------------
def generate_cypher(question, error=None):
    prompt = f"""
You are a Neo4j Cypher query generator. Output ONLY a valid Cypher query. Nothing else.

STRICT RULES — violating any rule will cause an error:
1. Start with MATCH. No WITH before MATCH.
2. NEVER use filter() — it was removed in Neo4j 4.x. Use list comprehensions instead: [x IN list WHERE condition]
3. NEVER use collect() or complex aggregations unless absolutely necessary.
4. NEVER use relationships() function on a node — only on a path.
5. NEVER use [*] unbounded traversal — always set a limit like [*1..3].
6. NEVER use type() on a list — only on a single relationship variable.
7. Keep queries simple. One MATCH clause is almost always enough.
8. RETURN only the variables you explicitly matched. Never return unbound variables.
9. All string values are case-sensitive. Use toLower() if unsure.
10. No explanation. No markdown. No backticks. No comments. Just the Cypher query.


- Property access is written as: n.name — never as [n.name](url)
- Node aliases go BEFORE the label: (company:Entity) — never (:Entity as company)
- Do not use markdown formatting of any kind in the output
- Output must be plain text only — no links, no bold, no italics

ALLOWED SCHEMA — only these exist:
  (Entity {{name: string}})-[:CEO_OF]->(Entity)
  (Entity {{name: string}})-[:LOCATED_IN]->(Entity)
  (Entity {{name: string}})-[:OPERATES_IN]->(Entity)

GOOD EXAMPLES:
  Q: Who is the CEO of Tesla?
  A: MATCH (e:Entity {{name: 'Tesla'}})-[:CEO_OF]->(ceo:Entity) RETURN ceo.name

  Q: Where is Apple located?
  A: MATCH (e:Entity {{name: 'Apple'}})-[:LOCATED_IN]->(loc:Entity) RETURN loc.name

  Q: What sectors does Google operate in?
  A: MATCH (e:Entity {{name: 'Google'}})-[:OPERATES_IN]->(sector:Entity) RETURN sector.name

  Q: What do you know about Tesla?
  A: MATCH (e:Entity {{name: 'Tesla'}})-[r]->(n:Entity) RETURN type(r) AS relationship, n.name AS value

BAD EXAMPLES — never generate these:
  ❌ filter(x in list WHERE ...)         — removed in Neo4j 4.x
  ❌ WITH x MATCH ...                    — MATCH must come first
  ❌ MATCH (n)-[*]->(m)                  — unbounded traversal
  ❌ type(relationships(node)[0])        — relationships() needs a path not a node
  ❌ RETURN n, m, collect(...), filter() — overly complex, keep it simple

"""

    if error:
        prompt += f"""
The previous query failed with error:
{error}

Fix the query.
"""

    prompt += f"""
Question:
{question}
"""

    res = requests.post(
        OLLAMA_URL,
        json={"model": MODEL, "prompt": prompt, "stream": False}
    )

    return res.json()["response"].strip()

# ---------------- RUN CYPHER ----------------
def run_query(cypher):
    with driver.session() as session:
        result = session.run(cypher)
        return [r.data() for r in result]

# ---------------- LLM: Format Answer ----------------
def format_answer(question, data):
    prompt = f"""
    You are a helpful assistant that answers questions using graph database results.

The user asked: {question}

The graph database returned this data: {data}

Write a clear, direct, conversational answer to the question using the data above.
Do not mention databases, graphs, or code.
Do not refuse or say you cannot answer.
Just answer the question naturally in 1-3 sentences.

Answer:
"""
    print("Formatting answer:")

    res = requests.post(
        OLLAMA_URL,
        json={"model": ANSWER_MODEL, "prompt": prompt, "stream": False}
    )

    return res.json()["response"]

UNSAFE_KEYWORDS = ["DELETE", "CREATE", "MERGE", "DROP", "SET", "REMOVE"]

def ask_graph(question, max_retries=3):
    error = None

    for attempt in range(max_retries):
        print(f"Attempt {attempt+1} to generate query...")
        raw = generate_cypher(question, error)
        cypher = extract_cypher(raw)

        if not cypher or not cypher.upper().startswith("MATCH"):
            error = f"Invalid query format. Raw output was: {raw[:200]}"
            continue

        if any(kw in cypher.upper() for kw in UNSAFE_KEYWORDS):
            return {"answer": "Unsafe query generated.", "cypher": cypher, "data": [], "question": question}

        try:
            data = run_query(cypher)

            if data:
                answer = format_answer(question, data)
                return {"answer": answer, "cypher": cypher, "data": data, "question": question}

            # Give the LLM the actual failing query so it can fix it
            error = f"Query returned no results:\n{cypher}\nTry broader MATCH conditions or check property names."

        except Exception as e:
            error = f"Query failed with error: {str(e)}\nQuery was:\n{cypher}"

    return {"answer": f"Failed after {max_retries} attempts. Last error: {error}", "cypher": cypher, "data": [], "question": question}
# ---------------- MAIN ENDPOINT ----------------

templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/trainer")
def train_ui(request: Request):
    return templates.TemplateResponse(request,"train.html")

@app.post("/chat")
def chat(q: Query):
    print("Received question:", q.question)
    try:
        result = ask_graph(q.question)
        return result

    except Exception as e:
        print("Error:", e)
        return {
            "question": q.question,
            "cypher": None,
            "data": [],
            "answer": "I am not able to answer that question currently."
        }
    

@app.post("/train")
async def train(topic: str):
    job_id = str(uuid.uuid4())
    job_topics[job_id] = topic  # just store it, don't start yet
    return {"job_id": job_id, "message": "Training started"}

@app.websocket("/ws/train/{job_id}")
async def train_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    connections[job_id] = websocket

    # NOW start the job — WebSocket is ready
    topic = job_topics.pop(job_id, None)
    if topic:
        await train_job(job_id, topic)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.pop(job_id, None)