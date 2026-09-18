using QuantConnect;
using QuantConnect.Data.Market;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using System.Text.Json;
using System.Globalization;

// This probes the real portfolio model, not the full transaction handler.
var fixture = JsonDocument.Parse(File.ReadAllText(args[0])).RootElement;
var output = new List<object>();
var time = new DateTime(2026, 9, 10, 1, 35, 0, DateTimeKind.Utc);
Market.Add("xshg", 90);
foreach (var scenario in fixture.GetProperty("cases").EnumerateArray())
{
    var symbol = new Symbol(SecurityIdentifier.GenerateEquity("600000", "xshg", false), "600000");
    var quoteCash = new Cash("CNY", 100000m, 1m);
    var security = new Security(symbol, SecurityExchangeHours.AlwaysOpen(TimeZones.Shanghai),
        quoteCash, new SymbolProperties("Synthetic A-share", "CNY", 1m, 0.01m, 100m, "600000"),
        ErrorCurrencyConverter.Instance, RegisteredSecurityDataTypesProvider.Null, new SecurityCache());
    security.SetMarketPrice(new Tick { Value = 10m });
    var manager = new SecurityManager(new TimeKeeper(time));
    var transactions = new SecurityTransactionManager(null, manager);
    var portfolio = new SecurityPortfolioManager(manager, transactions, new AlgorithmSettings());
    portfolio.SetAccountCurrency("CNY");
    portfolio.SetCash("CNY", 100000m, 1m);
    manager.Add(security);
    var events = new List<OrderEvent>();
    int seq = 0;
    foreach (var quantity in scenario.GetProperty("fills").EnumerateArray())
    {
        var qty = quantity.GetDecimal();
        var fill = new OrderEvent(1, symbol, time.AddSeconds(seq++), OrderStatus.Filled,
            qty > 0 ? OrderDirection.Buy : OrderDirection.Sell, 10m, qty,
            new OrderFee(new CashAmount(5m, "CNY")));
        events.Add(fill);
        portfolio.ProcessFills(new List<OrderEvent>{fill});
    }
    var cash = portfolio.CashBook["CNY"].Amount;
    var shares = security.Holdings.Quantity;
    if (cash != decimal.Parse(scenario.GetProperty("expected_cash").GetString()!, CultureInfo.InvariantCulture)
        || shares != scenario.GetProperty("expected_quantity").GetDecimal())
        throw new Exception("native accounting mismatch: " + scenario.GetProperty("id").GetString());
    output.Add(new { id = scenario.GetProperty("id").GetString(), cash, quantity = shares,
        fees = security.Holdings.TotalFees, boundary = "SecurityPortfolioManager.ProcessFills", passed = true });
    if (scenario.GetProperty("id").GetString() == "full")
    {
        portfolio.ProcessFills(new List<OrderEvent>{events[0]});
        output.Add(new { id = "duplicate_at_accounting_boundary", quantity = security.Holdings.Quantity,
            note = "Injected directly below OMS; not evidence that LEAN transaction handler permits duplicates" });
    }
}
Console.WriteLine(JsonSerializer.Serialize(new { engine = "LEAN", package = "QuantConnect.Common 2.5.18042",
    results = output, full_engine_tested = false }));
