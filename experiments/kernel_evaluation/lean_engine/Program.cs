using QuantConnect;
using QuantConnect.Algorithm;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.Brokerages;
using System.Text.Json;
using System.Reflection;

// Runs only the explicit local-backtest configuration passed by the harness.
var cfg = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
if (cfg.GetProperty("live-mode").GetBoolean() || cfg.GetProperty("environment").GetString() != "backtesting")
    throw new InvalidOperationException("Only local backtests are permitted");
typeof(QuantConnect.Lean.Launcher.Program).Assembly.EntryPoint!.Invoke(null, new object[]{new[]{"--config",args[0]}});

public class KernelEvaluationAlgorithm : QCAlgorithm
{
    private Symbol _symbol;
    private int _ticks;
    private string _mode;
    private OrderTicket _order;
    public override void Initialize()
    {
        SetStartDate(2026,9,10);
        SetEndDate(2026,9,10);
        SetTimeZone(TimeZones.Shanghai);
        SetAccountCurrency("CNY");
        SetCash(100000);
        SetBrokerageModel(BrokerageName.Default, AccountType.Cash);
        _mode=GetParameter("probe_mode", "same_day_roundtrip");
        Market.Add("xshg",90);
        MarketHoursDatabase.SetEntry("xshg","600000",SecurityType.Equity,
            SecurityExchangeHours.AlwaysOpen(TimeZones.Shanghai),TimeZones.Shanghai);
        SymbolPropertiesDatabase.SetEntry("xshg","600000",SecurityType.Equity,
            new SymbolProperties("Synthetic equity","CNY",1m,0.01m,100m,"600000"));
        var equity=AddEquity("600000",Resolution.Minute,"xshg",false,1,false);
        _symbol=equity.Symbol;
        equity.SetDataNormalizationMode(DataNormalizationMode.Raw);
        equity.SetFeeModel(new ConstantFeeModel(5,"CNY"));
        if (_mode=="suspended") equity.IsTradable=false;
        SetBenchmark(t=>100m);
    }
    public override void OnData(Slice data)
    {
        if (!data.Bars.ContainsKey(_symbol)) return;
        _ticks++;
        if (_ticks==1)
        {
            var quantity=_mode=="insufficient_cash" ? 20000 : _mode=="odd_lot" ? 101 : 1000;
            _order=_mode=="cash_reservation" ? LimitOrder(_symbol,quantity,9m)
                : _mode.StartsWith("partial") ? LimitOrder(_symbol,quantity,10m)
                : _mode=="aggressive_limit" ? LimitOrder(_symbol,quantity,10.01m) : MarketOrder(_symbol,quantity);
        }
        if (_ticks==2 && _mode=="same_day_roundtrip") MarketOrder(_symbol,-1000);
        if (_ticks==2 && _mode=="cash_reservation") _order.Cancel();
        if (_ticks==2 && _mode=="partial_cancel" && !_order.Status.IsClosed()) _order.Cancel();
    }
    public override void OnEndOfAlgorithm()
    {
        Debug("KERNEL_PROBE="+JsonSerializer.Serialize(new{
            mode=_mode,ticks=_ticks,cash=Portfolio.CashBook["CNY"].Amount,quantity=Portfolio[_symbol].Quantity,
            unsettled_cash=Portfolio.UnsettledCash, equity=Portfolio.TotalPortfolioValue,
            settlement_model=Securities[_symbol].SettlementModel.GetType().Name,
            order_count=Transactions.GetOrders().Count(),
            orders=Transactions.GetOrders().Select(o=>new {status=o.Status.ToString(),quantity=o.Quantity}).ToArray(),
            boundary="LEAN Engine local historical-data backtest"
        }));
    }
}
