from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError
from time import sleep

load_dotenv()

SQLALCHEMY_DATABASE_URL = "mysql+pymysql://newsuser:ckd12345@localhost:3306/news"

# 연결 재시도 함수
def create_engine_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            return create_engine(
                url,
                pool_recycle=1800,  # 30분마다 연결 재생성
                pool_pre_ping=True,  # 쿼리 실행 전 연결 상태 확인
                pool_size=5,         # 연결 풀 크기
                max_overflow=10,     # 추가로 생성할 수 있는 최대 연결 수
                connect_args={
                    'connect_timeout': 60,  # 연결 타임아웃 60초
                }
            )
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            sleep(1)

engine = create_engine_with_retry(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    except OperationalError as e:
        db.rollback()
        # 연결이 끊어진 경우 재시도
        if "MySQL server has gone away" in str(e):
            db = SessionLocal()
        raise
    finally:
        db.close()