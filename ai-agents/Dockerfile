FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8

COPY pyproject.toml README.md ./
COPY vitalmap_agent ./vitalmap_agent
RUN pip install --no-cache-dir .

COPY demo ./demo
COPY eval ./eval

EXPOSE 8000
CMD ["uvicorn", "vitalmap_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
