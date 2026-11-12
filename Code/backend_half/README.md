# E-Bidding Backend - Unified

This is the Python FastAPI backend for the unified E-Bidding system.

## Architecture

See `ARCHITECTURE.md` for detailed architecture documentation.

## Quick Start

### Installation

```bash
pip install -r requirements.txt
cp config/credentials.env.example config/credentials.env
# Edit config/credentials.env with your SAP credentials
```

### Run

```bash
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload
```

## Project Structure

```
backend/
├── src/                  # Python modules
│   ├── config_loader.py
│   ├── driver_factory.py
│   ├── depot_bidding_engine.py
│   ├── parallel_execution_orchestrator.py
│   └── ...
├── config/               # Configuration files
│   ├── application.yaml
│   ├── depots.yaml
│   └── credentials.env
├── backend_server.py     # FastAPI application
└── requirements.txt
```

## API Documentation

Once running, visit: http://localhost:8000/docs

## Logs

Backend logs are printed to stdout. For production, consider redirecting to a file.

## Integration with Frontend

The frontend (in the parent `E-BIDDING-UNIFIED/` directory) connects to this backend at `http://127.0.0.1:8000`.

## Original Location

This code was originally in `OLD/BCF/backend_parallel_code_COPT_EDITS_IMPROVED - Copy_FORTRIAL_SPI - Copy/`