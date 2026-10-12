# ---- build stage: compile the C++ extension engine/_native ----
FROM python:3.14-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ cmake make libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "pybind11>=3.1,<4"

WORKDIR /app
COPY CMakeLists.txt ./
COPY src ./src
RUN mkdir engine \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
        -DPython_EXECUTABLE=/usr/local/bin/python \
    && cmake --build build --target _native

# ---- runtime stage: no compiler, only Python and the built module ----
FROM python:3.14-slim

RUN pip install --no-cache-dir "requests>=2.32,<3" "python-dotenv>=1.2.4,<2"

# uid 1000 matches the default user on EC2 images, so ./data stays writable
RUN useradd --uid 1000 --create-home monitor \
    && mkdir /data && chown monitor /data

WORKDIR /app
COPY engine ./engine
COPY main.py service.py ./
COPY --from=build /app/engine/ ./engine/

ENV COURSE_MONITOR_DB=/data/course_monitor.db \
    PYTHONUNBUFFERED=1
USER monitor
VOLUME /data

CMD ["python", "service.py"]
