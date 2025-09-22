from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import admin, user, event, organizationadmin, user, scout, team

# Create FastAPI app
app = FastAPI(title="Scouting App API")

origins = [
    "http://localhost:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(user.router)
app.include_router(event.router)
app.include_router(organizationadmin.router)
app.include_router(user.router)
app.include_router(scout.router)
app.include_router(team.router)

@app.get("/ping")
def ping():
    return {"message": "pong"}