from sqlalchemy import Column, Integer, String, Boolean, DateTime
from .database import Base, engine
import secrets
from datetime import datetime

class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    employee_id = Column(String(20), nullable=False, unique=True, index=True)
    email = Column(String(100), unique=True, index=True)
    is_active = Column(Boolean, default=True)
    unsubscribe_token = Column(String(64), unique=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)

class Config:
    from_attributes = True

class News(Base):
    __tablename__ = "news"
    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(50))
    headline = Column(String(500))
    url = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)

# 기존 테이블 삭제 후 재생성
# Base.metadata.drop_all(bind=engine)  # 주의: 모든 데이터 삭제됨
Base.metadata.create_all(bind=engine)

def add_test_subscribers(db, count=50, start_index=None):
    """테스트용 구독자를 한번에 추가하는 함수"""
    import secrets
    from datetime import datetime
    
    try:
        # 시작 인덱스가 없으면 현재 DB의 최대 인덱스 찾기
        if start_index is None:
            # 이메일 형식이 'test숫자@example.com'인 구독자 중 가장 큰 숫자 찾기
            import re
            all_subscribers = db.query(Subscriber).all()
            max_index = 0
            
            for sub in all_subscribers:
                if sub.email and sub.email.startswith('test') and sub.email.endswith('@example.com'):
                    match = re.search(r'test(\d+)@example\.com', sub.email)
                    if match and match.group(1).isdigit():
                        index = int(match.group(1))
                        max_index = max(max_index, index)
            
            start_index = max_index + 1
        
        # 구독자 생성
        subscribers = []
        for i in range(start_index, start_index + count):
            # 구독자 정보 생성
            email = f"test{i}@example.com"
            name = f"테스트사용자{i}"
            employee_id = f"EMP{i:04d}"  # EMP0001, EMP0002 등 형식으로
            
            # 토큰 생성
            token = Subscriber.generate_token()
            
            # 이미 존재하는지 확인
            existing = db.query(Subscriber).filter(
                Subscriber.email == email
            ).first()
            
            if existing:
                print(f"이미 존재하는 이메일: {email}")
                continue
                
            # 구독자 객체 생성 
            subscriber = Subscriber(
                name=name,
                employee_id=employee_id,
                email=email,
                unsubscribe_token=token,
                is_active=True,
                created_at=datetime.now()
            )
            subscribers.append(subscriber)
        
        # 데이터베이스에 한번에 추가
        db.add_all(subscribers)
        db.commit()
        
        print(f"{len(subscribers)}명의 테스트 구독자가 추가되었습니다")
        return len(subscribers)
    except Exception as e:
        db.rollback()
        print(f"테스트 구독자 추가 실패: {str(e)}")
        return 0