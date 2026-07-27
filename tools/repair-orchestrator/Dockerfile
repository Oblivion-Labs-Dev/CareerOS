FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
ENV PYTHONPATH=/app/src

EXPOSE 8090
CMD ["python", "-m", "uvicorn", "repair_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8090"]
