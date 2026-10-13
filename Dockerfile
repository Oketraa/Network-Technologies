FROM python:3.12-slim

WORKDIR /usr/src/app

COPY . /usr/src/app

RUN pip install fastapi uvicorn

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]