from .database import SessionLocal
from .models import add_test_subscribers, Subscriber

def main():
    db = SessionLocal()
    try:
        # 50명의 테스트 구독자 추가
        add_test_subscribers(db, count=50)
    finally:
        db.close()

if __name__ == "__main__":
    main()