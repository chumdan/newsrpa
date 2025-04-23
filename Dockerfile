FROM python:3.9.12-slim

# 작업 디렉토리를 app 폴더로 설정
WORKDIR /newsrpa/app

# 저장소 업데이트 및 패키지 설치 (더 안정적인 방법)
RUN apt-get clean && \
    apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    build-essential \
    wget \
    gnupg \
    unzip \
    curl \
    gcc \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

# Chrome 브라우저 설치
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ChromeDriver 설치 (특정 버전으로 고정)
RUN CHROMEDRIVER_VERSION=114.0.5735.90 \
    && wget -q "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip" \
    && unzip chromedriver_linux64.zip \
    && mv chromedriver /usr/local/bin/ \
    && chmod +x /usr/local/bin/chromedriver \
    && rm chromedriver_linux64.zip

# 패키지 설치 전 pip 업그레이드
RUN pip install --upgrade pip setuptools wheel

# 파일 복사 (경로 수정)
COPY ./app .
COPY ./frontend ../frontend
COPY ./backend ../backend
COPY ./.env ../.env
COPY ./requirements.txt ../requirements.txt

# 패키지 설치 - Windows 전용 패키지 제외
RUN grep -v -E "windows-curses|pywin32|pywinauto|comtypes|PySide2|shiboken2|QtPy" ../requirements.txt > requirements_linux.txt && \
    pip install --no-cache-dir -r requirements_linux.txt

# 헤드리스 모드로 Chrome 실행하기 위한 설정
ENV PYTHONPATH=/newsrpa
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# 권한 설정
RUN mkdir -p /newsrpa/logs
RUN chmod -R 777 /newsrpa

# 포트 노출 설정
EXPOSE 80

# 실행 명령어 (로컬과 동일하게)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]