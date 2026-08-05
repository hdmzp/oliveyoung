"""scraper 패키지.

임포트 시점에 truststore 를 주입해 Python 이 OS(Windows) 인증서 저장소를 쓰도록 한다.
백신/보안 프로그램의 HTTPS 검사(SSL 인터셉션)로 self-signed 인증서가 끼어드는 환경에서
requests 가 CERTIFICATE_VERIFY_FAILED 로 실패하는 문제를 해결한다.
"""
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    # truststore 미설치/실패 시엔 기본 certifi 검증으로 동작
    pass
