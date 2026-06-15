from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET

app = Flask(__name__)
CORS(app)

API_BASE = 'https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'


def fetch_one_month(api_key, lawd_cd, deal_ymd):
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
        return jsonify({'error': '응답 시간 초과'}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'네트워크 오류: {str(e)}'}), 502
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'서버 오류: {str(e)}'}), 500


@app.route('/')
def index():
    return open('index.html', encoding='utf-8').read()


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
