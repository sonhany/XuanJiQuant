from copy import deepcopy


def request():
    return {
        'schema':'nautilus-baseline-v1','data_kind':'synthetic',
        'currency':'CNY','initial_cash':'100000.00',
        'instrument':{'code':'600000','venue':'XSHG','tick_size':'0.01','buy_lot':100},
        'calendar':['2026-09-10','2026-09-11'],
        'costs':{'commission_rate':'0.0003','minimum_commission':'5','sell_tax_rate':'0.0005','transfer_rate':'0.00001'},
        'participation':'1','max_quote_age_ms':3000,
        'frames':[
            frame('2026-09-10T09:35:00+08:00',[intent('buy-1','buy',1000)]),
            frame('2026-09-10T09:35:01+08:00',[]),
        ]
    }


def intent(identity,side,quantity,limit='10.00'):
    return {'id':identity,'side':side,'quantity':quantity,'limit_price':limit}


def frame(timestamp,orders,**changes):
    value={'timestamp':timestamp,'quote_timestamp':timestamp,'bid':'10.00','ask':'10.00',
           'bid_size':100000,'ask_size':100000,
           'market':{'date':timestamp[:10],'version':'fixture-master-v1',
                     'suspended':False,'lower_limit':'9.00','upper_limit':'11.00'},
           'orders':orders}
    value.update(changes)
    return value
