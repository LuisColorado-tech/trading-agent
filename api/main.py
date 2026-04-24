"""FastAPI — Dashboard API para el Trading Agent."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env antes de cualquier import interno
load_dotenv(Path(__file__).parent.parent / 'config' / '.env')
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import stocks, crypto, polymarket, options, live, overview

app = FastAPI(title='Trading Agent API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],   # Red interna — sin auth pública
    allow_methods=['GET'],
    allow_headers=['*'],
)

app.include_router(overview.router, prefix='/overview', tags=['overview'])
app.include_router(stocks.router,   prefix='/stocks',   tags=['stocks'])
app.include_router(crypto.router,   prefix='/crypto',   tags=['crypto'])
app.include_router(polymarket.router, prefix='/polymarket', tags=['polymarket'])
app.include_router(options.router,  prefix='/options',  tags=['options'])
app.include_router(live.router,     prefix='/live',     tags=['live'])


@app.get('/health')
def health():
    return {'status': 'ok'}
