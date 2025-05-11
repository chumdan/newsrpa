import sys
import time
import signal
from threading import Thread
import schedule
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
import traceback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
import os
from pathlib import Path
from datetime import datetime

# 애플리케이션 모듈 임포트
from . import models
from . import database
from .database import engine, SessionLocal, get_db
from .models import add_test_subscribers
from .news_crawler import (
    collect_all_headlines,
    send_headlines_email,
    generate_weekly_excel_report,
    send_weekly_report_email
)

#################################################
# 초기화 및 설정
#################################################

# 데이터 베이스 초기화
models.Base.metadata.create_all(bind=engine)

# FastAPI 앱 생성
app = FastAPI()

# 프로젝트 루트 디렉토리 찾기
BASE_DIR = Path(__file__).resolve().parent.parent

# 템플릿과 정적 파일 설정
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "frontend", "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "frontend", "static")), name="static")

# 보안 미들웨어 설정 - .git 경로 접근 차단
@app.middleware("http")
async def filter_git_requests(request, call_next):
    if ".git" in request.url.path:
        return Response(status_code=403)  # Forbidden
    return await call_next(request)

# 전역 변수로 스케줄러 스레드 관리
scheduler_thread = None
stop_scheduler = False
is_running = {'news': False, 'weekly': False}

# Pydantic 모델 정의
class SubscribeRequest(BaseModel):
    name: str
    employee_id: str
    email: str

#################################################
# 스케줄링 및 백그라운드 작업 함수
#################################################

def run_news_with_lock():
    """
    뉴스 수집 및 이메일 발송 작업 처리 (중복 실행 방지 락 적용)
    매일 오전 7:30에 스케줄러에 의해 자동 실행
    """
    global is_running
    if is_running['news']:
        print("뉴스 수집 작업이 이미 실행 중입니다.")
        return
    is_running['news'] = True
    try:
        # 헤드라인 수집 및 발송
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        with webdriver.Chrome(options=chrome_options) as driver:
            wait = WebDriverWait(driver, 10)
            all_headlines = collect_all_headlines(driver, wait)
            
            # 구독자 목록 가져오기
            db = SessionLocal()
            
            # 수집한 헤드라인을 DB에 저장
            print("수집한 헤드라인을 DB에 저장합니다...")
            saved_count = 0
            for headline in all_headlines:
                # 이미 존재하는 뉴스인지 확인
                existing_news = db.query(models.News).filter(
                    models.News.source == headline['source'],
                    models.News.headline == headline['headline']
                ).first()
                
                if not existing_news:
                    # 새로운 뉴스 저장
                    new_news = models.News(
                        source=headline['source'],
                        headline=headline['headline'],
                        url=headline['url'],
                        created_at=headline['published_at']  # published_at을 created_at에 매핑
                    )
                    db.add(new_news)
                    saved_count += 1
            
            # 변경사항 커밋
            db.commit()
            print(f"DB에 {saved_count}건의 새로운 헤드라인이 저장되었습니다.")
            
            # 구독자 목록 확인
            subscribers = db.query(models.Subscriber).filter(models.Subscriber.is_active == True).all()
            db.close()
            
            if subscribers:
                send_headlines_email(all_headlines, subscribers)
    finally:
        is_running['news'] = False

def run_schedule():
    """
    스케줄러 실행 루프 - 백그라운드 스레드에서 실행됨
    """
    global stop_scheduler
    while not stop_scheduler:
        schedule.run_pending()
        time.sleep(1)

def run_weekly_report_with_lock():
    """
    주간 뉴스 리포트 생성 및 발송 작업 (락 적용)
    매주 금요일 16:30에 스케줄러에 의해 자동 실행
    """
    global is_running
    if is_running['weekly']:
        print("주간 리포트 작업이 이미 실행 중입니다.")
        return
    
    is_running['weekly'] = True
    try:
        # DB 세션 생성
        db = SessionLocal()
        
        # 주간 보고서 생성 및 발송
        result = send_weekly_report_email(db)
        
        # 결과 로깅
        if result['success']:
            print(f"주간 보고서 발송 완료: {result['message']}")
        else:
            print(f"주간 보고서 발송 실패: {result['message']}")
        
        db.close()
    except Exception as e:
        print(f"주간 보고서 작업 중 오류 발생: {str(e)}")
        import traceback
        print(traceback.format_exc())
    finally:
        is_running['weekly'] = False

