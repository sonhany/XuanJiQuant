from datetime import datetime

import pytest
from scripts.market_data import _ensure_quote_timestamp, _parse_sina_quote


@pytest.mark.parametrize('code', ['sh600000', 'sh000001'])
def test_vendor_friday_date_survives_sunday_normalization(code):
    fields=['stock','10','10','10','10','10','0','0','1000','10000']+['0']*24
    fields[30]='2026-09-11'; fields[31]='15:34:59'
    parsed=_parse_sina_quote(code,fields)
    result=_ensure_quote_timestamp(parsed,now=datetime(2026,9,13,11,0))
    assert result['timestamp']=='20260911153459'
    assert result['time']=='15:34:59'


@pytest.mark.parametrize('vendor_date',['','invalid','2026-02-30'])
def test_unknown_vendor_date_never_becomes_current_day(vendor_date):
    fields=['stock','10','10','10','10','10','0','0','1000','10000']+['0']*24
    fields[30]=vendor_date; fields[31]='15:34:59'
    result=_ensure_quote_timestamp(_parse_sina_quote('sh600000',fields),now=datetime(2026,9,13,11,0))
    assert not result.get('timestamp')


def test_undated_cached_sina_quote_does_not_gain_today_date():
    result=_ensure_quote_timestamp({'source':'sina','time':'15:34:59'},now=datetime(2026,9,13,11,0))
    assert not result.get('timestamp')


def test_sina_stock_quote_preserves_best_bid_ask_as_shares():
    fields=['stock','10','9','10.01','10.10','9.90','10.00','10.01','1000','10000']+['0']*24
    fields[10]='1200'; fields[11]='10.00'
    fields[20]='2300'; fields[21]='10.01'
    fields[30]='2026-09-14'; fields[31]='13:22:11'

    parsed=_parse_sina_quote('sh600000',fields)

    assert parsed['bid']=='10.00'
    assert parsed['ask']=='10.01'
    assert parsed['bid_size']==1200
    assert parsed['ask_size']==2300
    assert parsed['size_unit']=='shares'
    assert parsed['timestamp_kind']=='exchange'
