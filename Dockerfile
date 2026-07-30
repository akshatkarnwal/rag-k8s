FROM python:3.11-slim

WORKDIR /app

# install uv
RUN pip install uv

# copy dependency files first (Docker layer caching)
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# copy app code
COPY app/ ./app/
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]