def schedule_news_service():
    """
    스케줄러 초기화 및 작업 등록
    서버 시작 시 실행됨
    """
    global scheduler_thread, stop_scheduler
    
    # 기존 스케줄러가 실행 중이면 완전히 중지
    if scheduler_thread and scheduler_thread.is_alive():
        stop_scheduler = True
        scheduler_thread.join()
        time.sleep(2)  # 완전히 종료되기를 기다림
    
    # 스케줄러 초기화
    schedule.clear()
    stop_scheduler = False
    
    # 일일 뉴스 수집 및 발송 스케줄 (매일 07:30)
    schedule.every().day.at("07:30").do(run_news_with_lock)
    
    # 주간 보고서 생성 및 발송 스케줄 (매주 금요일 16:30)
    schedule.every().friday.at("16:30").do(run_weekly_report_with_lock)
    
    # 스케줄러 스레드 시작
    scheduler_thread = Thread(target=run_schedule, daemon=True)
    scheduler_thread.start()

#################################################
# 이벤트 핸들러 및 시그널 처리
#################################################

# 서버 시작 시 스케줄러 시작
@app.on_event("startup")
async def startup_event():
    schedule_news_service()

# 서버 종료 시 스케줄러 정리
@app.on_event("shutdown")
async def shutdown_event():
    global stop_scheduler
    stop_scheduler = True
    if scheduler_thread:
        scheduler_thread.join(timeout=1)

# 종료 시그널 핸들러 - 서버 종료 시 스케줄러 정리
def signal_handler(signum, frame):
    global stop_scheduler
    print("\n서버 종료 중...")
    stop_scheduler = True
    if scheduler_thread:
        scheduler_thread.join(timeout=1)
    sys.exit(0)

# 종료 시그널 등록
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

#################################################
# 기본 사용자 기능 엔드포인트
#################################################

# 메인 페이지 (구독 신청 폼)
@app.get("/")
async def home(request: Request):
    """메인 페이지 - 구독 신청 폼 제공"""
    return templates.TemplateResponse("index.html", {"request": request})

# 구독 신청 처리
@app.post("/subscribe/")
def subscribe(subscriber: SubscribeRequest):
    """구독 신청 처리 엔드포인트"""
    db = SessionLocal()
    try:
        # 이메일 중복 체크
        if db.query(models.Subscriber).filter(models.Subscriber.email == subscriber.email).first():
            raise HTTPException(status_code=400, detail="이미 구독 중인 이메일입니다.")
        
        # 사번 중복 체크
        if db.query(models.Subscriber).filter(models.Subscriber.employee_id == subscriber.employee_id).first():
            raise HTTPException(status_code=400, detail="이미 구독 중인 사번입니다.")
        
        db_subscriber = models.Subscriber(
            name=subscriber.name,
            employee_id=subscriber.employee_id,
            email=subscriber.email,
            unsubscribe_token=models.Subscriber.generate_token()
        )
        db.add(db_subscriber)
        db.commit()
        return {"message": "구독이 완료되었습니다."}
    finally:
        db.close()

# 구독 취소 페이지
@app.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_page(request: Request, token: str):
    """구독 취소 확인 페이지"""
    db = SessionLocal()
    try:
        subscriber = db.query(models.Subscriber).filter(
            models.Subscriber.unsubscribe_token == token
        ).first()
        
        if not subscriber:
            return templates.TemplateResponse(
                "unsubscribe.html",
                {"request": request, "subscriber": None, "token": token, "error": "잘못된 구독 취소 링크입니다."}
            )
        
        return templates.TemplateResponse(
            "unsubscribe.html",
            {"request": request, "subscriber": subscriber, "token": token}
        )
    finally:
        db.close()

# 구독 취소 처리 (JavaScript에서 호출)
@app.post("/unsubscribe/{token}")
async def unsubscribe(token: str, db: Session = Depends(database.get_db)):
    """구독 취소 처리 엔드포인트"""
    subscriber = db.query(models.Subscriber).filter(
        models.Subscriber.unsubscribe_token == token
    ).first()
    
    if not subscriber:
        raise HTTPException(status_code=404, detail="잘못된 구독 취소 링크입니다.")
    
    db.delete(subscriber)
    db.commit()
    
    return {"message": "구독이 성공적으로 취소되었습니다."}

#################################################
# 주요 기능 엔드포인트
#################################################

