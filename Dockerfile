# LOCA - Flask 서비스 이미지
#
# 로컬 개발 환경이 Python 3.13 이므로 베이스도 3.13 으로 맞춘다.
# 버전이 어긋나면 requirements.txt 의 고정 버전이 설치되지 않을 수 있다.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul

WORKDIR /app

# 의존성을 먼저 복사한다. 코드만 바뀌었을 때 이 레이어를 재사용해
# 재빌드가 빨라진다.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "web/app.py"]
