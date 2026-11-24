FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY ui.py ./ui.py
RUN pip install --no-cache-dir '.'
ENV FREIGHT_DATA_DIR=/data
EXPOSE 8000 8501
CMD ["uvicorn", "freight_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
