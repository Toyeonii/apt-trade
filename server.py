from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import os

app = Flask(__name__)
CORS(app)

TRADE_API = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'
RENT_API  = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent'

API_KEY_TRADE    = os.environ.get('API_KEY', '').strip()
API_KEY_RENT     = os.environ.get('API_KEY_RENT', '').strip()
API_KEY_APT_LIST = os.environ.get('API_KEY_APT_LIST', '').strip()
API_KEY_APT_INFO = os.environ.get('API_KEY_APT_INFO', '').strip()

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
                'aptNm':        g('aptNm'),
                'excluUseAr':   g('excluUseAr'),
                'floor':        g('floor'),
                'dealAmount':   g('dealAmount'),
                'dealYear':     g('dealYear'),
                'dealMonth':    g('dealMonth'),
                'dealDay':      g('dealDay'),
                'buildYear':    g('buildYear'),
                'roadNm':       g('roadNm'),
                'roadNmBonbun': g('roadNmBonbun'),
                'umdNm':        g('umdNm'),
                'jibun':        g('jibun'),
                'aptSeq':       g('aptSeq'),
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
                'jibun':          g('jibun'),
                'roadNm':         g('roadNm'),
                'aptSeq':         g('aptSeq'),
                'preDeposit':     g('preDeposit'),
                'preMonthlyRent': g('preMonthlyRent'),
            })
    return items


def fetch_month(lawd_cd, deal_ymd, mode='trade'):
    cache_key = f"{mode}_{lawd_cd}_{deal_ymd}"
    now = time.time()
    if cache_key in _cache:
        ts, items = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return deal_ymd, items, True

    api_url = TRADE_API if mode == 'trade' else RENT_API
    api_key = API_KEY_TRADE if mode == 'trade' else API_KEY_RENT

    params = {
        'serviceKey': api_key,
        'LAWD_CD':    lawd_cd,
        'DEAL_YMD':   deal_ymd,
        'pageNo':     1,
        'numOfRows':  999,
    }
    resp = requests.get(api_url, params=params, timeout=30)
    resp.raise_for_status()
    items = parse_xml_items(resp.text, mode)
    _cache[cache_key] = (time.time(), items)
    return deal_ymd, items, False


@app.route('/api/trade/bulk')
def api_bulk():
    mode    = request.args.get('mode', 'trade')
    lawd_cd = request.args.get('LAWD_CD', '')
    months  = request.args.get('months', '')

    api_key = API_KEY_TRADE if mode == 'trade' else API_KEY_RENT
    if not api_key:
        return jsonify({'error': f'API 키 미설정 (mode={mode})'}), 500
    if not all([lawd_cd, months]):
        return jsonify({'error': '필수 파라미터 누락'}), 400

    month_list = [m.strip() for m in months.split(',') if m.strip()]
    if len(month_list) > 24:
        return jsonify({'error': '최대 24개월'}), 400

    all_items, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_month, lawd_cd, ym, mode): ym for ym in month_list}
        for future in as_completed(futures):
            try:
                _, items, _ = future.result()
                all_items.extend(items)
            except Exception as e:
                errors.append(f"{futures[future]}: {str(e)}")

    return jsonify({'ok': True, 'items': all_items, 'count': len(all_items), 'errors': errors})



@app.route('/api/kakao-key')
def kakao_key():
    key = os.environ.get('KAKAO_MAP_KEY', '')
    if not key:
        return jsonify({'error': 'KAKAO_MAP_KEY 미설정'}), 500
    return jsonify({'key': key})

_apt_list_cache = {}  # {sgg_cd: [{kaptCode, kaptName, ...}]}

def fetch_apt_list(sgg_cd):
    if sgg_cd in _apt_list_cache:
        return _apt_list_cache[sgg_cd]
    all_items = []
    page = 1
    while True:
        url = f"https://apis.data.go.kr/1613000/AptListService3/getSigunguAptList3?serviceKey={API_KEY_APT_LIST}&sigunguCode={sgg_cd}&pageNo={page}&numOfRows=100&_type=json"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        body = data.get('response', {}).get('body', {})
        items = body.get('items', [])
        if isinstance(items, dict):
            items = items.get('item', [])
        if not items:
            break
        for item in (items if isinstance(items, list) else [items]):
            all_items.append({
                'kaptCode': item.get('kaptCode', ''),
                'kaptName': item.get('kaptName', ''),
                'bjdCode':  item.get('bjdCode', ''),
            })
        total = int(body.get('totalCount', 0))
        if page * 100 >= total:
            break
        page += 1
    _apt_list_cache[sgg_cd] = all_items
    return all_items


