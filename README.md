# EA Bot - Monorepo

Monorepo untuk EA Bot project - Next.js + Node.js/Express + Python FastAPI

## Prerequisites

- **Node.js** (>=18.0.0) - install dari https://nodejs.org/ atau gunakan full path:
  ```
  /c/Users/billy/AppData/Local/hermes/node/node
  ```
- **npm** (>=9.0.0) - bundled with Node.js
- **Python** (>=3.11) - untuk FastAPI service

## Struktur Project

```
project-ea-bot/
├── apps/
│   ├── web/          # Next.js frontend (React)
│   └── api/          # Node.js/Express backend
├── services/
│   └── python/       # FastAPI backend service
├── packages/
│   ├── shared/       # TypeScript shared types/utils
│   └── eslint-config/# Shared ESLint configuration
├── infrastructure/
│   ├── docker/       # Docker compose & Dockerfiles
│   └── db/           # Database initialization scripts
├── .github/
│   └── workflows/    # CI/CD workflows (GitHub Actions)
├── package.json      # Root package.json dengan workspaces
├── tsconfig.base.json # Base TypeScript configuration
├── .eslintrc.json    # Root ESLint configuration
├── .prettierrc       # Prettier configuration
└── README.md         # Dokumentasi ini
```

## Quick Start

### Install Dependencies

```bash
# Gunakan npm path jika node tidak dalam PATH
npm install
```

### Development Mode

Jalankan semua service dalam mode development:

```bash
# Root - jalankan semua workspaces
npm run dev
```

Atau jalankan secara individual:

```bash
# Next.js Web (http://localhost:3000)
cd apps/web && npm run dev

# Express API (http://localhost:3001)
cd apps/api && npm run dev

# FastAPI (http://localhost:8000)
cd services/python
pip install -r requirements.txt
uvicorn main:app --reload
```

### Build

```bash
# Build semua workspaces
npm run build

# Individual
cd packages/shared && npm run build
cd apps/api && npm run build
```

### Linting & Formatting

```bash
npm run lint      # ESLint pada semua workspaces
npm run format    # Prettier formatting
```

## Environment Variables

Salin `.env.example` ke `.env` dan sesuaikan nilai:

```bash
cp .env.example .env
```

## Docker

Jalankan semua service dengan Docker Compose:

```bash
docker-compose -f infrastructure/docker/docker-compose.yml up -d
```

Atau build dari awal:

```bash
docker-compose -f infrastructure/docker/docker-compose.yml up -d --build
```

## Database

Inisialisasi database PostgreSQL:

```bash
psql -U postgres -f infrastructure/db/init.sql
```

## GitHub Actions

CI/CD dikonfigurasi di `.github/workflows/ci.yml`:
- **lint**: Jalankan ESLint pada semua workspaces
- **build**: Build TypeScript packages
- **test**: Runner tests (Python + Node.js)

## License

MIT
