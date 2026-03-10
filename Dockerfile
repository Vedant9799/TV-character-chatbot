# ─────────────────────────────────────────────────────────────
# Stage 1 — Build the React / Vite frontend
# ─────────────────────────────────────────────────────────────
FROM node:20-slim AS ui-builder

WORKDIR /build/ui

# Install deps first (cached unless package.json changes)
COPY ui/package*.json ./
RUN npm ci

# Copy source and build
COPY ui/ ./
RUN npm run build
# Vite outDir is '../ui_dist' relative to ui/ → output lands at /build/ui_dist/


# ─────────────────────────────────────────────────────────────
# Stage 2 — Python backend + baked ChromaDB + built UI
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install Python deps (cached layer)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy server code
COPY server.py .
COPY build_chromadb.py .

# Build ChromaDB from the CSV once at image build time (~5-10 min).
# The resulting ./chroma_db/ is baked in so startup is instant at runtime.
COPY merged_tv_dialogues.csv .
RUN python build_chromadb.py --csv merged_tv_dialogues.csv --reset
RUN rm merged_tv_dialogues.csv

# Synthesised character profiles (optional — server uses built-ins if absent)
COPY character_profiles.jso[n] .

# Copy built React SPA from Stage 1
COPY --from=ui-builder /build/ui_dist/ ./static/

EXPOSE 8001

# Pass at runtime: docker run -e GROQ_API_KEY=gsk_... -p 8001:8001 tv-chatbot
ENV GROQ_API_KEY=""

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8001"]
