from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

app = Flask(__name__)
CORS(app)

API_BASE = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'

# 캐시: { "11680_202501": (timestamp, items) }
_cache = {}
CACHE_TTL = 3600  # 1시간


def fetch_one_month(api_key, lawd_cd, deal_ymd):
    cache_key = f"{lawd_cd}_{deal_ymd}"
    now = time.time()

    # 캐시 히트
    if cache_key in _cache:
        ts, items = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return deal_ymd, items, True  # (월, 데이터, 캐시여부)

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


@app.route('/api/trade')
def api_trade():
    api_key  = request.args.get('serviceKey', '')
    lawd_cd  = request.args.get('LAWD_CD', '')
    deal_ymd = request.args.get('DEAL_YMD', '')

    if not all([api_key, lawd_cd, deal_ymd]):
        return jsonify({'error': '필수 파라미터 누락'}), 400

    try:
        _, items, cached = fetch_one_month(api_key, lawd_cd, deal_ymd)
        return jsonify({'ok': True, 'items': items, 'count': len(items), 'cached': cached})
    except requests.exceptions.Timeout:
        return jsonify({'error': '응답 시간 초과'}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'네트워크 오류: {str(e)}'}), 502
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'서버 오류: {str(e)}'}), 500


@app.route('/api/trade/bulk')
def api_trade_bulk():
    """여러 달을 한 번에 병렬 조회"""
    api_key  = request.args.get('serviceKey', '')
    lawd_cd  = request.args.get('LAWD_CD', '')
    months   = request.args.get('months', '')  # "202501,202502,202503"

    if not all([api_key, lawd_cd, months]):
        return jsonify({'error': '필수 파라미터 누락'}), 400

    month_list = [m.strip() for m in months.split(',') if m.strip()]
    if len(month_list) > 24:
        return jsonify({'error': '최대 24개월'}), 400

    all_items = []
    errors = []

    # 최대 8개 스레드로 병렬 처리
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_one_month, api_key, lawd_cd, ym): ym
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
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
