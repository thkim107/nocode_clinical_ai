import sqlite3
from datetime import datetime
from contextlib import contextmanager
import threading
import json


class JobStatusManager:
    def __init__(self, db_path: str = "/app/dbdata/job_status.db" ):
        self.db_path = db_path
        self.lock = threading.Lock()
    
    @contextmanager
    def _get_connection(self):
        """SQLite 연결 관리"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 딕셔너리 형태로 결과 반환
        try:
            yield conn
        finally:
            conn.close()
    
    def create_job(self, job_id:str,job_category: str = "eda-visualization") -> str:
        """새로운 job 생성"""
        current_time = datetime.now().isoformat()
        
        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO job_status 
                    (job_id, step, progress, message, error, created_at, updated_at, job_category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    job_id, 'queued', 0, 'Job queued for processing', '', 
                    current_time, current_time, job_category
                ))
                conn.commit()
    
    def update_job_status(self, job_id:str,step: str, progress: int, 
                         message: str = "", error: str = ""):
        """job 상태 업데이트"""
        current_time = datetime.now().isoformat()
        
        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE job_status 
                    SET step = ?, progress = ?, message = ?, error = ?, updated_at = ?
                    WHERE job_id = ?
                ''', (step, progress, message, error, current_time, job_id))
                conn.commit()
                
                if cursor.rowcount == 0:
                    raise ValueError(f"Job with ID {job_id} not found")
    
    def get_job_status(self, query: str) -> str:
        """특정 job 상태 조회"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                # 쿼리 타입에 따라 결과 처리
                if query.strip().upper().startswith('SELECT'):
                    # SELECT 쿼리의 경우 모든 결과를 가져옴
                    rows = cursor.fetchall()
                    if rows:
                        # sqlite3.Row를 딕셔너리 리스트로 변환하고 JSON 문자열로 반환
                        result = [dict(row) for row in rows]
                        return json.dumps(result, ensure_ascii=False, indent=2)
                    else:
                        return json.dumps([], ensure_ascii=False)
                else:
                    # INSERT, UPDATE, DELETE 등의 경우
                    affected_rows = cursor.rowcount
                    return json.dumps({"message": f"쿼리 실행 완료. 영향받은 행 수: {affected_rows}"}, ensure_ascii=False)
        except sqlite3.Error as e:
            error_msg = f"데이터베이스 오류 발생: {e}"
            print(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"예상치 못한 오류 발생: {e}"
            print(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
    
    def get_job_status_by_id(self, job_id: str) -> str:
        """job_id로 특정 job 상태 조회"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM job_status WHERE job_id = ?', (job_id,))
                row = cursor.fetchone()

                if row:
                    return json.dumps(dict(row), ensure_ascii=False, indent=2)
                else:
                    return json.dumps({"error": f"Job with ID {job_id} not found"}, ensure_ascii=False)
        except sqlite3.Error as e:
            error_msg = f"데이터베이스 오류 발생: {e}"
            print(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"예상치 못한 오류 발생: {e}"
            print(error_msg)
            return json.dumps({"error": error_msg}, ensure_ascii=False)

    def get_all_jobs(self) -> dict:
        """모든 job 상태 조회"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM job_status ORDER BY created_at DESC')
            rows = cursor.fetchall()

            return {row['job_id']: dict(row) for row in rows}
    
    def delete_job(self, job_id: str):
        """job 삭제"""
        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM job_status WHERE job_id = ?', (job_id,))
                conn.commit()
                
                if cursor.rowcount == 0:
                    raise ValueError(f"Job with ID {job_id} not found")
    
    def cleanup_old_jobs(self, days: int = 7):
        """오래된 job 정리 (기본 7일)"""
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)
        cutoff_str = cutoff_date.isoformat()

        with self.lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM job_status WHERE created_at < ?', (cutoff_str,))
                deleted_count = cursor.rowcount
                conn.commit()

        return deleted_count

    def get_latest_n_status(self, n: int) -> list:
        """가장 늦은 시간에 저장된 N개의 status rows 조회"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM job_status ORDER BY updated_at DESC LIMIT ?',
                (n,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

# 전역 인스턴스 생성
job_manager = JobStatusManager()

# 기존 코드와의 호환성을 위한 래퍼 함수들
def create_job(job_id:str, job_category: str) -> str:
    return job_manager.create_job(job_id, job_category)

def update_job_status(job_id: str, step: str, progress: int, message: str = "", error: str = ""):
    job_manager.update_job_status(job_id, step, progress, message, error)

async def get_job_status(query: str) -> str:
    return job_manager.get_job_status(query)

async def get_job_status_by_id(job_id: str) -> str:
    return job_manager.get_job_status_by_id(job_id)

def get_all_jobs() -> dict:
    return job_manager.get_all_jobs()

async def get_latest_n_status(n: int) -> list:
    return job_manager.get_latest_n_status(n)