# 뉴스 수집 및 발송 수동 실행 엔드포인트
@app.get("/headlines-now")
def headlines_now(db: Session = Depends(database.get_db)):
    """
    헤드라인 수집 및 이메일 발송을 수동으로 실행하는 엔드포인트
    수집한 뉴스를 DB에 저장하고 구독자에게 이메일로 발송
    run_news_with_lock과 동일한 환경에서 테스트 가능
    """
    try:
        # 헤드라인 수집 및 발송 (run_news_with_lock과 동일하게 구성)
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        with webdriver.Chrome(options=chrome_options) as driver:
            wait = WebDriverWait(driver, 10)
            
            # 헤드라인 수집
            all_headlines = collect_all_headlines(driver, wait)
            
            # 수집한 헤드라인을 DB에 저장
            print("수집한 헤드라인을 DB에 저장합니다...")
            saved_count = 0
            for headline in all_headlines:
                # 이미 존재하는 뉴스인지 확인
                existing_news = db.query(models.News).filter(
                    models.News.source == headline['source'],
                    models.News.headline == headline['headline']
                ).first()
                
                if not existing_news:
                    # 새로운 뉴스 저장
                    new_news = models.News(
                        source=headline['source'],
                        headline=headline['headline'],
                        url=headline['url'],
                        created_at=headline['published_at']  # published_at을 created_at에 매핑
                    )
                    db.add(new_news)
                    saved_count += 1
            
            # 변경사항 커밋
            db.commit()
            print(f"DB에 {saved_count}건의 새로운 헤드라인이 저장되었습니다.")
            
            # 구독자 목록 가져오기
            subscribers = db.query(models.Subscriber).filter(models.Subscriber.is_active == True).all()
            
            # 이메일 발송
            if subscribers:
                result = send_headlines_email(all_headlines, subscribers)
                email_result = f"이메일 {result['success']}건 발송 성공, {result['fail']}건 실패"
            else:
                email_result = "구독자가 없어 이메일을 발송하지 않았습니다."
            
            return {
                "success": True,
                "message": "헤드라인 수집, DB 저장 및 이메일 발송 완료",
                "headline_count": len(all_headlines),
                "saved_to_db": saved_count,
                "email_result": email_result
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"헤드라인 수집 및 이메일 발송 실패: {str(e)}",
            "error_details": traceback.format_exc()
        }

# 주간 리포트 이메일 발송 수동 실행 엔드포인트
@app.get("/api/send-weekly-report")
def api_send_weekly_report(
    start_date: str = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    주간 리포트 이메일 발송을 수동으로 실행하는 엔드포인트
    주간 뉴스 데이터를 Excel 파일로 생성하고 구독자에게 이메일로 발송
    """
    try:
        # 날짜 변환
        start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
        
        # 주간 보고서 이메일 발송
        result = send_weekly_report_email(db, None, start_dt, end_dt)
        
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"주간 리포트 이메일 발송 중 오류 발생: {str(e)}"
        }

#################################################
# 관리용 엔드포인트
#################################################

# 주간 엑셀 리포트 생성 엔드포인트 (이메일 발송 없음)
@app.get("/api/generate-excel-report")
def api_generate_excel_report(
    start_date: str = Query(None, description="시작 날짜 (YYYY-MM-DD)"),
    end_date: str = Query(None, description="종료 날짜 (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    주간 엑셀 리포트 생성 엔드포인트 (파일만 생성, 이메일 발송 없음)
    관리자용 기능으로 리포트 파일 생성만 수행
    """
    try:
        # 날짜 변환
        start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
        
        # 엑셀 리포트 생성
        filepath = generate_weekly_excel_report(db, start_dt, end_dt)
        
        if filepath:
            return {
                "success": True,
                "message": "엑셀 리포트가 성공적으로 생성되었습니다.",
                "file_path": filepath
            }
        else:
            return {
                "success": False,
                "message": "엑셀 리포트 생성에 실패했습니다. 해당 기간에 데이터가 없을 수 있습니다."
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"엑셀 리포트 생성 중 오류 발생: {str(e)}"
        }

# 테스트용 구독자 추가 엔드포인트 (운영 환경에서는 주석 처리 고려)
@app.get("/api/add-test-subscribers")
def add_test_subscribers(
    count: int = Query(30, description="추가할 테스트 구독자 수", ge=1, le=500),
    start_index: int = Query(None, description="시작 인덱스 (없으면 자동 계산)"),
    db: Session = Depends(get_db)
):
    """
    테스트용 구독자를 데이터베이스에 추가하는 엔드포인트
    테스트 환경에서만 사용하며, 운영 환경에서는 비활성화 고려
    """
    added_count = models.add_test_subscribers(db, count, start_index)
    
    if added_count > 0:
        return {
            "status": "success", 
            "message": f"{added_count}명의 테스트 구독자가 추가되었습니다."
        }
    elif added_count == 0:
        return {
            "status": "info",
            "message": "추가된 구독자가 없습니다. 이미 모든 테스트 이메일이 존재할 수 있습니다."
        }
    else:
        raise HTTPException(
            status_code=500, 
            detail="테스트 구독자 추가 중 오류가 발생했습니다."
        )

# 새로운 엔드포인트 추가
@app.get("/api/ping")
def ping():
    return {"status": "ok", "timestamp": str(datetime.now())}

#################################################
# 서버 실행 설정
#################################################

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=80,
        reload=True,
        use_colors=False  # 색상 코드 비활성화
    )

# 실행 명령어
# uvicorn app.main:app --host 0.0.0.0 --port 80 --reload