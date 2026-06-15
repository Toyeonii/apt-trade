"""
아파트 실거래가 조회 서버
실행: python server.py
접속: http://localhost:5000
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET
import os

app = Flask(__name__, static_folder='static')
CORS(app)

API_BASE = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'


def fetch_one_month(api_key, lawd_cd, deal_ymd):
    """한 달치 데이터 조회"""
    params = {
        'serviceKey': api_key,
        'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd,
        'pageNo': 1,
        'numOfRows': 999,
    }
    resp = requests.get(API_BASE, params=params, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)

    # 오류 코드 확인
    result_code = root.findtext('.//resultCode') or ''
    result_msg  = root.findtext('.//resultMsg')  or ''
    if result_code not in ('', '00', '0000'):
        raise ValueError(f'API 오류 [{result_code}]: {result_msg}')

    items = []
    for item in root.findall('.//item'):
        def g(tag):
            v = item.findtext(tag)
            return v.strip() if v else ''

        items.append({
            'aptNm':       g('aptNm'),
            'excluUseAr':  g('excluUseAr'),
            'floor':       g('floor'),
            'dealAmount':  g('dealAmount'),
            'dealYear':    g('dealYear'),
            'dealMonth':   g('dealMonth'),
            'dealDay':     g('dealDay'),
            'buildYear':   g('buildYear'),
            'roadNm':      g('roadNm'),
            'umdNm':       g('umdNm'),
            'jibun':       g('jibun'),
            'sggCd':       g('sggCd'),
            'cdealType':   g('cdealType'),
        })
    return items


@app.route('/api/trade')
def api_trade():
    api_key  = request.args.get('serviceKey', '')
    lawd_cd  = request.args.get('LAWD_CD', '')
    deal_ymd = request.args.get('DEAL_YMD', '')

    if not all([api_key, lawd_cd, deal_ymd]):
        return jsonify({'error': '필수 파라미터 누락'}), 400

    try:
        items = fetch_one_month(api_key, lawd_cd, deal_ymd)
        return jsonify({'ok': True, 'items': items, 'count': len(items)})
    except requests.exceptions.Timeout:
        return jsonify({'error': '공공데이터 API 응답 시간 초과'}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'네트워크 오류: {str(e)}'}), 502
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'서버 오류: {str(e)}'}), 500


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    import socket
    # 로컬 IP 표시 (같은 와이파이 모바일 접속용)
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
    except:
        local_ip = '알 수 없음'

    print("=" * 50)
    print("  아파트 실거래가 조회 서버 시작")
    print("=" * 50)
    print(f"  PC:     http://localhost:5000")
    print(f"  모바일: http://{local_ip}:5000  (같은 와이파이)")
    print("  종료:   Ctrl+C")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=False)
