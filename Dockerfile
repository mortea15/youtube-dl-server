FROM python:alpine

LABEL maintainer="mortea15@github"

ENV USER=abc
ENV PUID=1000
ENV PGID=985

RUN addgroup -g $PGID $USER
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/tmp/$USER" \
    --ingroup "$USER" \
    --no-create-home \
    --uid "$PUID" \
    "$USER"

RUN apk add --no-cache \
  ffmpeg \
  tzdata \
  gcc \
  build-base \
  taglib-dev
      
RUN mkdir -p /usr/src/app
WORKDIR /usr/src/app

COPY requirements.txt /usr/src/app/
RUN apk --update-cache add --virtual build-dependencies gcc libc-dev make \
  && pip install --no-cache-dir -r requirements.txt \
  && apk del build-dependencies

COPY . /usr/src/app

EXPOSE 8080

VOLUME ["/youtube-dl"]

USER $USER

CMD ["uvicorn", "youtube-dl-server:app", "--host", "0.0.0.0", "--port", "8080"]