@app.route('/api/apt-info')
def apt_info():
    apt_nm  = request.args.get('aptNm', '')
    sgg_cd  = request.args.get('sggCd', '')
    if not apt_nm or not sgg_cd:
        return jsonify({'error': 'aptNm, sggCd 필요'}), 400
    if not API_KEY_APT_LIST or not API_KEY_APT_INFO:
        return jsonify({'error': 'API 키 미설정'}), 500

    try:
        # 1단계: 단지 목록에서 kaptCode 찾기
        apt_list = fetch_apt_list(sgg_cd)
        # 아파트명 정규화 (공백/특수문자 제거 후 비교)
        import re
        def normalize(s):
            return re.sub(r'[\s\(\)\-_]', '', s).lower()
        norm_nm = normalize(apt_nm)
        kapt_code = ''
        for apt in apt_list:
            if normalize(apt['kaptName']) == norm_nm:
                kapt_code = apt['kaptCode']
                break
        # 부분 매칭 시도
        if not kapt_code:
            for apt in apt_list:
                if norm_nm in normalize(apt['kaptName']) or normalize(apt['kaptName']) in norm_nm:
                    kapt_code = apt['kaptCode']
                    break
        if not kapt_code:
            return jsonify({'ok': False, 'data': {}, 'msg': '단지 없음'})

        # 2단계: 기본정보 조회
        info_url = f"https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusBassInfoV4?serviceKey={API_KEY_APT_INFO}&kaptCode={kapt_code}&_type=json"
        resp = requests.get(info_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        item = data.get('response', {}).get('body', {}).get('item', {})
        if not item:
            return jsonify({'ok': False, 'data': {}})

        result = {
            'kaptName':    str(item.get('kaptName', '')),
            'kaptDongCnt': str(item.get('kaptDongCnt', '')),
            'kaptdaCnt':   str(int(item.get('kaptdaCnt', 0) or 0)),
            'kaptUsedate': str(item.get('kaptUsedate', '')),
            'kaptBcompany':str(item.get('kaptBcompany', '')),
            'kaptTopFloor':str(item.get('kaptTopFloor', '')),
            'doroJuso':    str(item.get('doroJuso', '')),
        }

        # 3단계: 상세정보 조회 (주차대수)
        try:
            dtl_url = f"https://apis.data.go.kr/1613000/AptBasisInfoServiceV4/getAphusDtlInfoV4?serviceKey={API_KEY_APT_INFO}&kaptCode={kapt_code}&_type=json"
            dtl_resp = requests.get(dtl_url, timeout=10)
            dtl_resp.raise_for_status()
            dtl_data = dtl_resp.json()
            dtl_item = dtl_data.get('response', {}).get('body', {}).get('item', {})
            if dtl_item:
                park_up = dtl_item.get('parkingSpaceCount', 0) or 0
                park_down = dtl_item.get('parkingGroundCount', 0) or 0
                total_park = int(park_up or 0) + int(park_down or 0)
                kaptdaCnt = int(item.get('kaptdaCnt', 0) or 0)
                if total_park > 0 and kaptdaCnt > 0:
                    result['parkingPerHouse'] = f"{total_park/kaptdaCnt:.1f}"
                result['parkingTotal'] = str(total_park)
        except:
            pass

        return jsonify({'ok': True, 'data': result, 'kaptCode': kapt_code})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read()

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json') if False else \
        (__import__('flask').Response(open('manifest.json').read(), mimetype='application/json'))

@app.route('/icon.png')
def icon():
    return __import__('flask').send_file('icon.png', mimetype='image/png')

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'trade_key': bool(API_KEY_TRADE), 'rent_key': bool(API_KEY_RENT), 'apt_list_key': bool(API_KEY_APT_LIST), 'apt_info_key': bool(API_KEY_APT_INFO)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
