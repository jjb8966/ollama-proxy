#!/bin/bash

docker-compose pull && \
docker-compose up -d --build && \
docker image prune -a -f
