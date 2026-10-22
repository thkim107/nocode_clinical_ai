import re
import ast
import time as _time
from urllib.parse import quote
import requests
import xml.etree.ElementTree as ET
import json

from audit_logger import audit_log_sync
from telemetry import record_external_call_sync

PUBMED_REQUEST_TIMEOUT = (5, 20)  # connect/read seconds; never block a worker indefinitely

def to_json(text):
    """Parse JSON from LLM response, supporting ```json ... ``` format"""
    # First, try to extract from ```json ... ``` code block
    json_block_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if json_block_match:
        json_str = json_block_match.group(1).strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Fallback: find raw JSON object
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        dict_str = match.group()
        try:
            return json.loads(dict_str)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(dict_str)
            except:
                pass

    return None

def pop_first_n_from_columns(matrix, n=5):
    """
    각 열에서 순차적으로 첫 번째 요소를 pop하여 n개의 값을 모을 때까지 반복.
    내부 리스트가 비어 있어도 안전하게 처리함.
    """
    result = []

    while len(result) < n:
        any_popped = False
        # 열 인덱스를 기준으로 접근
        max_len = max((len(row) for row in matrix), default=0)
        for col_idx in range(max_len):
            for row in matrix:
                if col_idx < len(row):
                    result.append(row.pop(col_idx))
                    any_popped = True
                    break  # 다음 열로 넘어감
            if len(result) >= n:
                break
        if not any_popped:
            break  # 더 이상 pop할 수 있는 값이 없음
    return result

def generate_pubmed_search_url(term=None, title=None, author=None, journal=None, 
                               start_date=None, end_date=None, num_results=10, use_related=False):
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    query_parts = []
    # 연관도 기반 검색: term 중심
    if use_related and term:
        query = quote(term)
    else:
        if term:
            query_parts.append(quote(term))
        if title:
            query_parts.append(f"{quote(title)}[Title]")
        if author:
            query_parts.append(f"{quote(author)}[Author]")
        if journal:
            query_parts.append(f"{quote(journal)}[Journal]")
        if start_date and end_date:
            query_parts.append(f"{start_date}:{end_date}[Date - Publication]")
        query = " AND ".join(query_parts)
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": num_results,
        "retmode": "xml"
    }
    # 파라미터 문자열 구성
    param_str = "&".join(f"{key}={value}" for key, value in params.items())
    full_url = f"{base_url}?{param_str}"
    return full_url

def search_pubmed(search_url):
    t0 = _time.time()
    error_msg = None
    result_ids = []
    status_code = None
    try:
        response = requests.get(search_url, timeout=PUBMED_REQUEST_TIMEOUT)
        status_code = response.status_code
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            id_list = root.find("IdList")
            if id_list is not None:
                result_ids = [id.text for id in id_list.findall("Id")]
            else:
                print("No results found.")
        else:
            error_msg = f"status_code={response.status_code}"
            print(f"Error: Unable to fetch data (status code: {response.status_code})")
    except Exception as e:
        error_msg = str(e)
    finally:
        duration_ms = int((_time.time() - t0) * 1000)
        audit_log_sync(
            "platform", "pubmed", "esearch.fcgi", "GET",
            request_summary={"url_len": len(search_url)},
            response_status=status_code,
            response_summary={"result_count": len(result_ids)},
            duration_ms=duration_ms,
            error=error_msg,
        )
        record_external_call_sync(
            service="pubmed", operation="esearch", duration_ms=duration_ms,
            status_code=status_code, result_count=len(result_ids),
            success=error_msg is None and status_code == 200, error=error_msg,
            metadata={"query_chars": len(search_url)},
        )
    return result_ids

def get_pubmed_metadata(pmid):
    t0 = _time.time()
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml"
    error_msg = None
    status_code = None
    metadata = None
    try:
        response = requests.get(url, timeout=PUBMED_REQUEST_TIMEOUT)
        status_code = response.status_code

        if response.status_code == 200:
            root = ET.fromstring(response.content)
            article = root.find(".//Article")
            if article is not None:
                title = article.find(".//ArticleTitle")
                title = title.text if title is not None else "No title available"
                root = ET.fromstring(response.content)
                article = root.find(".//Article")

                abstract = article.findall(".//Abstract/AbstractText")
                abstract_text = str()
                for elem in abstract:
                    label = elem.attrib.get("Label", "UNLABELED")
                    text = elem.text.strip() if elem.text else ""
                    abstract_text += label + ': ' + text + '\n'

                authors = []
                for author in article.findall(".//Author"):
                    last_name = author.find(".//LastName")
                    if last_name is not None and last_name.text:
                        authors.append(last_name.text)
                authors = ", ".join(authors) if authors else "No authors available"

                journal = article.find(".//Journal/Title")
                journal = journal.text if journal is not None else "No journal available"

                pub_date = article.find(".//PubDate/Year")
                pub_date = pub_date.text if pub_date is not None else "No publication date available"

                metadata = {
                    "PMID": pmid,
                    "Title": title,
                    "Authors": authors,
                    "Journal": journal,
                    "Publication Date": pub_date,
                    "Abstract": abstract_text
                }
            else:
                error_msg = f"No article data found for PMID: {pmid}"
                print(error_msg)
        else:
            error_msg = f"status_code={response.status_code}"
            print(f"Error: Unable to fetch metadata (status code: {response.status_code})")
    except Exception as e:
        error_msg = str(e)
    finally:
        duration_ms = int((_time.time() - t0) * 1000)
        audit_log_sync(
            "platform", "pubmed", "efetch.fcgi", "GET",
            request_summary={"pmid": pmid},
            response_status=status_code,
            response_summary={"found": metadata is not None},
            duration_ms=duration_ms,
            error=error_msg,
        )
        record_external_call_sync(
            service="pubmed", operation="efetch", duration_ms=duration_ms,
            status_code=status_code, result_count=1 if metadata is not None else 0,
            success=error_msg is None and status_code == 200 and metadata is not None,
            error=error_msg, metadata={"pmid": str(pmid)},
        )
    return metadata
    
    
def remove_think_tags(text):
    return re.sub(r'\s*<think>.*?</think>\s*', '', text, flags=re.DOTALL)
