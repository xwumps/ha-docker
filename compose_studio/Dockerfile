FROM docker:28.5.2-cli AS docker
FROM python:3.13-alpine3.22
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
WORKDIR /app
COPY app/ /app/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8099
CMD ["python3", "/app/server.py"]
