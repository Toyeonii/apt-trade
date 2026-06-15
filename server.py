from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os

app = Flask(__name__)
CORS(app)

API_BASE = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
API_KEY  = os.environ.get('API_KEY', '')

# 캐시: { "11680_202501": (timestamp, items) }
_cache = {}
CACHE_TTL = 3600  # 1시간


def fetch_one_month(lawd_cd, deal_ymd):
    cache_key = f"{lawd_cd}_{deal_ymd}"
    now = time.time()

    if cache_key in _cache:
        ts, items = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return deal_ymd, items, True

    params = {
        'serviceKey': API_KEY,
        'LAWD_CD': lawd_cd,
        'DEAL_YMD': deal_ymd,
        'pageNo': 1,
        'numOfRows': 999,
    }
    resp = requests.get(API_BASE, params=params, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    result_code = root.findtext('.//resultCode') or ''
    result_msg  = root.findtext('.//resultMsg')  or ''

    if result_code and result_code not in ('00', '000', '0000', 'OK'):
        raise ValueError(f'API 오류 [{result_code}]: {result_msg}')

    items = []
    for item in root.findall('.//item'):
        def g(tag):
            v = item.findtext(tag)
            return v.strip() if v else ''
        items.append({
            'aptNm':      g('aptNm'),
            'excluUseAr': g('excluUseAr'),
            'floor':      g('floor'),
            'dealAmount': g('dealAmount'),
            'dealYear':   g('dealYear'),
            'dealMonth':  g('dealMonth'),
            'dealDay':    g('dealDay'),
            'buildYear':  g('buildYear'),
            'roadNm':     g('roadNm'),
            'umdNm':      g('umdNm'),
        })

    _cache[cache_key] = (now, items)
    return deal_ymd, items, False


@app.route('/api/trade/bulk')
def api_trade_bulk():
    if not API_KEY:
        return jsonify({'error': '서버에 API_KEY가 설정되지 않았습니다'}), 500

    lawd_cd = request.args.get('LAWD_CD', '')
    months  = request.args.get('months', '')

    if not all([lawd_cd, months]):
        return jsonify({'error': '필수 파라미터 누락'}), 400

    month_list = [m.strip() for m in months.split(',') if m.strip()]
    if len(month_list) > 24:
        return jsonify({'error': '최대 24개월'}), 400

    all_items = []
    errors = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_one_month, lawd_cd, ym): ym
            for ym in month_list
        }
        for future in as_completed(futures):
            try:
                ym, items, cached = future.result()
                all_items.extend(items)
            except Exception as e:
                errors.append(f"{futures[future]}: {str(e)}")

    return jsonify({
        'ok': True,
        'items': all_items,
        'count': len(all_items),
        'errors': errors
    })


@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read()


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'api_key_set': bool(API_KEY)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
