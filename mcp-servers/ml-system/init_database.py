#!/usr/bin/env python3
"""
데이터베이스 초기화 스크립트
Docker 빌드 시 실행되어 SQLite 데이터베이스와 테이블을 생성합니다.
"""

import sqlite3
import os
from pathlib import Path

def init_database():
    """SQLite 데이터베이스 및 테이블 초기화"""
    
    # 데이터베이스 파일 경로
    db_path = "/app/dbdata/job_status.db"
    
    # 디렉토리가 없으면 생성
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # SQLite 연결
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # job_status 테이블 생성
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS job_status (
                job_id TEXT PRIMARY KEY,
                step TEXT NOT NULL,
                progress INTEGER NOT NULL,
                message TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                job_category TEXT NOT NULL
            )
        ''')
        
        # 인덱스 생성 (성능 최적화)
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_job_status_created_at 
            ON job_status(created_at)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_job_status_category 
            ON job_status(job_category)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_job_status_step 
            ON job_status(step)
        ''')
        
        # 변경사항 커밋
        conn.commit()
        
        print(f"✅ Database initialized successfully at {db_path}")
        
        # 테이블 정보 확인
        cursor.execute("PRAGMA table_info(job_status)")
        columns = cursor.fetchall()
        print("📋 Table structure:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
            
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    init_database()