import pytest
pytest.importorskip('nautilus_trader')
from trading_system.native import run_replay
from tests.nautilus_baseline.fixtures import request,frame,intent


def test_native_buy_updates_real_cash_positions_and_reconciliation():
    result=run_replay(request())
    assert result['cash']=='89994.90'
    assert result['positions']=={'600000':1000}
    assert result['available']=={'600000':0}
    assert result['reconciliation']['passed'] is True
    assert result['fills'][0]['quantity']==1000


def test_same_day_sell_new_decision_does_not_unlock_t1():
    req=request()
    req['frames'][1]['orders']=[intent('new-decision-sell','sell',1000)]
    result=run_replay(req)
    assert result['positions']=={'600000':1000}
    assert result['decisions'][-1]['reason']=='t1_or_available_quantity'


def test_next_declared_trading_day_sale_settles_profit_and_costs():
    req=request()
    req['frames'] += [frame('2026-09-11T09:35:00+08:00',[intent('exit','sell',1000)]),
                       frame('2026-09-11T09:35:01+08:00',[])]
    result=run_replay(req)
    assert result['positions']=={}
    assert result['cash']=='99984.80'
    assert len(result['fills'])==2
    assert result['reconciliation']['passed']


@pytest.mark.parametrize('mutation,reason',[
    ('suspended','suspended'),('upper','daily_price_limit'),('odd','buy_lot_invalid'),
    ('stale','quote_stale'),('future','quote_future'),('state','market_state_stale'),
    ('session','outside_session'),('cash','cash_insufficient'),
])
def test_rejects_before_native_order_creation(mutation,reason):
    req=request(); f=req['frames'][0]
    if mutation=='suspended':f['market']['suspended']=True
    elif mutation=='upper':f['ask']='11.00';f['orders'][0]['limit_price']='11.00'
    elif mutation=='odd':f['orders'][0]['quantity']=101
    elif mutation=='stale':f['quote_timestamp']='2026-09-10T09:34:00+08:00'
    elif mutation=='future':f['quote_timestamp']='2026-09-10T09:36:00+08:00'
    elif mutation=='state':f['market']['date']='2026-09-09'
    elif mutation=='session':f['timestamp']='2026-09-10T09:20:00+08:00';f['quote_timestamp']=f['timestamp']
    elif mutation=='cash':f['orders'][0]['quantity']=20000
    result=run_replay(req)
    assert not result['fills']
    assert result['cash']=='100000.00'
    assert result['decisions'][0]['reason']==reason
    assert result['orders']==[]


def test_two_orders_cannot_reserve_same_cash():
    req=request();req['frames'][0]['orders']=[intent('a','buy',6000),intent('b','buy',6000)]
    result=run_replay(req)
    assert result['positions']=={'600000':6000}
    assert result['decisions'][1]['reason']=='cash_insufficient'


def test_partial_ioc_cannot_infer_unobserved_depth():
    req=request();req['frames'][0]['ask_size']=400
    req['frames'][0]['orders'][0]['limit_price']='10.50'
    result=run_replay(req)
    assert sum(x['quantity'] for x in result['fills'])==400
    assert result['orders'][0]['filled_quantity']==400
    assert result['orders'][0]['remaining_quantity']==600
    assert result['orders'][0]['status']=='CANCELED'
    assert result['reserved_cash']=='0.00'
    assert result['reconciliation']['passed']


def test_visible_liquidity_is_shared_across_same_frame_orders():
    req=request();req['frames'][0]['ask_size']=1000
    req['frames'][0]['orders']=[intent('a','buy',1000),intent('b','buy',1000)]
    result=run_replay(req)
    assert sum(x['quantity'] for x in result['fills'])<=1000


def test_request_replay_has_stable_ids_and_account():
    assert run_replay(request()) == run_replay(request())


def test_duplicate_intent_id_is_not_executed_twice():
    req=request(); req['frames'][1]['orders']=[intent('buy-1','buy',1000)]
    result=run_replay(req)
    assert len(result['orders'])==1
    assert result['positions']=={'600000':1000}


def test_changed_intent_cannot_reuse_identity():
    req=request();req['frames'][1]['orders']=[intent('buy-1','buy',2000)]
    with pytest.raises(ValueError,match='intent_identity_conflict'):
        run_replay(req)


def test_stale_quotes_do_not_revalue_native_positions():
    req=request()
    req['frames'].append(frame('2026-09-10T09:36:00+08:00',[],bid='9.00',ask='9.00',
                               quote_timestamp='2026-09-10T09:30:00+08:00'))
    result=run_replay(req)
    assert result['equity']=='99994.90'
    assert result['valuation_timestamp']=='2026-09-10T09:35:01+08:00'
    assert result['last_quote_valid'] is False


def test_fixed_target_strategy_trades_and_holds_across_two_sessions():
    req=request()
    req['baseline_targets']={'2026-09-10':1000,'2026-09-11':0}
    req['frames'][0]['orders']=[]
    req['frames'] += [frame('2026-09-11T09:35:00+08:00',[]),frame('2026-09-11T09:35:01+08:00',[])]
    result=run_replay(req)
    assert result['cash']=='99984.80'
    assert result['positions']=={}
    assert len(result['fills'])==2
    assert [x['side'] for x in result['fills']]==['buy','sell']


def test_parallel_sell_intents_do_not_reuse_sellable_lots():
    req=request()
    req['frames'] += [frame('2026-09-11T09:35:00+08:00',[intent('a','sell',600),intent('b','sell',600)]),
                       frame('2026-09-11T09:35:01+08:00',[])]
    result=run_replay(req)
    assert result['positions']=={'600000':400}
    assert result['decisions'][-1]['reason']=='t1_or_available_quantity'
