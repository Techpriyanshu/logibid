# E-Bidding Frontend

A React TypeScript frontend for the E-Bidding system, built with Vite and shadcn/ui.

## Project Structure

This is part of the unified E-Bidding system with the backend located in the parent `backend/` directory.

```
E-BIDDING-UNIFIED/
├── backend/              # Python FastAPI backend
├── frontend/            # React frontend
│   ├── src/
│   │   ├── api/         # API clients
│   │   ├── components/  # React components
│   │   ├── pages/       # Page components
│   │   └── ...
│   └── ...
```

## Tech Stack

- **Vite** - Build tool and dev server
- **React 18** - UI library
- **TypeScript** - Type safety
- **shadcn/ui** - Component library
- **Tailwind CSS** - Styling
- **TanStack Router** - Routing
- **Zustand** - State management

## Quick Start

### Prerequisites

- Node.js 18+
- npm or bun

### Installation

```bash
cd E-BIDDING-UNIFIED/frontend
npm install
# or
bun install
```

### Environment Variables

Create a `.env` file with:

```
VITE_API_BASE_URL=http://127.0.0.1:8000
```

### Running

```bash
npm run dev
# or
bun run dev
```

The frontend will be available at http://localhost:5173

## Available Scripts

- `npm run dev` - Start dev server
- `npm run build` - Build for production
- `npm run preview` - Preview production build
- `npm run lint` - Run ESLint

## Integration with Backend

The frontend connects to the Python FastAPI backend at `http://127.0.0.1:8000`.

Make sure the backend is running before starting the frontend:

```bash
cd E-BIDDING-UNIFIED/backend
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload
```

## API Clients

Located in `src/api/`:
- `trucks.ts` - Truck management endpoints
- `bidOutcomes.ts` - Bid outcomes endpoints
- `liveBids.ts` - Live bids endpoints
- `fleetAdmin.ts` - Fleet admin endpoints
- `successfulBids.ts` - Successful bids endpoints
- `masterData.ts` - Master data endpoints

## Components

Located in `src/components/`:
- `depot-card.tsx` - Depot display card
- `depot-entry-row.tsx` - Depot entry row
- `NavLink.tsx` - Navigation link component

See `src/components/bidding/` and `src/components/fleet/` for more components.

## Pages

Located in `src/pages/`:
- `Index.tsx` - Main landing page
- `Login.tsx` - Login page
- `NotFound.tsx` - 404 page

## Development

### Running with Backend

**Terminal 1 - Backend:**
```bash
cd E-BIDDING-UNIFIED/backend
uvicorn backend_server:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 - Frontend:**
```bash
cd E-BIDDING-UNIFIED/frontend
npm run dev
```

### Building for Production

```bash
npm run build
```

The production build will be in the `dist/` directory.

## Original Location

This frontend was originally in `FRONTEND_E-BIDDING_111/`