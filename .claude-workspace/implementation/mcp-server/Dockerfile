FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY src/ ./src/

# Default environment
ENV CHROMA_HOST=chroma
ENV CHROMA_PORT=8000
ENV MCP_PORT=3000
ENV LOG_LEVEL=INFO

EXPOSE 3000

CMD ["python", "src/server.py"]
