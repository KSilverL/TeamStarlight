FROM node:20-bookworm-slim

# Chrome/Chromium headless deps required by Remotion renderer
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip \
    ffmpeg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    libxss1 \
    libxtst6 \
    xdg-utils \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Node deps (remotion render bundles from src/ on each job)
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts

# Python deps
COPY requirements.txt ./
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# App source
COPY src/ ./src/
COPY remotion.config.ts tsconfig.json ./
COPY agent/ ./agent/
COPY server.py ./

RUN mkdir -p out

EXPOSE 8001

CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
