from urllib import response

from click import prompt
from fastapi import FastAPI, Request, Query as FastAPIQuery
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
import traceback


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

def safe_json_load(s):
    if not s or not s.strip():
        return None
    try:
        return json.loads(s)
    except Exception as e:
        return None

def insert_triple(tx, s, r, o):
    query = f"""
    MERGE (a:Entity {{name: $s}})
    MERGE (b:Entity {{name: $o}})
    MERGE (a)-[:{r}]->(b)
    """
    tx.run(query, s=s, o=o)

def store_triples(triples):
    if not triples:
        return
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

def chunk_text(text, size=1000):
    return [text[i:i+size] for i in range(0, len(text), size)]

async def extract_triples_ollama(chunk):
    example = '[{"subject": "X", "relation": "RELATION", "object": "Y"}]'
    empty = '[]'

    prompt = f"""### Task
    Extract knowledge graph triples from the text below.

    ### Output format
    Output ONLY a JSON array. No explanation. No markdown. No extra text.

    {example}

    If no triples found, output: {empty}

    ### Rules
    - relation must be UPPERCASE with underscores: CEO_OF, LOCATED_IN, FOUNDED_BY
    - subject and object must be concise entity names
    - No duplicate triples
    - No nested objects, only flat key-value pairs
    - Every object must have exactly these 3 keys: subject, relation, object

    ### Text
    {chunk}

    ### JSON
    """
    issue = ""
    for attempt in range(3):
        try:
            res = requests.post(
                OLLAMA_URL,
                json={"model": MODEL, "prompt": prompt+issue, "stream": False},
                timeout=60
            )
            raw = res.json()["response"]

            # Check it's not empty or whitespace
            if not raw or not raw.strip():
                print(f"Attempt {attempt+1}/{3}: Empty response, retrying...")
                issue = "\nThe previous response was empty. Please provide valid JSON or [] if no triples."
                continue

            # Check it's not just "[]" (empty JSON array)
            if raw.strip() in ("[]", "[ ]"):
                print(f"Attempt {attempt+1}/{3}: Got empty array, retrying...")
                issue = "\nThe previous response was an empty array. If there are no triples, please confirm with [] without extra text."
                continue
            try:
                parsed = safe_json_load(raw)
                if not isinstance(parsed, list):
                    print(f"Attempt {attempt+1}/{3}: Not a list, retrying...")
                    issue = "\nThe previous response was not a JSON array. Please output a JSON array of triples."
                    continue

                valid = all(
                    isinstance(t, dict) and
                    all(k in t for k in ("subject", "relation", "object")) and
                    all(isinstance(t[k], str) and t[k].strip() for k in ("subject", "relation", "object"))
                    for t in parsed
                )

                if not valid:
                    print(f"Attempt {attempt+1}/{3}: Invalid triple format, retrying...")
                    issue = "\nThe previous response had invalid triple format. Each triple should be a JSON object with non-empty 'subject', 'relation', and 'object' string fields."
                    continue

            except Exception as e:
                print(f"Attempt {attempt+1}/{3}: JSON validation failed: {e}, retrying...")
                issue = "\nThe previous response was not valid JSON. Please ensure the output is a JSON array of triples."
                continue

            print(f"LLM raw response ({len(raw)} chars): {repr(raw[:300])}")
            return raw.strip()
        except (requests.exceptions.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Attempt {attempt+1}: Bad response from Ollama: {e}")
            if attempt == 3 - 1:
                raise RuntimeError(f"Ollama failed after {3} attempts: {e}")
            continue
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt+1}: Request failed: {e}")
            if attempt == 3 - 1:
                raise RuntimeError(f"Ollama request failed: {e}")
            continue
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            OLLAMA_URL,
            json={"model": ANSWER_MODEL, "prompt": prompt, "stream": False}
        )

