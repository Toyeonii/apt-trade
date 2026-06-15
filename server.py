from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET
import time
import os

app = Flask(__name__)
CORS(app)

TRADE_API = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
RENT_API  = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent'

API_KEY_TRADE = os.environ.get('API_KEY', '')
API_KEY_RENT  = os.environ.get('API_KEY_RENT', '')

_cache = {}
CACHE_TTL = 3600


def parse_xml_items(xml_text, mode='trade'):
    root = ET.fromstring(xml_text)
    result_code = root.findtext('.//resultCode') or ''
    result_msg  = root.findtext('.//resultMsg') or ''
    if result_code and result_code not in ('00', '000', '0000', 'OK'):
        raise ValueError(f'API 오류 [{result_code}]: {result_msg}')

    items = []
    for item in root.findall('.//item'):
        def g(tag, item=item):
            v = item.findtext(tag)
            return v.strip() if v else ''
        if mode == 'trade':
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
        else:
            items.append({
                'aptNm':          g('aptNm'),
                'excluUseAr':     g('excluUseAr'),
                'floor':          g('floor'),
                'deposit':        g('deposit'),
                'monthlyRent':    g('monthlyRent'),
                'contractTerm':   g('contractTerm'),
                'contractType':   g('contractType'),
                'dealYear':       g('dealYear'),
                'dealMonth':      g('dealMonth'),
                'dealDay':        g('dealDay'),
                'buildYear':      g('buildYear'),
                'umdNm':          g('umdNm'),
                'preDeposit':     g('preDeposit'),
                'preMonthlyRent': g('preMonthlyRent'),
            })
    return items


def fetch_month(lawd_cd, deal_ymd, mode, api_key, api_url):
    cache_key = f"{mode}_{lawd_cd}_{deal_ymd}"
    now = time.time()
    if cache_key in _cache:
        ts, items = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return items

    params = {
        'serviceKey': api_key,
        'LAWD_CD':    lawd_cd,
        'DEAL_YMD':   deal_ymd,
        'pageNo':     1,
        'numOfRows':  999,
    }

    for attempt in range(2):  # 최대 2회 시도
        try:
            resp = requests.get(api_url, params=params, timeout=30)
            resp.raise_for_status()
            items = parse_xml_items(resp.text, mode)
            _cache[cache_key] = (time.time(), items)
            return items
        except requests.exceptions.Timeout:
            if attempt == 0:
                time.sleep(2)
            else:
                raise
    return []


@app.route('/api/trade/bulk')
def api_bulk():
    mode    = request.args.get('mode', 'trade')
    lawd_cd = request.args.get('LAWD_CD', '')
    months  = request.args.get('months', '')

    api_key = API_KEY_TRADE if mode == 'trade' else API_KEY_RENT
    api_url = TRADE_API if mode == 'trade' else RENT_API

    if not api_key:
        return jsonify({'error': f'API 키 미설정 (mode={mode})'}), 500
    if not all([lawd_cd, months]):
        return jsonify({'error': '필수 파라미터 누락'}), 400

    month_list = [m.strip() for m in months.split(',') if m.strip()]
    if len(month_list) > 24:
        return jsonify({'error': '최대 24개월'}), 400

    # 메모리 절약을 위해 순차 처리 (병렬 제거)
    all_items, errors = [], []
    for ym in month_list:
        try:
            items = fetch_month(lawd_cd, ym, mode, api_key, api_url)
            all_items.extend(items)
        except Exception as e:
            errors.append(f"{ym}: {str(e)}")

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
    return jsonify({'status': 'ok', 'trade_key': bool(API_KEY_TRADE), 'rent_key': bool(API_KEY_RENT)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
