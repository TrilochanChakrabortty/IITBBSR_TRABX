from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from typing import List
from datetime import datetime
import requests

from database import engine, SessionLocal
from models import Base, User, Asteroid, AsteroidRisk, ChatMessage

# ---------------- DATABASE INIT ----------------
Base.metadata.create_all(bind=engine)

# ---------------- APP INIT ----------------
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# ---------------- NASA CONFIG ----------------
NASA_API_KEY = "ba2N1iELeaST7FyUJCcT2u6byKo1x51UvFfHO1h1"
NASA_NEO_URL = "https://api.nasa.gov/neo/rest/v1/feed"

# =====================================================
# ===================== PAGES =========================
# =====================================================

@app.get("/", response_class=HTMLResponse)
def auth_page(request: Request):
    return templates.TemplateResponse("auth.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: str):
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "username": user}
    )


@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request):
    return templates.TemplateResponse("alerts.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/asteroids/search", response_class=HTMLResponse)
def asteroid_search_page(request: Request):
    return templates.TemplateResponse(
        "asteroids_by_date.html",
        {"request": request}
    )

# =====================================================
# ===================== AUTH ==========================
# =====================================================

@app.post("/register")
def register(username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()

    if db.query(User).filter(User.username == username).first():
        db.close()
        return JSONResponse({"message": "Username already exists"}, status_code=400)

    db.add(User(username=username, password=password))
    db.commit()
    db.close()
    return {"message": "Registration successful"}


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()

    user = db.query(User).filter(
        User.username == username,
        User.password == password
    ).first()

    db.close()

    if not user:
        return JSONResponse({"message": "Invalid credentials"}, status_code=401)

    return {"message": "Login successful"}

# =====================================================
# ================= NASA FETCH ========================
# =====================================================

@app.get("/nasa/neo/save")
def fetch_and_save_asteroids(start_date: str, end_date: str):
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "api_key": NASA_API_KEY
    }

    response = requests.get(NASA_NEO_URL, params=params)
    if response.status_code != 200:
        return {"error": "NASA API failed"}

    data = response.json()
    db = SessionLocal()

    saved, skipped = 0, 0

    for date in data.get("near_earth_objects", {}):
        for neo in data["near_earth_objects"][date]:
            asteroid = Asteroid(
                neo_id=neo["id"],
                name=neo["name"],
                close_approach_date=date,
                diameter_km=neo["estimated_diameter"]["kilometers"]["estimated_diameter_max"],
                velocity_km_s=float(
                    neo["close_approach_data"][0]["relative_velocity"]["kilometers_per_second"]
                ),
                hazardous=neo["is_potentially_hazardous_asteroid"],
                nasa_url=neo["nasa_jpl_url"]
            )

            try:
                db.add(asteroid)
                db.commit()
                saved += 1
            except IntegrityError:
                db.rollback()
                skipped += 1

    db.close()
    return {"saved": saved, "skipped": skipped}

# =====================================================
# ================= RISK LOGIC ========================
# =====================================================

def calculate_risk(diameter_km, velocity_km_s, miss_distance_km, hazardous):
    score = (
        diameter_km * 40 +
        velocity_km_s * 2 -
        (miss_distance_km / 1_000_000)
    )

    if hazardous:
        score += 30

    score = round(score, 2)

    if score >= 80:
        level = "CRITICAL"
    elif score >= 50:
        level = "HIGH"
    elif score >= 30:
        level = "MODERATE"
    else:
        level = "LOW"

    return score, level

# =====================================================
# ================= RISK (DB) =========================
# =====================================================

@app.get("/asteroids/risk")
def asteroid_risk_analysis():
    db = SessionLocal()
    asteroids = db.query(Asteroid).all()
    db.close()

    analysis = []

    for a in asteroids:
        score, level = calculate_risk(
            a.diameter_km,
            a.velocity_km_s,
            1_000_000,   # default miss distance (DB doesn't store it)
            a.hazardous
        )

        analysis.append({
            "name": a.name,
            "neo_id": a.neo_id,
            "risk_score": score,
            "risk_level": level
        })

    return sorted(analysis, key=lambda x: x["risk_score"], reverse=True)


@app.post("/asteroids/risk/save")
def save_asteroid_risk():
    db = SessionLocal()
    asteroids = db.query(Asteroid).all()
    saved = 0

    for a in asteroids:
        score, level = calculate_risk(
            a.diameter_km,
            a.velocity_km_s,
            1_000_000,
            a.hazardous
        )

        db.add(AsteroidRisk(
            neo_id=a.neo_id,
            name=a.name,
            close_approach_date=a.close_approach_date,
            diameter_km=a.diameter_km,
            velocity_km_s=a.velocity_km_s,
            hazardous=a.hazardous,
            risk_score=score,
            risk_level=level
        ))
        saved += 1

    db.commit()
    db.close()
    return {"saved": saved}


@app.get("/asteroids/alerts")
def get_asteroid_alerts():
    db = SessionLocal()
    alerts = db.query(AsteroidRisk).filter(
        AsteroidRisk.risk_level.in_(["HIGH", "CRITICAL"])
    ).order_by(AsteroidRisk.risk_score.desc()).all()
    db.close()

    return [
        {
            "name": a.name,
            "risk_level": a.risk_level,
            "risk_score": a.risk_score
        }
        for a in alerts
    ]

# =====================================================
# ================= DATE SEARCH + RISK ================
# =====================================================

@app.get("/api/asteroids/by-date")
def get_asteroids_by_date(date: str = Query(...)):
    params = {
        "start_date": date,
        "end_date": date,
        "api_key": NASA_API_KEY
    }

    response = requests.get(NASA_NEO_URL, params=params)
    data = response.json()

    asteroids = data["near_earth_objects"].get(date, [])
    results = []

    for a in asteroids:
        approach = a["close_approach_data"][0]
        diameter = a["estimated_diameter"]["kilometers"]["estimated_diameter_max"]
        velocity = float(approach["relative_velocity"]["kilometers_per_second"])
        miss = float(approach["miss_distance"]["kilometers"])
        hazardous = a["is_potentially_hazardous_asteroid"]

        score, level = calculate_risk(diameter, velocity, miss, hazardous)

        results.append({
            "name": a["name"],
            "neo_id": a["id"],
            "risk_score": score,
            "risk_level": level,
            "diameter_km": round(diameter, 4),
            "velocity_km_s": round(velocity, 4),
            "miss_distance_km": round(miss, 2)
        })

    return results

# =====================================================
# ================= CHAT ==============================
# =====================================================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for conn in self.active_connections:
            await conn.send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await manager.connect(websocket)
    db = SessionLocal()

    try:
        while True:
            data = await websocket.receive_text()

            if ":" in data:
                username, message = data.split(":", 1)
            else:
                username = "Anonymous"
                message = data

            db.add(ChatMessage(
                username=username.strip(),
                message=message.strip()
            ))
            db.commit()

            await manager.broadcast(f"{username.strip()}: {message.strip()}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        db.close()


@app.get("/chat/history")
def chat_history():
    db = SessionLocal()
    msgs = db.query(ChatMessage).order_by(ChatMessage.timestamp).all()
    db.close()

    return [
        {
            "username": m.username,
            "message": m.message,
            "timestamp": m.timestamp.strftime("%H:%M")
        }
        for m in msgs
    ]