def parse_triples(raw):
    try:
        # Try direct parse first
        triples = safe_json_load(raw)
        
    except:
        # Find JSON array anywhere in the response
        match = re.search(r'\[[\s\S]*?\]', raw)
        if not match:
            print(f"No JSON found in: {raw[:200]}")
            return []
        try:
            triples = safe_json_load(match.group(0))
        except Exception as e:
            print(f"JSON parse failed: {e}\nRaw: {raw[:200]}")
            return []

    if not isinstance(triples, list):
        print(f"Parsed JSON is not a list: {triples}")
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
            # auto_suggest=False + exact title from search = no disambiguation needed
            results = wikipedia.search(topic)

            if not results:
                await send_progress(job_id, "❌ No results found")
                return

            page_title = results[0]

            await send_progress(job_id, f"Using page: {page_title}")

            page = wikipedia.page(page_title, auto_suggest=False)
        except wikipedia.DisambiguationError as e:
            # Only hits if user typed manually — pick option matching topic exactly first
            best = next(
                (opt for opt in e.options if opt.lower() == topic.lower()),  # exact match first
                next(
                    (opt for opt in e.options if topic.lower() in opt.lower()),  # partial match second
                    e.options[0]  # fallback to first
                )
            )
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

            try:
                raw = await extract_triples_ollama(chunk)
            except RuntimeError as e:
                print(f"Chunk {i+1} skipped after all retries: {e}")
                await asyncio.sleep(0)
                continue  # now async
            triples = parse_triples(raw)

            if triples:
                store_triples(triples)

            await asyncio.sleep(0)  # yield to event loop

        await send_progress(job_id, "Training complete ✅")

    except Exception as e:
        traceback.print_exc()
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

     # Remove markdown fences
    text = text.replace("```cypher", "").replace("```", "").replace("`", "").strip()

    # Fix markdown links: [model.name](http://...) → model.name
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # Fix quoted aliases: AS 'business model' → AS business_model
    text = re.sub(r"AS\s+'([^']+)'", lambda m: "AS " + m.group(1).replace(" ", "_"), text)
    text = re.sub(r'AS\s+"([^"]+)"', lambda m: "AS " + m.group(1).replace(" ", "_"), text)

    # Remove trailing semicolon
    text = text.rstrip(";").strip()

    # Fix "Label as Alias" → correct alias before label
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
    prompt = f"""### Task
    Convert the user question into a single Neo4j Cypher query.

    ### Schema
    Nodes: (Entity {{name: string}})
    Relationships: [:CEO_OF], [:LOCATED_IN], [:OPERATES_IN]

    ### Rules
    - Output ONLY the Cypher query, nothing else
    - Start with MATCH
    - No markdown, no backticks, no explanation
    - Node alias before label: (e:Entity) not (:Entity as e)
    - Property access: e.name not [e.name](url)
    - No filter(), no unbounded [*], no relationships() on a node

    ### Examples
    Q: Who is the CEO of Tesla?
    A: MATCH (e:Entity {{name: 'Tesla'}})-[:CEO_OF]->(ceo:Entity) RETURN ceo.name

    Q: Where is Apple located?
    A: MATCH (e:Entity {{name: 'Apple'}})-[:LOCATED_IN]->(loc:Entity) RETURN loc.name

    Q: What sectors does Google operate in?
    A: MATCH (e:Entity {{name: 'Google'}})-[:OPERATES_IN]->(sector:Entity) RETURN sector.name

    Q: What do you know about Tesla?
    A: MATCH (e:Entity {{name: 'Tesla'}})-[r]->(n:Entity) RETURN type(r) AS relationship, n.name AS value

    ### Examples of what NOT to do
    - RETURN [n.name](http://n.name)     — never use markdown links
    - RETURN n.name AS 'my alias'        — never quote aliases, use AS myAlias
    - MATCH ... ;                        — no semicolons
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
    for attempt in range(3):
            try:
                res = requests.post(
                    OLLAMA_URL,
                    json={"model": MODEL, "prompt": prompt, "stream": False},
                    timeout=60
                )
                res.raise_for_status()
                data = res.json()
                return data["response"].strip()
            except (requests.exceptions.JSONDecodeError, KeyError, ValueError) as e:
                print(f"Attempt {attempt+1}: Bad response from Ollama: {e}")
                if attempt == 3 - 1:
                    raise RuntimeError(f"Ollama failed after {3} attempts: {e}")
                continue
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt+1}: Request failed: {e}")
                if attempt == 3 - 1:
                    raise RuntimeError(f"Ollama request failed: {e}")
                continue

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
    except (WebSocketDisconnect, RuntimeError):
        pass  # client disconnected or WS already closed
    finally:
        connections.pop(job_id, None)

@app.get("/search")
def search_wiki(q: str = FastAPIQuery(..., min_length=3)):
    try:
        results = wikipedia.search(q, results=5)

        return {
            "query": q,
            "results": results
        }

    except Exception as e:
        return {"error": str(e)}