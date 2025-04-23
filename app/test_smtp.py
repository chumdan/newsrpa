import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def test_single_email():
    try:
        sender_email = os.getenv("SMTP_USER")
        app_password = os.getenv("SMTP_PASSWORD")
        receiver_email = "donghyeon.goh@ckdpharm.com"  # 실제 테스트 이메일로 변경
        
        # 서버 연결 (디버그 모드)
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=120)  # Gmail IP 주소 (변경될 수 있음)
        server.set_debuglevel(1)  # 디버그 활성화
        server.starttls()
        print("STARTTLS 성공")
        
        # 로그인
        server.login(sender_email, app_password)
        print("로그인 성공")
        
        # 간단한 메시지 작성
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = "연결 테스트 이메일"
        body = "이것은 SMTP 연결 테스트 이메일입니다."
        msg.attach(MIMEText(body, 'plain'))
        
        # 이메일 전송
        server.send_message(msg)
        print(f"{receiver_email}로 테스트 이메일 전송 완료!")
        
        server.quit()
        return True
    except Exception as e:
        print(f"테스트 이메일 전송 실패: {str(e)}")
        return False

if __name__ == "__main__":
    test_single_email()