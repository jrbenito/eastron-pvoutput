FROM python:3-alpine
LABEL maintainer="Josenivaldo Benito Jr. <jrbenito@benito.qsl.br>"

COPY requirements.txt .
RUN pip install --no-cache-dir  -r requirements.txt
